from __future__ import annotations

import subprocess
from pathlib import Path

from wiki_core.config import WikiConfig
from wiki_core.web.commands import build_action_cards, is_allowed_argv, run_action


def _init_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)


def test_action_cards_expose_safe_git_and_gate_actions() -> None:
    payload = build_action_cards(WikiConfig(repo_id="test"))
    action_ids = {action["id"] for action in payload["actions"]}

    assert {"git-status", "review-local-changes", "run-honesty-gates", "pr-summary"} <= action_ids
    assert all("commands" in action for action in payload["actions"])


def test_allowlist_rejects_arbitrary_shell_and_destructive_git() -> None:
    assert is_allowed_argv(["git", "status", "--short", "--branch"])
    assert is_allowed_argv(["python3", "scripts/wiki_audit.py", "--check"])
    assert not is_allowed_argv(["sh", "-c", "echo unsafe"])
    assert not is_allowed_argv(["git", "reset", "--hard"])
    assert not is_allowed_argv(["python3", "scripts/wiki_audit.py", "--write"])


def test_run_action_executes_read_action_and_supports_dry_run(tmp_path: Path) -> None:
    _init_repo(tmp_path)

    status = run_action(tmp_path, WikiConfig(repo_id="test"), "git-status", dry_run=False)
    assert status["ok"] is True
    assert status["results"][0]["dry_run"] is False

    dry = run_action(tmp_path, WikiConfig(repo_id="test"), "refresh-cockpit-write")
    assert dry["ok"] is True
    assert dry["dry_run"] is True
    assert dry["results"][0]["stdout"] == "dry run: command not executed"


def test_run_action_rejects_unknown_action(tmp_path: Path) -> None:
    result = run_action(tmp_path, WikiConfig(repo_id="test"), "nope")

    assert result["ok"] is False
    assert result["error"] == "unknown action"
