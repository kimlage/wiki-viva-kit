from __future__ import annotations

import subprocess
import sys
import hashlib
import json
from pathlib import Path
from typing import Any

from wiki_core.config import WikiConfig
from wiki_core.web.commands import SECRET_VALUE_RE
from wiki_core.web.git_ops import build_git_state
from wiki_core.web.source_triage import triage_source
from wiki_core.events import resolve_ingestion_event_identity


READ_STEPS = {"proposal_preview", "ingest_dry_run", "llm_request_preview"}
WRITE_STEPS = {"proposal_write", "llm_request_emit"}


def compose_event_action_preview(event_path: str, event: dict[str, Any], manifest: dict[str, Any],
                                 binding: Any, actions: list[dict[str, Any]], *, repo_id: str) -> dict[str, Any]:
    """Pure composition over explicit, revision-bound inputs. Never admission.

    Titles, context similarity and content hashes are not logical identities.
    Reuse means pointing to one canonical action, not executing/reopening it.
    """
    result: dict[str, Any] = {"status": "unmapped", "reason": "explicit_binding_required",
        "execution_ready": False, "writes": False, "task_ref": None, "preview_key": "",
        "source_checks": {}, "blockers": [], "owner_ref": "", "coordinator": ""}
    fields = {"repo_id", "source_key", "account_id", "context", "event_id", "event_sha256", "action_id", "action_sha256", "owner_ref", "coordinator"}
    if not isinstance(binding, dict) or not fields <= binding.keys() or set(binding) - fields - {"required_sources"}:
        return result
    if any(not isinstance(binding[k], str) or (not binding[k].strip() and k != "action_sha256") or len(binding[k]) > 300 for k in fields):
        return {**result, "reason": "invalid_binding"}
    from wiki_core.action_transition import _assert_no_secrets
    import re
    if any(any(ord(c) < 32 for c in binding[k]) or "://" in binding[k] or re.search(r"\bbearer\s+", binding[k], re.I) for k in fields):
        return {**result, "reason": "invalid_binding"}
    try:
        _assert_no_secrets(json.dumps(binding, allow_nan=False))
    except ValueError:
        return {**result, "reason": "invalid_binding"}
    required = binding.get("required_sources", [])
    if not isinstance(required, list) or any(not isinstance(v, str) or not v or len(v) > 100 for v in required):
        return {**result, "reason": "invalid_binding"}
    result["source_checks"] = {key: "unknown" for key in required}
    identity = resolve_ingestion_event_identity(Path(event_path), event, in_events_directory=False)
    if not identity.recognized or identity.compatibility != "canonical" or not identity.event_id:
        return {**result, "reason": "normalized_event_required"}
    if (binding["repo_id"] != repo_id or identity.event_id != binding["event_id"]
        or not isinstance(event.get("source_refs"), list) or binding["source_key"] not in event["source_refs"]
        or event.get("source_account") != binding["account_id"] or event.get("context") != binding["context"]
        or manifest.get("context") != binding["context"]):
        return {**result, "status": "conflict", "reason": "identity_or_context_mismatch"}
    result.update(task_ref={"repo_id": repo_id, "action_id": binding["action_id"]},
                  owner_ref=binding["owner_ref"], coordinator=binding["coordinator"])
    stable = {key: binding[key] for key in ("repo_id", "source_key", "account_id", "event_id", "action_id")}
    result["preview_key"] = hashlib.sha256(json.dumps(stable, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if not manifest.get("hash_sha256") or binding["event_sha256"] != manifest["hash_sha256"]:
        return {**result, "status": "reconcile", "reason": "event_revision_changed"}
    matches = [a for a in actions if a.get("action_id") == binding["action_id"]]
    if not matches:
        return {**result, "status": "propose", "reason": "new_card_requires_review_and_route", "blockers": ["coordinator_binding_pending"]}
    if len(matches) != 1:
        return {**result, "status": "conflict", "reason": "ambiguous_action"}
    action = matches[0]
    if action.get("context") != binding["context"] or action.get("owner_ref") != binding["owner_ref"] or action.get("coordinator") != binding["coordinator"]:
        return {**result, "status": "conflict", "reason": "action_binding_mismatch"}
    if action.get("content_sha256") != binding["action_sha256"]:
        return {**result, "status": "reconcile", "reason": "action_revision_changed"}
    blockers = list(action.get("blockers") or [])
    if action.get("state") in {"blocked", "waiting_human", "done", "cancelled"}:
        blockers.append(str(action["state"]))
    if action.get("stop"):
        blockers.append("STOP")
    return {**result, "status": "reuse", "reason": "explicit_revision_bound_action", "blockers": blockers}


def _action_preview(root: Path, config: WikiConfig, source: str, manifest: dict[str, Any], snapshot: dict | None) -> dict:
    from wiki_core.source_config import find_source_config
    from wiki_core.coordination import _read, coordination_index, CoordinationError
    from wiki_core.frontmatter import parse_frontmatter
    empty = compose_event_action_preview(source, {}, {}, None, [], repo_id=config.repo_id)
    try:
        configured = find_source_config(root, config, source)
        if not configured:
            return empty
        config_raw = _read(root, configured["path"])
        cfg, _ = parse_frontmatter(config_raw.decode())
        binding = cfg.get("action_binding")
        if binding is None:
            return empty
        if snapshot is None:
            return {**empty, "reason": "canonical_snapshot_required"}
        event_raw = _read(root, source)
        event, _ = parse_frontmatter(event_raw.decode())
        if hashlib.sha256(event_raw).hexdigest() != manifest.get("hash_sha256"):
            return {**empty, "status": "reconcile", "reason": "event_revision_changed"}
        index = coordination_index(root, snapshot)
        pages = {p["id"]: p for p in snapshot.get("pages.json", {}).get("pages", [])}
        actions = []
        for item in index["actions"]:
            raw = _read(root, item["path"])
            if hashlib.sha256(raw).hexdigest() != item["content_sha256"]:
                raise CoordinationError("action revision changed")
            fm, _ = parse_frontmatter(raw.decode())
            actions.append({**item, "context": pages[item["action_id"]].get("context"),
                            "owner_ref": fm.get("owner_ref"), "stop": fm.get("stop"),
                            "blockers": fm.get("blockers", [])})
        result = compose_event_action_preview(source, event, manifest, binding, actions, repo_id=config.repo_id)
        if (config_raw != _read(root, configured["path"]) or event_raw != _read(root, source)
            or hashlib.sha256(_read(root, "wiki.coordination.yaml")).hexdigest() != index["policy_sha256"]
            or any(hashlib.sha256(_read(root, a["path"])).hexdigest() != a["content_sha256"] for a in index["actions"])):
            return {**empty, "status": "reconcile", "reason": "inputs_changed"}
        return result
    except (ValueError, OSError, UnicodeError, KeyError, TypeError):
        return {**empty, "status": "conflict", "reason": "invalid_or_changed_inputs"}


def _redact(text: str) -> str:
    return SECRET_VALUE_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)


def _result(
    argv: list[str],
    *,
    ok: bool,
    returncode: int | None,
    stdout: str = "",
    stderr: str = "",
    dry_run: bool = False,
) -> dict[str, Any]:
    return {
        "argv": argv,
        "ok": ok,
        "returncode": returncode,
        "stdout": _redact(stdout),
        "stderr": _redact(stderr),
        "dry_run": dry_run,
    }


def _command_for_step(step_id: str, source: str, context: str) -> list[str] | None:
    if step_id == "proposal_preview":
        return ["python3", "scripts/wiki_new_ingest.py", "--source", source, "--context", context, "--dry-run"]
    if step_id == "ingest_dry_run":
        return ["python3", "scripts/wiki_ingest.py", "--source", source, "--context", context, "--dry-run", "--no-score"]
    if step_id == "proposal_write":
        return ["python3", "scripts/wiki_new_ingest.py", "--source", source, "--context", context]
    if step_id == "llm_request_preview":
        return ["python3", "scripts/wiki_llm_context_pass.py", "--source", source, "--context", context]
    if step_id == "llm_request_emit":
        return ["python3", "scripts/wiki_llm_context_pass.py", "--source", source, "--context", context, "--emit-request"]
    return None


def _stage(
    step_id: str,
    label: str,
    *,
    status: str,
    detail: str,
    command: list[str] | None = None,
    writes: bool = False,
) -> dict[str, Any]:
    return {
        "id": step_id,
        "label": label,
        "status": status,
        "detail": detail,
        "command": command,
        "writes": writes,
    }


def build_ingestion_plan(root: Path, config: WikiConfig, source: str, *, context: str | None = None, snapshot: dict | None = None) -> dict[str, Any]:
    triage = triage_source(root, config, source, context=context)
    selected_context = str(triage.get("context") or context or config.default_context)
    source_value = str(triage.get("source") or source)
    secret_block = bool(triage.get("secret_block"))
    missing_file = "file_not_found" in set(triage.get("risk_flags") or [])
    git = build_git_state(root, config)
    on_proposal_branch = bool(git.get("proposal", {}).get("is_proposal_branch"))
    branch_prefix = str(config.approval.get("branch_prefix") or "wiki/")

    commands = {
        step_id: _command_for_step(step_id, source_value, selected_context)
        for step_id in READ_STEPS | WRITE_STEPS
    }

    stages = [
        _stage(
            "source_triage",
            "Source triage",
            status="blocked" if secret_block else "warning" if missing_file else "complete",
            detail="Access secret blocks ingestion." if secret_block else "Source path is missing." if missing_file else "Source manifest and detector pre-scan are ready.",
        ),
        _stage(
            "proposal_preview",
            "Preview proposal",
            status="blocked" if secret_block else "ready",
            detail="Generate the private ingestion proposal as dry-run Markdown.",
            command=commands["proposal_preview"],
        ),
        _stage(
            "ingest_dry_run",
            "Run ingest dry-run",
            status="blocked" if secret_block else "ready",
            detail="Exercise manifest, extraction, chunking, index and LLM package path without persistence.",
            command=commands["ingest_dry_run"],
        ),
        _stage(
            "proposal_write",
            "Create proposal page",
            status="blocked" if secret_block else "ready" if on_proposal_branch else "waiting",
            detail=(
                "Write the proposal page on the current proposal branch."
                if on_proposal_branch
                else f"Switch to or create a {branch_prefix}<theme> branch before writing versioned memory."
            ),
            command=commands["proposal_write"],
            writes=True,
        ),
        _stage(
            "llm_request_preview",
            "Preview LLM request",
            status="blocked" if secret_block else "ready",
            detail="Build the agent handoff package without writing it.",
            command=commands["llm_request_preview"],
        ),
        _stage(
            "llm_request_emit",
            "Emit LLM request",
            status="blocked" if secret_block else "ready",
            detail="Write the derived LLM context request package for the agent pass.",
            command=commands["llm_request_emit"],
            writes=True,
        ),
        _stage(
            "human_gate",
            "Human PR gate",
            status="waiting",
            detail="After proposal changes are committed, publish the branch and open or update the draft PR.",
        ),
    ]
    blocked = next((stage for stage in stages if stage["status"] == "blocked"), None)
    waiting = next((stage for stage in stages if stage["status"] == "waiting"), None)
    return {
        "ok": blocked is None,
        "source": source_value,
        "context": selected_context,
        "source_id": triage.get("source_id"),
        "triage": triage,
        "action_preview": _action_preview(root, config, source_value, triage.get("manifest") or {}, snapshot) if not secret_block else {"status": "blocked", "reason": "secret_block", "execution_ready": False, "writes": False},
        "stages": stages,
        "next_blocked_stage": blocked or waiting,
    }


def run_ingestion_step(
    root: Path,
    config: WikiConfig,
    source: str,
    context: str,
    step_id: str,
    *,
    dry_run: bool = True,
    timeout_seconds: int = 180,
) -> dict[str, Any]:
    plan = build_ingestion_plan(root, config, source, context=context)
    stage = next((item for item in plan["stages"] if item["id"] == step_id), None)
    if stage is None or step_id not in READ_STEPS | WRITE_STEPS:
        return {"ok": False, "step_id": step_id, "dry_run": dry_run, "summary": "unknown ingestion step", "results": [], "plan": plan, "error": "unknown ingestion step"}
    if step_id in WRITE_STEPS and dry_run:
        argv = stage.get("command") or []
        return {
            "ok": True,
            "step_id": step_id,
            "dry_run": True,
            "summary": f"Dry-run {stage['label']}",
            "results": [_result(list(argv), ok=True, returncode=None, stdout="dry run: command not executed", dry_run=True)],
            "plan": plan,
        }
    if step_id in WRITE_STEPS and stage["status"] != "ready":
        return {
            "ok": False,
            "step_id": step_id,
            "dry_run": dry_run,
            "summary": str(stage["detail"]),
            "results": [],
            "plan": plan,
            "error": str(stage["detail"]),
        }
    if not plan["ok"] and step_id != "source_triage":
        return {
            "ok": False,
            "step_id": step_id,
            "dry_run": dry_run,
            "summary": "source triage blocks ingestion",
            "results": [],
            "plan": plan,
            "error": "source triage blocks ingestion",
        }

    argv = list(stage.get("command") or [])
    if not argv:
        return {"ok": False, "step_id": step_id, "dry_run": dry_run, "summary": "step has no command", "results": [], "plan": plan, "error": "step has no command"}
    executable = [sys.executable if index == 0 and value in {"python", "python3"} else value for index, value in enumerate(argv)]
    try:
        proc = subprocess.run(
            executable,
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "ok": False,
            "step_id": step_id,
            "dry_run": dry_run,
            "summary": str(stage["label"]),
            "results": [_result(argv, ok=False, returncode=None, stderr=str(exc), dry_run=False)],
            "plan": plan,
            "error": str(exc),
        }
    result = _result(argv, ok=proc.returncode == 0, returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr, dry_run=False)
    return {
        "ok": bool(result["ok"]),
        "step_id": step_id,
        "dry_run": dry_run,
        "summary": str(stage["label"]),
        "results": [result],
        "plan": build_ingestion_plan(root, config, source, context=context),
        "error": "" if result["ok"] else _redact(proc.stderr or proc.stdout),
    }
