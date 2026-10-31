"""Canonical action commands for an explicitly configured, local OpenClaw.

The existing admin bus owns authority, plans and single-writer admission. The
Gateway owns execution; these files are recovery receipts, never a task queue.
No shell, arbitrary RPC, browser-supplied destination or standalone entry point.
"""
from __future__ import annotations

import datetime as dt
import copy
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
import os
import re
import socket
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from wiki_core.action_transition import _assert_no_secrets, _parse_document, _action_file_lock
from wiki_core.config import load_config
from wiki_core.coordination import context_packet, digest
from wiki_core.paths import WikiPaths
from wiki_core.web.normal_proposal import _safe
from wiki_core.web.snapshot import build_snapshot


from wiki_core.openclaw_config import RuntimeErrorCode, require, validated_config

MAX_RECEIPT_BYTES = 256_000
MAX_RESULT_EXCERPT_CHARS = 1_600
_PREPARATORY_OBSERVATIONS = ContextVar("openclaw_preparatory_observations", default=None)


@contextmanager
def preparatory_observations():
    """Describe calls already made while planning, including a dry run."""
    observed = []
    token = _PREPARATORY_OBSERVATIONS.set(observed)
    try:
        yield observed
    finally:
        _PREPARATORY_OBSERVATIONS.reset(token)


def preparation_effects(observed):
    return ([f"OpenClaw chat.history during planning ({len(observed)} calls); native orphan reconciliation is possible"]
            if observed else [])


def route_for(config, profile):
    runtime = validated_config(config.openclaw)
    require(runtime["enabled"], "openclaw_not_configured")
    require(profile in runtime["routes"], "openclaw_profile_not_configured")
    return runtime, runtime["routes"][profile]


class GatewayRequestError(RuntimeErrorCode):
    def __init__(self, diagnostic):
        self.diagnostic = diagnostic
        super().__init__("openclaw_rpc_rejected_reconcile" if diagnostic["type"] == "rpc_rejection"
                         else "openclaw_transport_failed_reconcile")


def rpc_diagnostic(value):
    """Retain only closed, non-secret error enums, never arbitrary provider text."""
    error = value.get("error") if isinstance(value, dict) else None
    if not isinstance(error, dict):
        return None
    if (set(error) == {"type", "code", "reason"}
            and error["type"] in {"rpc_rejection", "transport_or_local"}
            and error["code"] in {"INVALID_REQUEST", "UNAVAILABLE", "FORBIDDEN", "UNAUTHORIZED", "NOT_FOUND", "TIMEOUT", "UNKNOWN"}
            and error["reason"] in {"system_provenance_requires_admin", "native_call_failed"}):
        return error
    return None


class Gateway:
    def __init__(self, runtime, route):
        self.runtime, self.route = runtime, route

    def call(self, method, params):
        require(method in {"chat.history", "chat.send", "sessions.patch"}, "openclaw_method_not_allowed")
        env = os.environ.copy()
        state = str(Path(self.runtime["state_dir"]).expanduser())
        env.update(OPENCLAW_PROFILE=self.runtime["profile"], OPENCLAW_STATE_DIR=state,
                   OPENCLAW_CONFIG_PATH=str(Path(state) / "openclaw.json"))
        helper = Path(__file__).resolve().parents[2] / "scripts/openclaw/mission-rpc.mjs"
        argv = [str(Path(self.runtime["node_binary"]).expanduser()), str(helper),
                str(Path(self.runtime["entrypoint"]).expanduser().parent)]
        request = json.dumps({"method": method, "params": params, "expectUrl": self.runtime["gateway"]})
        try:
            result = subprocess.run(argv, input=request, env=env, capture_output=True, text=True, timeout=35)
            require(len(result.stdout) <= 512_000, "openclaw_invalid_response")
            value = json.loads(result.stdout)
            if result.returncode:
                diagnostic = rpc_diagnostic(value)
                if diagnostic:
                    raise GatewayRequestError(diagnostic)
                raise RuntimeErrorCode("openclaw_transport_failed_reconcile")
            require(isinstance(value, dict), "openclaw_invalid_response")
            return value
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
            raise RuntimeErrorCode("openclaw_transport_unavailable_reconcile") from None

    def history(self, **extra):
        params = {"sessionKey": self.route["session_key"], "limit": 1, "maxChars": 1,
                  "toolResultMaxChars": 1, **extra}
        if params.get("messageId"):
            params["sessionId"] = self.route["session_id"]
        observed = _PREPARATORY_OBSERVATIONS.get()
        if observed is not None:
            observed.append("chat.history")
        value = self.call("chat.history", params)
        require(value.get("sessionId") == self.route["session_id"], "openclaw_session_identity_changed")
        return value


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, text=True, stderr=subprocess.DEVNULL,
                                   env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"}).strip()


def binding(root, config, profile, action_id, *, admissible=True, require_clean=True):
    require(load_config(root) == config, "openclaw_operator_config_changed_restart")
    if require_clean:
        require(not git(root, "status", "--porcelain", "--untracked-files=all"), "openclaw_checkout_not_clean")
    packet = context_packet(root, config, build_snapshot(root, config), profile, action_id)
    require(len(packet["actions"]) == 1, "openclaw_exact_action_required")
    action = packet["actions"][0]
    fm, _ = _parse_document((root / action["path"]).read_text())
    if admissible:
        require(all(row['ready'] for row in packet.get('information_use', [])),
                "openclaw_current_information_unverified")
        require(action["state"] in {"open", "in_progress"} and not action["dialogue"]["pending_question_ids"]
                and not fm.get("blocked_by") and not fm.get("blocker_reason"), "openclaw_action_not_admissible")
    result = {"repo_id": config.repo_id, "base_head": git(root, "rev-parse", "HEAD"),
            "action_id": action_id, "action_path": action["path"], "action_sha256": action["content_sha256"],
            "profile": profile, "policy_sha256": packet["policy_sha256"],
            "context_sha256": digest({k: v for k, v in packet.items() if k not in {"snapshot_id", "context_sha256"}}),
            "context_exported": False}
    validity = [r['valid_until'] for assessment in packet.get('information_use', [])
                for r in assessment['requirements'] if r.get('valid_until')]
    if validity:
        result['information_valid_until'] = min(validity,
            key=lambda value: dt.datetime.fromisoformat(value))
    return result


def storage(root, config, effect):
    require(isinstance(effect, str) and re.fullmatch(r"wiki-run-[0-9a-f]{32}", effect), "openclaw_invalid_effect")
    relative = (WikiPaths(root, config).derived_root / "openclaw" / effect).relative_to(root).as_posix()
    return _safe(root, relative)


def write_new(path, value):
    raw = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    _assert_no_secrets(raw)
    require(len(raw.encode("utf-8")) <= MAX_RECEIPT_BYTES, "openclaw_receipt_too_large")
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


def receipt_bytes(path):
    require(path.is_file() and not path.is_symlink(), "openclaw_receipt_missing")
    with path.open("rb") as stream:
        raw = stream.read(MAX_RECEIPT_BYTES + 1)
    require(len(raw) <= MAX_RECEIPT_BYTES, "openclaw_receipt_missing")
    return raw


def parse_receipt(raw):
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, UnicodeError):
        raise RuntimeErrorCode("openclaw_receipt_corrupt_reconcile") from None
    require(isinstance(value, dict), "openclaw_receipt_corrupt_reconcile")
    _assert_no_secrets(json.dumps(value))
    return value


def read_receipt(path):
    return parse_receipt(receipt_bytes(path))


