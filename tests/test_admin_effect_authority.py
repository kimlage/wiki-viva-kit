"""Native revocation must order actual effects, not cached descriptions."""
from __future__ import annotations

import re
import threading
from pathlib import Path

from tests.test_web_server import _repo
from wiki_core.web.admin.sessions import AdminSessionManager


def _session(root: Path):
    lines: list[str] = []
    manager = AdminSessionManager(_repo(root), announce=lines.append)
    result = manager.unlock(
        code=re.search(r"code: ([A-Z0-9-]+)", lines[-1]).group(1),
        challenge=manager.issue_challenge()["challenge"],
    )
    assert result["ok"]
    return manager, result, lines


def test_native_lock_refuses_same_material_and_new_unlock_can_execute(tmp_path):
    manager, session, lines = _session(tmp_path)
    target = tmp_path / "effect.txt"
    effect = lambda: target.write_text("unchanged reviewed material\n")
    old_token, old_id = session["token"], session["session"]["session_id"]
    assert manager.lock(old_token)["ok"]
    denied = manager.execute_current(old_token, old_id, ("git.propose",), effect)
    assert denied == {"ok": False, "error_code": "admin_session_invalid"}
    assert not target.exists()
    fresh = manager.unlock(
        code=re.search(r"code: ([A-Z0-9-]+)", lines[-1]).group(1),
        challenge=manager.issue_challenge()["challenge"],
    )
    assert fresh["ok"]
    # Replacement sessions cannot revive an old plan's identity.
    refused = manager.execute_current(fresh["token"], old_id, ("git.propose",), effect)
    assert not refused["ok"] and not target.exists()
    allowed = manager.execute_current(
        fresh["token"], fresh["session"]["session_id"], ("git.propose",), effect,
    )
    assert allowed["ok"]
    assert target.read_text() == "unchanged reviewed material\n"


def test_lock_acknowledges_after_inflight_effect_and_bars_next(tmp_path):
    manager, session, _lines = _session(tmp_path)
    started, release, locked = threading.Event(), threading.Event(), threading.Event()
    token, sid = session["token"], session["session"]["session_id"]
    effects = []

    def first():
        started.set()
        assert release.wait(3)
        effects.append("first")

    worker = threading.Thread(target=lambda: manager.execute_current(token, sid, ("git.propose",), first))
    worker.start()
    assert started.wait(3)

    def revoke():
        assert manager.lock(token)["ok"]
        locked.set()

    revoker = threading.Thread(target=revoke)
    revoker.start()
    assert not locked.wait(.05)
    release.set()
    worker.join(3)
    revoker.join(3)
    assert locked.is_set() and effects == ["first"]
    denied = manager.execute_current(token, sid, ("git.propose",), lambda: effects.append("second"))
    assert not denied["ok"] and effects == ["first"]


def test_live_expiry_and_role_refuse_before_effect(tmp_path):
    manager, session, _lines = _session(tmp_path)
    token, sid = session["token"], session["session"]["session_id"]
    effects = []
    manager._session.role = "observer"
    denied = manager.execute_current(token, sid, ("git.propose",), lambda: effects.append(1))
    assert denied["error_code"] == "admin_capability_denied" and effects == []
    manager.clock = lambda: float("inf")
    expired = manager.execute_current(token, sid, (), lambda: effects.append(2))
    assert expired["error_code"] == "admin_session_expired" and effects == []


def test_expiry_retires_confirmation_credential_until_inflight_effect_drains(tmp_path):
    manager, session, _lines = _session(tmp_path)
    token, sid = session["token"], session["session"]["session_id"]
    started, release = threading.Event(), threading.Event()
    effects = []
    def first():
        started.set()
        assert release.wait(15)
        effects.append("admitted")
    worker = threading.Thread(target=lambda: manager.execute_current(token, sid, ("git.propose",), first))
    worker.start()
    try:
        assert started.wait(3)
        manager.clock = lambda: float("inf")
        assert manager.validate(token)["error_code"] == "admin_session_expired"
        pending = manager.lock(token)
        assert pending["error_code"] == "admin_revocation_pending", pending
        assert not manager.execute_current(token, sid, ("git.propose",), lambda: effects.append("forbidden"))["ok"]
    finally:
        release.set()
        worker.join(3)
    assert effects == ["admitted"]
    assert manager.lock(token)["state"] == "locked"


def test_expired_uncertain_effect_remains_unconfirmed_with_zero_inflight(tmp_path):
    manager, session, _lines = _session(tmp_path)
    token, sid = session["token"], session["session"]["session_id"]
    result = manager.execute_current(token, sid, ("git.publish",),
                                     lambda: {"outcome_uncertain": True})
    assert result["ok"]
    manager.clock = lambda: float("inf")
    observed_session, activity = manager.capability_snapshot(token)
    assert observed_session is None
    assert activity == {"inflight_effects":0,"revocation_pending":False,"outcome_uncertain":True}
    refused = manager.execute_current(token,sid,("git.publish",),lambda: None)
    assert not refused["ok"]
    assert manager.lock(token)["error_code"] == "admin_effect_outcome_uncertain"
    assert manager.unlock(code="not-a-code", challenge="not-a-challenge")["error_code"] == "admin_effect_outcome_uncertain"
