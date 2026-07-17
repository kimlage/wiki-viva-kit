"""Local admin session lifecycle (god-mode plan §7.1, §13, §22.4).

Covers the full §22.4 list: challenge validity/expiry, wrong code, rate
limit, consumed code, invalid/expired token, renew rotation, lock, restart
invalidation, token/code absence from responses and audit, origin
rejection, and the preserved operator-security v2 POST contract.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from wiki_core.config import load_config
from wiki_core.web.admin.audit import audit_log_path, verify_admin_audit_chain
from wiki_core.web.admin.sessions import (
    CHALLENGE_TTL_S,
    UNLOCK_ATTEMPT_LIMIT,
    UNLOCK_CODE_TTL_S,
    ADMIN_SESSION_HEADER,
)

# Reuse the running-server fixture machinery from the web-server suite.
from tests.test_web_server import _repo, _Server, _write

_CODE_RE = re.compile(r"code: ([A-Z0-9]{4}-[A-Z0-9]{4})")


class _Clock:
    """Steppable monotonic clock injected into the session manager."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture()
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("WIKI_COCKPIT_CORS_ORIGINS", raising=False)
    config = _repo(tmp_path)
    srv = _Server(tmp_path, config)
    try:
        yield srv
    finally:
        srv.close()


def _arm(srv: _Server) -> tuple[list[str], _Clock]:
    """Re-arm the unlock code into a capture list and install a test clock."""

    lines: list[str] = []
    clock = _Clock()
    srv.server.admin_sessions.clock = clock
    srv.server.admin_sessions.arm(lines.append)
    return lines, clock


def _code(lines: list[str]) -> str:
    match = _CODE_RE.search(lines[-1])
    assert match, f"no unlock code announced in {lines!r}"
    return match.group(1)


def _challenge(srv: _Server) -> str:
    status, body = srv.post("/api/admin/session/challenge", {})
    assert status == 200 and body["ok"] is True
    return body["challenge"]


def _unlock(srv: _Server, code: str) -> tuple[int, dict[str, Any]]:
    return srv.post(
        "/api/admin/session/unlock",
        {"challenge": _challenge(srv), "code": code},
    )


def _capabilities(srv: _Server, token: str | None) -> dict[str, Any]:
    headers = {ADMIN_SESSION_HEADER: token} if token else {}
    status, body = srv.get("/api/admin/capabilities", headers=headers)
    assert status == 200
    return body


# ---------------------------------------------------------------------------
# challenge -> code -> unlock
# ---------------------------------------------------------------------------


def test_unlock_happy_path_grants_role_scoped_session(server: _Server) -> None:
    lines, _clock = _arm(server)
    status, body = _unlock(server, _code(lines))
    assert status == 200 and body["ok"] is True
    token = body["token"]
    assert isinstance(token, str) and len(token) >= 32
    session = body["session"]
    assert session["role"] == "admin"
    assert session["state"] == "active_full"
    assert session["expires_in_s"] == 15 * 60
    assert "token" not in session

    payload = _capabilities(server, token)
    assert payload["session_state"] == "active_full"
    assert payload["session"]["session_id"] == session["session_id"]
    assert "token" not in json.dumps(payload["session"]).lower()
    granted = {e["id"] for e in payload["capabilities"] if e["granted"]}
    assert "system.inspect" in granted and "session.manage" in granted
    # Break-glass stays off even for a full admin session (§17.4).
    break_glass = next(
        e for e in payload["capabilities"] if e["id"] == "break_glass.local"
    )
    assert break_glass["granted"] is False
    assert break_glass["reason"] == "disabled_by_config"


def test_unlock_rejects_unknown_and_expired_challenges(server: _Server) -> None:
    lines, clock = _arm(server)
    code = _code(lines)
    status, body = server.post(
        "/api/admin/session/unlock", {"challenge": "made-up", "code": code}
    )
    assert status == 403
    assert body["error_code"] == "admin_challenge_rejected"

    challenge = _challenge(server)
    clock.advance(CHALLENGE_TTL_S + 1)
    status, body = server.post(
        "/api/admin/session/unlock", {"challenge": challenge, "code": code}
    )
    assert status == 403
    assert body["error_code"] == "admin_challenge_rejected"


