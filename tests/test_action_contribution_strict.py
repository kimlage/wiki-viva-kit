"""Synthetic transaction/negative tests; fixture gates are not auditor proof.

The Git/canonical writer/C3/local gate invocations are real. Full auditor and
record semantics are separately exercised by the installed consumer proof.
"""
from __future__ import annotations

import json
import subprocess
import sys

import pytest
import yaml

import wiki_core.action_contribution as port
from wiki_core.action_transition import contribution_log_text
from wiki_core.document_records import sections
from test_action_contribution import fixture, git, sha, review, head_review, call, reconcile_pr_identity


C3 = '''import json,sys,hashlib
from pathlib import Path
payload=json.loads(Path(sys.argv[sys.argv.index('--contribution-file')+1]).read_text())
plan=payload['request']['consumer_preparation']['authored_plan']
assert plan == {'purpose':'Record this integration act; no domain conclusion or relationship reclassification.'}
p=Path(payload['derived_paths'][0]); contract=json.loads(p.read_text())
for name in contract['current_documents_sha256']:
    contract['current_documents_sha256'][name]=hashlib.sha256(Path(name).read_bytes()).hexdigest()
p.write_text(json.dumps(contract,sort_keys=True)+'\\n')
'''


def policy(root, *, c3=True, local=True, script=C3):
    config_file = root / "wiki.config.yaml"
    config = yaml.safe_load(config_file.read_text())
    if c3:
        (root / "records.json").write_text(json.dumps({"schema_version": "document_record.v1",
            "base_documents_sha256": {}, "current_documents_sha256": {
                p: sha((root / p).read_text()) for p in ("memories/actions/example.md", "memories/system/log.md")},
            "documents": [], "bindings": [], "artifacts": []}) + "\n")
        (root / "scripts/consumer_prepare.py").write_text(script)
        config["audit"] = {"freshness_records": "records.json"}
        config["approval"]["contribution_c3"] = {"argv": ["python3", "scripts/consumer_prepare.py"], "derived_paths": ["records.json"]}
    if local:
        config["approval"]["contribution_validation"] = {"mode": "local"}
        config["approval"]["contribution_gates"] = [[sys.executable, "scripts/wiki_input_stage.py", "--check"]]
    config_file.write_text(yaml.safe_dump(config, sort_keys=False))
    git(root, "add", "."); git(root, "commit", "-m", "Explicit synthetic consumer policy")


def strict(root, *, local=True, script=C3):
    p, request = fixture(root)
    policy(root, local=local, script=script)
    request["consumer_preparation"] = {"schema_version": "wiki_consumer_preparation.v1",
        "authored_plan": {"purpose": "Record this integration act; no domain conclusion or relationship reclassification."}}
    return p, request


def remote(root, prepared, monkeypatch):
    bare = root.parent / (root.name + "-remote.git")
    subprocess.run(["git", "clone", "--bare", "--shared", str(root), str(bare)], check=True, capture_output=True)
    git(root, "remote", "add", "origin", str(bare)); git(root, "push", "origin", "main", prepared["branch"])
    pr = {"number": 1, "state": "OPEN", "headRefOid": prepared["proposal_commit"],
          "baseRefName": "main", "statusCheckRollup": [], "isDraft": False}
    reconcile_pr_identity(pr, prepared)
    monkeypatch.setattr(port, "_pr", lambda *_: pr)
    monkeypatch.setattr(port, "_repository", lambda *_: "example.test/synthetic/wiki")
    real_run = port._run
    effects = []
    def run(where, *argv, **kwargs):
        if argv[:3] == ("gh", "pr", "merge"):
            effects.append(argv)
            git(root, "push", "origin", prepared["proposal_commit"] + ":refs/heads/main")
            pr.update(state="MERGED", mergeCommit={"oid": prepared["proposal_commit"]})
            return ""
        return real_run(where, *argv, **kwargs)
    monkeypatch.setattr(port, "_run", run)
    return pr, effects


def reviewed_head(request, prepared):
    return {**head_review(request, prepared["proposal_commit"]), "candidate_files": prepared["candidate_files"]}