def reviewed_receipt(path, sha):
    raw = receipt_bytes(path)
    require(hashlib.sha256(raw).hexdigest() == sha, "openclaw_failure_reviewed_bytes_changed")
    return parse_receipt(raw), raw.decode("utf-8")


def pending_page(history):
    require(isinstance(history, dict) and isinstance(history.get("sessionInfo"), dict)
            and isinstance(history.get("pendingInputs"), dict), "openclaw_pending_inputs_incomplete")
    pending = history["pendingInputs"]
    items = pending.get("items", [])
    require(type(pending.get("total")) is int and pending["total"] >= 0 and isinstance(items, list)
            and all(isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"] and isinstance(item.get("state"), str)
                    for item in items), "openclaw_pending_inputs_incomplete")
    cursor = pending.get("nextBefore")
    require(cursor is None or type(cursor) is int and cursor > 0, "openclaw_pending_inputs_incomplete")
    return pending, items, cursor


def idle_leaf(history, *, allow_empty=False):
    pending, items, cursor = pending_page(history)
    info = history["sessionInfo"]
    # Current Gateways include cancelled/interrupted history in total. Only
    # an explicit live queuedCount permits those retained historical records.
    queued = pending.get("queuedCount", pending["total"])
    require(info.get("hasActiveRun") is False and type(queued) is int and queued == 0,
            "openclaw_session_busy_reconcile")
    require(cursor is None and all(item.get("state") in {"cancelled", "interrupted"} for item in items),
            "openclaw_pending_inputs_reconcile")
    require(pending["total"] == len(items) and len({item["id"] for item in items}) == len(items),
            "openclaw_pending_inputs_incomplete")
    leaf = info.get("activeLeafEntryId")
    if allow_empty and leaf is None:
        require(not info.get("lastRunId") and history.get("totalMessages") == 0
                and history.get("messages") == [] and history.get("hasMore") is False
                and pending["total"] == 0, "openclaw_bootstrap_not_empty")
        return None
    require(isinstance(leaf, str) and bool(leaf), "openclaw_session_leaf_missing")
    return leaf


def idle_history(gateway, *, allow_empty=False):
    """Read the complete bounded pending-input history, without exporting it."""
    first = gateway.history(limit=20)
    pending, initial, cursor = pending_page(first)
    items, seen = list(initial), set()
    while cursor is not None:
        require(cursor not in seen and len(seen) < 25, "openclaw_pending_inputs_incomplete")
        seen.add(cursor)
        page = gateway.history(limit=20, pendingBefore=cursor)
        next_pending, next_items, cursor = pending_page(page)
        require({k: page["sessionInfo"].get(k) for k in ("hasActiveRun", "activeLeafEntryId", "lastRunId")} ==
                {k: first["sessionInfo"].get(k) for k in ("hasActiveRun", "activeLeafEntryId", "lastRunId")}
                and next_pending.get("total") == pending.get("total")
                and next_pending.get("queuedCount") == pending.get("queuedCount"),
                "openclaw_session_changed_reconcile")
        items.extend(next_items)
    first["pendingInputs"] = {**pending, "items": items, "nextBefore": None}
    idle_leaf(first, allow_empty=allow_empty)
    return first


def plan_dispatch(root, config, params):
    require(git(root, "branch", "--show-current") == str(config.approval.get("default_branch") or "main"),
            "openclaw_dispatch_requires_approved_checkout")
    profile, action = params["profile"], params["action_id"]
    message = params["message"]
    require(0 < len(message.strip()) <= 12000, "openclaw_message_size")
    _assert_no_secrets(message)
    runtime, route = route_for(config, profile)
    option = runtime.get("mission_options", {}).get(params.get("mission_id"))
    bootstrap = route.get("native_thread_binding") == "first_turn"
    require(option is not None and (route.get("native_thread_id") or bootstrap), "openclaw_mission_policy_required")
    mission = {"id": params["mission_id"], **option, "native_thread_id": route.get("native_thread_id")}
    if bootstrap:
        mission["native_thread_binding"] = "first_turn"
    elif runtime.get("recovery"):
        mission["recovery"] = copy.deepcopy(runtime["recovery"])
    canonical = binding(root, config, profile, action)
    require(canonical["action_sha256"] == params["action_sha256"], "openclaw_action_revision_changed")
    effect = "wiki-run-" + digest({"action": canonical, "message": message, "route": route, "mission": mission})[:32]
    directory = storage(root, config, effect)
    require(not (directory / "intent.json").exists(), "openclaw_intent_exists_reconcile")
    require(not any(not item["reconciled"] for item in attempts(root, config, profile, action)),
            "openclaw_uncollected_attempt_reconcile")
    require(not (directory.parent / "mission-active.json").exists(), "openclaw_mission_lock_reconcile")
    leaf = idle_leaf(idle_history(Gateway(runtime, route), allow_empty=bootstrap), allow_empty=bootstrap)
    require(not bootstrap or leaf is None, "openclaw_bootstrap_not_empty")
    return {"binding": canonical, "route": route, "route_sha256": digest(runtime), "message": message,
            "runtime_identity_sha256": digest({k: v for k, v in runtime.items() if k not in {"recovery", "recurring"}}),
            "message_sha256": hashlib.sha256(message.encode()).hexdigest(), "expected_leaf": leaf,
            "effect_key": effect, "mission": mission, "canonical_write": False}


