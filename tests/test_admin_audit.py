"""Admin audit trail (god-mode plan §18): chain, redaction, retention."""

from __future__ import annotations

import json
import multiprocessing
from pathlib import Path

import pytest

import wiki_core.action_transition as transition_module
from wiki_core.action_transition import ActionTransitionError
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


def _multiprocess_append(root: str, worker: int, retain: int, barrier, queue) -> None:
    import time
    from wiki_core.web.admin import audit
    original_read = audit._read_lines

    def slow_tail_read(path):
        lines = original_read(path)
        # Widen the read/append race that used to fork otherwise valid hashes.
        time.sleep(0.01)
        return lines

    audit._read_lines = slow_tail_read
    config = WikiConfig(admin={"audit": {"retain_events": retain}})
    barrier.wait(timeout=15)
    for index in range(8):
        append_admin_audit_event(Path(root), config, _event(f"worker {worker} event {index}"))
    queue.put(worker)


@pytest.mark.parametrize("retain", [100, 7])
def test_multiprocess_append_and_retention_preserve_one_chain(tmp_path: Path, retain: int) -> None:
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(3)
    queue = context.Queue()
    processes = [context.Process(target=_multiprocess_append, args=(str(tmp_path), worker, retain, barrier, queue))
                 for worker in range(3)]
    try:
        for process in processes:
            process.start()
        assert sorted(queue.get(timeout=20) for _ in processes) == [0, 1, 2]
        for process in processes:
            process.join(timeout=20)
            assert process.exitcode == 0
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        queue.close()
    path = audit_log_path(tmp_path, WikiConfig())
    events = _events_on_disk(path)
    assert len(events) == min(24, retain)
    assert len({event["event_id"] for event in events}) == len(events)
    assert len({event["output_summary"] for event in events}) == len(events)
    assert verify_admin_audit_chain(path)["ok"] is True


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
    before = path.read_bytes()
    append_admin_audit_event(tmp_path, config, _event("after the historical break"))
    assert path.read_bytes().startswith(before)
    assert verify_admin_audit_chain(path)["broken_index"] == 1


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


def test_unavailable_filesystem_lock_refuses_before_touching_journal(tmp_path: Path, monkeypatch) -> None:
    config = WikiConfig()
    append_admin_audit_event(tmp_path, config, _event("retained before lock failure"))
    path = audit_log_path(tmp_path, config)
    before, mtime = path.read_bytes(), path.stat().st_mtime_ns
    monkeypatch.setattr(transition_module, "_fcntl", None)
    monkeypatch.setattr(transition_module, "_msvcrt", None)
    with pytest.raises(ActionTransitionError, match="action_lock_backend_unavailable"):
        append_admin_audit_event(tmp_path, config, _event("must never append without a lock"))
    assert path.read_bytes() == before and path.stat().st_mtime_ns == mtime
    assert not path.with_name(path.name + ".tmp").exists()
