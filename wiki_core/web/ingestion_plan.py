from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from wiki_core.config import WikiConfig
from wiki_core.web.commands import SECRET_VALUE_RE
from wiki_core.web.git_ops import build_git_state
from wiki_core.web.source_triage import triage_source


READ_STEPS = {"proposal_preview", "ingest_dry_run", "llm_request_preview"}
WRITE_STEPS = {"proposal_write", "llm_request_emit"}
STEP_ORDER = (
    "source_triage",
    "proposal_preview",
    "ingest_dry_run",
    "proposal_write",
    "llm_request_preview",
    "llm_request_emit",
    "human_gate",
)


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


def build_ingestion_plan(root: Path, config: WikiConfig, source: str, *, context: str | None = None) -> dict[str, Any]:
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
