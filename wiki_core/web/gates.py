"""Honesty gates with PERSISTED run receipts.

The old gate payload hardcoded ``status: "not_run"`` at snapshot time, so the
cockpit's health verdict could never turn green no matter what the operator did.
That is the single most demoralizing dishonesty in the app. Here a gate run
writes a receipt (``derived_root/gate-receipts/<gate_id>.json``) with the real
outcome, and the read model reports last-known status — so running a gate
actually turns it green, and "not_run" means genuinely never run this session.

Receipts are RUNTIME facts, not content-derived facts, so they live outside the
content-hash paths: snapshot regeneration stays reproducible and CI diffs clean.
Zero LLM, subprocess allowlisted + timed + secret-redacted, like every other
deterministic action.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from wiki_core.config import WikiConfig
from wiki_core.paths import WikiPaths
from wiki_core.web.commands import SECRET_VALUE_RE
from wiki_core.web.schemas import WEB_GATE_SCHEMA_VERSION

# The honesty gates, id → argv. One place, shared by the read model and the
# runner so they never drift.
GATE_COMMANDS: tuple[tuple[str, list[str]], ...] = (
    ("wiki_audit", ["python3", "scripts/wiki_audit.py", "--check"]),
    ("methodology_coverage", ["python3", "scripts/wiki_check_methodology_coverage.py", "--check"]),
    ("operation_compile", ["python3", "scripts/wiki_operation_compile.py", "--check"]),
    ("input_stage", ["python3", "scripts/wiki_input_stage.py", "--check"]),
    ("semantic_inventory", ["python3", "scripts/wiki_semantic_inventory.py", "--check"]),
    ("pytest", ["python3", "-m", "pytest", "tests/"]),
)
_GATE_IDS = {gate_id for gate_id, _ in GATE_COMMANDS}
_GATE_TIMEOUT = 300


def _redact(text: str) -> str:
    return SECRET_VALUE_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)


def _receipts_dir(root: Path, config: WikiConfig) -> Path:
    return WikiPaths(root, config).derived_root / "gate-receipts"


def read_receipts(root: Path, config: WikiConfig) -> dict[str, dict[str, Any]]:
    directory = _receipts_dir(root, config)
    receipts: dict[str, dict[str, Any]] = {}
    if not directory.is_dir():
        return receipts
    for gate_id, _ in GATE_COMMANDS:
        path = directory / f"{gate_id}.json"
        if not path.is_file():
            continue
        try:
            receipts[gate_id] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
    return receipts


def write_receipt(root: Path, config: WikiConfig, gate_id: str, *, ok: bool, returncode: int | None) -> dict[str, Any]:
    directory = _receipts_dir(root, config)
    directory.mkdir(parents=True, exist_ok=True)
    receipt = {
        "gate_id": gate_id,
        "ok": bool(ok),
        "returncode": returncode,
        "finished_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    (directory / f"{gate_id}.json").write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    return receipt


def gates_payload(root: Path, config: WikiConfig) -> dict[str, Any]:
    """The read model: last-known status per gate, honest 'not_run' when never
    run. Overall status is pass only when ALL gates last passed."""
    receipts = read_receipts(root, config)
    gates: list[dict[str, Any]] = []
    statuses: list[str] = []
    for gate_id, argv in GATE_COMMANDS:
        receipt = receipts.get(gate_id)
        if receipt is None:
            status = "not_run"
        else:
            status = "pass" if receipt.get("ok") else "fail"
        statuses.append(status)
        gates.append(
            {
                "id": gate_id,
                "status": status,
                "argv": argv,
                "finished_at": (receipt or {}).get("finished_at"),
            }
        )
    if any(status == "fail" for status in statuses):
        overall = "fail"
    elif all(status == "pass" for status in statuses):
        overall = "pass"
    elif any(status == "pass" for status in statuses):
        overall = "partial"
    else:
        overall = "not_run"
    return {"schema_version": WEB_GATE_SCHEMA_VERSION, "status": overall, "gates": gates}


def run_gate(root: Path, config: WikiConfig, gate_id: str, *, timeout_seconds: int = _GATE_TIMEOUT) -> dict[str, Any]:
    """Run one gate, persist its receipt, return the redacted result."""
    if gate_id not in _GATE_IDS:
        return {"ok": False, "error": f"unknown gate: {gate_id}", "gate_id": gate_id}
    argv = next(cmd for gid, cmd in GATE_COMMANDS if gid == gate_id)
    try:
        proc = subprocess.run(  # noqa: S603 - fixed allowlisted argv, no shell
            argv, cwd=root, text=True, capture_output=True, check=False, timeout=timeout_seconds
        )
        returncode = proc.returncode
        stdout, stderr = proc.stdout, proc.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        write_receipt(root, config, gate_id, ok=False, returncode=None)
        return {"ok": False, "gate_id": gate_id, "returncode": None, "stdout": "", "stderr": _redact(str(exc))}
    ok = returncode == 0
    receipt = write_receipt(root, config, gate_id, ok=ok, returncode=returncode)
    return {
        "ok": ok,
        "gate_id": gate_id,
        "returncode": returncode,
        "stdout": _redact(stdout),
        "stderr": _redact(stderr),
        "finished_at": receipt["finished_at"],
    }
