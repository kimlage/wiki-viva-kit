"""Exact-head local gates with real synthetic Git; GitHub remains a test double."""
from __future__ import annotations

import copy
import subprocess
import sys

import pytest
import yaml

import wiki_core.action_contribution as port
from test_action_contribution import fixture, git, call, review, head_review, reconcile_pr_identity, sha
from wiki_core.config import load_config
from wiki_core.web.git_workflows import run_git_workflow


def integration(root, monkeypatch, *, policy="local_gates", human=False):
    path, request = fixture(root)
    config_file = root / "wiki.config.yaml"
    config = yaml.safe_load(config_file.read_text())
    if policy is not None:
        config["approval"]["contribution_validation"] = policy
    if human:
        config["approval"]["require_human_review"] = True
    config["approval"]["contribution_gates"] = [[sys.executable, "scripts/consumer_gate.py"]]
    config_file.write_text(yaml.safe_dump(config, sort_keys=False))
    (root / "scripts/consumer_gate.py").write_text(
        "import os\nraise SystemExit(int(os.environ.get('WIKI_SYNTHETIC_GATE_EXIT', '0')))\n")
    git(root, "add", "wiki.config.yaml", "scripts/consumer_gate.py")
    git(root, "commit", "-m", "Synthetic committed validation policy")
    prepared = call(root, "prepare", request, review=review(request))
    assert prepared["ok"], prepared
    remote = root.parent / (root.name + "-remote.git")
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    git(root, "remote", "add", "origin", str(remote))
    git(root, "push", "origin", "main", prepared["branch"])
    pr = {"number": 7, "state": "OPEN", "headRefOid": prepared["proposal_commit"],
          "baseRefName": "main", "statusCheckRollup": [], "reviews": []}
    reconcile_pr_identity(pr, prepared)
    monkeypatch.setattr(port, "_pr", lambda *_: copy.deepcopy(pr))
    monkeypatch.setattr(port, "_repository", lambda *_: "example.test/synthetic/wiki")
    effects = []
    real_run = port._run

    def run(location, *argv, **kwargs):
        if argv[:3] == ("gh", "pr", "merge"):
            assert "--admin" not in argv and "--force" not in argv
            assert argv[argv.index("--match-head-commit") + 1] == prepared["proposal_commit"]
            effects.append(argv)
            git(root, "push", "origin", prepared["proposal_commit"] + ":refs/heads/main")
            pr.update(state="MERGED", mergeCommit={"oid": prepared["proposal_commit"]})
            return ""
        return real_run(location, *argv, **kwargs)

    monkeypatch.setattr(port, "_run", run)
    return path, request, prepared, pr, effects


def integrate(root, request, prepared, **kwargs):
    return call(root, "integrate", request, pr=7,
                head_review=head_review(request, prepared["proposal_commit"]), **kwargs)


@pytest.mark.parametrize("policy", [None, "github_checks"])
def test_default_still_requires_remote_checks_even_with_supplied_receipts(tmp_path, monkeypatch, policy):
    _, request, prepared, _, effects = integration(tmp_path, monkeypatch, policy=policy)
    result = integrate(tmp_path, request, prepared, gate_receipts=[{"exit_code": 0}],
                       contribution_validation="local_gates")
    assert result["status"] == "waiting_ci_or_pr", result
    assert result["validation_policy"] == "github_checks" and not effects


def test_local_policy_runs_frozen_gates_and_reports_actual_commit_without_remote_ci(tmp_path, monkeypatch):
    path, request, prepared, _, effects = integration(tmp_path, monkeypatch)
    before = (git(tmp_path, "rev-parse", "HEAD"), path.read_bytes())
    # An unrelated local script edit is preserved and must never replace the
    # gate program from the approved parent of the reviewed proposal.
    local_gate = tmp_path / "scripts/consumer_gate.py"
    local_gate.write_text("raise SystemExit('unreviewed local gate')\n")
    observed = []
    real_gates = port._gates

    def gates(root, config, **kwargs):
        observed.append((root, git(root, "rev-parse", "HEAD"), kwargs))
        return real_gates(root, config, **kwargs)

    monkeypatch.setattr(port, "_gates", gates)
    result = integrate(tmp_path, request, prepared)
    assert result["remote_merged"] and result["status"] == "waiting_worktree_adoption", result
    assert result["validation_policy"] == "local_gates"
    assert result["validation_commit"] == prepared["proposal_commit"]
    assert result["validation_policy_sha256"] == sha(port._blob(tmp_path, prepared["proposal_commit"], "wiki.config.yaml"))
    assert result["remote_check_receipts"] == []
    assert len(result["gate_receipts"]) == 5 and all(r["exit_code"] == 0 for r in result["gate_receipts"])
    assert result["gate_receipts"][3]["argv"] == ["git", "diff", "--check",
        prepared["proposal_commit"] + "^", prepared["proposal_commit"]]
    assert len(observed) == 1 and observed[0][0] != tmp_path
    assert observed[0][1] == prepared["proposal_commit"]
    assert (git(tmp_path, "rev-parse", "HEAD"), path.read_bytes()) == before
    assert "unreviewed local gate" in local_gate.read_text() and len(effects) == 1