def dispatch(root, config, prepared):
    """Called only inside the existing live agents.execute effect admission."""
    require(git(root, "branch", "--show-current") == str(config.approval.get("default_branch") or "main"),
            "openclaw_dispatch_requires_approved_checkout")
    b = prepared["binding"]
    runtime, route = route_for(config, b["profile"])
    require(digest(runtime) == prepared["route_sha256"] and route == prepared["route"], "openclaw_route_changed")
    require(binding(root, config, b["profile"], b["action_id"]) == b, "openclaw_context_changed")
    gateway = Gateway(runtime, route)
    bootstrap = prepared["mission"].get("native_thread_binding") == "first_turn"
    require(idle_leaf(idle_history(gateway, allow_empty=bootstrap), allow_empty=bootstrap) == prepared["expected_leaf"], "openclaw_session_changed_reconcile")
    directory = storage(root, config, prepared["effect_key"])
    require(not (directory / "intent.json").exists(), "openclaw_intent_exists_reconcile")
    require(not any(not item["reconciled"] for item in attempts(root, config, b["profile"], b["action_id"])),
            "openclaw_uncollected_attempt_reconcile")
    write_new(directory / "intent.json", {"plan": prepared, "plan_sha256": digest(prepared),
              "attempted_at": dt.datetime.now(dt.timezone.utc).isoformat()})
    mission = prepared["mission"]
    provider, model = mission["model"].split("/", 1)
    contract = {"schema_version": "wiki_openclaw_mission.v1", "run_id": prepared["effect_key"],
        "session_key": route["session_key"], "session_id": route["session_id"],
        "native_thread_id": mission["native_thread_id"], "provider": provider, "model": model,
        "effort": mission["effort"], "message_sha256": prepared["message_sha256"],
        "plan_sha256": digest(prepared), "action_id": b["action_id"], "action_sha256": b["action_sha256"],
        "expires_at": (dt.datetime.now(dt.timezone.utc)+dt.timedelta(minutes=15)).isoformat()}
    if b.get('information_valid_until'):
        deadline = dt.datetime.fromisoformat(b['information_valid_until'])
        require(deadline > dt.datetime.now(dt.timezone.utc), "openclaw_current_information_expired")
        contract['expires_at'] = min(dt.datetime.fromisoformat(contract['expires_at']), deadline).isoformat()
    if bootstrap:
        contract["native_thread_binding"] = "first_turn"
    elif mission.get("recovery"):
        contract["recovery"] = {**mission["recovery"], "repo_root": str(root.resolve()),
            "approved_head": b["base_head"], "action_path": b["action_path"],
            "action_sha256": b["action_sha256"],
            "config_sha256": hashlib.sha256((root / "wiki.config.yaml").read_bytes()).hexdigest()}
    write_new(directory / "mission.json", contract)
    contract_sha = hashlib.sha256(receipt_bytes(directory / "mission.json")).hexdigest()
    with mission_mutex(directory):
        write_new(directory.parent / "mission-active.json", {"run_id": prepared["effect_key"], "contract_sha256": contract_sha})
    # Selection is followed by actual native turn/inference guards. This patch
    # alone is not a model lock. Physical-session CAS preserves the route.
    stage = "selection"
    try:
        gateway.call("sessions.patch", {"key": route["session_key"], "expectedSessionId": route["session_id"],
                                       "model": mission["model"], "thinkingLevel": mission["effort"]})
        # An uncertain transport leaves durable intent. Never retry chat.send.
        stage = "send"
        result = gateway.call("chat.send", {"sessionKey": route["session_key"], "message": prepared["message"],
            "expectedLeafEntryId": prepared["expected_leaf"], "idempotencyKey": prepared["effect_key"],
            "queueMode": "followup", "deliver": False, "sessionId": route["session_id"],
            "thinking": mission["effort"], "suppressCommandInterpretation": True, "wikiMission": contract_sha})
    except GatewayRequestError as exc:
        write_new(directory / "dispatch-error.json", {"schema_version": "wiki_openclaw_dispatch_error.v1",
            "run_id": prepared["effect_key"], "plan_sha256": digest(prepared), "stage": stage,
            "diagnostic": exc.diagnostic, "observed_at": dt.datetime.now(dt.timezone.utc).isoformat()})
        raise
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
    # A legacy result can still be inspected after adding a guard. Only the
    # additive mission policy is ignored, never a changed destination/runtime.
    previous_runtime = copy.deepcopy(runtime)
    collected_bootstrap = None
    if "mission" not in plan:
        previous_runtime.pop("mission_options", None)
        for prior_route in previous_runtime["routes"].values():
            prior_route.pop("native_thread_id", None)
    elif (plan["mission"].get("native_thread_binding") == "first_turn"
          and route.get("native_thread_id") and "native_thread_binding" not in route):
        require((directory / "result.json").exists(), "openclaw_route_changed")
        claim = read_receipt(directory / "guard-turn.json")
        require(route["native_thread_id"] == claim.get("thread_id"), "openclaw_route_changed")
        collected_bootstrap = read_receipt(directory / "result.json")
        prior_route = previous_runtime["routes"][params["profile"]]
        prior_route.pop("native_thread_id")
        prior_route["native_thread_binding"] = "first_turn"
    identity = {k: v for k, v in previous_runtime.items() if k not in {"recovery", "recurring"}}
    legacy_addition = {k: v for k, v in previous_runtime.items() if k not in {"recovery", "recurring"}}
    require((digest(previous_runtime) == plan["route_sha256"]
             or digest(legacy_addition) == plan["route_sha256"]
             or plan.get("runtime_identity_sha256") == digest(identity))
            and previous_runtime["routes"][params["profile"]] == plan["route"], "openclaw_route_changed")
    if collected_bootstrap is not None:
        message_id = collected_bootstrap.get("message_id")
        require(isinstance(message_id, str) and bool(message_id), "openclaw_exact_result_missing")
        data = Gateway(runtime, route).history(messageId=message_id, maxChars=64000, maxBytes=128000)
        verified = verified_result_message(directory, plan, route, message_id, data)
        require({k: v for k, v in collected_bootstrap.items() if k != "captured_at"} ==
                {k: v for k, v in verified.items() if k != "captured_at"}, "openclaw_retained_result_changed")
    if (directory / "accepted.json").exists():
        accepted = read_receipt(directory / "accepted.json")
        require(accepted["plan_sha256"] == intent["plan_sha256"] and accepted["run_id"] == plan["effect_key"],
                "openclaw_acceptance_changed")
    return directory, plan, runtime, route


def recovery_claim(directory, plan):
    file = directory / "guard-recovery.json"
    if not file.exists():
        return None
    claim = read_receipt(file)
    contract = read_receipt(directory / "mission.json")
    original = read_receipt(directory / "guard-bound-turn.json")
    sha = hashlib.sha256(receipt_bytes(directory / "mission.json")).hexdigest()
    selected = plan["mission"]
    require(contract.get("recovery", {}).get("mode") == "read_only"
            and contract["recovery"].get("max_continuations") == 1
            and claim.get("schema_version") == "wiki_openclaw_recovery.v1"
            and claim.get("run_id") == plan["effect_key"]
            and claim.get("session_id") == plan["route"]["session_id"]
            and claim.get("thread_id") == selected["native_thread_id"]
            and claim.get("source_turn_id") == original.get("turn_id")
            and isinstance(original.get("turn_id"), str) and bool(original["turn_id"])
            and original.get("run_id") == plan["effect_key"]
            and original.get("thread_id") == selected["native_thread_id"]
            and original.get("contract_sha256") == sha
            and original.get("session_id", plan["route"]["session_id"]) == plan["route"]["session_id"]
            and claim.get("contract_sha256") == sha
            and claim.get("model") == selected["model"].split("/", 1)[1]
            and claim.get("effort") == selected["effort"]
            and isinstance(claim.get("native_run_id"), str)
            and re.fullmatch(r"[a-f0-9-]{36}", claim["native_run_id"]),
            "openclaw_recovery_lineage_unproven")
    if (directory / "guard-recovery-turn.json").exists():
        turn = read_receipt(directory / "guard-recovery-turn.json")
        require(turn.get("native_run_id") == claim["native_run_id"]
                and turn.get("run_id") == claim["run_id"]
                and turn.get("contract_sha256") == sha,
                "openclaw_recovery_lineage_unproven")
    return claim