def test_challenge_is_single_use(server: _Server) -> None:
    lines, _clock = _arm(server)
    code = _code(lines)
    challenge = _challenge(server)
    status, body = server.post(
        "/api/admin/session/unlock", {"challenge": challenge, "code": "WRONG-CODE"}
    )
    assert status == 403 and body["error_code"] == "admin_unlock_code_rejected"
    # The consumed challenge cannot be replayed even with the right code.
    status, body = server.post(
        "/api/admin/session/unlock", {"challenge": challenge, "code": code}
    )
    assert status == 403 and body["error_code"] == "admin_challenge_rejected"


def test_wrong_code_is_rejected_without_echo(server: _Server) -> None:
    lines, _clock = _arm(server)
    real_code = _code(lines)
    status, body = _unlock(server, "AAAA-2222")
    assert status == 403
    assert body["ok"] is False
    assert body["error_code"] == "admin_unlock_code_rejected"
    flat = json.dumps(body)
    assert real_code not in flat and "AAAA-2222" not in flat
    assert "token" not in flat.lower()


def test_expired_code_is_rejected(server: _Server) -> None:
    lines, clock = _arm(server)
    code = _code(lines)
    clock.advance(UNLOCK_CODE_TTL_S + 1)
    status, body = _unlock(server, code)
    assert status == 403
    assert body["error_code"] == "admin_unlock_code_rejected"


def test_consumed_code_cannot_unlock_twice(server: _Server) -> None:
    lines, _clock = _arm(server)
    code = _code(lines)
    status, _body = _unlock(server, code)
    assert status == 200
    status, body = _unlock(server, code)
    assert status == 403
    assert body["error_code"] == "admin_unlock_code_rejected"


def test_unlock_attempts_are_rate_limited(server: _Server) -> None:
    _arm(server)
    for _ in range(UNLOCK_ATTEMPT_LIMIT):
        status, body = _unlock(server, "WRNG-GSSS")
        assert status == 403
        assert body["error_code"] == "admin_unlock_code_rejected"
    status, body = _unlock(server, "WRNG-GSSS")
    assert status == 429
    assert body["error_code"] == "admin_rate_limited"


# ---------------------------------------------------------------------------
# token validation, renew, lock, restart
# ---------------------------------------------------------------------------


def test_invalid_token_stays_locked_and_renew_fails(server: _Server) -> None:
    _arm(server)
    payload = _capabilities(server, "not-a-real-token")
    assert payload["session_state"] == "locked"
    assert payload["session"] is None
    status, body = server.post(
        "/api/admin/session/renew",
        {},
    )
    assert status == 403
    assert body["error_code"] == "admin_session_invalid"


def test_session_ttl_expires_server_side(server: _Server) -> None:
    lines, clock = _arm(server)
    _status, body = _unlock(server, _code(lines))
    token = body["token"]
    clock.advance(15 * 60 + 1)
    status, renewed = server.post(
        "/api/admin/session/renew", {}, headers={ADMIN_SESSION_HEADER: token}
    )
    assert status == 403
    assert renewed["error_code"] == "admin_session_expired"
    assert _capabilities(server, token)["session_state"] == "locked"


def test_idle_lock_expires_before_ttl(server: _Server) -> None:
    lines, clock = _arm(server)
    _status, body = _unlock(server, _code(lines))
    token = body["token"]
    clock.advance(5 * 60 + 1)  # idle default, well under the 15 min TTL
    status, renewed = server.post(
        "/api/admin/session/renew", {}, headers={ADMIN_SESSION_HEADER: token}
    )
    assert status == 403
    assert renewed["error_code"] == "admin_session_expired"


def test_renew_rotates_the_token(server: _Server) -> None:
    lines, _clock = _arm(server)
    _status, body = _unlock(server, _code(lines))
    old_token = body["token"]
    status, renewed = server.post(
        "/api/admin/session/renew", {}, headers={ADMIN_SESSION_HEADER: old_token}
    )
    assert status == 200 and renewed["ok"] is True
    new_token = renewed["token"]
    assert new_token != old_token
    # The old token died at rotation; the new one carries the session on.
    status, again = server.post(
        "/api/admin/session/renew", {}, headers={ADMIN_SESSION_HEADER: old_token}
    )
    assert status == 403 and again["error_code"] == "admin_session_invalid"
    assert _capabilities(server, new_token)["session_state"] == "active_full"


