"""Issues #522/#523: merge-condition case 2, a clean rebase of a covered head.

Every commit must be unchanged (`range-diff` all `=` at the same position, or
equal per-commit `git patch-id --stable`) with no new commit. Synthetic
repository only; local Git objects, no fetch or provider call.
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "wiki_core" / "patch_equivalence.py"


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, text=True,
                          capture_output=True).stdout.strip()


def write_commit(root: Path, path: str, text: str, message: str) -> str:
    (root / path).parent.mkdir(parents=True, exist_ok=True)
    (root / path).write_text(text, encoding="utf-8")
    git(root, "add", path)
    git(root, "commit", "-qm", message)
    return git(root, "rev-parse", "HEAD")


@pytest.fixture
def module():
    spec = importlib.util.spec_from_file_location("wiki_patch_equivalence_test", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


@pytest.fixture
def repo(tmp_path: Path):
    root = tmp_path / "synthetic"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "user.name", "Synthetic Test")
    old_base = write_commit(root, "page.md", "# Page\n\nline one\n", "base")
    git(root, "switch", "-qc", "wiki/proposal")
    write_commit(root, "action.md", "# Action\n\nresult\n", "proposal part 1")
    reviewed = write_commit(root, "page.md", "# Page\n\nline one\nline two\n", "proposal part 2")
    git(root, "switch", "-q", "main")
    new_base = write_commit(root, "other.md", "# Other\n", "unrelated integration")
    git(root, "update-ref", "refs/remotes/origin/main", new_base)
    git(root, "switch", "-qc", "wiki/rebased", reviewed)
    git(root, "rebase", "-q", new_base)
    rebased = git(root, "rev-parse", "HEAD")
    return root, old_base, reviewed, new_base, rebased


def test_clean_rebase_keeps_every_commit(module, repo):
    root, old_base, reviewed, new_base, rebased = repo
    result = module.compare(root, reviewed, rebased)
    assert result["verdict"] == "identical"
    assert result["commits"] == (2, 2)
    assert result["per_commit_patch_id"] is True and result["range_diff_unchanged"] is True
    assert result["old_base"] == old_base and result["new_base"] == new_base
    line = module.proof_line(result)
    assert line.startswith("Equivalence: identical commits=2 patch-id=per-commit-match range-diff=all-equal ")
    assert f"reviewed={reviewed}" in line and f"rebased={rebased}" in line
    details = module.proof_details(result)
    assert len(details) == 2 and all(" = " in row for row in details)


def test_squash_is_a_different_commit_set(module, repo):
    root, _, reviewed, new_base, _ = repo
    git(root, "switch", "-qc", "wiki/squashed", new_base)
    git(root, "merge", "-q", "--squash", reviewed)
    git(root, "commit", "-qm", "squashed")
    result = module.compare(root, reviewed, git(root, "rev-parse", "HEAD"))
    assert result["verdict"] == "different"
    assert result["commits"] == (2, 1)
    assert "commits=2->1" in module.proof_line(result)


def test_new_commit_in_the_rebase_is_different(module, repo):
    root, _, reviewed, _, _ = repo
    git(root, "switch", "-q", "wiki/rebased")
    changed = write_commit(root, "action.md", "# Action\n\nresult changed after review\n", "new change")
    result = module.compare(root, reviewed, changed)
    assert result["verdict"] == "different" and result["commits"] == (2, 3)


def test_changed_commit_content_is_different(module, repo):
    root, _, reviewed, new_base, _ = repo
    git(root, "switch", "-qc", "wiki/amended", new_base)
    write_commit(root, "action.md", "# Action\n\nresult, reworded\n", "proposal part 1")
    amended = write_commit(root, "page.md", "# Page\n\nline one\nline two\n", "proposal part 2")
    result = module.compare(root, reviewed, amended)
    assert result["verdict"] == "different"
    assert result["per_commit_patch_id"] is False and result["range_diff_unchanged"] is False


def test_reordered_commits_are_different(module, repo):
    root, _, reviewed, new_base, _ = repo
    git(root, "switch", "-qc", "wiki/reordered", new_base)
    write_commit(root, "page.md", "# Page\n\nline one\nline two\n", "proposal part 2")
    reordered = write_commit(root, "action.md", "# Action\n\nresult\n", "proposal part 1")
    result = module.compare(root, reviewed, reordered)
    assert result["verdict"] == "different"


def test_merge_commit_is_not_provable(module, repo):
    root, _, reviewed, new_base, _ = repo
    git(root, "switch", "-qc", "wiki/merged", reviewed)
    git(root, "merge", "-q", "--no-edit", new_base)
    result = module.compare(root, reviewed, git(root, "rev-parse", "HEAD"))
    assert result["verdict"] == "not_provable"


def test_cli_exit_codes(module, repo, capsys):
    root, _, reviewed, new_base, rebased = repo
    r = ["--root", str(root)]
    assert module.main([*r, "--reviewed", reviewed, "--rebased", rebased]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("Equivalence: identical commits=2") and len(out) == 3
    assert module.main([*r, "--reviewed", reviewed, "--rebased", reviewed]) == 2  # not on the new base
    assert module.main([*r, "--reviewed=-bad", "--rebased", rebased]) == 2
    assert module.main([*r, "--reviewed", new_base, "--rebased", new_base]) == 1  # empty patch
    assert "empty_patch" in capsys.readouterr().out


def _hook():
    path = Path(__file__).resolve().parents[1] / "scripts" / "wiki_session_hook.py"
    spec = importlib.util.spec_from_file_location("wiki_session_hook_equivalence_test", path)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


REVIEWED, REBASED, BASE = "a" * 40, "c" * 40, "b" * 40


def _handoff(extra: str = "") -> str:
    return (f"Proposal: PR 1 repo=owner/repo target=main\nHead: {REBASED}\nBase: {BASE}\n"
            f"Review: https://example.test/review {REVIEWED}\nGates: pytest=passed\nPending: none\n"
            f"Responsible-Thread: thread:sample{extra}")


def test_handoff_keeps_review_only_with_identical_per_commit_proof():
    hook = _hook()
    assert "review" in hook.handoff_problems(_handoff())
    proof = (f"\nEquivalence: identical commits=2 patch-id=per-commit-match range-diff=all-equal "
             f"reviewed={REVIEWED} base={'e' * 40} rebased={REBASED} onto={BASE}")
    assert hook.handoff_problems(_handoff(proof)) == []
    for bad in (proof.replace("identical", "different"),
                proof.replace("commits=2", "commits=2->1"),
                proof.replace(f"rebased={REBASED}", f"rebased={'f' * 40}"),
                proof.replace(f"reviewed={REVIEWED}", f"reviewed={'f' * 40}")):
        assert "review" in hook.handoff_problems(_handoff(bad))


def test_merge_condition_text_keeps_its_limits():
    root = Path(__file__).resolve().parents[1]
    guide = " ".join((root / "docs/references/guides/context-coordinators.md").read_text(encoding="utf-8").split())
    brief = " ".join((root / "docs/references/templates/wiki/subagent-brief.md").read_text(encoding="utf-8").split())
    for clause in (
        "Only three cases cover the final SHA",
        "no conflict and no new commit",
        "the `git patch-id --stable` of each commit equal to that of the covered head",
        "a coordinator who did not make the delta's commits checks the range `<reviewed SHA>..<final SHA>`",
        "which only fixes findings already recorded by the reviewers",
        "New content outside those findings requires a new independent review",
        "If the coordinator's brief chose between alternatives or drafted the fix",
        "the delta goes back to the reviewer of the last round",
    ):
        assert clause in guide, clause
    for clause in ("only fixes findings already recorded by the reviewers",
                   "New content requires a new independent review",
                   "the delta goes back to the reviewer of the last round",
                   "no conflict and no new commit"):
        assert clause in brief, clause