def test_local_failure_cannot_be_replaced_by_payload_receipts(tmp_path, monkeypatch):
    _, request, prepared, _, effects = integration(tmp_path, monkeypatch)
    monkeypatch.setenv("WIKI_SYNTHETIC_GATE_EXIT", "7")
    result = integrate(tmp_path, request, prepared, gate_receipts=[{"exit_code": 0}],
                       validation_commit=prepared["proposal_commit"])
    assert result["error"].startswith("proposal_gate_failed"), result
    assert result["gate_receipts"][-1]["exit_code"] == 7 and not effects
    assert result["validation_commit"] == prepared["proposal_commit"]


def test_uncommitted_local_opt_in_does_not_authorize_integration(tmp_path, monkeypatch):
    _, request, prepared, _, effects = integration(tmp_path, monkeypatch, policy=None)
    config_file = tmp_path / "wiki.config.yaml"
    config = yaml.safe_load(config_file.read_text())
    config["approval"]["contribution_validation"] = "local_gates"
    config_file.write_text(yaml.safe_dump(config, sort_keys=False))
    monkeypatch.setattr(port, "_local_integration_gates", lambda *_: pytest.fail("uncommitted policy executed gates"))
    result = integrate(tmp_path, request, prepared)
    assert result["error"] == "policy_changed_since_prepare" and not effects


@pytest.mark.parametrize("failure", ["unavailable", "timeout"])
def test_unavailable_local_gate_refuses_without_a_merge(tmp_path, monkeypatch, failure):
    _, request, prepared, _, effects = integration(tmp_path, monkeypatch)
    real_run = subprocess.run

    def run(argv, *args, **kwargs):
        if argv[:2] == [sys.executable, "scripts/consumer_gate.py"]:
            if failure == "timeout":
                raise subprocess.TimeoutExpired(argv, 600)
            raise OSError("Synthetic unavailable gate")
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(port.subprocess, "run", run)
    result = integrate(tmp_path, request, prepared)
    assert result["error"] == "gate_unavailable" and not effects


@pytest.mark.parametrize("policy", ["skip", "", True, None, {}])
def test_invalid_validation_policy_fails_closed(tmp_path, monkeypatch, policy):
    _, request, prepared, pr, effects = integration(tmp_path, monkeypatch, policy="local_gates")
    # Mutating only the loaded configuration also exercises rejection before
    # any supplied success report or remote success could grant promotion.
    config = load_config(tmp_path)
    config.approval["contribution_validation"] = policy
    monkeypatch.setattr(port, "load_config", lambda *_: config)
    pr["statusCheckRollup"] = [{"conclusion": "SUCCESS"}]
    result = integrate(tmp_path, request, prepared)
    assert result["error"] == "invalid_contribution_validation_policy" and not effects


@pytest.mark.parametrize("checks", [[{"conclusion": "FAILURE"}], [{"state": "PENDING"}], [{"conclusion": "CANCELLED"}]])
def test_local_policy_does_not_ignore_present_remote_failures(tmp_path, monkeypatch, checks):
    _, request, prepared, pr, effects = integration(tmp_path, monkeypatch)
    pr["statusCheckRollup"] = checks
    monkeypatch.setattr(port, "_local_integration_gates", lambda *_: pytest.fail("must not run gates while PR blocked"))
    result = integrate(tmp_path, request, prepared)
    assert result["status"] == "waiting_ci_or_pr" and result["remote_check_receipts"] == checks
    assert not effects


def test_local_policy_keeps_explicit_human_approval_requirement(tmp_path, monkeypatch):
    _, request, prepared, _, effects = integration(tmp_path, monkeypatch, human=True)
    result = integrate(tmp_path, request, prepared)
    assert result["status"] == "waiting_human_review" and not effects


