"""Canonical action commands for an explicitly configured, local OpenClaw.

The existing admin bus owns authority, plans and single-writer admission. The
Gateway owns execution; these files are recovery receipts, never a task queue.
No shell, arbitrary RPC, browser-supplied destination or standalone entry point.
"""
from __future__ import annotations

import datetime as dt
import copy
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from wiki_core.action_transition import _assert_no_secrets, _parse_document
from wiki_core.config import load_config
from wiki_core.coordination import context_packet, digest
from wiki_core.paths import WikiPaths
from wiki_core.web.normal_proposal import _safe
from wiki_core.web.snapshot import build_snapshot


from wiki_core.openclaw_config import RuntimeErrorCode, require, validated_config


def route_for(config, profile):
    runtime = validated_config(config.openclaw)
    require(runtime["enabled"], "openclaw_not_configured")
    require(profile in runtime["routes"], "openclaw_profile_not_configured")
    return runtime, runtime["routes"][profile]


class Gateway:
    def __init__(self, runtime, route):
        self.runtime, self.route = runtime, route

    def call(self, method, params):
        require(method in {"chat.history", "chat.send"}, "openclaw_method_not_allowed")
        env = os.environ.copy()
        state = str(Path(self.runtime["state_dir"]).expanduser())
        env.update(OPENCLAW_PROFILE=self.runtime["profile"], OPENCLAW_STATE_DIR=state,
                   OPENCLAW_CONFIG_PATH=str(Path(state) / "openclaw.json"))
        argv = [str(Path(self.runtime["node_binary"]).expanduser()),
                str(Path(self.runtime["entrypoint"]).expanduser()),
                "gateway", "call", "--expect-url", self.runtime["gateway"],
                "--json", "--timeout", "20000", method, "--params", json.dumps(params)]
        try:
            result = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=35)
            require(result.returncode == 0, "openclaw_transport_failed_reconcile")
            value = json.loads(result.stdout)
            require(isinstance(value, dict), "openclaw_invalid_response")
            return value
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
            raise RuntimeErrorCode("openclaw_transport_unavailable_reconcile") from None

    def history(self, **extra):
        params = {"sessionKey": self.route["session_key"], "limit": 1, "maxChars": 1,
                  "toolResultMaxChars": 1, **extra}
        if params.get("messageId"):
            params["sessionId"] = self.route["session_id"]
        value = self.call("chat.history", params)
        require(value.get("sessionId") == self.route["session_id"], "openclaw_session_identity_changed")
        return value


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()


def binding(root, config, profile, action_id, *, admissible=True):
    require(load_config(root) == config, "openclaw_operator_config_changed_restart")
    require(not git(root, "status", "--porcelain", "--untracked-files=all"), "openclaw_checkout_not_clean")
    packet = context_packet(root, config, build_snapshot(root, config), profile, action_id)
    require(len(packet["actions"]) == 1, "openclaw_exact_action_required")
    action = packet["actions"][0]
    fm, _ = _parse_document((root / action["path"]).read_text())
    if admissible:
        require(action["state"] in {"open", "in_progress"} and not action["dialogue"]["pending_question_ids"]
                and not fm.get("blocked_by") and not fm.get("blocker_reason"), "openclaw_action_not_admissible")
    return {"repo_id": config.repo_id, "base_head": git(root, "rev-parse", "HEAD"),
            "action_id": action_id, "action_path": action["path"], "action_sha256": action["content_sha256"],
            "profile": profile, "policy_sha256": packet["policy_sha256"],
            "context_sha256": digest({k: v for k, v in packet.items() if k not in {"snapshot_id", "context_sha256"}}),
            "context_exported": False}


def storage(root, config, effect):
    require(isinstance(effect, str) and re.fullmatch(r"wiki-run-[0-9a-f]{32}", effect), "openclaw_invalid_effect")
    relative = (WikiPaths(root, config).derived_root / "openclaw" / effect).relative_to(root).as_posix()
    return _safe(root, relative)