def verified_mission_guard(directory, plan, native_run_id=None):
    """Verify the retained turn/inference/terminal chain without native calls."""
    if "mission" not in plan:
        return
    contract = read_receipt(directory / "mission.json")
    sha = hashlib.sha256(receipt_bytes(directory / "mission.json")).hexdigest()
    selected = plan["mission"]
    claim = read_receipt(directory / "guard-turn.json")
    thread_id = claim.get("thread_id")
    bootstrap = selected.get("native_thread_binding") == "first_turn"
    require(isinstance(thread_id, str) and len(thread_id) > 8
            and (bootstrap or thread_id == selected["native_thread_id"]), "openclaw_mission_selection_unproven")
    if bootstrap:
        require(selected["native_thread_id"] is None and plan["expected_leaf"] is None
                and contract.get("native_thread_binding") == "first_turn" and contract.get("native_thread_id") is None, "openclaw_bootstrap_unproven")
        for name in ("guard-bootstrap-admission.json", "guard-bootstrap-start.json", "guard-bootstrap-thread.json"):
            proof = read_receipt(directory / name)
            require(proof.get("run_id") == plan["effect_key"] and proof.get("session_id") == plan["route"]["session_id"]
                    and proof.get("contract_sha256") == sha, "openclaw_bootstrap_unproven")
            if name == "guard-bootstrap-thread.json":
                require(proof.get("thread_id") == thread_id and proof.get("model") == claim.get("model"), "openclaw_bootstrap_unproven")
    require(contract["plan_sha256"] == digest(plan) and claim.get("contract_sha256") == sha
            and claim.get("run_id") == plan["effect_key"] and claim.get("session_id") == plan["route"]["session_id"]
            and claim.get("model") == selected["model"].split("/", 1)[1]
            and claim.get("effort") == selected["effort"], "openclaw_mission_selection_unproven")
    recovered = native_run_id is not None and native_run_id != plan["effect_key"]
    recovery = recovery_claim(directory, plan) if recovered else None
    require(not recovered or recovery and recovery["native_run_id"] == native_run_id,
            "openclaw_recovery_lineage_unproven")
    prefix = "guard-recovery-" if recovered else "guard-"
    bound = read_receipt(directory / (prefix + "bound-turn.json"))
    terminal = read_receipt(directory / (prefix + "terminal.json"))
    if recovered:
        resumed = read_receipt(directory / "guard-recovery-turn.json")
        require(all(resumed.get(k) == claim.get(k) for k in ("run_id", "session_id", "thread_id", "model", "effort", "contract_sha256"))
                and resumed.get("native_run_id") == native_run_id,
                "openclaw_recovery_lineage_unproven")
    require(isinstance(bound.get("turn_id"), str) and bool(bound["turn_id"]), "openclaw_mission_turn_unproven")
    for record in (bound, terminal):
        require(record.get("run_id") == plan["effect_key"] and record.get("thread_id") == claim["thread_id"]
                and record.get("contract_sha256") == sha and record.get("turn_id") == bound["turn_id"],
                "openclaw_mission_turn_unproven")
        require(not recovered or record.get("native_run_id") == native_run_id,
                "openclaw_recovery_lineage_unproven")
    require(terminal.get("status") == "completed", "openclaw_mission_terminal_unproven")
    lines = receipt_bytes(directory / (prefix + "inference.jsonl")).decode().splitlines()
    require(bool(lines), "openclaw_mission_inference_unproven")
    for line in lines:
        item = json.loads(line)
        require(item.get("contract_sha256") == sha and item.get("run_id") == plan["effect_key"]
                and item.get("thread_id") == thread_id
                and item.get("model") == claim["model"] and item.get("effort") == claim["effort"]
                and item.get("turn_id") == bound["turn_id"] and item.get("path") in {"/responses", "/responses/compact"},
                "openclaw_mission_selection_unproven")
        require(not recovered or item.get("native_run_id") == native_run_id,
                "openclaw_recovery_lineage_unproven")
    if recovered and (directory / "guard-inference.jsonl").exists():
        original = read_receipt(directory / "guard-bound-turn.json")
        for line in receipt_bytes(directory / "guard-inference.jsonl").decode().splitlines():
            item = json.loads(line)
            require(item.get("run_id") == plan["effect_key"] and item.get("contract_sha256") == sha
                    and item.get("thread_id") == thread_id and item.get("turn_id") == original["turn_id"]
                    and item.get("model") == claim["model"] and item.get("effort") == claim["effort"]
                    and item.get("path") in {"/responses", "/responses/compact"},
                    "openclaw_mission_selection_unproven")
    return claim


def verify_mission_selection(directory, plan, message, native_run_id=None):
    claim = verified_mission_guard(directory, plan, native_run_id)
    if claim is not None:
        require(message.get("model") == claim["model"], "openclaw_mission_selection_unproven")


