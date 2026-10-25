"""Controlled provider adapters test admission/CAS, not a live remote account."""
from __future__ import annotations

import json
import pytest

from tests.test_normal_proposal_admission import prepared, _git, _sha, _state
from tests.test_admin_commands import _plan, _execute
from wiki_core.config import load_config
from wiki_core.paths import WikiPaths
from wiki_core.web.admin.sessions import ADMIN_SESSION_HEADER


def _reviewed(prepared):
    srv, root, _params, unlock, _clock = prepared
    config_path = root / "wiki.config.yaml"
    config_path.write_text(config_path.read_text() + "\napproval:\n  gate: github_pr\n  require_human_review: false\n  contribution_validation: local_gates\n")
    _git(root, "add", "wiki.config.yaml")
    _git(root, "commit", "-m", "Declare synthetic promotion policy")
    srv.server.config = load_config(root)
    head = _git(root, "rev-parse", "HEAD")
    path = WikiPaths(root, srv.server.config).derived_root / "review.json"
    path.write_text(json.dumps({"schema_version": "wiki_normal_review.v1", "head": head,
        "repository": "github.com/synthetic/wiki",
        "author": "synthetic-author", "reviewer": "independent-synthetic-reviewer", "decision": "approved",
        "unresolved_findings": [], "evidence": "Controlled synthetic review fixture; not a real review of a provider PR."}))
    return srv, root, unlock(), {"expected_head": head, "pr": "17",
        "review_path": path.relative_to(root).as_posix(), "review_sha256": _sha(path.read_bytes())}


def _controlled_gates(monkeypatch, after=None):
    from wiki_core import action_contribution
    def gates(root, config, *, committed_head, effect_runner):
        # The authority is native; this intentionally controls only gate work.
        effect_runner(lambda: None)
        if after:
            after()
        return [{"argv": ["controlled-gate"], "exit_code": 0}]
    monkeypatch.setattr(action_contribution, "_gates", gates)


def test_revocation_after_gates_prevents_provider_write(prepared, monkeypatch):
    from wiki_core.web import git_workflows
    srv, root, token, params = _reviewed(prepared)
    _controlled_gates(monkeypatch, lambda: srv.server.admin_sessions.lock(token))
    writes = []
    def provider(root, argv, **kwargs):
        if argv[2] != "view":
            writes.append(argv)
        return {"ok": True, "returncode": 0, "stdout": json.dumps({"headRefOid": params["expected_head"],
            "baseRefName": "main", "state": "OPEN", "isDraft": False, "statusCheckRollup": []})}
    monkeypatch.setattr(git_workflows, "_run", provider)
    status, plan = _plan(srv, token, "wiki.proposal.promote", params=params)
    assert status == 200, plan
    before = _state(root)
    status, denied = _execute(srv, token, plan, confirmation=plan["plan"]["confirmation"]["text"])
    assert status == 403 and denied["error_code"] == "admin_session_invalid", denied
    assert writes == [] and _state(root) == before


@pytest.mark.parametrize("uncertain", [False, True])
def test_provider_cas_and_uncertain_outcome_are_distinct(prepared, monkeypatch, uncertain):
    from wiki_core.web import git_workflows
    srv, root, token, params = _reviewed(prepared)
    _controlled_gates(monkeypatch)
    dispatched = []
    merged = False
    def provider(root, argv, **kwargs):
        nonlocal merged
        if argv[2] == "merge":
            dispatched.append(argv)
            merged = not uncertain
            return {"ok": not uncertain, "returncode": None if uncertain else 0, "stdout": "", "stderr": ""}
        if uncertain and dispatched:
            return {"ok": False, "returncode": 1, "stdout": "", "stderr": "controlled unknown observation"}
        return {"ok": True, "returncode": 0, "stdout": json.dumps({"headRefOid": params["expected_head"],
            "baseRefName": "main", "state": "MERGED" if merged else "OPEN", "isDraft": False,
            "statusCheckRollup": [], "mergeCommit": {"oid": "f" * 40} if merged else None})}
    monkeypatch.setattr(git_workflows, "_run", provider)
    status, plan = _plan(srv, token, "wiki.proposal.promote", params=params)
    assert status == 200, plan
    status, result = _execute(srv, token, plan, confirmation=plan["plan"]["confirmation"]["text"])
    assert dispatched == [["gh", "pr", "merge", "17", "--repo", "github.com/synthetic/wiki",
                           "--squash", "--match-head-commit", params["expected_head"]]]
    assert result["output"]["outcome_uncertain"] is uncertain
    if uncertain:
        assert status != 200 and not result["ok"]
        status, locked = srv.post("/api/admin/session/lock", {}, headers={ADMIN_SESSION_HEADER: token})
        assert status == 409 and locked["error_code"] == "admin_effect_outcome_uncertain"
        denied = srv.server.admin_sessions.execute_current(token, plan["plan"]["preconditions"][0]["expected"],
            ("git.publish",), lambda: dispatched.append(["duplicate"]))
        assert not denied["ok"] and len(dispatched) == 1
    else:
        assert status == 200 and result["ok"] and result["output"]["status"] == "merged"
        assert not result["output"]["served_adoption_verified"]


def test_publish_plan_after_native_lock_never_dispatches(prepared, monkeypatch):
    from wiki_core.web import git_workflows
    srv, root, _params, unlock, _clock = prepared
    token = unlock()
    calls = []
    monkeypatch.setattr(git_workflows, "_run", lambda *a, **k: calls.append(1))
    status, plan = _plan(srv, token, "wiki.proposal.publish", params={
        "expected_head": _git(root, "rev-parse", "HEAD"), "operation": "publish_proposal"})
    assert status == 200, plan
    assert srv.post("/api/admin/session/lock", {}, headers={ADMIN_SESSION_HEADER: token})[0] == 200
    status, denied = _execute(srv, token, plan, confirmation=plan["plan"]["confirmation"]["text"])
    assert status == 403 and denied["error_code"] == "admin_session_invalid" and calls == []
