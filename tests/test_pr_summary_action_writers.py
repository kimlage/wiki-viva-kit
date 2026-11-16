"""Issue #521: the PR summary warns about a second writer on an action.

Synthetic repository only. Other open proposals are observed from local
remote-tracking branches; nothing is fetched and no provider is contacted.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "wiki_pr_summary.py"
ACTION = "memories/work/actions/synthetic-action.md"
OTHER_ACTION = "memories/work/actions/other-action.md"


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, text=True,
                          capture_output=True).stdout.strip()


def _commit(root: Path, path: str, text: str, message: str) -> str:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    git(root, "add", path)
    git(root, "commit", "-qm", message)
    return git(root, "rev-parse", "HEAD")


def _publish(root: Path, branch: str) -> None:
    git(root, "update-ref", f"refs/remotes/origin/{branch}", git(root, "rev-parse", "HEAD"))


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    root = tmp_path / "synthetic-wiki"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "user.name", "Synthetic Test")
    _commit(root, ACTION, "# Synthetic action\n", "base action")
    _commit(root, OTHER_ACTION, "# Other synthetic action\n", "other action")
    _commit(root, "memories/work/actions/index.md", "# Actions\n", "index")
    _publish(root, "main")
    base = git(root, "rev-parse", "HEAD")

    git(root, "switch", "-qc", "wiki/merged", base)
    _commit(root, ACTION, "# Synthetic action\n\nIntegrated earlier.\n", "merged result")
    git(root, "switch", "-q", "main")
    git(root, "merge", "-q", "--no-edit", "wiki/merged")
    _publish(root, "main")
    _publish(root, "wiki/merged")
    base = git(root, "rev-parse", "HEAD")

    git(root, "switch", "-qc", "wiki/second-writer", base)
    _commit(root, ACTION, "# Synthetic action\n\nSecond writer.\n", "second writer")
    _commit(root, "memories/work/actions/index.md", "# Actions\n\n- second\n", "index second")
    _publish(root, "wiki/second-writer")

    git(root, "switch", "-qc", "wiki/unrelated", base)
    _commit(root, OTHER_ACTION, "# Other synthetic action\n\nUnrelated.\n", "unrelated")
    _publish(root, "wiki/unrelated")

    git(root, "switch", "-qc", "wiki/this-proposal", base)
    _commit(root, ACTION, "# Synthetic action\n\nThis proposal.\n", "first commit")
    _publish(root, "wiki/this-proposal")  # own earlier push: ancestor of HEAD
    _commit(root, "memories/work/actions/index.md", "# Actions\n\n- this\n", "index this")
    return root


@pytest.fixture
def summary(monkeypatch, repository):
    spec = importlib.util.spec_from_file_location("wiki_pr_summary_writers_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", repository)
    return module


def run(summary, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["wiki_pr_summary.py"])
    status = summary.main()
    return status, capsys.readouterr().out


def test_second_open_proposal_on_same_action_is_warned(summary, monkeypatch, capsys):
    status, out = run(summary, monkeypatch, capsys)
    assert status == 0
    warnings = [line for line in out.splitlines() if line.startswith("WARNING: `memories/")]
    assert warnings == [
        f"WARNING: `{ACTION}` is also changed by `origin/wiki/second-writer`; one writer per "
        "action per round: add this result to that proposal or wait for its merge."
    ]
    # Own pushed history, integrated branches, unrelated actions and the
    # actions index are not second writers.
    for name in ("origin/wiki/this-proposal", "origin/wiki/merged", "origin/wiki/unrelated", "index.md` is also"):
        assert name not in out


def test_single_writer_reports_no_conflict(summary, repository, monkeypatch, capsys):
    git(repository, "update-ref", "-d", "refs/remotes/origin/wiki/second-writer")
    status, out = run(summary, monkeypatch, capsys)
    assert status == 0
    assert "No other observed proposal branch changes these action files." in out
    assert "WARNING: `memories/" not in out


def test_no_action_change_has_no_writer_section(summary, repository, monkeypatch, capsys):
    git(repository, "switch", "-qc", "wiki/docs-only", "origin/main")
    _commit(repository, "docs/note.md", "# Synthetic note\n", "docs only")
    status, out = run(summary, monkeypatch, capsys)
    assert status == 0
    assert "Concurrent writers on actions" not in out
