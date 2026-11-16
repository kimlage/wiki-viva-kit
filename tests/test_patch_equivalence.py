"""Issue #522: a clean rebase with a proven-identical patch.

Synthetic repository only; local Git objects, no fetch or provider call.
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


def test_clean_rebase_is_proven_identical(module, repo):
    root, old_base, reviewed, new_base, rebased = repo
    result = module.compare(root, reviewed, rebased)
    assert result["verdict"] == "identical"
    assert result["old_base"] == old_base and result["new_base"] == new_base
    assert result["range_diff_unchanged"] is True
    line = module.proof_line(result)
    assert line.startswith("Equivalence: identical patch-id=")
    assert f"reviewed={reviewed}" in line and f"rebased={rebased}" in line and "range-diff=unchanged" in line


def test_squash_keeps_patch_identity_but_range_diff_changes(module, repo):
    root, old_base, reviewed, new_base, _ = repo
    git(root, "switch", "-qc", "wiki/squashed", new_base)
    git(root, "merge", "-q", "--squash", reviewed)
    git(root, "commit", "-qm", "squashed")
    result = module.compare(root, reviewed, git(root, "rev-parse", "HEAD"))
    assert result["verdict"] == "identical"
    assert result["range_diff_unchanged"] is False


def test_conflict_resolution_or_new_change_is_different(module, repo):
    root, _, reviewed, _, rebased = repo
    git(root, "switch", "-q", "wiki/rebased")
    changed = write_commit(root, "action.md", "# Action\n\nresult changed after review\n", "new change")
    result = module.compare(root, reviewed, changed)
    assert result["verdict"] == "different"
    assert result["patch_id"] is None


def test_cli_exit_codes(module, repo, monkeypatch, capsys):
    root, _, reviewed, new_base, rebased = repo
    r = ["--root", str(root)]
    assert module.main([*r, "--reviewed", reviewed, "--rebased", rebased]) == 0
    assert capsys.readouterr().out.startswith("Equivalence: identical")
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


REVIEWED, REBASED, BASE, PATCH = "a" * 40, "c" * 40, "b" * 40, "d" * 40


def _handoff(extra: str = "") -> str:
    return (f"Proposal: PR 1 repo=owner/repo target=main\nHead: {REBASED}\nBase: {BASE}\n"
            f"Review: https://example.test/review {REVIEWED}\nGates: pytest=passed\nPending: none\n"
            f"Responsible-Thread: thread:sample{extra}")


def test_handoff_keeps_review_only_with_identical_equivalence_proof():
    hook = _hook()
    assert "review" in hook.handoff_problems(_handoff())
    proof = (f"\nEquivalence: identical patch-id={PATCH} reviewed={REVIEWED} base={'e' * 40} "
             f"rebased={REBASED} onto={BASE} range-diff=unchanged")
    assert hook.handoff_problems(_handoff(proof)) == []
    assert "review" in hook.handoff_problems(_handoff(proof.replace("identical", "different")))
    assert "review" in hook.handoff_problems(_handoff(proof.replace(f"rebased={REBASED}", f"rebased={'f' * 40}")))
    assert "review" in hook.handoff_problems(_handoff(proof.replace(f"reviewed={REVIEWED}", f"reviewed={'f' * 40}")))
