from __future__ import annotations

import subprocess
from pathlib import Path

from wiki_core.config import WikiConfig
from wiki_core.web.git_workflows import run_git_workflow


def _run(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, text=True, capture_output=True)


def _repo(root: Path) -> WikiConfig:
    _run(root, "init", "-b", "main")
    _run(root, "config", "user.email", "wiki@example.test")
    _run(root, "config", "user.name", "Wiki Test")
    (root / "memories").mkdir()
    (root / "memories/index.md").write_text("# Root\n", encoding="utf-8")
    _run(root, "add", "memories/index.md")
    _run(root, "commit", "-m", "init")
    return WikiConfig(repo_id="test", contexts=("example",))


def test_start_proposal_validates_theme_and_creates_branch(tmp_path: Path) -> None:
    config = _repo(tmp_path)

    bad = run_git_workflow(tmp_path, config, "start_proposal", {"theme": "../bad"}, dry_run=True)
    assert bad["ok"] is False
    assert bad["error"] == "invalid proposal theme"

    dry = run_git_workflow(tmp_path, config, "start_proposal", {"theme": "system-threejs"}, dry_run=True)
    assert dry["ok"] is True
    assert dry["results"][0]["dry_run"] is True
    assert dry["data"]["branch"] == "wiki/system-threejs"

    result = run_git_workflow(tmp_path, config, "start_proposal", {"theme": "system-threejs"}, dry_run=False)
    assert result["ok"] is True
    assert result["data"]["branch"] == "wiki/system-threejs"

    listed = run_git_workflow(tmp_path, config, "list_proposals")
    assert listed["data"]["branches"] == ["wiki/system-threejs"]


def test_stage_commit_and_pr_workflows_are_scoped_to_proposal_branch(tmp_path: Path) -> None:
    config = _repo(tmp_path)
    (tmp_path / "memories/index.md").write_text("# Root\n\nChanged.\n", encoding="utf-8")

    blocked = run_git_workflow(tmp_path, config, "commit_proposal", {"message": "update root"}, dry_run=True)
    assert blocked["ok"] is False
    assert blocked["error"] == "current branch is not a proposal branch"

    invalid_stage = run_git_workflow(tmp_path, config, "stage_paths", {"paths": ["../outside.md"]}, dry_run=True)
    assert invalid_stage["ok"] is False
    assert "known changed file" in invalid_stage["error"]

    _run(tmp_path, "switch", "-c", "wiki/system-threejs")

    stage = run_git_workflow(tmp_path, config, "stage_paths", {"paths": ["memories/index.md"]}, dry_run=True)
    assert stage["ok"] is True
    assert stage["data"]["paths"] == ["memories/index.md"]

    commit = run_git_workflow(tmp_path, config, "commit_proposal", {"message": "update root page"}, dry_run=True)
    assert commit["ok"] is True
    assert commit["results"][0]["argv"] == ["git", "commit", "-m", "update root page"]

    publish = run_git_workflow(tmp_path, config, "publish_proposal", dry_run=True)
    assert publish["ok"] is True
    assert publish["results"][0]["argv"] == ["git", "push", "-u", "origin", "wiki/system-threejs"]

    pr = run_git_workflow(tmp_path, config, "open_draft_pr", {"title": "System Threejs", "body": "Draft body"}, dry_run=True)
    assert pr["ok"] is True
    assert pr["results"][0]["argv"][:4] == ["gh", "pr", "create", "--draft"]
    assert pr["data"]["base"] == "main"

    update = run_git_workflow(tmp_path, config, "update_draft_pr", {"title": "System Threejs", "body": "Updated body"}, dry_run=True)
    assert update["ok"] is True
    assert update["results"][0]["argv"] == [
        "gh",
        "pr",
        "edit",
        "wiki/system-threejs",
        "--title",
        "System Threejs",
        "--body",
        "Updated body",
    ]