@pytest.mark.parametrize("report", ["missing", "wrong_head", "self_review"])
def test_local_policy_requires_independent_review_of_generated_head(tmp_path, monkeypatch, report):
    _, request, prepared, _, effects = integration(tmp_path, monkeypatch)
    head = head_review(request, prepared["proposal_commit"])
    if report == "missing":
        head = None
    elif report == "wrong_head":
        head["proposal_commit"] = "0" * 40
    else:
        head["reviewer_session_id"] = request["session_ref"]["session_id"]
    result = call(tmp_path, "integrate", request, pr=7, head_review=head)
    assert result["error"] in {"exact_generated_head_review_required", "independent_reviewer_required"}
    assert not effects


@pytest.mark.parametrize("mutation", ["body", "index", "untracked", "head"])
def test_local_gate_cannot_change_validated_tree_or_commit(tmp_path, monkeypatch, mutation):
    _, request, prepared, _, effects = integration(tmp_path, monkeypatch)
    real_gates = port._gates

    def gates(root, config, **kwargs):
        receipts = real_gates(root, config, **kwargs)
        if mutation in {"body", "index"}:
            target = root / request["files"][0]["path"]
            target.write_text(target.read_text() + "Changed by gate\n")
            if mutation == "index":
                git(root, "add", request["files"][0]["path"])
        elif mutation == "untracked":
            (root / "unreviewed.txt").write_text("Unexpected authored output")
        else:
            git(root, "checkout", "--detach", prepared["proposal_commit"] + "^")
        return receipts

    monkeypatch.setattr(port, "_gates", gates)
    result = integrate(tmp_path, request, prepared)
    assert result["error"] == "local_validation_modified_proposal" and not effects


@pytest.mark.parametrize("drift", ["policy", "action", "log", "proposal", "pr_checks", "pr_head", "pr_draft"])
def test_local_validation_rechecks_live_inputs_after_gates(tmp_path, monkeypatch, drift):
    path, request, prepared, pr, effects = integration(tmp_path, monkeypatch)
    real_gates = port._gates

    def gates(root, config, **kwargs):
        receipts = real_gates(root, config, **kwargs)
        if drift == "policy":
            target = tmp_path / "wiki.config.yaml"
            target.write_text(target.read_text() + "# Concurrent policy edit\n")
        elif drift == "action":
            path.write_text(path.read_text() + "Concurrent action edit\n")
        elif drift == "log":
            target = tmp_path / "memories/system/log.md"
            target.write_text(target.read_text() + "Concurrent log append\n")
        elif drift == "proposal":
            git(tmp_path, "update-ref", "refs/heads/" + prepared["branch"], git(tmp_path, "rev-parse", "HEAD"))
        elif drift == "pr_checks":
            pr["statusCheckRollup"] = [{"state": "PENDING"}]
        elif drift == "pr_head":
            pr["headRefOid"] = "0" * 40
        else:
            pr["isDraft"] = True
        return receipts

    monkeypatch.setattr(port, "_gates", gates)
    result = integrate(tmp_path, request, prepared)
    expected = {"policy": "policy_changed_since_prepare", "action": "source_changed_since_prepare",
                "log": "canonical_or_worktree_log_changed", "proposal": "proposal_head_changed_after_review",
                "pr_checks": "waiting_ci_or_pr", "pr_head": "pr_identity_conflict", "pr_draft": "waiting_pr_review"}
    assert result.get("error", result["status"]).startswith(expected[drift]), result
    assert not effects
    assert len(result["gate_receipts"]) == 5


def test_local_dry_run_does_not_run_gates_or_claim_ready(tmp_path, monkeypatch):
    _, request, prepared, _, effects = integration(tmp_path, monkeypatch)
    before = git(tmp_path, "for-each-ref", "--format=%(refname) %(objectname)")
    monkeypatch.setattr(port, "_local_integration_gates", lambda *_: pytest.fail("dry run executed gates"))
    result = run_git_workflow(tmp_path, load_config(tmp_path), "integrate_contribution",
        {"request": request, "pr": 7, "head_review": head_review(request, prepared["proposal_commit"])}, dry_run=True)
    assert result["status"] == "dry_run" and result["validation_status"] == "local_validation_required"
    assert result["gates_not_run"] and "validation_commit" not in result and not effects
    assert git(tmp_path, "for-each-ref", "--format=%(refname) %(objectname)") == before
