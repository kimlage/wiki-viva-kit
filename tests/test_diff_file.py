from __future__ import annotations

import subprocess
from pathlib import Path

from wiki_core.config import WikiConfig
from wiki_core.web.diff import file_diff


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _repo(root: Path) -> WikiConfig:
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "t@e.test")
    _git(root, "config", "user.name", "T")
    (root / "memories").mkdir()
    (root / "memories/index.md").write_text("# Root\noriginal line\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial commit")
    return WikiConfig(repo_id="diff-test")


def test_tracked_file_change_produces_a_diff(tmp_path: Path) -> None:
    config = _repo(tmp_path)
    (tmp_path / "memories/index.md").write_text("# Root\nEDITED line\n", encoding="utf-8")
    result = file_diff(tmp_path, config, "memories/index.md")
    assert result["ok"] is True
    assert result["tracked"] is True
    body = "\n".join(result["diff"])
    assert "EDITED line" in body
    assert "original line" in body


def test_untracked_file_diffs_against_devnull(tmp_path: Path) -> None:
    config = _repo(tmp_path)
    (tmp_path / "memories/new.md").write_text("brand new page\n", encoding="utf-8")
    result = file_diff(tmp_path, config, "memories/new.md")
    assert result["ok"] is True
    assert result["tracked"] is False
    assert any("brand new page" in line for line in result["diff"])


def test_secrets_are_redacted_in_the_diff(tmp_path: Path) -> None:
    config = _repo(tmp_path)
    (tmp_path / "memories/index.md").write_text('# Root\ntoken: sk-supersecret12345\n', encoding="utf-8")
    result = file_diff(tmp_path, config, "memories/index.md")
    body = "\n".join(result["diff"])
    assert "sk-supersecret12345" not in body
    assert "[REDACTED]" in body


def test_unsafe_paths_are_rejected(tmp_path: Path) -> None:
    config = _repo(tmp_path)
    for bad in ("../etc/passwd", "/etc/passwd", "a/../../b"):
        assert file_diff(tmp_path, config, bad)["ok"] is False