def test_lock_revokes_and_rearms_a_fresh_code(server: _Server) -> None:
    lines, _clock = _arm(server)
    first_code = _code(lines)
    _status, body = _unlock(server, first_code)
    token = body["token"]
    status, locked = server.post(
        "/api/admin/session/lock", {}, headers={ADMIN_SESSION_HEADER: token}
    )
    assert status == 200 and locked["state"] == "locked"
    assert _capabilities(server, token)["session_state"] == "locked"
    # Locking re-armed a NEW single-use code (§5.4) — announced, different,
    # and immediately usable without restarting the process.
    assert len(lines) == 2
    second_code = _code(lines)
    assert second_code != first_code
    status, body = _unlock(server, second_code)
    assert status == 200 and body["ok"] is True


def test_restart_invalidates_every_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("WIKI_COCKPIT_CORS_ORIGINS", raising=False)
    config = _repo(tmp_path)
    first = _Server(tmp_path, config)
    try:
        lines, _clock = _arm(first)
        _status, body = _unlock(first, _code(lines))
        token = body["token"]
        assert _capabilities(first, token)["session_state"] == "active_full"
    finally:
        first.close()
    second = _Server(tmp_path, config)
    try:
        payload = _capabilities(second, token)
        assert payload["session_state"] == "locked"
        status, body = second.post(
            "/api/admin/session/renew", {}, headers={ADMIN_SESSION_HEADER: token}
        )
        assert status == 403 and body["error_code"] == "admin_session_invalid"
    finally:
        second.close()


# ---------------------------------------------------------------------------
# secrecy: token and code never leak
# ---------------------------------------------------------------------------


def test_token_and_code_never_reach_audit_or_error_bodies(server: _Server) -> None:
    lines, _clock = _arm(server)
    code = _code(lines)
    _status, wrong = _unlock(server, "AAAA-3333")
    assert code not in json.dumps(wrong)
    _status, body = _unlock(server, code)
    token = body["token"]
    server.post("/api/admin/session/renew", {}, headers={ADMIN_SESSION_HEADER: token})
    _status, renewed = server.post(
        "/api/admin/session/renew", {}, headers={ADMIN_SESSION_HEADER: token}
    )
    audit_path = audit_log_path(server.server.root, server.server.config)
    audit_text = audit_path.read_text(encoding="utf-8")
    assert code not in audit_text
    assert token not in audit_text
    assert renewed.get("token", "") not in audit_text or renewed.get("token") is None
    # The chain of session lifecycle events verifies end to end.
    assert verify_admin_audit_chain(audit_path)["ok"] is True
    events = [json.loads(line) for line in audit_text.splitlines() if line.strip()]
    assert {"session.unlock", "session.renew"} <= {e["command_id"] for e in events}
    assert any(e["result"] == "failure" for e in events)
    assert any(e["result"] == "success" for e in events)


# ---------------------------------------------------------------------------
# transport contract: origin, nonce, attempt key, disabled config
# ---------------------------------------------------------------------------


def test_unlock_rejects_untrusted_origin(server: _Server) -> None:
    lines, _clock = _arm(server)
    status, body = server.post(
        "/api/admin/session/unlock",
        {"challenge": "x", "code": _code(lines)},
        origin="https://evil.example",
    )
    assert status == 403
    assert "origin" in body["error"]


def test_session_posts_preserve_operator_security_contract(server: _Server) -> None:
    # Wrong nonce → the v2 contract rejects BEFORE any session logic runs.
    status, body = server.post("/api/admin/session/challenge", {}, nonce="wrong")
    assert status == 403
    assert "nonce" in body["error"]
    # Missing/invalid attempt key → same fail-closed contract.
    status, body = server.post("/api/admin/session/challenge", {}, attempt_key="!bad")
    assert status == 400
    assert "attempt key" in body["error"]


def test_disabled_admin_rejects_session_endpoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("WIKI_COCKPIT_CORS_ORIGINS", raising=False)
    _repo(tmp_path)
    _write(
        tmp_path / "wiki.config.yaml",
        "repo_id: srv-test\ndefault_context: system\ncodex:\n  enabled: false\n"
        "admin:\n  enabled: false\n",
    )
    srv = _Server(tmp_path, load_config(tmp_path))
    try:
        status, body = srv.post("/api/admin/session/challenge", {})
        assert status == 403
        assert body["error_code"] == "admin_disabled"
        status, body = srv.post(
            "/api/admin/session/unlock", {"challenge": "x", "code": "y"}
        )
        assert status == 403
        assert body["error_code"] == "admin_disabled"
    finally:
        srv.close()


def test_unknown_session_action_is_not_found(server: _Server) -> None:
    status, body = server.post("/api/admin/session/promote", {})
    assert status == 404
    assert body["ok"] is False
