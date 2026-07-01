from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from wiki_core.config import WikiConfig
from wiki_core.web.git_ops import build_git_state


def _run(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, text=True, capture_output=True)


def test_git_state_detects_proposal_branch_and_dirty_paths(tmp_path: Path) -> None:
    _run(tmp_path, "init", "-b", "main")
    _run(tmp_path, "config", "user.email", "wiki@example.test")
    _run(tmp_path, "config", "user.name", "Wiki Test")
    (tmp_path / "memories").mkdir()
    (tmp_path / "memories/index.md").write_text(
        "---\npage_id: root\npage_type: root_index\ncontext: system\n---\n# Root\n",
        encoding="utf-8",
    )
    _run(tmp_path, "add", "memories/index.md")
    _run(tmp_path, "commit", "-m", "init")
    _run(tmp_path, "switch", "-c", "wiki/example")
    (tmp_path / "memories/index.md").write_text(
        "---\npage_id: root\npage_type: root_index\ncontext: system\n---\n# Root\n\nChanged.\n",
        encoding="utf-8",
    )

    state = build_git_state(tmp_path, WikiConfig(repo_id="test", contexts=("example",)))

    assert state["available"] is True
    assert state["default_branch"] == "main"
    assert state["current_branch"] == "wiki/example"
    assert state["proposal"]["is_proposal_branch"] is True
    assert state["proposal"]["theme"] == "example"
    assert state["proposal"]["human_gate_state"] == "not_opened"
    assert state["worktree"]["clean"] is False
    assert state["worktree"]["changed_files"][0]["path"] == "memories/index.md"


def test_git_state_uses_github_pr_metadata_when_available(tmp_path: Path, monkeypatch: Any) -> None:
    _run(tmp_path, "init", "-b", "main")
    _run(tmp_path, "config", "user.email", "wiki@example.test")
    _run(tmp_path, "config", "user.name", "Wiki Test")
    (tmp_path / "memories").mkdir()
    (tmp_path / "memories/index.md").write_text("# Root\n", encoding="utf-8")
    _run(tmp_path, "add", "memories/index.md")
    _run(tmp_path, "commit", "-m", "init")
    _run(tmp_path, "switch", "-c", "wiki/example")

    monkeypatch.setattr(
        "wiki_core.web.git_ops._gh_pr_metadata",
        lambda root, branch: {
            "url": "https://github.com/example/wiki/pull/42",
            "isDraft": True,
            "state": "OPEN",
        },
    )

    state = build_git_state(tmp_path, WikiConfig(repo_id="test", contexts=("example",)))

    assert state["proposal"]["draft_pr_url"] == "https://github.com/example/wiki/pull/42"
    assert state["proposal"]["human_gate_state"] == "draft"


def test_git_state_handles_non_git_directory(tmp_path: Path) -> None:
    state = build_git_state(tmp_path, WikiConfig(repo_id="test"))

    assert state["available"] is False
    assert state["proposal"]["human_gate_state"] == "blocked"
