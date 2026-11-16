"""Issue #525: executor worktrees need an active owner.

Synthetic repositories only; no provider is contacted. An executor declares an
active worktree with `git worktree lock --reason "owner=<thread>"` and removes
it after push. The integration check flags clean, unlocked worktrees of open
proposals, locks without an identifiable owner and prunable worktrees.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from wiki_core import integration_check as check

HEAD = "a" * 40
BASE = "b" * 40


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, text=True, capture_output=True).stdout


def test_worktree_inventory_reads_owner_lock_and_prunable(tmp_path: Path) -> None:
    root = tmp_path / "wiki"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "tests@example.invalid")
    _git(root, "config", "user.name", "Synthetic")
    (root / "page.md").write_text("# Synthetic\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "synthetic base")
    for name in ("idle", "owned", "anonymous", "gone"):
        _git(root, "worktree", "add", "-q", str(tmp_path / name), "-b", f"wiki/{name}")
    _git(root, "worktree", "lock", "--reason", "owner=thread:executor-1", str(tmp_path / "owned"))
    _git(root, "worktree", "lock", "--reason", "kept by someone", str(tmp_path / "anonymous"))
    shutil.rmtree(tmp_path / "gone")

    items = {Path(item["path"]).name: item for item in check._worktrees(root)}

    assert items["wiki"]["main"] is True
    assert not items["idle"]["locked"]
    assert items["idle"]["dirty"] is False and "owner" not in items["idle"]
    assert items["owned"]["locked"] and items["owned"]["owner"] == "thread:executor-1"
    assert items["anonymous"]["locked"] and "owner" not in items["anonymous"]
    assert items["gone"]["prunable"] and items["gone"]["dirty"] is None


def test_unsafe_lock_reason_is_not_an_owner() -> None:
    assert check._worktree_owner("owner=thread:ok-1") == "thread:ok-1"
    assert check._worktree_owner("owner=https://example.test/x") is None
    assert check._worktree_owner("owner=\x1b[31mthread:x") is None
    assert check._worktree_owner(None) is None


def _inventory(monkeypatch, tmp_path, worktrees):
    pr = {"number": 1, "url": "https://example.test/pull/1", "state": "OPEN",
          "author": {"login": "author"}, "headRefOid": HEAD, "baseRefOid": BASE,
          "headRefName": "wiki/open", "baseRefName": "main", "isDraft": True,
          "headRepositoryOwner": {"login": "owner"}, "isCrossRepository": False,
          "mergeStateStatus": "CLEAN", "statusCheckRollup": [], "reviews": [], "comments": []}

    def git(root, *args):
        if args[:3] == ("ls-remote", "--symref", "origin"):
            return "ref: refs/heads/main\tHEAD\n" + BASE + "\tHEAD"
        if args == ("ls-remote", "--heads", "origin"):
            return f"{BASE}\trefs/heads/main\n{HEAD}\trefs/heads/wiki/open"
        return f"main\t{BASE}\nwiki/open\t{HEAD}"

    monkeypatch.setattr(check, "_repository", lambda root: "github.com/owner/repo")
    monkeypatch.setattr(check, "_gh", lambda root, *args: [pr])
    monkeypatch.setattr(check, "_git", git)
    monkeypatch.setattr(check, "policy", lambda root, base: {"gate": "github_pr"})
    monkeypatch.setattr(check, "_ancestry", lambda *args: "current")
    monkeypatch.setattr(check, "_action_findings", lambda *args: ([], True))
    monkeypatch.setattr(check, "_worktrees", lambda root: worktrees)
    result = check.inspect(tmp_path)
    assert result["ok"]
    return [(item["status"], item.get("path")) for item in result["hygiene"]
            if "worktree" in item["status"] or "owner" in item["status"]]


def test_open_proposal_worktree_without_active_owner_is_flagged(monkeypatch, tmp_path):
    base = {"branch": "wiki/open", "head": HEAD, "dirty": False, "main": False, "prunable": False}
    findings = _inventory(monkeypatch, tmp_path, [
        {"path": "/wiki", "branch": "main", "head": BASE, "dirty": False, "main": True, "locked": False, "prunable": False},
        base | {"path": "/tmp/idle", "locked": False},
        base | {"path": "/tmp/owned", "locked": True, "owner": "thread:executor-1"},
        base | {"path": "/tmp/anonymous", "locked": True},
        base | {"path": "/tmp/gone", "locked": False, "prunable": True, "dirty": None},
    ])
    assert findings == [
        ("warn:worktree_without_active_owner", "/tmp/idle"),
        ("observe:worktree_owner", "/tmp/owned"),
        ("warn:worktree_owner_unidentified", "/tmp/anonymous"),
        ("fix:prunable_worktree", "/tmp/gone"),
    ]


def test_main_and_dirty_worktrees_keep_their_existing_findings(monkeypatch, tmp_path):
    findings = _inventory(monkeypatch, tmp_path, [
        {"path": "/wiki", "branch": "main", "head": BASE, "dirty": False, "main": True, "locked": False, "prunable": False},
        {"path": "/tmp/dirty", "branch": "wiki/open", "head": HEAD, "dirty": True, "main": False, "locked": False, "prunable": False},
        {"path": "/tmp/other-repo-executor", "branch": "wiki/no-pr", "head": HEAD, "dirty": False, "main": False, "locked": True, "owner": "thread:x", "prunable": False},
    ])
    assert findings == [("fix:dirty_worktree", "/tmp/dirty"), ("fix:worktree_without_pr", "/tmp/other-repo-executor")]
