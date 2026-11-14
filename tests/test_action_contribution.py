"""Synthetic Git/CLI contracts; mocked GitHub is explicitly not live CI."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
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


def head_review(request, commit):
    return {**review(request), "proposal_commit": commit}


@pytest.mark.parametrize('mutation', ['tracked', 'untracked', 'index_flag'])
def test_gates_stop_before_next_command_when_candidate_changes(tmp_path, mutation):
    target, _ = fixture(tmp_path)
    calls = []

    def runner(call):
        calls.append(True)
        result = call()
        if len(calls) == 1:
            if mutation == 'tracked':
                target.write_text('temporary synthetic change\n')
            elif mutation == 'untracked':
                (tmp_path / 'new-synthetic-input').write_text('temporary\n')
            else:
                git(tmp_path, 'update-index', '--assume-unchanged', str(target.relative_to(tmp_path)))
        return result

    with pytest.raises(port.ContributionError, match='gate_modified_candidate_inputs'):
        port._gates(tmp_path, load_config(tmp_path), effect_runner=runner)
    assert len(calls) == 1


def test_gates_allow_unchanged_proposal_already_modified_before_validation(tmp_path):
    target, _ = fixture(tmp_path)
    target.write_text(target.read_text() + '\nSynthetic proposed change.\n')
    before = target.read_bytes()
    results = port._gates(tmp_path, load_config(tmp_path))
    assert all(result['exit_code'] == 0 for result in results)
    assert target.read_bytes() == before


def test_gates_refuse_existing_untracked_input_before_running(tmp_path):
    fixture(tmp_path)
    (tmp_path / 'synthetic-input').write_text('untracked\n')
    with pytest.raises(port.ContributionError, match='gate_untracked_candidate_inputs'):
        port._gates(tmp_path, load_config(tmp_path), effect_runner=lambda _: pytest.fail('gate ran'))


def test_gates_refuse_preexisting_assume_unchanged_before_running(tmp_path):
    target, _ = fixture(tmp_path)
    git(tmp_path, 'update-index', '--assume-unchanged', str(target.relative_to(tmp_path)))
    target.write_text('hidden candidate change\n')
    with pytest.raises(port.ContributionError, match='gate_candidate_index_unqualified'):
        port._gates(tmp_path, load_config(tmp_path), effect_runner=lambda _: pytest.fail('gate ran'))


def call(root, op, request, **kwargs):
    return run_git_workflow(root, load_config(root), op + "_contribution", {"request": request, **kwargs}, dry_run=False)


def reconcile_pr_identity(pr, prepared):
    pr.update(headRefName=prepared["branch"], isCrossRepository=False,
              headRepository={"name": "wiki"}, headRepositoryOwner={"login": "synthetic"})


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
    assert again["generated_paths"] == out["generated_paths"] == ["memories/system/log.md"]


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
    remote = tmp_path.parent / (tmp_path.name + "-remote.git")
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    git(tmp_path, "remote", "add", "origin", str(remote))
    git(tmp_path, "push", "origin", "main", out["branch"])
    reconcile_pr_identity(pr, out)
    monkeypatch.setattr(port, "_repository", lambda *_: "example.test/synthetic/wiki")
    assert call(tmp_path, "reconcile", request, pr=1)["status"] == "waiting_pr"


@pytest.mark.parametrize('checkout_eol', ['lf', 'crlf'])
def test_remote_merge_is_not_checkout_or_served_adoption(tmp_path, monkeypatch, checkout_eol):
    p, request = fixture(tmp_path)
    if checkout_eol == 'crlf':
        (tmp_path / '.gitattributes').write_text('memories/actions/*.md text eol=crlf\n')
        git(tmp_path, 'add', '.gitattributes')
        git(tmp_path, 'commit', '-m', 'Synthetic checkout conversion')
        request['files'][0]['base_commit'] = git(tmp_path, 'rev-parse', 'HEAD')
        p.unlink()
        git(tmp_path, 'checkout', '--', request['files'][0]['path'])
        assert b'\r\n' in p.read_bytes()
    out = call(tmp_path, "prepare", request, review=review(request))
    remote = tmp_path.parent / (tmp_path.name + "-remote.git")
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    git(tmp_path, "remote", "add", "origin", str(remote))
    git(tmp_path, "push", "origin", out["proposal_commit"] + ":refs/heads/main")
    # Real Git objects/readback, simulated GitHub control plane; not live CI.
    pr = {"number": 1, "state": "MERGED", "headRefOid": out["proposal_commit"],
          "baseRefName": "main", "mergeCommit": {"oid": out["proposal_commit"]}}
    reconcile_pr_identity(pr, out)
    monkeypatch.setattr(port, "_repository", lambda *_: "example.test/synthetic/wiki")
    monkeypatch.setattr(port, "_pr", lambda *_: pr)
    first = call(tmp_path, "reconcile", request, pr=1)
    assert first["remote_merged"] and not first["canonical_body_adopted"]
    assert first["status"] == "waiting_worktree_adoption"
    git(tmp_path, "merge", "--ff-only", "origin/main")
    second = call(tmp_path, "reconcile", request, pr=1)
    assert second["canonical_body_adopted"] and second["canonical_matches_material"]
    assert second["served_adoption_verified"] is False
    assert "Reviewed historical evidence." in p.read_text()
    if checkout_eol == 'crlf':
        assert b'\r\n' in p.read_bytes()
        p.write_bytes(p.read_bytes().replace(b'Reviewed historical evidence.', b'Different factual evidence.'))
        third = call(tmp_path, "reconcile", request, pr=1)
        assert third['canonical_matches_material'] and not third['worktree_adopted']
        assert third['status'] == 'waiting_worktree_adoption'


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
    reconcile_pr_identity(pr, out)
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
    result = call(tmp_path, "integrate", request, pr=1, head_review=head_review(request, out["proposal_commit"]))
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


@pytest.mark.parametrize('target', ['action', 'log'])
@pytest.mark.parametrize('mode', ['100755', '120000'])
def test_candidate_refuses_changed_git_mode_without_materializing_symlink(tmp_path, target, mode):
    _, request = fixture(tmp_path)
    prepared = call(tmp_path, 'prepare', request, review=review(request))
    assert prepared['ok'], prepared
    commit = prepared['proposal_commit']
    action = request['files'][0]['path']
    ref = action if target == 'action' else 'memories/system/log.md'
    # The ordinary candidate is valid before its tree mode is changed.
    port._entry(tmp_path, commit, action, request, port.digest(request))
    blob = git(tmp_path, 'rev-parse', f'{commit}:{ref}')
    parent = git(tmp_path, 'rev-parse', commit + '^')
    git(tmp_path, 'read-tree', commit)
    git(tmp_path, 'update-index', '--add', '--cacheinfo', f'{mode},{blob},{ref}')
    tree = git(tmp_path, 'write-tree')
    altered = git(tmp_path, 'commit-tree', tree, '-p', parent, '-m', 'synthetic altered mode')
    with pytest.raises(port.ContributionError, match='candidate_file_mode_changed'):
        port._entry(tmp_path, altered, action, request, port.digest(request))


@pytest.mark.parametrize('raw_is_valid', [False, True])
def test_candidate_validation_uses_real_objects_despite_replace_ref(tmp_path, raw_is_valid):
    _, request = fixture(tmp_path)
    prepared = call(tmp_path, 'prepare', request, review=review(request))
    assert prepared['ok'], prepared
    valid = prepared['proposal_commit']
    action = request['files'][0]['path']
    original = port._blob(tmp_path, valid, action)
    altered = original.replace('Reviewed historical evidence.', 'Different synthetic evidence.')
    assert altered != original
    blob = subprocess.check_output(['git', 'hash-object', '-w', '--stdin'], cwd=tmp_path,
                                   input=altered.encode()).decode().strip()
    parent = git(tmp_path, 'rev-parse', valid + '^')
    git(tmp_path, 'read-tree', valid)
    git(tmp_path, 'update-index', '--add', '--cacheinfo', f'100644,{blob},{action}')
    invalid = git(tmp_path, 'commit-tree', git(tmp_path, 'write-tree'), '-p', parent,
                  '-m', 'synthetic different body')
    raw, replacement = (valid, invalid) if raw_is_valid else (invalid, valid)
    git(tmp_path, 'replace', raw, replacement)
    if raw_is_valid:
        port._entry(tmp_path, raw, action, request, port.digest(request))
    else:
        with pytest.raises(port.ContributionError, match='candidate_material_or_frontmatter_tampered'):
            port._entry(tmp_path, raw, action, request, port.digest(request))


def test_candidate_validation_ignores_inherited_git_directory(tmp_path, monkeypatch):
    root = tmp_path / 'selected'
    root.mkdir()
    _, request = fixture(root)
    prepared = call(root, 'prepare', request, review=review(request))
    assert prepared['ok'], prepared
    other = tmp_path / 'other'
    other.mkdir()
    git(other, 'init', '-q')
    monkeypatch.setenv('GIT_DIR', str(other / '.git'))
    monkeypatch.setenv('GIT_INDEX_FILE', str(other / 'synthetic-index'))
    port._entry(root, prepared['proposal_commit'], request['files'][0]['path'], request, port.digest(request))


@pytest.mark.skipif(os.name == 'nt', reason='synthetic shell hook is POSIX-only')
def test_local_git_observation_does_not_run_configured_fsmonitor(tmp_path):
    fixture(tmp_path)
    marker = tmp_path.parent / (tmp_path.name + '-fsmonitor-ran')
    hook = tmp_path / 'synthetic-fsmonitor.sh'
    hook.write_text('#!/bin/sh\nprintf ran > "' + str(marker) + '"\n')
    hook.chmod(0o755)
    git(tmp_path, 'config', 'core.fsmonitor', str(hook))
    port._git(tmp_path, 'status', '--porcelain')
    assert not marker.exists()


def test_local_gate_environment_keeps_whitespace_policy_but_drops_other_injection(tmp_path, monkeypatch):
    fixture(tmp_path)
    monkeypatch.setenv('GIT_CONFIG_COUNT', '2')
    monkeypatch.setenv('GIT_CONFIG_KEY_0', 'core.whitespace')
    monkeypatch.setenv('GIT_CONFIG_VALUE_0', 'cr-at-eol')
    monkeypatch.setenv('GIT_CONFIG_KEY_1', 'core.fsmonitor')
    monkeypatch.setenv('GIT_CONFIG_VALUE_1', '/tmp/synthetic-hook')
    env = port._local_process_environment(tmp_path)
    pairs = [(env[f'GIT_CONFIG_KEY_{i}'], env[f'GIT_CONFIG_VALUE_{i}'])
             for i in range(int(env['GIT_CONFIG_COUNT']))]
    assert ('core.whitespace', 'cr-at-eol') in pairs
    assert ('core.fsmonitor', '/tmp/synthetic-hook') not in pairs
    assert ('core.fsmonitor', 'false') in pairs


@pytest.mark.parametrize('source', ['global', 'local', 'injected'])
def test_local_gate_environment_preserves_effective_whitespace(tmp_path, monkeypatch, source):
    fixture(tmp_path)
    if source == 'global':
        config = tmp_path.parent / (tmp_path.name + '-gitconfig')
        config.write_text('[core]\n\twhitespace = cr-at-eol\n')
        monkeypatch.setenv('GIT_CONFIG_GLOBAL', str(config))
    elif source == 'local':
        git(tmp_path, 'config', 'core.whitespace', 'cr-at-eol')
    else:
        monkeypatch.setenv('GIT_CONFIG_COUNT', '1')
        monkeypatch.setenv('GIT_CONFIG_KEY_0', 'core.whitespace')
        monkeypatch.setenv('GIT_CONFIG_VALUE_0', 'cr-at-eol')
    env = port._local_process_environment(tmp_path)
    pairs = [(env[f'GIT_CONFIG_KEY_{i}'], env[f'GIT_CONFIG_VALUE_{i}'])
             for i in range(int(env['GIT_CONFIG_COUNT']))]
    assert ('core.whitespace', 'cr-at-eol') in pairs


def test_prepare_uses_selected_repo_despite_inherited_git_directory(tmp_path, monkeypatch):
    root = tmp_path / 'selected'
    root.mkdir()
    _, request = fixture(root)
    other = tmp_path / 'other'
    other.mkdir()
    git(other, 'init', '-q')
    monkeypatch.setenv('GIT_DIR', str(other / '.git'))
    monkeypatch.setenv('GIT_INDEX_FILE', str(other / 'synthetic-index'))
    result = call(root, 'prepare', request, review=review(request))
    assert result['ok'] and result['status'] == 'prepared', result


def test_prepare_preserves_global_identity_without_inherited_repo(tmp_path, monkeypatch):
    root = tmp_path / 'selected'
    root.mkdir()
    _, request = fixture(root)
    git(root, 'config', '--local', '--unset', 'user.name')
    git(root, 'config', '--local', '--unset', 'user.email')
    global_config = tmp_path / 'global-gitconfig'
    global_config.write_text('[user]\n\tname = Synthetic Global\n\temail = global@example.test\n')
    other = tmp_path / 'other'
    other.mkdir()
    git(other, 'init', '-q')
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', str(global_config))
    monkeypatch.setenv('GIT_DIR', str(other / '.git'))
    result = call(root, 'prepare', request, review=review(request))
    assert result['ok'] and result['status'] == 'prepared', result
    author = port._local_git_bytes(root, 'show', '-s', '--format=%an <%ae>', result['proposal_commit'])
    assert author.strip() == b'Synthetic Global <global@example.test>'


@pytest.mark.skipif(os.name == 'nt' or shutil.which('ssh-keygen') is None, reason='requires POSIX SSH signing fixture')
@pytest.mark.parametrize('source', ['global', 'local', 'injected'])
def test_prepare_preserves_required_ssh_signing(tmp_path, monkeypatch, source):
    root = tmp_path / 'selected'
    root.mkdir()
    _, request = fixture(root)
    key = tmp_path / 'synthetic-signing-key'
    subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(key)], check=True)
    settings = [('commit.gpgSign', 'true'), ('gpg.format', 'ssh'), ('user.signingkey', str(key)),
                ('gpg.ssh.program', shutil.which('ssh-keygen'))]
    if source == 'global':
        global_config = tmp_path.parent / (tmp_path.name + '-gitconfig')
        global_config.write_text('[commit]\n\tgpgSign = true\n[gpg]\n\tformat = ssh\n[gpg "ssh"]\n\tprogram = ' + shutil.which('ssh-keygen') + '\n[user]\n\tsigningkey = ' + str(key) + '\n')
        monkeypatch.setenv('GIT_CONFIG_GLOBAL', str(global_config))
    elif source == 'local':
        for name, value in settings:
            if name == 'user.signingkey':
                git(root, 'config', '--add', name, 'missing-old-key')
                git(root, 'config', '--add', name, value)
            elif name == 'gpg.ssh.program':
                git(root, 'config', '--add', name, 'old-ambiguous-signer')
                git(root, 'config', '--add', name, value)
            else:
                git(root, 'config', name, value)
    else:
        monkeypatch.setenv('GIT_CONFIG_COUNT', str(len(settings)))
        for index, (name, value) in enumerate(settings):
            monkeypatch.setenv(f'GIT_CONFIG_KEY_{index}', name)
            monkeypatch.setenv(f'GIT_CONFIG_VALUE_{index}', value)
    result = call(root, 'prepare', request, review=review(request))
    assert result['ok'] and result['status'] == 'prepared', result
    allowed = tmp_path / 'allowed-signers'
    allowed.write_text('operator@example.test ' + key.with_suffix('.pub').read_text())
    verify = subprocess.run(['git', '-c', 'gpg.format=ssh', '-c', f'gpg.ssh.allowedSignersFile={allowed}',
                             'verify-commit', result['proposal_commit']], cwd=root, capture_output=True)
    assert verify.returncode == 0, verify.stderr.decode(errors='replace')


@pytest.mark.skipif(os.name == 'nt' or shutil.which('false') is None, reason='requires POSIX failing signer')
def test_prepare_does_not_install_ref_when_required_signer_fails(tmp_path):
    _, request = fixture(tmp_path)
    git(tmp_path, 'config', 'commit.gpgSign', 'true')
    git(tmp_path, 'config', 'gpg.format', 'ssh')
    git(tmp_path, 'config', 'gpg.ssh.program', shutil.which('false'))
    git(tmp_path, 'config', 'user.signingkey', '/synthetic/missing-key')
    result = call(tmp_path, 'prepare', request, review=review(request))
    assert not result['ok']
    assert result['error'] == 'command_failed:git'
    assert port._candidate(tmp_path, result['branch']) is None


def test_prepare_refuses_signing_policy_change_before_commit(tmp_path, monkeypatch):
    _, request = fixture(tmp_path)
    original = port._gates
    def gates_then_change(*args, **kwargs):
        receipts = original(*args, **kwargs)
        git(tmp_path, 'config', 'commit.gpgSign', 'true')
        return receipts
    monkeypatch.setattr(port, '_gates', gates_then_change)
    result = call(tmp_path, 'prepare', request, review=review(request))
    assert result['error'] == 'git_commit_signing_policy_changed'
    assert port._candidate(tmp_path, result['branch']) is None


def test_prepare_refuses_signing_policy_change_after_commit(tmp_path, monkeypatch):
    _, request = fixture(tmp_path)
    original = port._local_git_effect
    def commit_then_change(root, *args, **kwargs):
        value = original(root, *args, **kwargs)
        if args and args[0] == 'commit':
            git(tmp_path, 'config', 'commit.gpgSign', 'true')
        return value
    monkeypatch.setattr(port, '_local_git_effect', commit_then_change)
    result = call(tmp_path, 'prepare', request, review=review(request))
    assert result['error'] == 'git_commit_signing_policy_changed'
    assert port._candidate(tmp_path, result['branch']) is None


@pytest.mark.skipif(os.name == 'nt' or shutil.which('ssh-keygen') is None, reason='requires POSIX SSH signing fixture')
def test_prepare_uses_repo_relative_ssh_key_and_program(tmp_path):
    _, request = fixture(tmp_path)
    key = tmp_path / '.git' / 'synthetic-signing-key'
    subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(key)], check=True)
    wrapper = tmp_path / '.git' / 'synthetic-ssh-signer'
    wrapper.write_text('#!/bin/sh\nexec "' + shutil.which('ssh-keygen') + '" "$@"\n')
    wrapper.chmod(0o755)
    git(tmp_path, 'config', 'commit.gpgSign', 'true')
    git(tmp_path, 'config', 'gpg.format', 'ssh')
    git(tmp_path, 'config', 'user.signingkey', '.git/synthetic-signing-key')
    git(tmp_path, 'config', 'gpg.ssh.program', '.git/synthetic-ssh-signer')
    result = call(tmp_path, 'prepare', request, review=review(request))
    assert result['ok'] and result['status'] == 'prepared', result
    allowed = tmp_path.parent / (tmp_path.name + '-allowed-signers')
    allowed.write_text('operator@example.test ' + key.with_suffix('.pub').read_text())
    verify = subprocess.run(['git', '-c', 'gpg.ssh.allowedSignersFile=' + str(allowed), 'verify-commit',
                             result['proposal_commit']], cwd=tmp_path, capture_output=True)
    assert verify.returncode == 0, verify.stderr.decode(errors='replace')


@pytest.mark.skipif(os.name == 'nt' or shutil.which('ssh-keygen') is None, reason='requires POSIX SSH signing fixture')
def test_prepare_refuses_unproven_signer_resolution_from_relative_path(tmp_path, monkeypatch):
    _, request = fixture(tmp_path)
    key = tmp_path / '.git' / 'synthetic-signing-key'
    subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(key)], check=True)
    wrapper = tmp_path / '.git' / 'synthetic-signer'
    wrapper.write_text('#!/bin/sh\nexec "' + shutil.which('ssh-keygen') + '" "$@"\n')
    wrapper.chmod(0o755)
    git(tmp_path, 'config', 'commit.gpgSign', 'true')
    git(tmp_path, 'config', 'gpg.format', 'ssh')
    git(tmp_path, 'config', 'user.signingkey', str(key))
    git(tmp_path, 'config', 'gpg.ssh.program', 'synthetic-signer')
    monkeypatch.setenv('PATH', '.git' + os.pathsep + os.environ.get('PATH', ''))
    result = call(tmp_path, 'prepare', request, review=review(request))
    assert not result['ok']
    assert result['error'] == 'git_signer_path_selection_unsupported'
    assert port._candidate(tmp_path, result['branch']) is None


def test_signer_selection_refuses_defaults_and_ambiguous_paths(tmp_path):
    with pytest.raises(port.ContributionError, match='git_signer_path_selection_unsupported'):
        port._scratch_signing_settings(tmp_path, (('gpg.format', 'ssh'), ('user.signingkey', 'key::literal')))
    with pytest.raises(port.ContributionError, match='git_signer_path_selection_unsupported'):
        port._scratch_signing_settings(tmp_path, (('gpg.format', 'ssh'), ('user.signingkey', 'key::literal'),
                                                   ('gpg.ssh.program', r'synthetic\signer')))
    with pytest.raises(port.ContributionError, match='git_ssh_default_signing_key_unsupported'):
        port._scratch_signing_settings(tmp_path, (('gpg.format', 'ssh'), ('gpg.ssh.program', '/synthetic/signer'),
                                                   ('gpg.ssh.defaultkeycommand', './synthetic-command')))
    with pytest.raises(port.ContributionError, match='git_ssh_default_signing_key_unsupported'):
        port._scratch_signing_settings(tmp_path, (('gpg.format', 'ssh'), ('gpg.ssh.program', '/synthetic/signer'),
                                                   ('user.signingkey', 'key::old'), ('user.signingkey', '')))
    with pytest.raises(port.ContributionError, match='git_signing_key_path_unsupported'):
        port._scratch_signing_settings(tmp_path, (('gpg.format', 'ssh'), ('gpg.ssh.program', '/synthetic/signer'),
                                                   ('user.signingkey', 'missing-relative-key')))
    with pytest.raises(port.ContributionError, match='git_signing_config_value_unsupported'):
        port._scratch_signing_settings(tmp_path, (('gpg.format', 'ssh'), ('gpg.ssh.program', '/synthetic/signer'),
                                                   ('user.signingkey', 'key::literal'), ('gpg.mintrustlevel', '')))


def test_selected_local_unsigned_policy_overrides_global_signing(tmp_path, monkeypatch):
    fixture(tmp_path)
    git(tmp_path, 'config', 'commit.gpgSign', 'false')
    global_config = tmp_path.parent / (tmp_path.name + '-gitconfig')
    global_config.write_text('[commit]\n\tgpgSign = true\n')
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', str(global_config))
    assert port._commit_signing_policy(tmp_path) == (False, ())


def test_transport_uses_selected_repo_despite_inherited_git_directory(tmp_path, monkeypatch):
    selected = tmp_path / 'selected'
    selected.mkdir()
    fixture(selected)
    other = tmp_path / 'other'
    other.mkdir()
    fixture(other)
    (other / 'extra').write_text('different synthetic repository')
    git(other, 'add', 'extra')
    git(other, 'commit', '-qm', 'other repository')
    selected_oid = git(selected, 'rev-parse', 'HEAD')
    other_oid = git(other, 'rev-parse', 'HEAD')
    assert selected_oid != other_oid
    remote = tmp_path / 'remote.git'
    subprocess.run(['git', 'init', '--bare', str(remote)], check=True, capture_output=True)
    git(selected, 'remote', 'add', 'origin', str(remote))
    git(other, 'remote', 'add', 'origin', str(remote))
    with monkeypatch.context() as scoped:
        scoped.setenv('GIT_DIR', str(other / '.git'))
        scoped.setenv('GIT_INDEX_FILE', str(other / 'synthetic-index'))
        port._git(selected, 'push', 'origin', 'refs/heads/main:refs/heads/main')
        assert port._fetch_remote_ref(selected, 'refs/heads/main') == selected_oid
        assert port._remote_branch(selected, 'main') == selected_oid
    assert git(remote, 'rev-parse', 'refs/heads/main') == selected_oid
    assert git(selected, 'for-each-ref', 'refs/wiki/contribution-read') == ''
    assert git(other, 'for-each-ref', 'refs/wiki/contribution-read') == ''


def test_transport_environment_preserves_auth_but_binds_repository(tmp_path, monkeypatch):
    fixture(tmp_path)
    monkeypatch.setenv('GIT_SSH_COMMAND', 'synthetic-ssh-command')
    monkeypatch.setenv('GIT_ASKPASS', 'synthetic-askpass')
    monkeypatch.setenv('GIT_OBJECT_DIRECTORY', '/synthetic/unrelated-objects')
    env = port._transport_git_environment(tmp_path)
    assert env['GIT_SSH_COMMAND'] == 'synthetic-ssh-command'
    assert env['GIT_ASKPASS'] == 'synthetic-askpass'
    assert 'GIT_OBJECT_DIRECTORY' not in env
    assert Path(env['GIT_DIR']).resolve() == (tmp_path / '.git').resolve()
    assert Path(env['GIT_WORK_TREE']).resolve() == tmp_path.resolve()


def test_local_gates_use_selected_clone_despite_inherited_git_directory(tmp_path, monkeypatch):
    root = tmp_path / 'selected'
    root.mkdir()
    _, request = fixture(root)
    gate = root / 'scripts/wiki_input_stage.py'
    gate.write_text(
        'from pathlib import Path\nimport subprocess\n'
        'top = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()\n'
        'assert Path(top).resolve() == Path.cwd().resolve()\n'
        'path = Path("memories/actions/example.md")\n'
        'assert "Reviewed historical evidence." in path.read_text()\n'
        'if subprocess.run(["git", "diff", "--quiet"]).returncode == 0:\n'
        '    text = subprocess.check_output(["git", "show", "HEAD:memories/actions/example.md"], text=True)\n'
        '    assert "Reviewed historical evidence." in text\n'
    )
    git(root, 'add', 'scripts/wiki_input_stage.py')
    git(root, 'commit', '-qm', 'synthetic Git observation gate')
    request['files'][0]['base_commit'] = git(root, 'rev-parse', 'HEAD')
    prepared = call(root, 'prepare', request, review=review(request))
    assert prepared['ok'], prepared
    other = tmp_path / 'other'
    other.mkdir()
    git(other, 'init', '-q')
    monkeypatch.setenv('GIT_DIR', str(other / '.git'))
    monkeypatch.setenv('GIT_INDEX_FILE', str(other / 'synthetic-index'))
    receipts = port._local_integration_gates(root, prepared['proposal_commit'], required_policy='github_checks')
    assert receipts and all(receipt['exit_code'] == 0 for receipt in receipts)


@pytest.mark.parametrize('target', ['action', 'log'])
@pytest.mark.parametrize('mode', ['100755', '120000'])
def test_canonical_mode_change_requires_reconciliation(tmp_path, monkeypatch, target, mode):
    _, request = fixture(tmp_path)
    prepared = call(tmp_path, 'prepare', request, review=review(request))
    assert prepared['ok'], prepared
    commit = prepared['proposal_commit']
    action = request['files'][0]['path']
    ref = action if target == 'action' else 'memories/system/log.md'
    entry, _ = port._entry(tmp_path, commit, action, request, port.digest(request))
    parent = git(tmp_path, 'rev-parse', commit + '^')
    monkeypatch.setattr(port, '_canonical_observation', lambda *_args, **_kw: parent)
    port._integration_source_check(tmp_path, load_config(tmp_path), commit, action, entry, dry_run=True)
    blob = git(tmp_path, 'rev-parse', f'{parent}:{ref}')
    git(tmp_path, 'read-tree', parent)
    git(tmp_path, 'update-index', '--add', '--cacheinfo', f'{mode},{blob},{ref}')
    tree = git(tmp_path, 'write-tree')
    canonical = git(tmp_path, 'commit-tree', tree, '-p', parent, '-m', 'synthetic canonical mode')
    monkeypatch.setattr(port, '_canonical_observation', lambda *_args, **_kw: canonical)
    with pytest.raises(port.ContributionError, match='canonical_file_mode_changed'):
        port._integration_source_check(tmp_path, load_config(tmp_path), commit, action, entry, dry_run=True)


@pytest.mark.parametrize('target', ['action', 'log'])
def test_merge_readback_refuses_mode_inherited_from_advanced_base(tmp_path, monkeypatch, target):
    _, request = fixture(tmp_path)
    prepared = call(tmp_path, 'prepare', request, review=review(request))
    assert prepared['ok'], prepared
    candidate = prepared['proposal_commit']
    action = request['files'][0]['path']
    ref = action if target == 'action' else 'memories/system/log.md'
    parent = git(tmp_path, 'rev-parse', candidate + '^')
    git(tmp_path, 'read-tree', parent)
    blob = git(tmp_path, 'rev-parse', f'{parent}:{ref}')
    git(tmp_path, 'update-index', '--add', '--cacheinfo', f'100755,{blob},{ref}')
    advanced = git(tmp_path, 'commit-tree', git(tmp_path, 'write-tree'), '-p', parent,
                   '-m', 'synthetic advanced mode')
    git(tmp_path, 'read-tree', candidate)
    blob = git(tmp_path, 'rev-parse', f'{candidate}:{ref}')
    git(tmp_path, 'update-index', '--add', '--cacheinfo', f'100755,{blob},{ref}')
    merged = git(tmp_path, 'commit-tree', git(tmp_path, 'write-tree'), '-p', advanced, '-p', candidate,
                 '-m', 'synthetic merge mode')
    monkeypatch.setattr(port, '_canonical_observation', lambda *_args, **_kw: merged)
    with pytest.raises(port.ContributionError, match='merged_file_mode_mismatch'):
        port._canonical_readback(tmp_path, load_config(tmp_path), {'mergeCommit': {'oid': merged}},
                                 action, candidate, request, port.digest(request), dry_run=True)


@pytest.mark.parametrize('target', ['action', 'log'])
def test_readback_does_not_claim_current_adoption_after_mode_change(tmp_path, monkeypatch, target):
    _, request = fixture(tmp_path)
    prepared = call(tmp_path, 'prepare', request, review=review(request))
    assert prepared['ok'], prepared
    candidate = prepared['proposal_commit']
    action = request['files'][0]['path']
    ref = action if target == 'action' else 'memories/system/log.md'
    git(tmp_path, 'read-tree', candidate)
    blob = git(tmp_path, 'rev-parse', f'{candidate}:{ref}')
    git(tmp_path, 'update-index', '--add', '--cacheinfo', f'100755,{blob},{ref}')
    current = git(tmp_path, 'commit-tree', git(tmp_path, 'write-tree'), '-p', candidate,
                  '-m', 'synthetic later mode')
    monkeypatch.setattr(port, '_canonical_observation', lambda *_args, **_kw: current)
    result = port._canonical_readback(tmp_path, load_config(tmp_path), {'mergeCommit': {'oid': candidate}},
                                      action, candidate, request, port.digest(request), dry_run=True)
    assert result['remote_merged'] and not result['canonical_modes_match']
    assert not result['canonical_matches_material'] and not result['canonical_body_adopted']


@pytest.mark.parametrize('target', ['action', 'log'])
def test_candidate_refuses_a_symlink_already_in_parent_tree(tmp_path, target):
    _, request = fixture(tmp_path)
    prepared = call(tmp_path, 'prepare', request, review=review(request))
    assert prepared['ok'], prepared
    commit = prepared['proposal_commit']
    action = request['files'][0]['path']
    ref = action if target == 'action' else 'memories/system/log.md'
    parent = git(tmp_path, 'rev-parse', commit + '^')
    git(tmp_path, 'read-tree', parent)
    blob = git(tmp_path, 'rev-parse', f'{parent}:{ref}')
    git(tmp_path, 'update-index', '--add', '--cacheinfo', f'120000,{blob},{ref}')
    forged_parent = git(tmp_path, 'commit-tree', git(tmp_path, 'write-tree'), '-p', parent,
                        '-m', 'synthetic parent link')
    git(tmp_path, 'read-tree', commit)
    blob = git(tmp_path, 'rev-parse', f'{commit}:{ref}')
    git(tmp_path, 'update-index', '--add', '--cacheinfo', f'120000,{blob},{ref}')
    candidate = git(tmp_path, 'commit-tree', git(tmp_path, 'write-tree'), '-p', forged_parent,
                    '-m', 'synthetic unchanged link mode')
    with pytest.raises(port.ContributionError, match='candidate_file_mode_changed'):
        port._entry(tmp_path, candidate, action, request, port.digest(request), approved=forged_parent)


def test_candidate_preserves_existing_executable_regular_modes(tmp_path, monkeypatch):
    action, request = fixture(tmp_path)
    for ref in (request['files'][0]['path'], 'memories/system/log.md'):
        if os.name != 'nt':
            file = tmp_path / ref
            file.chmod(file.stat().st_mode | 0o111)
        git(tmp_path, 'update-index', '--chmod=+x', '--', ref)
    git(tmp_path, 'commit', '-qm', 'synthetic executable regular files')
    prepared = call(tmp_path, 'prepare', request, review=review(request))
    assert prepared['ok'], prepared
    commit = prepared['proposal_commit']
    for ref in (request['files'][0]['path'], 'memories/system/log.md'):
        assert port._tree_file_mode(tmp_path, commit + '^', ref) == '100755'
        assert port._tree_file_mode(tmp_path, commit, ref) == '100755'
    entry, _ = port._entry(tmp_path, commit, request['files'][0]['path'], request, port.digest(request))
    parent = git(tmp_path, 'rev-parse', commit + '^')
    monkeypatch.setattr(port, '_canonical_observation', lambda *_args, **_kw: parent)
    port._integration_source_check(tmp_path, load_config(tmp_path), commit, request['files'][0]['path'],
                                   entry, dry_run=True)


@pytest.mark.parametrize('name', ['literal[1].md', 'line\nname.md', 'carriage\rname.md'])
def test_git_tree_mode_uses_literal_bytes_despite_inherited_pathspec_setting(tmp_path, monkeypatch, name):
    if os.name == 'nt' and ('\n' in name or '\r' in name):
        pytest.skip('the host cannot create line breaks in file names')
    fixture(tmp_path)
    (tmp_path / name).write_text('Synthetic regular file\n')
    git(tmp_path, 'add', '--all')
    git(tmp_path, 'commit', '-qm', 'synthetic literal file name')
    monkeypatch.setenv('GIT_LITERAL_PATHSPECS', '1')
    assert port._tree_file_mode(tmp_path, 'HEAD', name) == '100644'


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


@pytest.mark.parametrize('proposed_endings', ['lf', 'crlf', 'crlf_allowed'])
def test_prepare_contribution_retains_crlf_preimage_bytes(tmp_path, monkeypatch, proposed_endings):
    if proposed_endings == 'crlf_allowed':
        monkeypatch.setenv('GIT_CONFIG_COUNT', '1')
        monkeypatch.setenv('GIT_CONFIG_KEY_0', 'core.whitespace')
        monkeypatch.setenv('GIT_CONFIG_VALUE_0', 'cr-at-eol')
    p, request = fixture(tmp_path)
    original = p.read_bytes().replace(b'\n', b'\r\n')
    p.write_bytes(original)
    git(tmp_path, 'add', str(p.relative_to(tmp_path)))
    git(tmp_path, 'commit', '-m', 'Synthetic CRLF action')
    text = original.decode('utf-8')
    proposed = text.replace('Original evidence.', 'Reviewed historical evidence.')
    if proposed_endings == 'lf':
        proposed = proposed.replace('\r\n', '\n')
    request['files'][0].update(base_commit=git(tmp_path, 'rev-parse', 'HEAD'),
        base_sha256=sha(text), sha256=sha(proposed), text=proposed)
    out = call(tmp_path, 'prepare', request, review=review(request))
    if proposed_endings == 'crlf':
        assert out['status'] == 'refused' and out['error'] == 'proposal_gate_failed:git'
        assert p.read_bytes() == original
        return
    assert out['status'] == 'prepared', json.dumps(out, indent=2)
    candidate = port._blob(tmp_path, out['proposal_commit'], request['files'][0]['path'])
    assert action_transition_diagnostics(text, candidate) == ()
    assert p.read_bytes() == original


@pytest.mark.parametrize('changed_endings', ['crlf', 'mixed'])
def test_source_check_refuses_newline_only_byte_change_before_remote_effect(tmp_path, monkeypatch, changed_endings):
    path, request = fixture(tmp_path)
    before = path.read_bytes()
    if changed_endings == 'crlf':
        path.write_bytes(before.replace(b'\n', b'\r\n'))
    else:
        path.write_bytes(before.replace(b'\n', b'\r\n', 1))
    current = path.read_bytes()
    monkeypatch.setattr(port, '_canonical_observation', lambda *a, **k: pytest.fail('remote check reached'))
    with pytest.raises(port.ContributionError, match='source_changed_since_prepare'):
        port._integration_source_check(tmp_path, load_config(tmp_path), request['files'][0]['base_commit'],
            request['files'][0]['path'], {'before_sha256': hashlib.sha256(before).hexdigest()}, dry_run=False)
    assert path.read_bytes() == current


@pytest.mark.parametrize('factual_change', [False, True])
def test_contribution_reconciles_lf_git_blob_with_crlf_checkout(tmp_path, factual_change):
    p, request = fixture(tmp_path)
    (tmp_path / '.gitattributes').write_text('memories/actions/*.md text eol=crlf\n')
    git(tmp_path, 'add', '.gitattributes')
    git(tmp_path, 'commit', '-m', 'Synthetic checkout conversion')
    ref = request['files'][0]['path']
    base_commit = git(tmp_path, 'rev-parse', 'HEAD')
    blob = port._blob(tmp_path, base_commit, ref)
    request['files'][0]['base_commit'] = base_commit
    assert '\r\n' not in blob
    p.unlink()
    git(tmp_path, 'checkout', '--', ref)
    assert b'\r\n' in p.read_bytes()
    git(tmp_path, 'diff', '--quiet', '--', ref)
    if factual_change:
        p.write_bytes(p.read_bytes().replace(b'Original evidence.', b'Different evidence.'))
    physical = p.read_bytes()
    out = call(tmp_path, 'prepare', request, review=review(request))
    if factual_change:
        assert out['status'] == 'refused' and out['error'] == 'source_body_conflict'
        assert p.read_bytes() == physical
        return
    assert out['status'] == 'prepared', json.dumps(out, indent=2)
    candidate = port._blob(tmp_path, out['proposal_commit'], ref)
    assert action_transition_diagnostics(blob, candidate) == ()
    assert p.read_bytes() == physical


@pytest.mark.parametrize('change', ['failed', 'pending', 'draft', 'changes_requested', 'head', 'base', 'number', 'head_ref', 'repository', 'owner', 'cross_repo', 'null', 'list'])
def test_github_checks_are_reobserved_before_merge_effect(tmp_path, monkeypatch, change):
    _, request = fixture(tmp_path)
    prepared = call(tmp_path, 'prepare', request, review=review(request))
    commit = prepared['proposal_commit']
    remote = tmp_path.parent / (tmp_path.name + '-remote.git')
    subprocess.run(['git', 'init', '--bare', str(remote)], check=True, capture_output=True)
    git(tmp_path, 'remote', 'add', 'origin', str(remote))
    git(tmp_path, 'push', 'origin', 'main')
    initial = {'number': 1, 'state': 'OPEN', 'headRefOid': commit, 'baseRefName': 'main',
               'statusCheckRollup': [{'conclusion': 'SUCCESS'}]}
    reconcile_pr_identity(initial, prepared)
    later = copy.deepcopy(initial)
    if change == 'failed': later['statusCheckRollup'] = [{'conclusion': 'FAILURE'}]
    elif change == 'pending': later['statusCheckRollup'] = [{'state': 'PENDING'}]
    elif change == 'draft': later['isDraft'] = True
    elif change == 'changes_requested': later['reviewDecision'] = 'CHANGES_REQUESTED'
    elif change == 'head': later['headRefOid'] = '0' * 40
    elif change == 'base': later['baseRefName'] = 'other'
    elif change == 'head_ref': later['headRefName'] = 'other'
    elif change == 'repository': later['headRepository'] = {'name': 'other'}
    elif change == 'owner': later['headRepositoryOwner'] = {'login': 'other'}
    elif change == 'cross_repo': later['isCrossRepository'] = True
    elif change == 'null': later = None
    elif change == 'list': later = []
    else: later['number'] = 2
    observed = []
    def read_pr(*_args):
        observed.append(True)
        return initial if len(observed) == 1 else later
    monkeypatch.setattr(port, '_pr', read_pr)
    monkeypatch.setattr(port, '_repository', lambda *_: 'example.test/synthetic/wiki')
    real_run = port._run
    def guarded_run(root, *argv, **kwargs):
        if argv[:3] == ('gh', 'pr', 'merge'):
            pytest.fail('merge reached after refreshed PR became ineligible')
        return real_run(root, *argv, **kwargs)
    monkeypatch.setattr(port, '_run', guarded_run)
    result = call(tmp_path, 'integrate', request, pr=1, head_review=head_review(request, commit))
    assert len(observed) == 2
    assert not result.get('remote_merged', False)
    if change in {'null', 'list'}:
        assert result['status'] == 'unknown'
        assert result['error'] == 'contribution_observation_unknown'
    else:
        assert result['status'] in {'waiting_ci_or_pr', 'waiting_pr_review', 'refused'}
