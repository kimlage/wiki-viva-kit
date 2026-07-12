from __future__ import annotations

from pathlib import Path

import pytest

from wiki_core.output_safety import prepare_managed_output_directory


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_managed_output_refuses_target_symlink_and_preserves_external_directory(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    external = tmp_path / "external-target"
    keeper = external / "keep.txt"
    _write(keeper, "external target\n")
    target = root / "output-link"
    target.symlink_to(external, target_is_directory=True)

    with pytest.raises(ValueError, match="cannot be a symlink"):
        prepare_managed_output_directory(
            root,
            target,
            kind="test_output",
            repo_id="repo",
            clean=True,
            force_unowned=True,
        )

    assert target.is_symlink()
    assert keeper.read_text(encoding="utf-8") == "external target\n"
    assert sorted(
        path.relative_to(external).as_posix()
        for path in external.rglob("*")
        if path.is_file()
    ) == ["keep.txt"]


def test_managed_output_refuses_ancestor_symlink_escape_and_preserves_external_directory(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    external = tmp_path / "external-ancestor"
    keeper = external / "nested" / "keep.txt"
    _write(keeper, "external ancestor\n")
    linked_parent = root / "linked-parent"
    linked_parent.symlink_to(external, target_is_directory=True)

    with pytest.raises(ValueError, match="inside repository root"):
        prepare_managed_output_directory(
            root,
            linked_parent / "nested",
            kind="test_output",
            repo_id="repo",
            clean=True,
            force_unowned=True,
        )

    assert linked_parent.is_symlink()
    assert keeper.read_text(encoding="utf-8") == "external ancestor\n"
    assert sorted(
        path.relative_to(external).as_posix()
        for path in external.rglob("*")
        if path.is_file()
    ) == ["nested/keep.txt"]