def test_strict_prepare_and_immutable_local_integration_without_remote_checks(tmp_path, monkeypatch):
    p, request = strict(tmp_path)
    before = p.read_bytes(); metadata = (tmp_path / "records.json").read_bytes()
    prepared = call(tmp_path, "prepare", request, review=review(request))
    assert prepared["ok"], prepared
    assert prepared["coverage"] == port.C3_COVERAGE
    assert len(prepared["candidate_files"]) == 3
    assert prepared["c3_receipt"]["exit_code"] == 0
    assert len(prepared["c3_receipt"]["executable_sha256"]) == 64
    assert p.read_bytes() == before and (tmp_path / "records.json").read_bytes() == metadata
    pr, effects = remote(tmp_path, prepared, monkeypatch)
    result = call(tmp_path, "integrate", request, pr=1, head_review=reviewed_head(request, prepared))
    assert result["remote_merged"] and not result["canonical_body_adopted"], result
    receipt = result["validation_receipt"]
    assert receipt["proposal_commit"] == prepared["proposal_commit"]
    assert receipt["proposal_tree"] == prepared["proposal_tree"]
    assert receipt["candidate_files"] == prepared["candidate_files"]
    assert receipt["policy_sha256"] == sha((tmp_path / "wiki.config.yaml").read_text())
    assert receipt["command_sources"] and all(g["exit_code"] == 0 for g in receipt["gate_receipts"])
    assert result["validation_receipt_sha256"] == port.digest(receipt)
    assert len(effects) == 1 and len(result["readback_files"]) == 3
    # Readback never executes C3 or local gates and does not repeat the merge.
    monkeypatch.setattr(port, "_run_c3", lambda *_: pytest.fail("recovery must not run C3"))
    monkeypatch.setattr(port, "_gates", lambda *_a, **_k: pytest.fail("recovery must not run gates"))
    assert call(tmp_path, "reconcile", request, pr=1)["status"] == "waiting_worktree_adoption"
    git(tmp_path, "merge", "--ff-only", "origin/main")
    adopted = call(tmp_path, "reconcile", request, pr=1)
    assert adopted["canonical_body_adopted"] and not adopted["served_adoption_verified"]
    assert len(effects) == 1


@pytest.mark.parametrize("c3", [False, True])
def test_local_dry_run_does_not_run_or_claim_gates(tmp_path, monkeypatch, c3):
    if c3:
        _, request = strict(tmp_path)
    else:
        _, request = fixture(tmp_path); policy(tmp_path, c3=False)
    prepared = call(tmp_path, "prepare", request, review=review(request))
    remote(tmp_path, prepared, monkeypatch)
    monkeypatch.setattr(port, "_validate_local_candidate", lambda *_: pytest.fail("dry-run executed validation"))
    result = port.run_contribution(tmp_path, None, "integrate_contribution", {
        "request": request, "pr": 1, "head_review": reviewed_head(request, prepared)}, dry_run=True)
    assert result["validation_status"] == "ready_for_local_validation", result
    assert result["local_gates_not_run"] and "validation_receipt" not in result


@pytest.mark.parametrize("mutate,expected", [
    (lambda r: r.pop("consumer_preparation"), "reviewed_consumer_preparation_plan_required"),
    (lambda r: r["consumer_preparation"].update(authored_plan={"unreviewed": True}), "consumer_c3_failed"),
])
def test_missing_or_rejected_authorship_never_installs_proposal(tmp_path, mutate, expected):
    p, request = strict(tmp_path); before = p.read_bytes()
    mutate(request)
    result = call(tmp_path, "prepare", request, review=review(request))
    assert result["error"] == expected, result
    assert p.read_bytes() == before and not git(tmp_path, "branch", "--list", "wiki/contribution-*")


@pytest.mark.parametrize("suffix", [
    "raise SystemExit(4)\n",
    "Path('memories/actions/example.md').write_text('tamper')\n",
    "Path('wiki.config.yaml').write_text('tamper')\n",
    "Path('records.json').chmod(0o755)\n",
    "Path('records.json').unlink(); Path('records.json').symlink_to('wiki.config.yaml')\n",
    "contract['base_documents_sha256']={'forged':'proof'}; p.write_text(json.dumps(contract))\n",
    "contract['artifacts']=[{'id':'forged-capture'}]; p.write_text(json.dumps(contract))\n",
])
def test_c3_failure_or_scope_escape_never_installs_ref(tmp_path, suffix):
    p, request = strict(tmp_path, script=C3 + suffix)
    before = p.read_bytes()
    result = call(tmp_path, "prepare", request, review=review(request))
    assert not result["ok"] and result["status"] == "refused", result
    assert p.read_bytes() == before and not git(tmp_path, "branch", "--list", "wiki/contribution-*")


