"""Append-only administrative audit trail (god-mode plan §18, PR3).

One JSONL file per repo — ``<derived_root>/admin/audit.jsonl`` — written
only by the operator process, hash-chained so tampering is evident
(``prev_hash``/``event_hash``), redacted BEFORE anything touches disk
(§18.3 never-audit list) and bounded by ``admin.audit.retain_events``.

Retention truncates from the head. Inside the retained window the chain
still verifies link by link; the first retained event keeps its original
``prev_hash``, which then points at a dropped event — that is the
documented, bounded-retention trade-off, not a tamper signal.

Timestamps here are real wall-clock UTC on purpose: this is an
operational log of things that actually happened, not a deterministic
snapshot builder.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from wiki_core.config import WikiConfig
from wiki_core.paths import WikiPaths

AUDIT_SCHEMA_VERSION = "wiki_admin_audit.v1"
AUDIT_RELATIVE_PATH = "admin/audit.jsonl"
# The very first event of a chain links to this marker instead of a hash.
AUDIT_CHAIN_GENESIS = "genesis"

_REDACTED = "[redacted]"

# §18.3 — values that must NEVER be persisted in clear text. Key names are
# normalized (lowercase, '-' -> '_') before matching, so "Set-Cookie" and
# "set_cookie" are the same forbidden key.
NEVER_AUDIT_KEYS = frozenset(
    {
        "code",
        "unlock_code",
        "token",
        "session_token",
        "admin_token",
        "access_token",
        "refresh_token",
        "authorization",
        "cookie",
        "cookies",
        "set_cookie",
        "password",
        "passphrase",
        "secret",
        "secrets",
        "api_key",
        "github_token",
        "private_key",
        "prompt",
    }
)

# One writer lock per process: the operator server is the only writer, and
# its request threads serialize here so the chain never forks.
_APPEND_LOCK = threading.Lock()


def redact_audit_value(value: Any) -> Any:
    """Recursively replace never-audit values with a redaction marker."""

    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key).strip().lower().replace("-", "_")
            if name in NEVER_AUDIT_KEYS:
                redacted[str(key)] = _REDACTED
            else:
                redacted[str(key)] = redact_audit_value(item)
        return redacted
    if isinstance(value, (list, tuple)):
        return [redact_audit_value(item) for item in value]
    return value


def audit_log_path(root: Path, config: WikiConfig) -> Path:
    return WikiPaths(root, config).derived_root / AUDIT_RELATIVE_PATH


def _canonical(record: dict[str, Any]) -> str:
    return json.dumps(
        record, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )


def _event_hash(record: dict[str, Any]) -> str:
    body = {key: value for key, value in record.items() if key != "event_hash"}
    digest = hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _read_lines(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    return [line for line in text.splitlines() if line.strip()]


def _audit_settings(config: WikiConfig) -> dict[str, Any]:
    section = config.admin.get("audit")
    section = section if isinstance(section, dict) else {}
    return {
        "enabled": bool(section.get("enabled", True)),
        "hash_chain": bool(section.get("hash_chain", True)),
        "retain_events": int(section.get("retain_events", 10_000)),
    }


def append_admin_audit_event(
    root: Path, config: WikiConfig, event: dict[str, Any]
) -> dict[str, Any]:
    """Append one structured, redacted, chained event (§18.1/§18.2).

    The caller supplies domain fields (actor, command_id, result, …); this
    function owns the envelope: schema version, event id, timestamp, chain
    hashes and retention. Returns ``{"written": False}`` when the config
    disables auditing — callers never branch on audit availability.
    """

    settings = _audit_settings(config)
    if not settings["enabled"]:
        return {"written": False, "reason": "audit_disabled"}

    payload = redact_audit_value(dict(event))
    record: dict[str, Any] = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "event_id": f"audit_{secrets.token_hex(10)}",
        "timestamp": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "actor": payload.get("actor") or {"id": "unknown", "adapter": None},
        "session_id": payload.get("session_id"),
        "command_id": payload.get("command_id"),
        "capabilities_checked": list(payload.get("capabilities_checked") or ()),
        "risk_level": str(payload.get("risk_level") or "read"),
        "plan_id": payload.get("plan_id"),
        "plan_sha": payload.get("plan_sha"),
        "result": str(payload.get("result") or "unknown"),
        "affected_paths": list(payload.get("affected_paths") or ()),
        "branch": payload.get("branch"),
        "commit": payload.get("commit"),
        "external_refs": list(payload.get("external_refs") or ()),
        "output_summary": str(payload.get("output_summary") or ""),
        "undo": payload.get("undo") or {"available": False, "strategy": None},
    }

    path = audit_log_path(root, config)
    with _APPEND_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = _read_lines(path)
        prev_hash = AUDIT_CHAIN_GENESIS
        if settings["hash_chain"] and lines:
            try:
                prev_hash = str(
                    json.loads(lines[-1]).get("event_hash") or AUDIT_CHAIN_GENESIS
                )
            except json.JSONDecodeError:
                # A corrupt tail is preserved as-is; the verifier will flag
                # it. The new event still chains to a deterministic marker.
                prev_hash = AUDIT_CHAIN_GENESIS
        record["prev_hash"] = prev_hash if settings["hash_chain"] else None
        record["event_hash"] = (
            _event_hash(record) if settings["hash_chain"] else None
        )
        lines.append(_canonical(record))
        if len(lines) > settings["retain_events"]:
            lines = lines[-settings["retain_events"] :]
            # Retention rewrites atomically so a crash can never leave a
            # half-truncated chain behind.
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
            os.replace(tmp, path)
        else:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(lines[-1] + "\n")
    return {"written": True, "event": record}


def verify_admin_audit_chain(path: Path) -> dict[str, Any]:
    """Walk the retained window and verify every hash and every link."""

    lines = _read_lines(path)
    previous_hash: str | None = None
    for index, line in enumerate(lines):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return {"ok": False, "events": len(lines), "broken_index": index}
        if not isinstance(event, dict):
            return {"ok": False, "events": len(lines), "broken_index": index}
        if event.get("event_hash") != _event_hash(event):
            return {"ok": False, "events": len(lines), "broken_index": index}
        if previous_hash is not None and event.get("prev_hash") != previous_hash:
            return {"ok": False, "events": len(lines), "broken_index": index}
        previous_hash = str(event.get("event_hash"))
    return {"ok": True, "events": len(lines), "broken_index": None}