def verified_result_message(directory, plan, route, message_id, data):
    """Verify the exact native message and guard chain before trusting a receipt."""
    require(len(data.get("messages", [])) == 1, "openclaw_exact_result_missing")
    message = data["messages"][0]
    meta = message.get("__openclaw", {})
    recovery = recovery_claim(directory, plan)
    native_run_id = recovery["native_run_id"] if recovery and meta.get("runId") == recovery["native_run_id"] else plan["effect_key"]
    require(message.get("role") == "assistant" and meta.get("runId") == native_run_id
            and meta.get("id") == message_id and meta.get("runTerminal") and not meta.get("truncated")
            and message.get("stopReason") == "stop" and not message.get("errorMessage"), "openclaw_result_not_complete")
    verify_mission_selection(directory, plan, message, native_run_id)
    content = message.get("content", [])
    require(content and all(c.get("type") == "text" for c in content), "openclaw_text_result_required")
    text = "\n".join(c["text"] for c in content)
    _assert_no_secrets(text)
    return {"action_id": plan["binding"]["action_id"], "effect_key": plan["effect_key"], "run_id": plan["effect_key"],
            **({"native_run_id": native_run_id, "recovery": "native_continuation"} if native_run_id != plan["effect_key"] else {}),
            "plan_sha256": digest(plan), "session_id": route["session_id"], "message_id": message_id,
            "text": text, "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "captured_at": dt.datetime.now(dt.timezone.utc).isoformat()}


@contextmanager
def mission_mutex(directory):
    directory.parent.mkdir(parents=True, exist_ok=True)
    with _action_file_lock(directory.parent, "openclaw-mission"):
        yield



def release_mission_lock(directory, plan):
    if "mission" not in plan:
        return
    with mission_mutex(directory):
        _release_mission_lock_locked(directory, plan)


def _release_mission_lock_locked(directory, plan):
    if "mission" not in plan:
        return
    active = directory.parent / "mission-active.json"
    if not active.exists():
        return
    value = read_receipt(active)
    if value.get("run_id") != plan["effect_key"]:
        return
    require(value.get("contract_sha256") == hashlib.sha256(receipt_bytes(directory / "mission.json")).hexdigest(),
            "openclaw_mission_lock_changed")
    active.unlink()


def inspect(root, config, params):
    """Reconcile one retained run, including after an operator restart."""
    directory, plan, runtime, route = retained_intent(root, config, params)
    if (directory / "failure-resolution.json").exists():
        resolution = verified_failure_resolution(directory, plan, root)
        return {"action_id": params["action_id"], "effect_key": params["effect_key"],
                "status": "resolved_without_result", "reconciled": True, "result_available": False,
                "resolution": resolution, "new_dispatch": False, "canonical_write": False}
    gateway = Gateway(runtime, route)
    history = gateway.history()
    info = history["sessionInfo"]
    recovery = recovery_claim(directory, plan)
    native_run_id = recovery["native_run_id"] if recovery else plan["effect_key"]
    observed = {"action_id": params["action_id"], "effect_key": params["effect_key"],
                "status": info.get("status"), "active": info.get("hasActiveRun"),
                "same_run": info.get("lastRunId") == native_run_id, "new_dispatch": False,
                **({"native_run_id": native_run_id, "recovery": "native_continuation"} if recovery else {}),
                "canonical_write": False}
    # Once captured, its exact message stays readable even if later activity
    # has advanced the session. Its identity is still checked natively.
    old = read_receipt(directory / "result.json") if (directory / "result.json").exists() else None
    if old is None and not (observed["same_run"] and observed["active"] is False and observed["status"] == "done"):
        return {**observed, "result_available": False}
    message_id = old["message_id"] if old else info.get("activeLeafEntryId")
    data = gateway.history(messageId=message_id, maxChars=64000, maxBytes=128000)
    result = verified_result_message(directory, plan, route, message_id, data)
    if old:
        require({k: v for k, v in old.items() if k != "captured_at"} ==
                {k: v for k, v in result.items() if k != "captured_at"}, "openclaw_retained_result_changed")
        result = old
    else:
        write_new(directory / "result.json", result)
    release_mission_lock(directory, plan)
    try:
        current = binding(root, config, params["profile"], params["action_id"])
        hold = None if current == plan["binding"] else "canonical_context_changed"
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        hold = "canonical_state_unavailable_or_ineligible"
    return {**observed, "result_available": True, "result": result, "integration_hold": hold,
            "idempotent_read": old is not None, "documentary_integration": "pending_review"}


def retained_attempt(root, config, path, intent, *, include_details=False):
    """Verify one local attempt for both command preflight and observation."""
    plan = intent["plan"]
    require(digest(plan) == intent.get("plan_sha256") and plan["effect_key"] == path.parent.name,
            "openclaw_intent_changed")
    require(isinstance(intent.get("attempted_at"), str), "openclaw_receipt_corrupt_reconcile")
    directory = storage(root, config, plan["effect_key"])
    result = verified_result(directory, plan) if (directory / "result.json").exists() else None
    resolved = (directory / "failure-resolution.json").exists()
    resolution = verified_failure_resolution(directory, plan, root) if resolved else None
    value = {"effect_key": plan["effect_key"], "attempted_at": intent["attempted_at"],
            "has_result": result is not None, "reconciled": result is not None or resolved,
            "resolved_without_result": resolved, "result_captured_at": result.get("captured_at") if result else None,
            "proposal": proposal_status(root, config, directory, plan)}
    if not include_details:
        return value
    guard = {"status": "not_observed", "model": None, "effort": None, "error_code": None}
    if "mission" in plan and any(directory.glob("guard-*.json")):
        try:
            # A complete retained chain proves historical guard admission, not
            # current execution or a currently valid administrative grant.
            claim = verified_mission_guard(directory, plan, result.get("native_run_id") if result else None)
            guard.update(status="retained_chain_verified", model=claim["model"], effort=claim["effort"])
        except (ValueError, KeyError, TypeError, AttributeError, OSError):
            guard.update(status="unavailable", error_code="retained_guard_chain_unavailable")
    return {**value, "run_id": plan["effect_key"],
        "action_path": _safe(root, plan["binding"]["action_path"]).relative_to(root).as_posix(),
        "result": {"excerpt": result["text"][:MAX_RESULT_EXCERPT_CHARS], "text_sha256": result["text_sha256"],
                   "truncated": len(result["text"]) > MAX_RESULT_EXCERPT_CHARS} if result else None,
        "authorization": {"status": "not_observed"}, "guard_admission": guard,
        "review": {"status": "failure_resolution_reviewed" if resolution else "not_observed",
                   "head": resolution["review"]["head"] if resolution else None}}


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
            found.append(retained_attempt(root, config, path, intent))
    return found


def transport_observation(config):
    """Connect to the allowlisted loopback port, without protocol bytes or auth.

    A TCP listener is not proof of Gateway identity, readiness or model activity.
    Native chat.history can reconcile; sessions.describe can certify SQLite
    canonical readiness. Neither is admitted to this read-only observation.
    """
    runtime = validated_config(config.openclaw)
    value = {"status": "not_configured", "scope": "loopback_tcp_only",
             "observed_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    if not runtime["enabled"]:
        return value
    address = urlsplit(runtime["gateway"])
    try:
        with socket.create_connection((address.hostname, address.port), timeout=2):
            pass
        value["status"] = "reachable"
    except OSError:
        value["status"] = "unreachable"
    return value


def runtime_observations(root, config):
    """Project retained evidence only. Never call native APIs or any writer."""
    from wiki_core.web.openclaw_recurring import latest_wakes
    runtime = validated_config(config.openclaw)
    value = {"configured": runtime["enabled"], "observation_scope": "retained_local_evidence",
             "gateway_status": "not_observed", "active_run": None, "pending_inputs": None,
             "usage": {"status": "not_measured", "tokens": None, "cost": None},
             "attempts": [], "rules": [], "native_observations": [], "errors": []}
    if not runtime["enabled"]:
        return value
    value["native_observations"] = [
        {"profile": profile, "observed_at": None, "status": "unavailable",
         "has_active_run": None, "active_run_ids": None, "session_status": None,
         "error_code": "native_read_api_may_write"} for profile in runtime["routes"]]
    try:
        parent = storage(root, config, "wiki-run-" + "0" * 32).parent
    except (OSError, ValueError):
        value["errors"].append("openclaw_receipt_unavailable_reconcile")
        parent = None
    for path in sorted(parent.glob("wiki-run-*/intent.json")) if parent else ():
        try:
            _safe(root, path.relative_to(root).as_posix())
            intent = read_receipt(path)
            plan = intent["plan"]
            require(digest(plan) == intent["plan_sha256"], "openclaw_intent_changed")
            profile, action_id = plan["binding"]["profile"], plan["binding"]["action_id"]
            require(isinstance(profile, str) and isinstance(action_id, str), "openclaw_receipt_corrupt_reconcile")
            if profile in runtime["routes"]:
                attempt = retained_attempt(root, config, path, intent, include_details=True)
                # Timestamps are observations, never a liveness assertion.
                for timestamp in (attempt["attempted_at"], attempt["result_captured_at"]):
                    if timestamp is not None:
                        require(dt.datetime.fromisoformat(timestamp.replace("Z", "+00:00")).tzinfo is not None,
                                "openclaw_receipt_corrupt_reconcile")
                value["attempts"].append({**attempt, "profile": profile, "action_id": action_id,
                    "status": "result_retained" if attempt["has_result"] else
                              "resolved_without_result" if attempt["resolved_without_result"] else "awaiting_reconciliation"})
        except (ValueError, KeyError, TypeError, AttributeError, OSError, subprocess.SubprocessError):
            value["errors"].append("openclaw_receipt_unavailable_reconcile")
    value["attempts"].sort(key=lambda row: row["attempted_at"], reverse=True)
    wakes, error = latest_wakes(root, config) if runtime.get("recurring") else ({}, None)
    if error:
        value["errors"].append(error)
    for rule_id, rule in runtime.get("recurring", {}).items():
        wake = wakes.get(rule_id)
        expected = None
        if wake:
            expected = (dt.datetime.fromisoformat(wake["observed_at"].replace("Z", "+00:00"))
                        + dt.timedelta(minutes=rule["interval_minutes"])).isoformat()
        value["rules"].append({"rule_id": rule_id, "profile": rule["profile"],
            "action_id": rule["action_id"], "interval_minutes": rule["interval_minutes"],
            "last_wake": wake, "next_expected_observation_at": expected,
            "scheduler_status": "not_observed"})
    value["errors"] = sorted(set(value["errors"]))
    return value


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


def validate_failure_review(review, plan, head, action_sha256):
    require(isinstance(review, dict), "openclaw_independent_failure_review_required")
    fields = {"schema_version", "head", "plan_sha256", "action_id", "action_sha256", "run_id", "session_id",
              "author", "reviewer", "decision", "evidence_path", "evidence_sha256", "reason", "limits"}
    require(set(review) == fields and review["schema_version"] == "wiki_openclaw_failure_review.v1" and
            review["head"] == head and review["plan_sha256"] == digest(plan) and
            review["action_id"] == plan["binding"]["action_id"] and review["action_sha256"] == action_sha256 and
            review["run_id"] == plan["effect_key"] and review["session_id"] == plan["route"]["session_id"] and
            review["decision"] == "resolve_without_result" and
            all(isinstance(review[k], str) and 8 <= len(review[k].strip()) <= 8192
                for k in ("author", "reviewer", "reason", "limits")) and
            review["author"].strip() != review["reviewer"].strip(), "openclaw_independent_failure_review_required")


def validate_failure_evidence(evidence, plan, directory=None):
    require(isinstance(evidence, dict), "openclaw_preserved_terminal_error_required")
    if evidence.get("status") in {"expired_unaccepted", "expired_interrupted"}:
        require(set(evidence) == {"status", "runId", "contract_sha256", "expires_at"}
                and evidence["runId"] == plan["effect_key"] and "mission" in plan
                and isinstance(evidence["contract_sha256"], str)
                and re.fullmatch(r"[a-f0-9]{64}", evidence["contract_sha256"])
                and isinstance(evidence["expires_at"], str), "openclaw_expired_mission_evidence_required")
        try:
            expires = dt.datetime.fromisoformat(evidence["expires_at"].replace("Z", "+00:00"))
            require(expires.tzinfo is not None and expires <= dt.datetime.now(dt.timezone.utc),
                    "openclaw_mission_not_expired")
        except (TypeError, ValueError):
            raise RuntimeErrorCode("openclaw_mission_not_expired") from None
        return
    recovery = recovery_claim(directory, plan) if directory is not None else None
    expected_run = recovery["native_run_id"] if recovery else plan["effect_key"]
    require(set(evidence) == {"status", "runId", "startedAt", "endedAt", "error"} and
            evidence["status"] == "error" and evidence["runId"] == expected_run and
            type(evidence["startedAt"]) is int and type(evidence["endedAt"]) is int and
            0 < evidence["startedAt"] <= evidence["endedAt"] <= int(dt.datetime.now(dt.timezone.utc).timestamp()*1000) and
            (evidence["error"] is None or
             isinstance(evidence["error"], str) and 0 < len(evidence["error"]) <= 2048),
            "openclaw_preserved_terminal_error_required")


def validate_expired_unaccepted(directory, plan, evidence, root=None):
    """No fabricated terminal: a now-unadmittable contract with no guarded turn."""
    validate_failure_evidence(evidence, plan)
    require(evidence.get("status") == "expired_unaccepted"
            and not (directory / "accepted.json").exists()
            and not (directory / "result.json").exists()
            and not any(directory.glob("guard-*")), "openclaw_unaccepted_mission_not_eligible")
    validate_expired_contract(directory, plan, evidence, root)


def validate_expired_contract(directory, plan, evidence, root):
    raw = receipt_bytes(directory / "mission.json")
    contract = parse_receipt(raw.decode())
    expected = {"schema_version": "wiki_openclaw_mission.v1", "run_id": plan["effect_key"],
        "session_key": plan["route"]["session_key"], "session_id": plan["route"]["session_id"],
        "native_thread_id": plan["mission"]["native_thread_id"],
        "provider": plan["mission"]["model"].split("/", 1)[0],
        "model": plan["mission"]["model"].split("/", 1)[1], "effort": plan["mission"]["effort"],
        "message_sha256": plan["message_sha256"], "plan_sha256": digest(plan),
        "action_id": plan["binding"]["action_id"], "action_sha256": plan["binding"]["action_sha256"],
        "expires_at": evidence["expires_at"]}
    if plan["mission"].get("native_thread_binding") == "first_turn":
        expected["native_thread_binding"] = "first_turn"
    elif plan["mission"].get("recovery"):
        b = plan["binding"]
        require(root is not None, "openclaw_recovery_root_required")
        original_config = subprocess.check_output(["git", "show", b["base_head"] + ":wiki.config.yaml"],
                                                   cwd=root, stderr=subprocess.DEVNULL)
        # The root recorded in this immutable contract is compared to the
        # original approved checkout by the planner's independently reviewed bytes.
        expected["recovery"] = {**plan["mission"]["recovery"], "repo_root": str(root.resolve()),
            "approved_head": b["base_head"], "action_path": b["action_path"], "action_sha256": b["action_sha256"],
            "config_sha256": hashlib.sha256(original_config).hexdigest()}
    require(contract == expected and hashlib.sha256(raw).hexdigest() == evidence["contract_sha256"],
            "openclaw_expired_mission_changed")



def validate_expired_interrupted(directory, plan, evidence, root):
    """Expired admitted original, no continuation or manufactured terminal."""
    validate_failure_evidence(evidence, plan)
    require(evidence.get('status') == 'expired_interrupted' and 'mission' in plan
            and not plan['mission'].get('native_thread_binding')
            and plan['mission'].get('recovery') == {'mode':'read_only','max_continuations':1}
            and not (directory/'result.json').exists()
            and not (directory/'guard-terminal.json').exists(),
            'openclaw_interrupted_mission_not_eligible')
    validate_expired_contract(directory, plan, evidence, root)
    accepted=read_receipt(directory/'accepted.json')
    require(accepted.get('plan_sha256') == digest(plan) and accepted.get('run_id') == plan['effect_key'],
            'openclaw_acceptance_changed')
    claim=read_receipt(directory/'guard-turn.json');bound=read_receipt(directory/'guard-bound-turn.json')
    selected=plan['mission'];sha=evidence['contract_sha256']
    require(claim.get('run_id') == plan['effect_key'] and claim.get('session_id') == plan['route']['session_id']
            and claim.get('thread_id') == selected['native_thread_id'] and claim.get('contract_sha256') == sha
            and claim.get('model') == selected['model'].split('/',1)[1] and claim.get('effort') == selected['effort']
            and bound.get('run_id') == plan['effect_key'] and bound.get('thread_id') == claim['thread_id']
            and bound.get('contract_sha256') == sha and isinstance(bound.get('turn_id'),str) and bool(bound['turn_id']),
            'openclaw_mission_selection_unproven')
    lines=receipt_bytes(directory/'guard-inference.jsonl').decode().splitlines()
    require(bool(lines),'openclaw_mission_inference_unproven')
    for line in lines:
        item=json.loads(line)
        require(all(item.get(k) == claim.get(k) for k in ('run_id','thread_id','contract_sha256','model','effort'))
                and item.get('turn_id') == bound['turn_id'] and item.get('path') in {'/responses','/responses/compact'}
                and not item.get('native_run_id'), 'openclaw_mission_selection_unproven')
    interrupted_recovery_preparation(directory, plan)


def interrupted_recovery_preparation(directory, plan):
    """A sole preparation is not a terminal or evidence of admitted model work."""
    files = list(directory.glob('guard-recovery*'))
    if not files:
        return None
    require({p.name for p in files} == {'guard-recovery.json'},
            'openclaw_interrupted_mission_not_eligible')
    claim = recovery_claim(directory, plan)
    require(set(claim) == {'schema_version','run_id','native_run_id','session_id','thread_id',
                          'source_turn_id','contract_sha256','model','effort'}, 'openclaw_recovery_lineage_unproven')
    require(re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', claim['native_run_id'])
            and claim['native_run_id'] != plan['effect_key'], 'openclaw_recovery_lineage_unproven')
    return {'native_run_id': claim['native_run_id'],
            'sha256': hashlib.sha256(receipt_bytes(directory/'guard-recovery.json')).hexdigest()}


def interrupted_observation(gateway, history, plan):
    info=history['sessionInfo'];leaf=idle_leaf(history)
    require(info.get('status') == 'interrupted' and info.get('lastRunId') in (None,plan['effect_key']),
            'openclaw_interrupted_native_state_changed')
    exact=gateway.history(messageId=leaf,maxChars=1,toolResultMaxChars=1)
    messages=exact.get('messages',[])
    pending,_,_=pending_page(exact)
    queued=pending.get('queuedCount',pending['total'])
    require(type(queued) is int and queued == 0, 'openclaw_interrupted_native_state_changed')
    require(len(messages)==1 and exact['sessionInfo'].get('hasActiveRun') is False
            and exact['sessionInfo'].get('status') == 'interrupted'
            # Native messageId reads use a physical snapshot projection with
            # no active leaf. Current liveness belongs to both complete live reads.
            and exact['sessionInfo'].get('activeLeafEntryId') in (None,leaf)
            and exact['sessionInfo'].get('lastRunId') == info.get('lastRunId')
            and messages[0].get('__openclaw',{}).get('id') == leaf
            and messages[0].get('__openclaw',{}).get('runId') == plan['effect_key'],
            'openclaw_interrupted_native_state_changed')
    latest=idle_history(gateway)
    require(all(latest['sessionInfo'].get(k) == info.get(k)
                for k in ('status','hasActiveRun','activeLeafEntryId','lastRunId')),
            'openclaw_interrupted_native_state_changed')
    return {'status':'interrupted','leaf_run_id':plan['effect_key']}


def verified_failure_resolution(directory, plan, root=None):
    value = read_receipt(directory / "failure-resolution.json")
    require(not (directory / "result.json").exists() and
            value.get("schema_version") == "wiki_openclaw_failure_resolution.v1" and
            value.get("status") == "resolved_without_result" and
            value.get("plan_sha256") == digest(plan) and
            value.get("effect_key") == plan["effect_key"] and
            value.get("session_id") == plan["route"]["session_id"] and
            value.get("action_id") == plan["binding"]["action_id"] and
            value.get("evidence_basis") == "preserved_observation_independently_reviewed" and
            value.get("external_effects") == "not_determined_by_this_receipt" and
            value.get("review_sha256") == digest(value.get("review")) and
            value.get("evidence_sha256") == digest(value.get("evidence")),
            "openclaw_failure_resolution_changed")
    review = value.get("review")
    require(isinstance(review, dict), "openclaw_failure_resolution_changed")
    validate_failure_review(review, plan, review.get("head"), review.get("action_sha256"))
    validate_failure_evidence(value.get("evidence"), plan, directory)
    if value["evidence"].get("status") == "expired_unaccepted":
        validate_expired_unaccepted(directory, plan, value["evidence"], root)
    elif value['evidence'].get('status') == 'expired_interrupted':
        validate_expired_interrupted(directory, plan, value['evidence'], root)
        require(value.get('observation',{}).get('status') == 'interrupted'
                and value['observation'].get('leaf_run_id') == plan['effect_key']
                and value['observation'].get('session_id') == plan['route']['session_id'],
                'openclaw_failure_resolution_changed')
        require(value.get('observation',{}).get('recovery_preparation') ==
                interrupted_recovery_preparation(directory, plan), 'openclaw_failure_resolution_changed')
    raw = value.get("evidence_raw")
    require(isinstance(raw, str) and hashlib.sha256(raw.encode()).hexdigest() == review.get("evidence_sha256")
            and parse_receipt(raw) == value["evidence"], "openclaw_failure_resolution_changed")
    require(isinstance(review.get("head"), str) and re.fullmatch(r"[0-9a-f]{40}", review["head"])
            and isinstance(review.get("action_sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", review["action_sha256"]), "openclaw_failure_resolution_changed")
    return value


def plan_failure_resolution(root, config, params):
    """An explicit reviewed recovery, not a reconstructed native final answer."""
    directory, plan, runtime, route = retained_intent(root, config, params)
    require(not (directory / "result.json").exists(), "openclaw_failure_resolution_not_eligible")
    current = binding(root, config, params["profile"], params["action_id"])
    require(git(root, "branch", "--show-current") == str(config.approval.get("default_branch") or "main"),
            "openclaw_resolution_requires_approved_checkout")
    derived = WikiPaths(root, config).derived_root
    path = _safe(root, params["review_path"])
    require(path.is_relative_to(derived), "openclaw_review_must_be_derived")
    review, _ = reviewed_receipt(path, params["review_sha256"])
    validate_failure_review(review, plan, current["base_head"], current["action_sha256"])
    evidence_path = _safe(root, review["evidence_path"])
    require(evidence_path.is_relative_to(derived), "openclaw_evidence_must_be_derived")
    evidence, evidence_raw = reviewed_receipt(evidence_path, review["evidence_sha256"])
    validate_failure_evidence(evidence, plan, directory)
    expired_interrupted = evidence.get('status') == 'expired_interrupted'
    if expired_interrupted:
        validate_expired_interrupted(directory, plan, evidence, root)
        if (directory/'failure-resolution.json').exists():
            verified_failure_resolution(directory, plan, root)
        else:
            active=read_receipt(directory.parent/'mission-active.json')
            require(active == {'run_id':plan['effect_key'],'contract_sha256':evidence['contract_sha256']},
                    'openclaw_mission_lock_changed')
    expired_unaccepted = evidence.get("status") == "expired_unaccepted"
    if expired_unaccepted:
        validate_expired_unaccepted(directory, plan, evidence, root)
    else:
        require((directory / "accepted.json").exists(), "openclaw_failure_resolution_not_eligible")
    gateway = Gateway(runtime, route)
    allow_empty = expired_unaccepted and plan["mission"].get("native_thread_binding") == "first_turn"
    history = idle_history(gateway, allow_empty=allow_empty)
    if expired_unaccepted:
        require(idle_leaf(history, allow_empty=allow_empty) == plan["expected_leaf"]
                and history["sessionInfo"].get("lastRunId") != plan["effect_key"]
                and not any(row.get("runId") == plan["effect_key"]
                            for row in history["pendingInputs"].get("items", [])),
                "openclaw_unaccepted_native_state_changed")
    interrupted = interrupted_observation(gateway, history, plan) if expired_interrupted else {}
    observation = {**interrupted, "leaf": idle_leaf(history, allow_empty=allow_empty), "session_id": history["sessionId"],
                   "last_run": history["sessionInfo"].get("lastRunId"),
                   "pending": [{k: row.get(k) for k in ("id", "runId", "state")}
                               for row in history["pendingInputs"].get("items", [])]}
    if expired_interrupted:
        preparation = interrupted_recovery_preparation(directory, plan)
        if preparation:
            observation['recovery_preparation'] = preparation
    return {"plan": plan, "review": review, "evidence": evidence, "evidence_raw": evidence_raw, "observation": observation,
            "canonical_write": False, "new_dispatch": False,
            "external_effects": "not_determined_by_this_receipt"}


def resolve_failed(root, config, params, prepared):
    # Current native authority surrounds this entire effect. Changed evidence,
    # physical session, queue or canonical inputs refuse before persistence.
    directory = storage(root, config, params['effect_key'])
    with mission_mutex(directory):
        current = plan_failure_resolution(root, config, params)
        require(current == prepared, "openclaw_failure_resolution_inputs_changed")
        directory = storage(root, config, params["effect_key"])
        plan = current["plan"]
        if (directory / "failure-resolution.json").exists():
            value = verified_failure_resolution(directory, plan, root)
            require(value["review"] == current["review"] and value["evidence"] == current["evidence"],
                    "openclaw_failure_resolution_changed")
        else:
            value = {"schema_version": "wiki_openclaw_failure_resolution.v1", "status": "resolved_without_result",
                     "effect_key": plan["effect_key"], "action_id": plan["binding"]["action_id"],
                     "session_id": plan["route"]["session_id"], "plan_sha256": digest(plan),
                     "evidence_basis": "preserved_observation_independently_reviewed",
                     "external_effects": "not_determined_by_this_receipt", "review": current["review"],
                     "review_sha256": digest(current["review"]), "evidence": current["evidence"],
                     "evidence_sha256": digest(current["evidence"]), "evidence_raw": current["evidence_raw"], "observation": current["observation"],
                     "recorded_at": dt.datetime.now(dt.timezone.utc).isoformat()}
            # Re-read immediately before the atomic local receipt; no provider write.
            require(plan_failure_resolution(root, config, params) == current, "openclaw_failure_resolution_inputs_changed")
            write_new(directory / "failure-resolution.json", value)
        _release_mission_lock_locked(directory, plan)
        return {"action_id": params["action_id"], "effect_key": params["effect_key"], "reconciled": True,
                "status": "resolved_without_result", "result_available": False, "new_dispatch": False,
                "canonical_write": False, "resolution": value}


def _main_body_progress(root, plan, received, current):
    """Derive approved body incorporation from existing writer/Git transitions.

    Received material is a native communication, never a factual contribution.
    Validate real Git segments so an integration followed by an editorial
    consolidation in a later commit does not require relaxing their validator.
    """
    from wiki_core.action_transition import action_transition_diagnostics, operational_comment_receipt
    old, old_body = _parse_document(received)
    new, new_body = _parse_document(current)
    history = old.get("action_state_history", [])
    if (new.get("page_id") != plan["binding"]["action_id"]
            or new.get("action_state_history", [])[:len(history)] != history
            or new.get("action_dialogue", [])[:len(old.get("action_dialogue", []))] != old.get("action_dialogue", [])):
        return False, False
    sha = lambda text: hashlib.sha256(text.encode()).hexdigest()
    states = {sha(received): False}
    action = plan["binding"]["action_path"]
    revisions = git(root, "rev-list", "--reverse", "--topo-order", "--full-history",
                    plan["binding"]["base_head"] + "..HEAD", "--", action).splitlines()
    # Only changes of this action count; unrelated repository history does not.
    require(len(revisions) <= 1024, "openclaw_incorporation_history_budget")
    def blob(revision):
        return subprocess.check_output(["git", "show", revision + ":" + action],
            cwd=root, stderr=subprocess.DEVNULL).decode()
    for revision in revisions:
        after = blob(revision)
        if sha(after) in states:
            continue
        for parent in git(root, "show", "-s", "--format=%P", revision).split():
            before = blob(parent)
            if sha(before) not in states:
                # The normal proposal may commit the receipt and its later
                # curation together. The virtual boundary is exact native bytes.
                if operational_comment_receipt(before, received) is None:
                    continue
                before = received
            if action_transition_diagnostics(before, after):
                continue
            previous, before_body = _parse_document(before)
            next_fm, after_body = _parse_document(after)
            additions = next_fm.get("action_state_history", [])[len(previous.get("action_state_history", [])):]
            content = [e for e in additions if e.get("kind") in {"body_integration", "body_consolidation"}
                       or e.get("page_edit") is not None]
            incorporated = False
            identities_consistent = True
            for event in content:
                metadata = event.get("contribution", {})
                structured = metadata.get("run_ref")
                flat = metadata.get("run_id")
                nested = structured.get("run_id") if isinstance(structured, dict) else None
                if flat is not None and nested is not None and flat != nested:
                    identities_consistent = False
            if len(content) == 1 and content[0].get("kind") in {"body_integration", "body_consolidation"}:
                material = content[0].get("contribution", {})
                run_ref = material.get("run_ref")
                run = material.get("run_id") or (run_ref.get("run_id") if isinstance(run_ref, dict) else None)
                incorporated = (identities_consistent and run == plan["effect_key"] and before_body != after_body
                    and material.get("before_body_sha256") == sha(before_body)
                    and material.get("after_body_sha256") == sha(after_body)
                    and material.get("before_body_revision") != material.get("after_body_revision"))
            # General action diagnostics permit ordinary unreceipted prose
            # edits. They cannot carry this narrower material provenance.
            carry = states[sha(before)] and (before_body == after_body or bool(content)) and identities_consistent
            states[sha(after)] = carry or incorporated
            break
    valid = sha(current) in states
    return valid, bool(valid and states[sha(current)] and new_body != old_body)


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
    ref = subprocess.run(["git", "rev-parse", "--verify", "--quiet", "refs/heads/" + material["branch"]],
                         cwd=root, capture_output=True, text=True)
    require(ref.returncode in {0, 1}, "openclaw_proposal_ref_unavailable")
    proposal_head = ref.stdout.strip() if ref.returncode == 0 else ""
    prepared = bool(proposal_head) and matches(proposal_head)
    # A merged proposal branch is disposable. The prepared action bytes are
    # retained with their output digest, so incorporation can be checked from
    # approved content even after normal branch cleanup or later comments.
    from wiki_core.action_transition import operational_comment_receipt
    action = material["action"]["page_ref"]
    before = subprocess.check_output(["git", "show", material["base_head"] + ":" + action], cwd=root).decode()
    after = saved.get("action_after_text")
    require(isinstance(after, str) and hashlib.sha256(after.encode()).hexdigest() == expected[action],
            "openclaw_material_changed")
    proof = operational_comment_receipt(before, after)
    require(bool(proof) and proof["event_id"] == "received-" + plan["effect_key"],
            "openclaw_receipt_semantics_changed")
    historical = False
    incorporated = False
    if not matched and branch == str(config.approval.get("default_branch") or "main"):
        current_text = subprocess.check_output(["git", "show", "HEAD:" + action], cwd=root).decode()
        old_fm, _ = _parse_document(after)
        current_fm, _ = _parse_document(current_text)
        events = old_fm.get("action_dialogue", [])
        proof_doc = material["documents"][0]["path"]
        try:
            proof_bytes = subprocess.check_output(["git", "show", "HEAD:" + proof_doc], cwd=root, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            # A revocation after switching to main can leave its old approved
            # revision selected. The receipt is still awaiting adoption.
            proof_bytes = None
        valid, incorporated = _main_body_progress(root, plan, after, current_text)
        historical = (proof_bytes is not None
                      and current_fm.get("action_dialogue", [])[:len(events)] == events
                      and valid
                      and hashlib.sha256(proof_bytes).hexdigest() == expected[proof_doc])
    status = "received_in_main" if historical else ("received_in_main" if branch == str(config.approval.get("default_branch") or "main")
              else "prepared") if matched else "awaiting_adoption" if prepared else "material_ready" if (
                  head == material["base_head"] and branch == material["branch"]) else "reconciliation_required"
    if incorporated and str(config.approval.get("gate") or "github_pr") == "github_pr":
        approved = "refs/remotes/origin/" + str(config.approval.get("default_branch") or "main")
        incorporated = subprocess.run(["git", "merge-base", "--is-ancestor", "HEAD", approved], cwd=root,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    result_path = _safe(root, material["documents"][0]["path"]).relative_to(root).as_posix()
    return {"status": status, "content_incorporated_in_main": status == "received_in_main" and incorporated,
            "head": head, "approved_base": material["base_head"],
            "proposal_head": proposal_head, "branch": branch,
            "material_path": saved["material_path"], "material_sha256": saved["material_sha256"],
            "result_path": result_path}


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
        material_raw = (json.dumps(material, ensure_ascii=False, indent=2) + "\n").encode()
        saved = {"material_path": material_file.relative_to(root).as_posix(),
                 "material_sha256": hashlib.sha256(material_raw).hexdigest(),
                 "action_after_text": after,
                 "output_hashes": {ref: hashlib.sha256(raw).hexdigest() for ref, raw in initial["outputs"].items()}}
        # Check the actual UTF-8 serialized size before either recovery file
        # is published. Never leave a manifest that its own reader refuses.
        require(len((json.dumps(saved, ensure_ascii=False, indent=2) + "\n").encode()) <= MAX_RECEIPT_BYTES,
                "openclaw_receipt_material_too_large")
        write_new(material_file, material)
        write_new(manifest, saved)
        return {**saved, "proposal": proposal_status(root, config, directory, plan),
                "action_id": params["action_id"], "effect_key": params["effect_key"],
                "canonical_write": False, "next_command": "wiki.proposal.prepare"}
    finally:
        scratch.unlink(missing_ok=True)