@pytest.mark.parametrize("path", ["records.json", "scripts/consumer_prepare.py", "wiki.config.yaml"])
def test_uncommitted_or_symlink_policy_inputs_are_not_used(tmp_path, path):
    _, request = strict(tmp_path)
    original = tmp_path / path
    saved = original.read_bytes(); target = tmp_path / "outside.fixture"; target.write_bytes(saved)
    original.unlink(); original.symlink_to(target)
    result = call(tmp_path, "prepare", request, review=review(request))
    assert not result["ok"], result
    assert not git(tmp_path, "branch", "--list", "wiki/contribution-*")


def test_ancestor_symlink_is_rejected(tmp_path):
    _, request = strict(tmp_path)
    scripts = tmp_path / "scripts"; scripts.rename(tmp_path / "actual-scripts"); scripts.symlink_to("actual-scripts", target_is_directory=True)
    assert call(tmp_path, "prepare", request, review=review(request))["error"] == "contribution_symlink_path"


@pytest.mark.parametrize("field", ["candidate_files", "proposal_commit"])
def test_strict_requires_exact_full_candidate_review(tmp_path, monkeypatch, field):
    _, request = strict(tmp_path)
    prepared = call(tmp_path, "prepare", request, review=review(request)); _, effects = remote(tmp_path, prepared, monkeypatch)
    report = reviewed_head(request, prepared); report.pop(field)
    result = call(tmp_path, "integrate", request, pr=1, head_review=report)
    assert not result["ok"] and not effects, result


def test_generated_candidate_executable_mode_is_refused(tmp_path):
    _, request = strict(tmp_path)
    prepared = call(tmp_path, "prepare", request, review=review(request))
    git(tmp_path, "switch", prepared["branch"])
    (tmp_path / "records.json").chmod(0o755)
    git(tmp_path, "add", "records.json"); git(tmp_path, "commit", "--amend", "--no-edit"); git(tmp_path, "switch", "main")
    assert call(tmp_path, "prepare", request, review=review(request))["error"] == "candidate_file_mode_changed"


def test_local_validation_does_not_accept_mutating_gate_or_old_receipt(tmp_path, monkeypatch):
    _, request = strict(tmp_path)
    prepared = call(tmp_path, "prepare", request, review=review(request)); _, effects = remote(tmp_path, prepared, monkeypatch)
    # Mutate only the validation clone, not the frozen candidate/source. This
    # simulates a formerly passing configured gate becoming input-dependent.
    real_gates = port._gates
    def gates(root, config, **kwargs):
        if kwargs.get("frozen_commit"):
            (root / "records.json").write_text("{}")
        return real_gates(root, config, **kwargs)
    monkeypatch.setattr(port, "_gates", gates)
    result = call(tmp_path, "integrate", request, pr=1, head_review=reviewed_head(request, prepared),
                  validation_receipt={"ok": True, "proposal_commit": prepared["proposal_commit"]})
    assert result["error"] == "gate_modified_immutable_candidate" and not effects, result


@pytest.mark.parametrize("target", ["records.json", "scripts/consumer_prepare.py"])
def test_metadata_and_script_overlap_after_validation_refuses_merge(tmp_path, monkeypatch, target):
    _, request = strict(tmp_path)
    prepared = call(tmp_path, "prepare", request, review=review(request)); _, effects = remote(tmp_path, prepared, monkeypatch)
    real_validate = port._validate_local_candidate
    def validate(*args):
        result = real_validate(*args)
        p = tmp_path / target; p.write_text(p.read_text() + "\n")
        return result
    monkeypatch.setattr(port, "_validate_local_candidate", validate)
    result = call(tmp_path, "integrate", request, pr=1, head_review=reviewed_head(request, prepared))
    assert result["error"].startswith("contribution_local_file_changed") and not effects, result


def test_strict_record_log_preserves_prior_bytes_and_same_day_headings_are_unique():
    old = "# Log\n\n## Historical record\nLiteral old observation.\n"
    one = contribution_log_text(old, "memories/actions/a.md", "memories/system/log.md", "a" * 64, "2026-10-19", log_format="record_v1")
    two = contribution_log_text(one, "memories/actions/a.md", "memories/system/log.md", "b" * 64, "2026-10-19", log_format="record_v1")
    assert sections(old)[1]["Historical record"][2] == sections(two)[1]["Historical record"][2]
    assert len(sections(two)[1]) == 3 and two.startswith(old)
    # Legacy104 keeps its exact format and remains separately verifiable.
    assert contribution_log_text(old, "a.md", "log.md", "x", "2026-10-19").startswith(old + "\n\n## [2026-10-19] Reviewed action body\n")