def write_new(path, value):
    raw = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    _assert_no_secrets(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Publish complete bytes atomically, with exclusive creation. A second
    # caller cannot overwrite an intent, even after an interrupted response.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".pending-receipt-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_receipt(path):
    require(path.is_file() and path.stat().st_size <= 256_000 and not path.is_symlink(), "openclaw_receipt_missing")
    try:
        value = json.loads(path.read_text())
    except (json.JSONDecodeError, UnicodeError):
        raise RuntimeErrorCode("openclaw_receipt_corrupt_reconcile") from None
    require(isinstance(value, dict), "openclaw_receipt_corrupt_reconcile")
    _assert_no_secrets(json.dumps(value))
    return value


def idle_leaf(history):
    info = history["sessionInfo"]
    require(info.get("hasActiveRun") is False and history["pendingInputs"]["total"] == 0,
            "openclaw_session_busy_reconcile")
    leaf = info.get("activeLeafEntryId")
    require(isinstance(leaf, str) and bool(leaf), "openclaw_session_leaf_missing")
    return leaf


def plan_dispatch(root, config, params):
    profile, action = params["profile"], params["action_id"]
    message = params["message"]
    require(0 < len(message.strip()) <= 12000, "openclaw_message_size")
    _assert_no_secrets(message)
    runtime, route = route_for(config, profile)
    canonical = binding(root, config, profile, action)
    require(canonical["action_sha256"] == params["action_sha256"], "openclaw_action_revision_changed")
    effect = "wiki-run-" + digest({"action": canonical, "message": message, "route": route})[:32]
    directory = storage(root, config, effect)
    require(not (directory / "intent.json").exists(), "openclaw_intent_exists_reconcile")
    require(not any(not item["has_result"] for item in attempts(root, config, profile, action)),
            "openclaw_uncollected_attempt_reconcile")
    leaf = idle_leaf(Gateway(runtime, route).history())
    return {"binding": canonical, "route": route, "route_sha256": digest(runtime), "message": message,
            "message_sha256": hashlib.sha256(message.encode()).hexdigest(), "expected_leaf": leaf,
            "effect_key": effect, "canonical_write": False}


def dispatch(root, config, prepared):
    """Called only inside the existing live agents.execute effect admission."""
    b = prepared["binding"]
    runtime, route = route_for(config, b["profile"])
    require(digest(runtime) == prepared["route_sha256"] and route == prepared["route"], "openclaw_route_changed")
    require(binding(root, config, b["profile"], b["action_id"]) == b, "openclaw_context_changed")
    gateway = Gateway(runtime, route)
    require(idle_leaf(gateway.history()) == prepared["expected_leaf"], "openclaw_session_changed_reconcile")
    directory = storage(root, config, prepared["effect_key"])
    require(not (directory / "intent.json").exists(), "openclaw_intent_exists_reconcile")
    require(not any(not item["has_result"] for item in attempts(root, config, b["profile"], b["action_id"])),
            "openclaw_uncollected_attempt_reconcile")
    write_new(directory / "intent.json", {"plan": prepared, "plan_sha256": digest(prepared),
              "attempted_at": dt.datetime.now(dt.timezone.utc).isoformat()})
    # An uncertain transport leaves durable intent. Never retry chat.send.
    result = gateway.call("chat.send", {"sessionKey": route["session_key"], "message": prepared["message"],
        "expectedLeafEntryId": prepared["expected_leaf"], "idempotencyKey": prepared["effect_key"],
        "queueMode": "followup", "deliver": False})
    require(result.get("runId") == prepared["effect_key"], "openclaw_unexpected_run_reconcile")
    receipt = {"effect_key": prepared["effect_key"], "action_id": b["action_id"],
               "run_id": result["runId"], "status": result.get("status"), "plan_sha256": digest(prepared)}
    write_new(directory / "accepted.json", receipt)
    return {**receipt, "canonical_write": False, "new_dispatch": True}


def retained_intent(root, config, params):
    # An effect is always qualified by the requesting action/profile. It is
    # never accepted as an arbitrary path or an identifier from another card.
    require(load_config(root) == config, "openclaw_operator_config_changed_restart")
    directory = storage(root, config, params["effect_key"])
    intent = read_receipt(directory / "intent.json")
    plan = intent["plan"]
    require(digest(plan) == intent["plan_sha256"] and plan["effect_key"] == params["effect_key"], "openclaw_intent_changed")
    require(plan["binding"]["profile"] == params["profile"] and plan["binding"]["action_id"] == params["action_id"],
            "openclaw_wrong_action")
    runtime, route = route_for(config, params["profile"])
    require(digest(runtime) == plan["route_sha256"] and route == plan["route"], "openclaw_route_changed")
    if (directory / "accepted.json").exists():
        accepted = read_receipt(directory / "accepted.json")
        require(accepted["plan_sha256"] == intent["plan_sha256"] and accepted["run_id"] == plan["effect_key"],
                "openclaw_acceptance_changed")
    return directory, plan, runtime, route


def inspect(root, config, params):
    """Reconcile one retained run, including after an operator restart."""
    directory, plan, runtime, route = retained_intent(root, config, params)
    gateway = Gateway(runtime, route)
    history = gateway.history()
    info = history["sessionInfo"]
    observed = {"action_id": params["action_id"], "effect_key": params["effect_key"],
                "status": info.get("status"), "active": info.get("hasActiveRun"),
                "same_run": info.get("lastRunId") == plan["effect_key"], "new_dispatch": False,
                "canonical_write": False}
    # Once captured, its exact message stays readable even if later activity
    # has advanced the session. Its identity is still checked natively.
    old = read_receipt(directory / "result.json") if (directory / "result.json").exists() else None
    if old is None and not (observed["same_run"] and observed["active"] is False and observed["status"] == "done"):
        return {**observed, "result_available": False}
    message_id = old["message_id"] if old else info.get("activeLeafEntryId")
    data = gateway.history(messageId=message_id, maxChars=64000, maxBytes=128000)
    require(len(data.get("messages", [])) == 1, "openclaw_exact_result_missing")
    message = data["messages"][0]
    meta = message.get("__openclaw", {})
    require(message.get("role") == "assistant" and meta.get("runId") == plan["effect_key"]
            and meta.get("id") == message_id and meta.get("runTerminal") and not meta.get("truncated")
            and message.get("stopReason") == "stop" and not message.get("errorMessage"), "openclaw_result_not_complete")
    content = message.get("content", [])
    require(content and all(c.get("type") == "text" for c in content), "openclaw_text_result_required")
    text = "\n".join(c["text"] for c in content)
    _assert_no_secrets(text)
    result = {"action_id": params["action_id"], "effect_key": plan["effect_key"], "run_id": plan["effect_key"],
              "plan_sha256": digest(plan), "session_id": route["session_id"], "message_id": message_id,
              "text": text, "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
              "captured_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    if old:
        require({k: v for k, v in old.items() if k != "captured_at"} ==
                {k: v for k, v in result.items() if k != "captured_at"}, "openclaw_retained_result_changed")
        result = old
    else:
        write_new(directory / "result.json", result)
    try:
        current = binding(root, config, params["profile"], params["action_id"])
        hold = None if current == plan["binding"] else "canonical_context_changed"
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        hold = "canonical_state_unavailable_or_ineligible"
    return {**observed, "result_available": True, "result": result, "integration_hold": hold,
            "idempotent_read": old is not None, "documentary_integration": "pending_review"}


def attempts(root, config, profile, action_id):
    """Discovery of recovery evidence, not readiness or a second task list."""
    parent = WikiPaths(root, config).derived_root / "openclaw"
    if not parent.exists():
        return []
    _safe(root, parent.relative_to(root).as_posix())
    found = []
    for path in sorted(parent.glob("wiki-run-*/intent.json")):
        _safe(root, path.relative_to(root).as_posix())
        intent = read_receipt(path)
        require(isinstance(intent.get("plan"), dict) and isinstance(intent["plan"].get("binding"), dict)
                and isinstance(intent.get("attempted_at"), str), "openclaw_receipt_corrupt_reconcile")
        plan = intent["plan"]
        require(digest(plan) == intent.get("plan_sha256"), "openclaw_intent_changed")
        if plan["binding"]["profile"] == profile and plan["binding"]["action_id"] == action_id:
            result_path = path.parent / "result.json"
            has_result = result_path.exists()
            if has_result:
                verified_result(path.parent, plan)
            found.append({"effect_key": plan["effect_key"], "attempted_at": intent["attempted_at"],
                          "has_result": has_result,
                          "proposal": proposal_status(root, config, path.parent, plan)})
    return found


def verified_result(directory, plan):
    result = read_receipt(directory / "result.json")
    require(result.get("plan_sha256") == digest(plan) and result.get("run_id") == plan["effect_key"]
            and result.get("effect_key") == plan["effect_key"]
            and result.get("action_id") == plan["binding"]["action_id"]
            and result.get("session_id") == plan["route"]["session_id"]
            and isinstance(result.get("message_id"), str) and bool(result["message_id"])
            and isinstance(result.get("text"), str)
            and result.get("text_sha256") == hashlib.sha256(result["text"].encode()).hexdigest(),
            "openclaw_retained_result_changed")
    return result


def proposal_status(root, config, directory, plan):
    """Read the existing material/Git outcome; never retry a write on reload."""
    manifest = directory / "receipt-material-integrity.json"
    if not manifest.exists():
        return None
    saved = read_receipt(manifest)
    material_file = _safe(root, saved["material_path"])
    require(hashlib.sha256(material_file.read_bytes()).hexdigest() == saved["material_sha256"],
            "openclaw_material_changed")
    from wiki_core.web.normal_proposal import MAX_MATERIAL_BYTES
    require(material_file.stat().st_size <= MAX_MATERIAL_BYTES, "openclaw_material_changed")
    material = json.loads(material_file.read_text())
    require(material["action"]["run_id"] == plan["effect_key"]
            and material["base_head"] == plan["binding"]["base_head"], "openclaw_material_changed")
    expected = saved["output_hashes"]
    def matches(revision):
        for ref, sha in expected.items():
            _safe(root, ref)
            try:
                raw = subprocess.check_output(["git", "show", revision + ":" + ref], cwd=root, stderr=subprocess.DEVNULL)
            except subprocess.CalledProcessError:
                return False
            if hashlib.sha256(raw).hexdigest() != sha:
                return False
        return True
    matched = matches("HEAD")
    head = git(root, "rev-parse", "HEAD")
    branch = git(root, "branch", "--show-current")
    proposal_head = git(root, "rev-parse", "refs/heads/" + material["branch"])
    prepared = matches(proposal_head)
    if matched or prepared:
        from wiki_core.action_transition import operational_comment_receipt
        action = material["action"]["page_ref"]
        before = subprocess.check_output(["git", "show", material["base_head"] + ":" + action], cwd=root).decode()
        after = subprocess.check_output(["git", "show", (head if matched else proposal_head) + ":" + action], cwd=root).decode()
        proof = operational_comment_receipt(before, after)
        require(bool(proof) and proof["event_id"] == "received-" + plan["effect_key"],
                "openclaw_receipt_semantics_changed")
    status = ("received_in_main" if branch == str(config.approval.get("default_branch") or "main")
              else "prepared") if matched else "awaiting_adoption" if prepared else "material_ready" if (
                  head == material["base_head"] and branch == material["branch"]) else "reconciliation_required"
    return {"status": status, "head": head, "approved_base": material["base_head"],
            "proposal_head": proposal_head, "branch": branch,
            "material_path": saved["material_path"], "material_sha256": saved["material_sha256"]}


def receipt_source(root, config, params):
    """Only a verified, retained terminal return can become proposal material."""
    directory, plan, _, _ = retained_intent(root, config, params)
    result = verified_result(directory, plan)
    require(binding(root, config, params["profile"], params["action_id"]) == plan["binding"],
            "openclaw_context_changed")
    return directory, plan, result


def prepare_receipt_material(root, config, params, *, expected_result_sha256):
    """Derive a pure-comment normal proposal, never install canonical files.

    The native writer proves communication-only semantics. Physical CURRENT
    identity guards follow that delta; interpretations, BASE and evidence are
    preserved. The ordinary proposal audit/review still decides admission.
    """
    from wiki_core.action_transition import operational_comment_receipt
    from wiki_core.web.normal_proposal import preview_proposal
    directory, plan, result = receipt_source(root, config, params)
    require(digest(result) == expected_result_sha256, "openclaw_reviewed_result_changed")
    material_file = directory / "receipt-material.json"
    manifest = directory / "receipt-material-integrity.json"
    if manifest.exists():
        saved = read_receipt(manifest)
        raw = material_file.read_bytes()
        require(saved["material_sha256"] == hashlib.sha256(raw).hexdigest(), "openclaw_material_changed")
        return {**saved, "proposal": proposal_status(root, config, directory, plan),
                "action_id": params["action_id"], "effect_key": params["effect_key"],
                "canonical_write": False, "next_command": "wiki.proposal.prepare"}
    require(not material_file.exists(), "openclaw_material_incomplete_reconcile")
    # Reuse the proposal branch workflow; main stays approved and untouched.
    # This command's plan advertises the branch creation and git.propose gate.
    if git(root, "branch", "--show-current") == str(config.approval.get("default_branch") or "main"):
        from wiki_core.web.git_workflows import run_git_workflow
        created = run_git_workflow(root, config, "start_proposal",
            {"theme": "runtime-return-" + plan["effect_key"].removeprefix("wiki-run-")}, dry_run=False)
        require(created.get("ok"), "openclaw_proposal_branch_failed")
    b = plan["binding"]
    ref = b["action_path"]
    before = (root / ref).read_text()
    fm, _ = _parse_document(before)
    stamp = dt.datetime.now(dt.timezone.utc).isoformat()
    reference = (WikiPaths(root, config).references_root / "runtime-returns" / plan["effect_key"]).relative_to(root)
    proof_ref = (reference / "result.json").as_posix()
    contract_ref = (reference / "records.json").as_posix()
    link = os.path.relpath(proof_ref, Path(ref).parent)
    material = {"schema_version": "wiki_normal_proposal.v1", "base_head": b["base_head"],
        "branch": git(root, "branch", "--show-current"),
        "action": {"page_ref": ref, "page_id": params["action_id"], "expected_sha256": b["action_sha256"],
            "run_id": plan["effect_key"], "effect_key": "received-" + plan["effect_key"],
            "transition": {"next_state": fm["action_state"], "recorded_at": stamp,
                "dialogue_event": {"event_id": "received-" + plan["effect_key"], "kind": "comment",
                    "coordinator": params["profile"],
                    "text": "Resultado recebido pela entrada integrada desta ação. Run: " + plan["effect_key"] +
                    ". [Mensagem, resultado e identidade da execução](" + link + "). "
                    "Recebimento não conclui a ação nem incorpora alterações documentais propostas pelo executor. "
                    "O integrador revisa o resultado e o próximo passo nesta mesma ação."}}},
        "documents": [{"path": proof_ref, "before_sha256": None,
            "after_text": json.dumps({"plan": plan, "result": result,
                "interpretation": "Producer output, received for review; no autonomous canonical write or task completion"},
                indent=2, ensure_ascii=False) + "\n"}],
        "c2": [], "generated_at": stamp, "commit_message": "Receive the canonical action runtime result"}
    scratch = directory / "receipt-preview.json"
    require(not scratch.exists(), "openclaw_material_incomplete_reconcile")
    def preview():
        scratch.write_text(json.dumps(material, ensure_ascii=False, indent=2) + "\n")
        raw = scratch.read_bytes()
        return preview_proposal(root, config, {"material_path": scratch.relative_to(root).as_posix(),
                                              "material_sha256": hashlib.sha256(raw).hexdigest()})
    try:
        initial = preview()
        after = initial["outputs"][ref].decode()
        require(bool(operational_comment_receipt(before, after)), "openclaw_return_not_pure_comment")
        contract_path = config.audit.get("freshness_records")
        if contract_path:
            original = json.loads(_safe(root, contract_path).read_text())
            contract = copy.deepcopy(original)
            require(contract["current_documents_sha256"].get(ref) == b["action_sha256"], "openclaw_contract_snapshot_changed")
            after_sha = hashlib.sha256(after.encode()).hexdigest()
            contract["current_documents_sha256"][ref] = after_sha
            for guard in contract.get("bindings", []):
                if guard.get("origin") == "current" and guard.get("role") in {"provenance", "navigation", "change_target"}:
                    for key in ("prerequisite_document_sha256", "target_document_sha256"):
                        if guard.get(key) == b["action_sha256"]:
                            guard[key] = after_sha
            material["documents"].append({"path": contract_ref, "before_sha256": None,
                "after_text": json.dumps(contract, ensure_ascii=False, indent=2) + "\n"})
            material["freshness_pointer"] = {
                "before_sha256": hashlib.sha256((root / "wiki.config.yaml").read_bytes()).hexdigest(),
                "freshness_base": config.audit["freshness_base"], "freshness_records": contract_ref}
            initial = preview()
        write_new(material_file, material)
        saved = {"material_path": material_file.relative_to(root).as_posix(),
                 "material_sha256": hashlib.sha256(material_file.read_bytes()).hexdigest(),
                 "output_hashes": {ref: hashlib.sha256(raw).hexdigest() for ref, raw in initial["outputs"].items()}}
        write_new(manifest, saved)
        return {**saved, "proposal": proposal_status(root, config, directory, plan),
                "action_id": params["action_id"], "effect_key": params["effect_key"],
                "canonical_write": False, "next_command": "wiki.proposal.prepare"}
    finally:
        scratch.unlink(missing_ok=True)
