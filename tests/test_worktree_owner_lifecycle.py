"""Issue #525: executor worktrees need an active owner.

Synthetic repositories only; no provider is contacted. An executor declares an
active worktree with `git worktree lock --reason "owner=<thread>"` and removes
it after push. The integration check reports the declaration status, and the
owner's activity only from a host observation: an ended owner is a fix, an
unobserved owner stays explicitly unknown.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

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


def _inventory(monkeypatch, tmp_path, worktrees, activity=None):
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
    result = check.inspect(tmp_path, owner_activity=activity)
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
        ("warn:worktree_owner_undeclared", "/tmp/idle"),
        ("waiting:verify_worktree_owner", "/tmp/owned"),
        ("warn:worktree_owner_unidentified", "/tmp/anonymous"),
        ("fix:prunable_worktree", "/tmp/gone"),
    ]


OWNED = {"branch": "wiki/open", "head": HEAD, "dirty": False, "main": False, "prunable": False, "locked": True}
MAIN = {"path": "/wiki", "branch": "main", "head": BASE, "dirty": False, "main": True, "locked": False, "prunable": False}


def test_ended_owner_is_flagged_from_the_host_observation(monkeypatch, tmp_path):
    findings = _inventory(monkeypatch, tmp_path, [
        MAIN,
        OWNED | {"path": "/tmp/ended", "owner": "thread:finished-1"},
        OWNED | {"path": "/tmp/active", "owner": "thread:running-1"},
        OWNED | {"path": "/tmp/unlisted", "owner": "thread:unlisted-1"},
    ], activity=check.owner_activity_from_mapping({
        "thread:finished-1": "ended", "thread:running-1": "Active", "https://example.test/x": "ended"}))
    assert findings == [
        ("fix:worktree_owner_ended", "/tmp/ended"),
        ("observe:worktree_owner_active", "/tmp/active"),
        ("waiting:verify_worktree_owner", "/tmp/unlisted"),
    ]


def test_without_observation_owner_activity_is_explicitly_unknown(monkeypatch, tmp_path):
    monkeypatch.setattr(check, "_repository", lambda root: "github.com/owner/repo")
    findings = _inventory(monkeypatch, tmp_path, [MAIN, OWNED | {"path": "/tmp/ended", "owner": "thread:finished-1"}])
    assert findings == [("waiting:verify_worktree_owner", "/tmp/ended")]
    item = check._owner_finding(OWNED | {"path": "/tmp/ended", "owner": "thread:finished-1"}, None)
    assert item["owner_activity"] == "unknown"


def test_owner_activity_input_is_bounded_and_filtered(tmp_path):
    assert check.owner_activity_from_mapping({"thread:a": "ended", "thread:b": "paused", 3: "ended",
                                              "thread:\x1b[31m": "ended"}) == {"thread:a": "ended"}
    with pytest.raises(ValueError):
        check.owner_activity_from_mapping(["thread:a"])
    good = tmp_path / "activity.json"
    good.write_text('{"thread:a": "ended"}', encoding="utf-8")
    assert check.load_owner_activity(good) == {"thread:a": "ended"}
    for content in ("not json", "[]", "{" + '"x": 1,' * 20000 + '"y": 2}'):
        bad = tmp_path / "bad.json"
        bad.write_text(content, encoding="utf-8")
        with pytest.raises(ValueError):
            check.load_owner_activity(bad)
    with pytest.raises(ValueError):
        check.load_owner_activity(tmp_path / "missing.json")


def test_cli_rejects_unusable_owner_activity_without_echoing_it(tmp_path, capsys):
    import importlib.util
    script = Path(__file__).resolve().parents[1] / "scripts" / "wiki_integration_check.py"
    spec = importlib.util.spec_from_file_location("wiki_integration_check_cli_test", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    bad = tmp_path / "activity.json"
    bad.write_text("SYNTHETIC-NOT-JSON", encoding="utf-8")
    import sys
    argv = sys.argv
    sys.argv = ["wiki_integration_check.py", "--root", str(tmp_path), "--owner-activity", str(bad)]
    try:
        with pytest.raises(SystemExit) as exc:
            module.main()
    finally:
        sys.argv = argv
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "owner activity is not JSON" in err and "SYNTHETIC-NOT-JSON" not in err


def test_main_and_dirty_worktrees_keep_their_existing_findings(monkeypatch, tmp_path):
    findings = _inventory(monkeypatch, tmp_path, [
        {"path": "/wiki", "branch": "main", "head": BASE, "dirty": False, "main": True, "locked": False, "prunable": False},
        {"path": "/tmp/dirty", "branch": "wiki/open", "head": HEAD, "dirty": True, "main": False, "locked": False, "prunable": False},
        {"path": "/tmp/other-repo-executor", "branch": "wiki/no-pr", "head": HEAD, "dirty": False, "main": False, "locked": True, "owner": "thread:x", "prunable": False},
    ])
    assert findings == [("fix:dirty_worktree", "/tmp/dirty"), ("fix:worktree_without_pr", "/tmp/other-repo-executor")]