@pytest.mark.parametrize("change", ["no-local-gates", "unknown-mode", "metadata-is-memory", "extra-derived-path", "metadata-executable", "shell-source"])
def test_invalid_committed_policies_refuse_preparation(tmp_path, change):
    _, request = strict(tmp_path)
    p = tmp_path / "wiki.config.yaml"; config = yaml.safe_load(p.read_text())
    if change == "no-local-gates": config["approval"]["contribution_gates"] = []
    elif change == "unknown-mode": config["approval"]["contribution_validation"] = {"mode": "automatic"}
    elif change == "metadata-is-memory":
        config["audit"]["freshness_records"] = "memories/records.json"
        config["approval"]["contribution_c3"]["derived_paths"] = ["memories/records.json"]
    elif change == "extra-derived-path": config["approval"]["contribution_c3"]["derived_paths"].append("other.json")
    elif change == "metadata-executable": (tmp_path / "records.json").chmod(0o755)
    else: config["approval"]["contribution_c3"]["argv"] = ["bash", "-c", "unqualified command"]
    p.write_text(yaml.safe_dump(config)); git(tmp_path, "add", "."); git(tmp_path, "commit", "-m", "Synthetic invalid policy")
    result = call(tmp_path, "prepare", request, review=review(request))
    assert not result["ok"] and not git(tmp_path, "branch", "--list", "wiki/contribution-*"), result


def test_local_mode_does_not_ignore_present_failed_remote_checks(tmp_path, monkeypatch):
    _, request = strict(tmp_path)
    prepared = call(tmp_path, "prepare", request, review=review(request))
    pr, effects = remote(tmp_path, prepared, monkeypatch)
    pr["statusCheckRollup"] = [{"conclusion": "FAILURE"}]
    result = call(tmp_path, "integrate", request, pr=1, head_review=reviewed_head(request, prepared))
    assert result["status"] == "waiting_ci_or_pr" and not effects


def test_gate_cannot_modify_then_rely_on_a_later_gate_restoring_content(tmp_path):
    fixture(tmp_path)
    (tmp_path / "scripts/wiki_audit.py").write_text("from pathlib import Path\nPath('memories/actions/example.md').write_text('changed by check')\n")
    git(tmp_path, "add", "."); git(tmp_path, "commit", "-m", "Synthetic mutating check")
    with pytest.raises(port.ContributionError, match="gate_modified_candidate_inputs"):
        port._gates(tmp_path, port.load_config(tmp_path))


def test_unknown_merge_requires_read_only_reconciliation_without_repeating_gates_or_effect(tmp_path, monkeypatch):
    _, request = strict(tmp_path)
    prepared = call(tmp_path, "prepare", request, review=review(request)); _, effects = remote(tmp_path, prepared, monkeypatch)
    real_run = port._run
    def run(root, *argv, **kwargs):
        result = real_run(root, *argv, **kwargs)
        if argv[:3] == ("gh", "pr", "merge"):
            raise port.ContributionError("command_outcome_unknown: reconcile before retry")
        return result
    monkeypatch.setattr(port, "_run", run)
    result = call(tmp_path, "integrate", request, pr=1, head_review=reviewed_head(request, prepared))
    assert result["status"] == "unknown" and len(effects) == 1
    monkeypatch.setattr(port, "_run_c3", lambda *_: pytest.fail("UNKNOWN reconciliation executed C3"))
    monkeypatch.setattr(port, "_validate_local_candidate", lambda *_: pytest.fail("UNKNOWN reconciliation executed gates"))
    observed = call(tmp_path, "reconcile", request, pr=1)
    assert observed["remote_merged"] and not observed["canonical_body_adopted"] and len(effects) == 1


def test_proposal_ref_change_after_local_validation_refuses_merge(tmp_path, monkeypatch):
    _, request = strict(tmp_path)
    prepared = call(tmp_path, "prepare", request, review=review(request)); _, effects = remote(tmp_path, prepared, monkeypatch)
    real_validate = port._validate_local_candidate
    def validate(*args):
        result = real_validate(*args)
        git(tmp_path, "update-ref", "refs/heads/" + prepared["branch"], git(tmp_path, "rev-parse", "main"))
        return result
    monkeypatch.setattr(port, "_validate_local_candidate", validate)
    result = call(tmp_path, "integrate", request, pr=1, head_review=reviewed_head(request, prepared))
    assert result["error"] == "proposal_head_changed_after_validation" and not effects, result
