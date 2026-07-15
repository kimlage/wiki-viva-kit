from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from wiki_core.source_integrity import SourceIntegrityError, verify_clean_source


def _git(root: Path, *arguments: str) -> str:
    return subprocess.check_output(["git", *arguments], cwd=root, text=True).strip()


def _repo(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "source"
    root.mkdir()
    _git(root, "init", "-q")
    (root / "tracked.txt").write_text("stable\n", encoding="utf-8")
    _git(root, "add", "tracked.txt")
    _git(
        root,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "initial",
    )
    return root, _git(root, "rev-parse", "HEAD")


def test_exact_clean_source_is_stable(tmp_path: Path) -> None:
    root, head = _repo(tmp_path)
    first = verify_clean_source(root, head)
    second = verify_clean_source(root, head)
    assert first == second
    assert first.head_sha == head
    assert first.tracked_entry_count == 1


def test_assume_unchanged_cannot_hide_tracked_mutation(tmp_path: Path) -> None:
    root, head = _repo(tmp_path)
    _git(root, "update-index", "--assume-unchanged", "tracked.txt")
    (root / "tracked.txt").write_text("mutated\n", encoding="utf-8")
    with pytest.raises(SourceIntegrityError, match="bytes differ"):
        verify_clean_source(root, head)


def test_untracked_path_fails_closed(tmp_path: Path) -> None:
    root, head = _repo(tmp_path)
    (root / "untracked.txt").write_text("new\n", encoding="utf-8")
    with pytest.raises(SourceIntegrityError, match="tracked or untracked drift"):
        verify_clean_source(root, head)


def test_changed_head_fails_closed(tmp_path: Path) -> None:
    root, head = _repo(tmp_path)
    (root / "second.txt").write_text("second\n", encoding="utf-8")
    _git(root, "add", "second.txt")
    _git(
        root,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "second",
    )
    with pytest.raises(SourceIntegrityError, match="HEAD differs"):
        verify_clean_source(root, head)


def test_hardlinked_tracked_file_fails_closed(tmp_path: Path) -> None:
    root, head = _repo(tmp_path)
    external = tmp_path / "external.txt"
    (root / "tracked.txt").rename(external)
    (root / "tracked.txt").hardlink_to(external)
    with pytest.raises(SourceIntegrityError, match="unsafe"):
        verify_clean_source(root, head)


def test_executable_local_git_config_fails_closed(tmp_path: Path) -> None:
    root, head = _repo(tmp_path)
    _git(root, "config", "--local", "filter.evil.clean", "/tmp/never-run")
    with pytest.raises(SourceIntegrityError, match="Git policy is unsafe"):
        verify_clean_source(root, head)
