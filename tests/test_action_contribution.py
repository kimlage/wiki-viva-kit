"""Synthetic Git/CLI contracts; mocked GitHub is explicitly not live CI."""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path

import pytest
import yaml

import wiki_core.action_contribution as port
from wiki_core.action_transition import _parse_document, transition_action_page, action_transition_diagnostics
from wiki_core.config import load_config
from wiki_core.web.git_workflows import run_git_workflow


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root).decode().strip()


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def fixture(root):
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Synthetic Operator")
    git(root, "config", "user.email", "operator@example.test")
    (root / "wiki.config.yaml").write_text("repo_id: synthetic\ncontexts: example\napproval:\n  gate: github_pr\n")
    (root / ".gitignore").write_text("data/derived/\n")
    (root / "scripts").mkdir()
    # These executable gate fixtures prove invocation and failure propagation,
    # not production auditor acceptance. The installed CLI smoke uses real kit.
    for name in ("wiki_audit", "wiki_input_stage", "wiki_pr_summary"):
        (root / f"scripts/{name}.py").write_text("print('synthetic gate fixture')\n")
    log = root / "memories/system/log.md"
    log.parent.mkdir(parents=True)
    log.write_text("# Synthetic memory log\n")
    p = root / "memories/actions/example.md"
    p.parent.mkdir(parents=True)
    p.write_text("---\n" + yaml.safe_dump({"page_id": "example-action", "page_type": "action",
        "action_state": "open", "updated_at": "2026-01-01", "next_action": "Review source",
        "owner_ref": "synthetic-owner", "operational_task": {"tools": ["local-read"]}}, sort_keys=False)
        + "---\n# Synthetic action\n\nOriginal evidence.\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "synthetic base")
    old = p.read_text()
    text = old.replace("Original evidence.", "Reviewed historical evidence.")
    request = {"schema_version": port.SCHEMA, "task_ref": {"repo_id": "synthetic", "action_id": "example-action"},
        "run_ref": {"runtime": "optional-local-adapter", "task_id": "native-task", "run_id": "one"},
        "session_ref": {"session_id": "author-session", "coverage": "Selected messages only; no transcript"},
        "effect_key": "synthetic-body-one", "files": [{"path": "memories/actions/example.md",
        "base_commit": git(root, "rev-parse", "HEAD"), "base_sha256": sha(old), "sha256": sha(text), "text": text}]}
    return p, request


def review(request):
    return {"material_sha256": port.digest(request), "reviewer_session_id": "independent-session",
            "evidence_ref": "synthetic-review", "report": {"criteria": ["scope", "evidence"], "findings": []}, "decision": "approved"}


def call(root, op, request, **kwargs):
    return run_git_workflow(root, load_config(root), op + "_contribution", {"request": request, **kwargs}, dry_run=False)


def test_prepare_preserves_real_canonical_suffix_and_disjoint_wip(tmp_path):
    p, request = fixture(tmp_path)
    original = p.read_text()
    transition_action_page(tmp_path, p, "open", next_action="Clarify target", expected_sha256=sha(original))
    transition_action_page(tmp_path, p, "open", dialogue_event={"event_id": "question-test-1",
        "kind": "question", "coordinator": "research", "text": "Which synthetic source?"},
        dialogue_actor="coordinator:research", expected_sha256=sha(p.read_text()))
    transition_action_page(tmp_path, p, "open", dialogue_event={"event_id": "answer-test-1",
        "kind": "answer", "coordinator": "research", "text": "The retained synthetic source.",
        "reply_to": "question-test-1"}, expected_sha256=sha(p.read_text()))
    before = p.read_text()
    (tmp_path / "unrelated.md").write_text("Untracked WIP remains here")
    out = call(tmp_path, "prepare", request, review=review(request))
    assert out["status"] == "prepared", out
    assert out["canonical_body_adopted"] is False
    assert len(out["gate_receipts"]) == 4 and all(g["exit_code"] == 0 for g in out["gate_receipts"])
    adopted = port._blob(tmp_path, out["proposal_commit"], request["files"][0]["path"])
    old_fm, _ = _parse_document(before)
    fm, body = _parse_document(adopted)
    assert fm["next_action"] == "Clarify target" and fm["owner_ref"] == old_fm["owner_ref"]
    assert fm["operational_task"] == old_fm["operational_task"]
    assert fm["action_state_history"][:-1] == old_fm["action_state_history"]
    assert fm["action_dialogue"] == old_fm["action_dialogue"] and len(fm["action_dialogue"]) == 2
    from wiki_core.page_types import _action_history_shape_errors
    assert _action_history_shape_errors("synthetic", fm, "open") == []
    assert "Reviewed historical evidence." in body
    assert action_transition_diagnostics(original, adopted) == ()
    assert action_transition_diagnostics(original.rstrip(), adopted) == ()
    assert p.read_text() == before and (tmp_path / "unrelated.md").read_text().startswith("Untracked")
    again = call(tmp_path, "prepare", request, review=review(request))
    assert again["proposal_commit"] == out["proposal_commit"] and again["idempotent"]


@pytest.mark.parametrize("change,error", [("owner", "source_authority_or_frontmatter_conflict"),
    ("history", "unproved_source_history_suffix"), ("body", "source_body_conflict")])
def test_refuses_overlap_or_unproved_suffix(tmp_path, change, error):
    p, request = fixture(tmp_path)
    text = p.read_text()
    if change == "owner":
        text = text.replace("synthetic-owner", "different-owner")
    elif change == "history":
        text = text.replace("next_action: Review source", "next_action: forged")
    else:
        text += "Concurrent body work\n"
    p.write_text(text)
    out = call(tmp_path, "prepare", request, review=review(request))
    assert out["error"] == error
    assert not git(tmp_path, "branch", "--list", "wiki/contribution-*")
    assert p.read_text() == text


def test_source_change_during_audit_is_cas_conflict_without_lost_event(tmp_path, monkeypatch):
    p, request = fixture(tmp_path)
    def gates(*_):
        transition_action_page(tmp_path, p, "open", next_action="New canonical direction", expected_sha256=sha(p.read_text()))
        return []
    monkeypatch.setattr(port, "_gates", gates)
    out = call(tmp_path, "prepare", request, review=review(request))
    assert out["error"] == "source_changed_during_prepare"
    assert "New canonical direction" in p.read_text()
    assert not git(tmp_path, "branch", "--list", "wiki/contribution-*")


def test_review_material_and_effect_key_are_bound(tmp_path):
    _, request = fixture(tmp_path)
    report = review(request)
    report["reviewer_session_id"] = request["session_ref"]["session_id"]
    assert call(tmp_path, "prepare", request, review=report)["error"] == "independent_reviewer_required"
    out = call(tmp_path, "prepare", request, review=review(request))
    assert out["ok"]
    changed = copy.deepcopy(request)
    changed["session_ref"]["coverage"] = "Different material"
    assert call(tmp_path, "prepare", changed, review=review(changed))["error"] == "effect_key_conflict"
    changed["material_sha256"] = "0" * 64
    assert call(tmp_path, "prepare", changed, review=review(changed))["error"] == "material_hash_mismatch"


def test_normal_gate_failure_does_not_install_candidate(tmp_path):
    p, request = fixture(tmp_path)
    gate = tmp_path / "scripts/wiki_audit.py"
    gate.write_text("raise SystemExit(7)\n")
    git(tmp_path, "add", str(gate))
    git(tmp_path, "commit", "-m", "synthetic failing gate")
    before = p.read_bytes()
    out = call(tmp_path, "prepare", request, review=review(request))
    assert out["error"].startswith("proposal_gate_failed")
    assert out["gate_receipts"][0]["exit_code"] == 7
    assert "wiki_audit.py" in out["gate_receipts"][0]["argv"][-2]
    assert p.read_bytes() == before and not git(tmp_path, "branch", "--list", "wiki/contribution-*")


def test_waits_for_real_ci_human_policy_and_unknown_is_read_only(tmp_path, monkeypatch):
    p, request = fixture(tmp_path)
    out = call(tmp_path, "prepare", request, review=review(request))
    pr = {"number": 1, "state": "OPEN", "headRefOid": out["proposal_commit"], "baseRefName": "main", "statusCheckRollup": []}
    monkeypatch.setattr(port, "_pr", lambda *_: pr)
    assert call(tmp_path, "integrate", request, pr=1)["status"] == "waiting_ci_or_pr"
    pr["statusCheckRollup"] = [{"conclusion": "SUCCESS"}]
    pr["isDraft"] = True
    assert call(tmp_path, "integrate", request, pr=1)["status"] == "waiting_pr_review"
    pr["isDraft"] = False
    before = p.read_text()
    transition_action_page(tmp_path, p, "open", next_action="Post-prepare event", expected_sha256=sha(before))
    assert call(tmp_path, "integrate", request, pr=1)["error"].startswith("source_changed_since_prepare")
    # A reconcile never invokes merge even after the effect outcome was unknown.
    assert call(tmp_path, "reconcile", request, pr=1)["status"] == "waiting_pr"


def test_remote_merge_is_not_checkout_or_served_adoption(tmp_path, monkeypatch):
    p, request = fixture(tmp_path)
    out = call(tmp_path, "prepare", request, review=review(request))
    remote = tmp_path.parent / (tmp_path.name + "-remote.git")
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    git(tmp_path, "remote", "add", "origin", str(remote))
    git(tmp_path, "push", "origin", out["proposal_commit"] + ":refs/heads/main")
    # Real Git objects/readback, simulated GitHub control plane; not live CI.
    pr = {"number": 1, "state": "MERGED", "headRefOid": out["proposal_commit"],
          "baseRefName": "main", "mergeCommit": {"oid": out["proposal_commit"]}}
    monkeypatch.setattr(port, "_pr", lambda *_: pr)
    first = call(tmp_path, "reconcile", request, pr=1)
    assert first["remote_merged"] and not first["canonical_body_adopted"]
    assert first["status"] == "waiting_worktree_adoption"
    git(tmp_path, "merge", "--ff-only", "origin/main")
    second = call(tmp_path, "reconcile", request, pr=1)
    assert second["canonical_body_adopted"] and second["canonical_matches_material"]
    assert second["served_adoption_verified"] is False
    assert "Reviewed historical evidence." in p.read_text()


def test_unrelated_committed_branch_is_not_a_proposal_base(tmp_path):
    _, request = fixture(tmp_path)
    git(tmp_path, "switch", "-c", "wiki/unrelated")
    (tmp_path / "unrelated-committed.md").write_text("Must not ride along")
    git(tmp_path, "add", "unrelated-committed.md")
    git(tmp_path, "commit", "-m", "unrelated work")
    assert call(tmp_path, "prepare", request, review=review(request))["error"] == "checkout_not_at_approved_base"


def test_cached_config_cannot_skip_explicit_human_review(tmp_path, monkeypatch):
    _, request = fixture(tmp_path)
    cached = load_config(tmp_path)
    config_file = tmp_path / "wiki.config.yaml"
    config_file.write_text(config_file.read_text() + "  require_human_review: true\n")
    git(tmp_path, "add", "wiki.config.yaml")
    git(tmp_path, "commit", "-m", "require human review")
    out = call(tmp_path, "prepare", request, review=review(request))
    pr = {"number": 1, "state": "OPEN", "headRefOid": out["proposal_commit"], "baseRefName": "main",
          "statusCheckRollup": [{"conclusion": "SUCCESS"}], "reviews": []}
    monkeypatch.setattr(port, "_pr", lambda *_: pr)
    result = run_git_workflow(tmp_path, cached, "integrate_contribution", {"request": request, "pr": 1}, dry_run=False)
    assert result["status"] == "waiting_human_review"


def test_malformed_body_receipt_is_a_diagnostic_not_exception(tmp_path):
    p, _ = fixture(tmp_path)
    old = p.read_text()
    fm, body = _parse_document(old)
    fm["action_state_history"] = [{"kind": "body_integration", "contribution": []}]
    changed = "---\n" + yaml.safe_dump(fm) + "---\n" + body
    assert action_transition_diagnostics(old, changed)[0].code == "invalid_action_transition_receipt"


def test_cli_processes_share_the_action_guard(tmp_path):
    _, request = fixture(tmp_path)
    r, v = tmp_path / "request.json", tmp_path / "review.json"
    r.write_text(json.dumps(request)); v.write_text(json.dumps(review(request)))
    cli = Path(__file__).resolve().parents[1] / "scripts/wiki_contribution.py"
    import sys
    argv = [sys.executable, str(cli), "prepare", "--root", str(tmp_path), "--request", str(r), "--review", str(v), "--apply"]
    workers = [subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
    values = [json.loads(w.communicate(timeout=40)[0]) for w in workers]
    assert any(v["status"] == "prepared" for v in values), values
    assert all(v["status"] == "prepared" or v.get("error", "").startswith("contribution_prepared_concurrently") for v in values)
    refs = git(tmp_path, "branch", "--list", "wiki/contribution-*").splitlines()
    assert len(refs) == 1
    assert "Original evidence." in (tmp_path / request["files"][0]["path"]).read_text()


def test_integration_uses_real_git_and_reconcile_does_not_repeat_effect(tmp_path, monkeypatch):
    _, request = fixture(tmp_path)
    out = call(tmp_path, "prepare", request, review=review(request))
    remote = tmp_path.parent / (tmp_path.name + "-remote.git")
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    git(tmp_path, "remote", "add", "origin", str(remote))
    git(tmp_path, "push", "origin", "main")
    pr = {"number": 1, "state": "OPEN", "headRefOid": out["proposal_commit"], "baseRefName": "main",
          "statusCheckRollup": [{"conclusion": "SUCCESS"}]}
    monkeypatch.setattr(port, "_pr", lambda *_: pr)
    monkeypatch.setattr(port, "_repository", lambda *_: "example.test/synthetic/wiki")
    real_run = port._run
    effects = []
    def run(root, *argv, **kwargs):
        if argv[:3] == ("gh", "pr", "merge"):
            effects.append(argv)
            git(tmp_path, "push", "origin", out["proposal_commit"] + ":refs/heads/main")
            pr.update(state="MERGED", mergeCommit={"oid": out["proposal_commit"]})
            return ""
        return real_run(root, *argv, **kwargs)
    monkeypatch.setattr(port, "_run", run)
    result = call(tmp_path, "integrate", request, pr=1)
    assert result["remote_merged"] and result["status"] == "waiting_worktree_adoption", result
    assert len(effects) == 1
    assert call(tmp_path, "reconcile", request, pr=1)["remote_merged"]
    assert len(effects) == 1


def test_remote_policy_change_blocks_stale_integration(tmp_path, monkeypatch):
    _, request = fixture(tmp_path)
    out = call(tmp_path, "prepare", request, review=review(request))
    remote = tmp_path.parent / (tmp_path.name + "-remote.git")
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    git(tmp_path, "remote", "add", "origin", str(remote)); git(tmp_path, "push", "origin", "main")
    other = tmp_path.parent / (tmp_path.name + "-other")
    subprocess.run(["git", "clone", "-b", "main", str(remote), str(other)], check=True, capture_output=True)
    git(other, "config", "user.name", "Other operator"); git(other, "config", "user.email", "other@example.test")
    p = other / "wiki.config.yaml"; p.write_text(p.read_text() + "  require_human_review: true\n")
    git(other, "add", "wiki.config.yaml"); git(other, "commit", "-m", "Require human now"); git(other, "push", "origin", "main")
    monkeypatch.setattr(port, "_pr", lambda *_: {"number": 1, "state": "OPEN", "headRefOid": out["proposal_commit"],
        "baseRefName": "main", "statusCheckRollup": [{"conclusion": "SUCCESS"}], "reviews": []})
    result = call(tmp_path, "integrate", request, pr=1)
    assert result["error"].startswith("canonical_policy_changed"), result
    assert not result["canonical_body_adopted"]


@pytest.mark.parametrize("field", ["owner", "body"])
def test_reused_candidate_revalidates_effective_bytes(tmp_path, field):
    p, request = fixture(tmp_path)
    out = call(tmp_path, "prepare", request, review=review(request))
    git(tmp_path, "switch", out["branch"])
    text = p.read_text()
    p.write_text(text.replace("synthetic-owner", "unauthorized-owner") if field == "owner"
                 else text.replace("Reviewed historical evidence.", "Unreviewed replacement."))
    git(tmp_path, "add", str(p)); git(tmp_path, "commit", "--amend", "--no-edit")
    git(tmp_path, "switch", "main")
    result = call(tmp_path, "prepare", request, review=review(request))
    assert result["error"] == "candidate_material_or_frontmatter_tampered"
    assert not result["canonical_body_adopted"]


def test_structured_review_keeps_nonblocking_findings_losslessly(tmp_path):
    _, request = fixture(tmp_path)
    report = review(request)
    report["report"] = {"criteria": [{"criterion": "Evidence verified", "met": True,
        "evidence_refs": ["synthetic-source"]}], "findings": [{"blocking": False,
        "description": "Retained limitation", "evidence_refs": ["synthetic-source"]}]}
    out = call(tmp_path, "prepare", request, review=report)
    assert out["ok"], out
    entry, _ = port._entry(tmp_path, out["proposal_commit"], request["files"][0]["path"], request, port.digest(request))
    assert entry["contribution"]["review"] == report
    for field in ("criterion", "finding"):
        bad = copy.deepcopy(report)
        if field == "criterion":
            bad["report"]["criteria"][0]["met"] = False
        else:
            bad["report"]["findings"][0]["blocking"] = True
        with pytest.raises(port.ContributionError, match="review_not_approved"):
            port._review(request, port.digest(request), bad)


def test_canonical_fetch_ignores_shared_fetch_head(tmp_path, monkeypatch):
    _, request = fixture(tmp_path)
    old = git(tmp_path, "rev-parse", "HEAD")
    remote = tmp_path.parent / (tmp_path.name + "-remote.git")
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    git(tmp_path, "remote", "add", "origin", str(remote)); git(tmp_path, "push", "origin", "main")
    (tmp_path / "unrelated.md").write_text("Concurrent canonical work")
    git(tmp_path, "add", "."); git(tmp_path, "commit", "-m", "Canonical advance")
    current = git(tmp_path, "rev-parse", "HEAD"); git(tmp_path, "push", "origin", "main")
    real_git = port._git
    def interleaved(root, *args):
        out = real_git(root, *args)
        if args[:3] == ("fetch", "--no-write-fetch-head", "origin"):
            git(tmp_path, "fetch", str(tmp_path), old)
        return out
    monkeypatch.setattr(port, "_git", interleaved)
    assert port._fetch_canonical(tmp_path, "main") == current
    assert git(tmp_path, "rev-parse", "FETCH_HEAD") == old
    assert git(tmp_path, "for-each-ref", "refs/wiki/contribution-read") == ""


def test_overlapping_log_wip_is_preserved_as_a_conflict(tmp_path):
    _, request = fixture(tmp_path)
    log = tmp_path / "memories/system/log.md"
    before = log.read_text() + "\nConcurrent append\n"
    log.write_text(before)
    result = call(tmp_path, "prepare", request, review=review(request))
    assert result["error"] == "log_overlap_reconcile_required"
    assert log.read_text() == before


def test_external_effect_failure_is_unknown_not_automatic_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(port.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 1, "", "connection lost"))
    with pytest.raises(port.ContributionError, match="outcome_unknown"):
        port._run(tmp_path, "gh", "pr", "merge", "1")
