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
    approved = _git(root, "rev-parse", "HEAD")
    _git(root, "branch", "-f", "main", approved)
    page = root / "memories/index.md"
    page.write_text(page.read_text() + "\nA reviewed synthetic documentary update.\n")
    _git(root, "add", "memories/index.md")
    _git(root, "commit", "-m", "Prepare synthetic documentary update")
    srv.server.config = load_config(root)
    head = _git(root, "rev-parse", "HEAD")
    path = WikiPaths(root, srv.server.config).derived_root / "review.json"
    path.write_text(json.dumps({"schema_version": "wiki_normal_review.v1", "head": head,
        "approved_base": approved,
        "repository": "github.com/synthetic/wiki",
        "author": "synthetic-author", "reviewer": "independent-synthetic-reviewer", "decision": "approved",
        "unresolved_findings": [], "evidence": "Controlled synthetic review fixture; not a real review of a provider PR."}))
    return srv, root, unlock(), {"expected_head": head, "approved_base": approved, "pr": "17",
        "review_path": path.relative_to(root).as_posix(), "review_sha256": _sha(path.read_bytes())}


def _controlled_gates(monkeypatch, after=None):
    from wiki_core import action_contribution
    def gates(root, committed_head, *, effect_runner, **kwargs):
        # The authority is native; this intentionally controls only gate work.
        effect_runner(lambda: None)
        if after:
            after()
        return [{"argv": ["controlled-gate"], "exit_code": 0}]
    monkeypatch.setattr(action_contribution, "_local_integration_gates", gates)


