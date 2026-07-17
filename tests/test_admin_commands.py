"""Admin command bus: plan -> review -> execute (god-mode plan §9, §11, §12.2).

Covers §22.5 (per-command capability matrix, including a capability revoked
between plan and execute) and §22.6 (tampered sha, changed file, changed
branch, dry run writes nothing, materialized undo, snapshot invalidated
after a write), plus catalog honesty and audit/plan linkage.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from wiki_core.config import load_config
from wiki_core.web.admin.audit import audit_log_path, verify_admin_audit_chain
from wiki_core.web.admin.commands import ADMIN_COMMAND_SPECS
from wiki_core.web.admin.sessions import ADMIN_SESSION_HEADER
from wiki_core.web.commands import RISK_LEVELS
from wiki_core.web.git_workflows import CHECKOUT_LOCK

# Reuse the running-server fixture machinery from the sibling suites.
from tests.test_admin_sessions import _arm, _code
from tests.test_web_server import _repo, _Server, _write

COMMAND_IDS = [spec.id for spec in ADMIN_COMMAND_SPECS]


@pytest.fixture()
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("WIKI_COCKPIT_CORS_ORIGINS", raising=False)
    config = _repo(tmp_path)
    srv = _Server(tmp_path, config)
    try:
        yield srv
    finally:
        srv.close()


def _unlock_admin(srv: _Server) -> str:
    lines, _clock = _arm(srv)
    status, body = srv.post("/api/admin/session/challenge", {})
    assert status == 200
    status, body = srv.post(
        "/api/admin/session/unlock",
        {"challenge": body["challenge"], "code": _code(lines)},
    )
    assert status == 200 and body["ok"] is True
    return str(body["token"])


def _plan(
    srv: _Server,
    token: str,
    command_id: str,
    *,
    params: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> tuple[int, dict[str, Any]]:
    return srv.post(
        "/api/admin/commands/plan",
        {"command_id": command_id, "params": params or {}, "dry_run": dry_run},
        headers={ADMIN_SESSION_HEADER: token},
    )


def _execute(
    srv: _Server,
    token: str,
    plan: dict[str, Any],
    *,
    confirmation: str | None = None,
    plan_sha: str | None = None,
) -> tuple[int, dict[str, Any]]:
    body: dict[str, Any] = {
        "plan_id": plan["plan_id"],
        "plan_sha": plan_sha if plan_sha is not None else plan["plan_sha"],
    }
    if confirmation is not None:
        body["confirmation"] = confirmation
    return srv.post(
        "/api/admin/commands/execute",
        body,
        headers={ADMIN_SESSION_HEADER: token},
    )


# ---------------------------------------------------------------------------
# catalog (GET /api/admin/commands)
# ---------------------------------------------------------------------------


def test_catalog_locked_lists_commands_without_grants(server: _Server) -> None:
    status, body = server.get("/api/admin/commands")
    assert status == 200 and body["ok"] is True
    assert body["schema_version"] == "wiki_admin_commands.v1"
    assert body["action_schema_version"] == "wiki_web_actions.v1"
    assert body["risk_levels"] == list(RISK_LEVELS)
    assert [entry["id"] for entry in body["commands"]] == COMMAND_IDS
    for entry in body["commands"]:
        assert entry["granted"] is False
        assert entry["reason"] == "session_not_authorized"
    # No argv anywhere in the catalog — the bus never exposes one.
    assert "argv" not in json.dumps(body)


def test_catalog_grants_follow_session_role(server: _Server) -> None:
    token = _unlock_admin(server)
    status, body = server.get(
        "/api/admin/commands", headers={ADMIN_SESSION_HEADER: token}
    )
    assert status == 200
    assert all(entry["granted"] is True for entry in body["commands"])
    # Observer keeps the inspects but loses validate/rebuild (§8.3).
    server.server.admin_sessions._session.role = "observer"
    _status, partial = server.get(
        "/api/admin/commands", headers={ADMIN_SESSION_HEADER: token}
    )
    granted = {e["id"] for e in partial["commands"] if e["granted"]}
    assert granted == {"system.inspect", "config.inspect"}
    denied = {e["id"]: e["reason"] for e in partial["commands"] if not e["granted"]}
    assert denied == {
        "config.validate": "role_not_authorized",
        "snapshot.rebuild": "role_not_authorized",
    }


def test_health_advertises_admin_commands_capability(server: _Server) -> None:
    _status, body = server.get("/api/health")
    assert "admin_commands_v1" in body["schema_capabilities"]


# ---------------------------------------------------------------------------
# §22.5 capability matrix, per command
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command_id", COMMAND_IDS)
def test_plan_without_session_is_a_typed_refusal(
    server: _Server, command_id: str
) -> None:
    status, body = server.post(
        "/api/admin/commands/plan", {"command_id": command_id, "params": {}}
    )
    assert status == 403
    assert body["error_code"] == "admin_session_invalid"


@pytest.mark.parametrize("command_id", COMMAND_IDS)
def test_plan_with_admin_session_materializes(server: _Server, command_id: str) -> None:
    token = _unlock_admin(server)
    status, body = _plan(server, token, command_id)
    assert status == 200 and body["ok"] is True
    assert body["plan_id"].startswith("plan_")
    assert body["plan_sha"].startswith("sha256:")
    plan = body["plan"]
    assert plan["schema_version"] == "wiki_admin_plan.v1"
    assert plan["command_id"] == command_id
    assert plan["risk_level"] in RISK_LEVELS
    assert {p["id"] for p in plan["preconditions"]} == {
        "session",
        "capabilities",
        "branch",
        "worktree_fingerprint",
        "config_fingerprint",
        "targets_exist",
        "checkout_lock",
    }
    assert set(plan["effects"]) == {
        "files_read",
        "files_write",
        "external_calls",
        "snapshot_invalidated",
    }
    assert plan["confirmation"]["kind"] in {"none", "simple", "typed"}


@pytest.mark.parametrize(
    "command_id, allowed",
    [
        ("system.inspect", True),
        ("config.inspect", True),
        ("config.validate", False),
        ("snapshot.rebuild", False),
    ],
)
def test_partial_role_plans_only_its_subset(
    server: _Server, command_id: str, allowed: bool
) -> None:
    token = _unlock_admin(server)
    server.server.admin_sessions._session.role = "observer"
    status, body = _plan(server, token, command_id)
    if allowed:
        assert status == 200 and body["ok"] is True
    else:
        assert status == 403
        assert body["error_code"] == "admin_capability_denied"
        assert body["reason"] == "role_not_authorized"


def test_capability_revoked_between_plan_and_execute(server: _Server) -> None:
    token = _unlock_admin(server)
    _status, planned = _plan(server, token, "config.validate")
    assert planned["ok"] is True
    # The role is downgraded AFTER review: execute must revalidate and refuse.
    server.server.admin_sessions._session.role = "observer"
    status, body = _execute(server, token, planned)
    assert status == 403
    assert body["error_code"] == "admin_capability_denied"


def test_session_locked_between_plan_and_execute(server: _Server) -> None:
    token = _unlock_admin(server)
    _status, planned = _plan(server, token, "system.inspect")
    status, _body = server.post(
        "/api/admin/session/lock", {}, headers={ADMIN_SESSION_HEADER: token}
    )
    assert status == 200
    status, body = _execute(server, token, planned)
    assert status == 403
    assert body["error_code"] == "admin_session_invalid"


def test_unknown_command_and_unexpected_params_fail_typed(server: _Server) -> None:
    token = _unlock_admin(server)
    status, body = _plan(server, token, "raw.shell")
    assert status == 400 and body["error_code"] == "admin_unknown_command"
    status, body = _plan(
        server, token, "system.inspect", params={"argv": "rm -rf /"}
    )
    assert status == 400 and body["error_code"] == "admin_invalid_params"
    status, body = _plan(server, token, "system.inspect", dry_run=True)
    assert status == 400 and body["error_code"] == "admin_invalid_params"


# ---------------------------------------------------------------------------
# §22.6 plan/execute integrity
# ---------------------------------------------------------------------------


def test_execute_runs_exactly_the_reviewed_plan(server: _Server) -> None:
    token = _unlock_admin(server)
    _status, planned = _plan(server, token, "system.inspect")
    status, body = _execute(server, token, planned)
    assert status == 200 and body["ok"] is True
    assert body["status"] == "success"
    assert body["plan_id"] == planned["plan_id"]
    assert body["plan_sha"] == planned["plan_sha"]
    assert body["output"]["admin"]["server_version"] == "wiki_admin.v1"
    assert body["snapshot_invalidated"] is False
    # The session token never appears in any bus payload.
    assert token not in json.dumps(planned) + json.dumps(body)


def test_tampered_plan_sha_is_refused(server: _Server) -> None:
    token = _unlock_admin(server)
    _status, planned = _plan(server, token, "system.inspect")
    status, body = _execute(
        server, token, planned, plan_sha="sha256:" + "0" * 64
    )
    assert status == 409
    assert body["error_code"] == "admin_plan_sha_mismatch"


def test_worktree_change_between_plan_and_execute_stales(server: _Server, tmp_path: Path) -> None:
    token = _unlock_admin(server)
    _status, planned = _plan(server, token, "system.inspect")
    _write(tmp_path / "memories/new-page.md", "# New\n")
    status, body = _execute(server, token, planned)
    assert status == 409
    assert body["error_code"] == "admin_plan_stale"
    assert "worktree_fingerprint" in body["failed_preconditions"]
    # Stale plans are consumed: the same plan can never execute later.
    status, body = _execute(server, token, planned)
    assert status == 404
    assert body["error_code"] == "admin_plan_not_found"


def test_branch_change_between_plan_and_execute_stales(server: _Server, tmp_path: Path) -> None:
    token = _unlock_admin(server)
    _status, planned = _plan(server, token, "system.inspect")
    subprocess.run(
        ["git", "checkout", "-b", "wiki/elsewhere"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    status, body = _execute(server, token, planned)
    assert status == 409
    assert body["error_code"] == "admin_plan_stale"
    assert "branch" in body["failed_preconditions"]


def test_config_change_between_plan_and_execute_stales(server: _Server, tmp_path: Path) -> None:
    token = _unlock_admin(server)
    _status, planned = _plan(server, token, "config.inspect")
    config_path = tmp_path / "wiki.config.yaml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8") + "# reviewed reality moved\n",
        encoding="utf-8",
    )
    status, body = _execute(server, token, planned)
    assert status == 409
    assert body["error_code"] == "admin_plan_stale"
    assert "config_fingerprint" in body["failed_preconditions"]


def test_dry_run_writes_nothing(server: _Server, tmp_path: Path) -> None:
    token = _unlock_admin(server)
    _status, planned = _plan(server, token, "snapshot.rebuild", dry_run=True)
    plan = planned["plan"]
    assert plan["dry_run"] is True
    assert plan["effects"]["files_write"] == []
    assert plan["effects"]["snapshot_invalidated"] is False
    # No writes -> nothing to confirm (§9 policy).
    assert plan["confirmation"] == {"kind": "none", "text": None}
    status, body = _execute(server, token, planned)
    assert status == 200 and body["ok"] is True
    assert body["output"]["dry_run"] is True
    assert body["output"]["written"] == []
    assert sorted(body["output"]["would_write"]) == body["output"]["would_write"]
    assert not (tmp_path / "data/derived/wiki/web-snapshot").exists()
    assert body["snapshot_invalidated"] is False


def test_snapshot_rebuild_confirms_writes_and_materializes_undo(
    server: _Server, tmp_path: Path
) -> None:
    token = _unlock_admin(server)
    _status, planned = _plan(server, token, "snapshot.rebuild")
    plan = planned["plan"]
    assert plan["effects"]["snapshot_invalidated"] is True
    assert plan["confirmation"] == {"kind": "simple", "text": "RUN snapshot.rebuild"}
    # Missing then wrong confirmation: refused without consuming the plan.
    status, body = _execute(server, token, planned)
    assert status == 400 and body["error_code"] == "admin_confirmation_required"
    status, body = _execute(server, token, planned, confirmation="RUN everything")
    assert status == 400 and body["error_code"] == "admin_confirmation_mismatch"
    # The exact reviewed phrase runs it.
    status, body = _execute(
        server, token, planned, confirmation="RUN snapshot.rebuild"
    )
    assert status == 200 and body["ok"] is True
    assert body["snapshot_invalidated"] is True
    assert body["affected_paths"] == ["data/derived/wiki/web-snapshot"]
    assert (tmp_path / "data/derived/wiki/web-snapshot").exists()
    # First build: undo is materialized but honestly unavailable (no prior).
    assert body["undo"]["kind"] == "restore_previous_snapshot_revision"
    assert body["undo"]["available"] is False
    # Second rebuild: the undo now points at the first revision.
    _status, replanned = _plan(server, token, "snapshot.rebuild")
    status, second = _execute(
        server, token, replanned, confirmation="RUN snapshot.rebuild"
    )
    assert status == 200 and second["ok"] is True
    assert second["undo"]["available"] is True
    assert second["undo"]["previous_revision"]


def test_snapshot_cache_invalidated_after_write(server: _Server) -> None:
    token = _unlock_admin(server)
    status, _manifest = server.get("/api/snapshot/manifest.json")
    assert status == 200
    assert server.server._snapshot_cache is not None
    _status, planned = _plan(server, token, "snapshot.rebuild")
    status, body = _execute(
        server, token, planned, confirmation="RUN snapshot.rebuild"
    )
    assert status == 200 and body["ok"] is True
    # The commit boundary published the invalidation before the response.
    assert server.server._snapshot_cache is None


def test_plans_are_single_use(server: _Server) -> None:
    token = _unlock_admin(server)
    _status, planned = _plan(server, token, "system.inspect")
    status, body = _execute(server, token, planned)
    assert status == 200 and body["ok"] is True
    status, body = _execute(server, token, planned)
    assert status == 409
    assert body["error_code"] == "admin_plan_already_executed"


def test_concurrent_executes_cannot_both_consume_one_plan(
    server: _Server,
) -> None:
    """The single-use gate is the ATOMIC store transition, not the advisory
    peek: even when two racing requests both saw status "planned" on their
    stale peeked copies, only one can win `consume` (plan §11.3)."""

    from wiki_core.web.admin.plans import AdminPlanStore

    store = AdminPlanStore()
    store.put("plan_race", "sha256:" + "0" * 64, {"command_id": "x"}, "session_1")
    # Both threads have already peeked "planned" — the interleaving the
    # request path can hit between its peek and the checkout lock.
    assert store.peek("plan_race")["status"] == "planned"
    assert store.consume("plan_race") is True
    assert store.consume("plan_race") is False
    assert store.peek("plan_race")["status"] == "executed"
    # Unknown plans never consume.
    assert store.consume("plan_missing") is False


def test_unknown_plan_is_not_found(server: _Server) -> None:
    token = _unlock_admin(server)
    status, body = server.post(
        "/api/admin/commands/execute",
        {"plan_id": "plan_missing", "plan_sha": "sha256:" + "0" * 64},
        headers={ADMIN_SESSION_HEADER: token},
    )
    assert status == 404
    assert body["error_code"] == "admin_plan_not_found"


def test_checkout_lock_busy_refuses_execution(server: _Server) -> None:
    token = _unlock_admin(server)
    _status, planned = _plan(server, token, "system.inspect")
    assert CHECKOUT_LOCK.acquire(timeout=1)
    try:
        status, body = _execute(server, token, planned)
    finally:
        CHECKOUT_LOCK.release()
    assert status == 409
    assert body["error_code"] == "admin_checkout_busy"
    assert body["retryable"] is True
    # The refusal did not consume the plan: it runs once the lock frees.
    status, body = _execute(server, token, planned)
    assert status == 200 and body["ok"] is True


def test_config_validate_reports_invalid_file_without_writing(
    server: _Server, tmp_path: Path
) -> None:
    token = _unlock_admin(server)
    config_path = tmp_path / "wiki.config.yaml"
    broken = (
        "repo_id: srv-test\ndefault_context: system\ncodex:\n  enabled: false\n"
        "admin:\n  local_unlock: password_file\n"
    )
    config_path.write_text(broken, encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(tmp_path)
    _status, planned = _plan(server, token, "config.validate")
    status, body = _execute(server, token, planned)
    assert status == 200 and body["ok"] is True
    assert body["output"]["valid"] is False
    assert "local_unlock" in body["output"]["error"]
    # Validation wrote nothing: the broken file is byte-identical.
    assert config_path.read_text(encoding="utf-8") == broken


def test_plan_endpoint_is_session_scoped(server: _Server) -> None:
    token = _unlock_admin(server)
    _status, planned = _plan(server, token, "system.inspect")
    status, body = server.get(
        f"/api/admin/plans/{planned['plan_id']}",
        headers={ADMIN_SESSION_HEADER: token},
    )
    assert status == 200 and body["ok"] is True
    assert body["plan_sha"] == planned["plan_sha"]
    assert body["plan"]["command_id"] == "system.inspect"
    status, body = server.get(f"/api/admin/plans/{planned['plan_id']}")
    assert status == 403 and body["error_code"] == "admin_session_invalid"
    status, _body = server.get(
        "/api/admin/plans/plan_missing", headers={ADMIN_SESSION_HEADER: token}
    )
    assert status == 404


def test_audit_links_plan_and_execution(server: _Server, tmp_path: Path) -> None:
    token = _unlock_admin(server)
    _status, planned = _plan(server, token, "system.inspect")
    _status, executed = _execute(server, token, planned)
    assert executed["ok"] is True
    path = audit_log_path(tmp_path, load_config(tmp_path))
    lines = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    linked = [e for e in lines if e.get("plan_id") == planned["plan_id"]]
    assert len(linked) == 2  # one plan event, one execute event
    assert all(e["plan_sha"] == planned["plan_sha"] for e in linked)
    assert all(e["command_id"] == "system.inspect" for e in linked)
    assert verify_admin_audit_chain(path)["ok"] is True
    # Neither the token nor an unlock code ever reaches the trail.
    flat = path.read_text(encoding="utf-8")
    assert token not in flat
