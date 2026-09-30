"""Admin audit trail (god-mode plan §18): chain, redaction, retention."""

from __future__ import annotations

import json
from pathlib import Path

from wiki_core.config import WikiConfig, load_config
from wiki_core.web.admin.audit import (
    AUDIT_CHAIN_GENESIS,
    AUDIT_SCHEMA_VERSION,
    NEVER_AUDIT_KEYS,
    append_admin_audit_event,
    audit_log_path,
    redact_audit_value,
    verify_admin_audit_chain,
)


def _event(summary: str) -> dict:
    return {
        "actor": {"id": "local-owner", "adapter": "local_startup_code"},
        "session_id": "session_abc",
        "command_id": "session.unlock",
        "capabilities_checked": ["session.manage"],
        "risk_level": "read",
        "result": "success",
        "output_summary": summary,
    }


def _events_on_disk(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_chain_links_from_genesis_and_verifies(tmp_path: Path) -> None:
    config = WikiConfig()
    for index in range(3):
        result = append_admin_audit_event(tmp_path, config, _event(f"event {index}"))
        assert result["written"] is True
    path = audit_log_path(tmp_path, config)
    events = _events_on_disk(path)
    assert len(events) == 3
    assert events[0]["prev_hash"] == AUDIT_CHAIN_GENESIS
    assert events[1]["prev_hash"] == events[0]["event_hash"]
    assert events[2]["prev_hash"] == events[1]["event_hash"]
    assert all(e["schema_version"] == AUDIT_SCHEMA_VERSION for e in events)
    assert all(e["event_hash"].startswith("sha256:") for e in events)
    assert verify_admin_audit_chain(path) == {
        "ok": True,
        "events": 3,
        "broken_index": None,
    }


def test_tampering_breaks_verification(tmp_path: Path) -> None:
    config = WikiConfig()
    for index in range(3):
        append_admin_audit_event(tmp_path, config, _event(f"event {index}"))
    path = audit_log_path(tmp_path, config)
    events = _events_on_disk(path)
    events[1]["output_summary"] = "history, rewritten"
    path.write_text(
        "\n".join(json.dumps(e, sort_keys=True) for e in events) + "\n",
        encoding="utf-8",
    )
    verdict = verify_admin_audit_chain(path)
    assert verdict["ok"] is False
    assert verdict["broken_index"] == 1


def test_redaction_strips_every_never_audit_key(tmp_path: Path) -> None:
    config = WikiConfig()
    poisoned = {
        **_event("redaction probe"),
        # Top-level junk outside the §18.1 schema is dropped entirely…
        "code": "AAAA-2222",
        "token": "super-secret-token",
        # …and secret-shaped keys INSIDE schema fields are redacted in place.
        "actor": {
            "id": "local-owner",
            "adapter": "local_startup_code",
            "Authorization": "Bearer nope",
            "github_token": "ghp_forbidden",
            "Set-Cookie": "sid=1",
            "nested": [{"password": "hunter2"}],
            "kept": "visible",
        },
    }
    result = append_admin_audit_event(tmp_path, config, poisoned)
    assert result["written"] is True
    text = audit_log_path(tmp_path, config).read_text(encoding="utf-8")
    for secret in ("AAAA-2222", "super-secret-token", "Bearer nope", "ghp_forbidden", "sid=1", "hunter2"):
        assert secret not in text
    assert "visible" in text
    # The pure redactor is reusable by future audit writers.
    redacted = redact_audit_value({"token": "x", "safe": {"cookie": "y", "id": 1}})
    assert redacted == {"token": "[redacted]", "safe": {"cookie": "[redacted]", "id": 1}}
    assert "token" in NEVER_AUDIT_KEYS and "unlock_code" in NEVER_AUDIT_KEYS


def test_retention_bounds_the_file(tmp_path: Path) -> None:
    (tmp_path / "wiki.config.yaml").write_text(
        "repo_id: audit-test\nlanguage: en\n"
        "admin:\n  audit:\n    retain_events: 5\n",
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    for index in range(9):
        append_admin_audit_event(tmp_path, config, _event(f"event {index}"))
    path = audit_log_path(tmp_path, config)
    events = _events_on_disk(path)
    assert len(events) == 5
    assert events[-1]["output_summary"] == "event 8"
    # Within the retained window the chain still verifies; the head's
    # prev_hash points at a dropped event by design (documented trade-off).
    assert verify_admin_audit_chain(path)["ok"] is True


def test_disabled_audit_writes_nothing(tmp_path: Path) -> None:
    (tmp_path / "wiki.config.yaml").write_text(
        "repo_id: audit-test\nlanguage: en\n"
        "admin:\n  audit:\n    enabled: false\n",
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    result = append_admin_audit_event(tmp_path, config, _event("never lands"))
    assert result == {"written": False, "reason": "audit_disabled"}
    assert not audit_log_path(tmp_path, config).exists()