def test_revocation_after_gates_prevents_provider_write(prepared, monkeypatch):
    from wiki_core.web import git_workflows
    srv, root, token, params = _reviewed(prepared)
    _controlled_gates(monkeypatch, lambda: srv.server.admin_sessions.lock(token))
    writes = []
    def provider(root, argv, **kwargs):
        if argv[2] != "view":
            writes.append(argv)
        return {"ok": True, "returncode": 0, "stdout": json.dumps({"headRefOid": params["expected_head"],
            "number":17,"headRefName":"wiki/synthetic-proposal","baseRefOid":params["approved_base"],
            "isCrossRepository":False,"headRepository":{"name":"wiki"},"headRepositoryOwner":{"login":"synthetic"},
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
            "number":17,"headRefName":"wiki/synthetic-proposal","baseRefOid":params["approved_base"],
            "isCrossRepository":False,"headRepository":{"name":"wiki"},"headRepositoryOwner":{"login":"synthetic"},
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


def _pr(params, **overrides):
    return {"number":17, "headRefOid":params["expected_head"],
        "headRefName":"wiki/synthetic-proposal", "baseRefOid":params["approved_base"],
        "baseRefName":"main", "isCrossRepository":False, "headRepository":{"name":"wiki"},
        "headRepositoryOwner":{"login":"synthetic"}, "state":"OPEN", "isDraft":False,
        "reviewDecision":"", "statusCheckRollup":[], **overrides}


def _run_promote(srv, token, params):
    status, plan = _plan(srv, token, "wiki.proposal.promote", params=params)
    assert status == 200, plan
    return _execute(srv, token, plan, confirmation=plan["plan"]["confirmation"]["text"])


@pytest.mark.parametrize("refusal", [{"reviewDecision":"CHANGES_REQUESTED"},
    {"statusCheckRollup":[{"name":"synthetic-check", "conclusion":"FAILURE"}]}])
def test_local_gate_policy_never_overrides_remote_refusals(prepared, monkeypatch, refusal):
    from wiki_core.web import git_workflows
    srv, root, token, params = _reviewed(prepared)
    calls = []
    _controlled_gates(monkeypatch)
    def provider(root, argv, **kwargs):
        calls.append(argv[2])
        return {"ok":True,"stdout":json.dumps(_pr(params, **refusal))}
    monkeypatch.setattr(git_workflows, "_run", provider)
    status, result = _run_promote(srv, token, params)
    assert status != 200 and not result["ok"]
    assert calls == ["view"]


@pytest.mark.parametrize("malformed", ["json", "merge_commit"])
def test_malformed_post_merge_readback_bars_further_writes(prepared, monkeypatch, malformed):
    from wiki_core.web import git_workflows
    srv, root, token, params = _reviewed(prepared)
    _controlled_gates(monkeypatch)
    dispatched = []
    def provider(root, argv, **kwargs):
        if argv[2] == "merge":
            dispatched.append(argv)
            return {"ok":True,"returncode":0,"stdout":""}
        value = _pr(params)
        if dispatched:
            if malformed == "json":
                return {"ok":True,"stdout":"{invalid synthetic JSON"}
            value.update(state="MERGED", mergeCommit=["invalid synthetic shape"])
        return {"ok":True,"stdout":json.dumps(value)}
    monkeypatch.setattr(git_workflows, "_run", provider)
    status, result = _run_promote(srv, token, params)
    assert len(dispatched) == 1 and status != 200
    assert result["output"]["outcome_uncertain"] is True
    assert srv.post("/api/admin/session/lock", {}, headers={ADMIN_SESSION_HEADER:token})[1]["error_code"] == "admin_effect_outcome_uncertain"


@pytest.mark.parametrize("failure", ["revocation", "remote_refusal"])
def test_ready_receipt_survives_later_refusal(prepared, monkeypatch, failure):
    from wiki_core.web import git_workflows
    srv, root, token, params = _reviewed(prepared)
    _controlled_gates(monkeypatch)
    writes = []
    def provider(root, argv, **kwargs):
        if argv[2] == "ready":
            writes.append("ready")
            if failure == "revocation":
                srv.server.admin_sessions.lock(token)
            return {"ok":True,"returncode":0,"stdout":""}
        assert argv[2] == "view", "merge must not be dispatched"
        # First readback confirms the completed ready effect. Next pre-effect
        # observation can independently refuse the merge.
        provider.views += 1
        refusal = failure == "remote_refusal" and writes and provider.views >= 5
        return {"ok":True,"stdout":json.dumps(_pr(params, isDraft=not bool(writes),
            reviewDecision="CHANGES_REQUESTED" if refusal else ""))}
    provider.views = 0
    monkeypatch.setattr(git_workflows, "_run", provider)
    status, result = _run_promote(srv, token, params)
    assert status != 200 and writes == ["ready"]
    assert result["output"]["status"] == "partial"
    ready, = result["output"]["results"]
    assert ready["stage"] == "pr.ready" and ready["ok"]
    assert result["output"]["outcome_uncertain"] is False


def test_immutable_gate_checkout_ignores_mutable_scripts_and_policy(tmp_path, monkeypatch):
    import wiki_core.action_contribution as port
    from test_action_contribution import fixture
    fixture(tmp_path)
    config = tmp_path / "wiki.config.yaml"
    config.write_text(config.read_text() + "  contribution_validation: local_gates\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "Approved synthetic immutable policy")
    committed = _git(tmp_path, "rev-parse", "HEAD")
    script = tmp_path / "scripts/wiki_audit.py"
    expected = script.read_bytes()
    script.write_text("raise SystemExit('mutable caller is not the reviewed gate')\n")
    config.write_text(config.read_text().replace("local_gates", "github_checks"))
    calls = []
    def gates(root, config, **kwargs):
        assert root != tmp_path and _git(root, "rev-parse", "HEAD") == committed
        assert (root / "scripts/wiki_audit.py").read_bytes() == expected
        assert config.approval["contribution_validation"] == "local_gates"
        return [{"exit_code":0}]
    monkeypatch.setattr(port, "_gates", gates)
    def guard(call):
        calls.append(1)
        return call()
    assert port._local_integration_gates(tmp_path, committed, effect_runner=guard) == [{"exit_code":0}]
    assert _git(tmp_path, "rev-parse", "HEAD") == committed and script.read_bytes() != expected


@pytest.mark.parametrize("field", ["title", "body"])
def test_publication_secrets_are_refused_before_plan_echo_or_dispatch(prepared, monkeypatch, field):
    from wiki_core.web import git_workflows
    srv, root, _params, unlock, _clock = prepared
    calls = []
    monkeypatch.setattr(git_workflows, "_run", lambda *a, **k: calls.append(a))
    synthetic_secret = "AKIAIOSFODNN7EXAMPLE"
    status, result = _plan(srv, unlock(), "wiki.proposal.publish", params={
        "expected_head":_git(root, "rev-parse", "HEAD"), "operation":"open_draft_pr", field:synthetic_secret})
    assert status != 200 and synthetic_secret not in json.dumps(result) and calls == []


def test_distinct_effective_push_url_is_refused_before_dispatch(prepared, monkeypatch):
    from wiki_core.web import git_workflows
    srv, root, _params, unlock, _clock = prepared
    _git(root, "remote", "set-url", "--push", "origin", "git@github.com:other-synthetic/wiki.git")
    calls = []
    monkeypatch.setattr(git_workflows, "_run", lambda *a, **k: calls.append(a))
    status, result = _plan(srv, unlock(), "wiki.proposal.publish", params={
        "expected_head":_git(root, "rev-parse", "HEAD"), "operation":"publish_proposal"})
    assert status != 200 and calls == []


@pytest.mark.parametrize("wrong_after", [False, True, "malformed_shape"])
def test_pr_edit_binds_pre_and_post_head_and_requested_content(prepared, monkeypatch, wrong_after):
    from wiki_core.web import git_workflows
    srv, root, _params, unlock, _clock = prepared
    head = _git(root, "rev-parse", "HEAD")
    branch = _git(root, "branch", "--show-current")
    calls = []
    before = {"headRefOid":head if wrong_after else "0"*40,"headRefName":branch,
        "baseRefName":"main","state":"OPEN", "url":"https://example.invalid/synthetic-pr"}
    def provider(root, argv, **kwargs):
        if argv[:2] == ["git", "ls-remote"]:
            return {"ok":True,"stdout":head+"\trefs/heads/"+branch+"\n"}
        if argv[2] == "edit":
            calls.append(argv)
            return {"ok":False,"returncode":1,"stdout":"","stderr":"controlled edit failure"}
        value = [before] if argv[2] == "list" else (["not a PR object"] if wrong_after == "malformed_shape" else
            {**before,"headRefOid":head,"title":"Old title","body":"Old body"})
        return {"ok":True,"stdout":json.dumps(value)}
    monkeypatch.setattr(git_workflows, "_run", provider)
    token = unlock()
    status, plan = _plan(srv, token, "wiki.proposal.publish", params={
        "expected_head":head, "operation":"update_draft_pr", "title":"Reviewed synthetic title", "body":"Reviewed synthetic body"})
    assert status == 200, plan
    status, result = _execute(srv, token, plan, confirmation=plan["plan"]["confirmation"]["text"])
    assert status != 200 and not result["ok"]
    if wrong_after:
        assert len(calls) == 1 and result["output"]["outcome_uncertain"] is True
    else:
        assert calls == []
