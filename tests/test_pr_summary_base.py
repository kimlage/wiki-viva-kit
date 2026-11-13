"""PR summary bases are selected from explicit or observed Git refs."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'wiki_pr_summary.py'


def git(root: Path, *args: str) -> str:
    result = subprocess.run(['git', *args], cwd=root, check=True, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.stdout.strip()


@pytest.fixture
def repository(tmp_path: Path):
    root = tmp_path / 'synthetic-wiki'
    root.mkdir()
    git(root, 'init', '-q', '-b', 'main')
    git(root, 'config', 'user.email', 'test@example.invalid')
    git(root, 'config', 'user.name', 'Synthetic Test')
    (root / 'tracked.md').write_text('base\n')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'synthetic base')
    base_a = git(root, 'rev-parse', 'HEAD')

    # A remote-tracking ref is a local observation: no network or other clone.
    git(root, 'switch', '-qc', 'synthetic-remote-update')
    (root / 'integrated-policy.md').write_text('synthetic approved change\n')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'advance observed base')
    base_b = git(root, 'rev-parse', 'HEAD')
    git(root, 'update-ref', 'refs/remotes/origin/main', base_b)

    git(root, 'switch', '-qc', 'wiki/synthetic-proposal', base_a)
    (root / 'proposal.md').write_text('synthetic proposal\n')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'proposal')
    git(root, 'merge', '--no-edit', 'refs/remotes/origin/main')
    (root / 'staged.md').write_text('staged\n')
    git(root, 'add', 'staged.md')
    (root / 'tracked.md').write_text('unstaged\n')
    (root / 'untracked.md').write_text('untracked\n')
    return root, base_a, base_b


@pytest.fixture
def summary(monkeypatch, repository):
    spec = importlib.util.spec_from_file_location('wiki_pr_summary_base_test', SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'ROOT', repository[0])
    return module


def invoke(summary, monkeypatch, capsys, *args):
    monkeypatch.setattr(sys, 'argv', ['wiki_pr_summary.py', *args])
    try:
        status = summary.main()
    except SystemExit as exc:
        status = exc.code
    captured = capsys.readouterr()
    return status, captured.out, captured.err


def test_default_uses_observed_remote_base_and_preserves_all_local_changes(repository, summary, monkeypatch, capsys):
    root, local_sha, remote_sha = repository
    status, out, err = invoke(summary, monkeypatch, capsys)
    assert status == 0, err
    assert 'origin/main' in out and remote_sha in out
    assert 'merge-base' in out.lower() and remote_sha in out
    assert 'warning' in (out + err).lower() and local_sha in (out + err)
    assert 'integrated-policy.md' not in out
    for path in ('proposal.md', 'staged.md', 'tracked.md', 'untracked.md'):
        assert path in out
    assert git(root, 'rev-parse', 'main') == local_sha
    assert git(root, 'rev-parse', 'origin/main') == remote_sha


def test_special_names_survive_git_nul_parsing(repository, summary, monkeypatch, capsys):
    root, _, _ = repository
    staged_name = 'synthetic space-ç-\tstaged.md'
    untracked_name = 'synthetic space-λ-\tuntracked.md'
    (root / staged_name).write_text('synthetic staged content\n')
    (root / untracked_name).write_text('synthetic untracked content\n')
    git(root, 'add', '--', staged_name)
    status, out, err = invoke(summary, monkeypatch, capsys)
    assert status == 0, err
    assert staged_name in out and untracked_name in out


def test_staged_and_unstaged_statuses_for_same_path_are_retained(repository, summary, monkeypatch, capsys):
    root, _, _ = repository
    path = root / 'staged.md'  # Already added to the synthetic index.
    path.write_text('additional unstaged change\n')
    status, out, err = invoke(summary, monkeypatch, capsys)
    assert status == 0, err
    rows = [line for line in out.splitlines() if '`staged.md`' in line]
    assert rows
    assert all('`A/M`' in line or '`M/A`' in line for line in rows)


def test_git_diff_failure_cannot_be_reported_as_empty(repository, summary, monkeypatch, capsys):
    original_run = summary.subprocess.run

    def fail_diff(argv, *args, **kwargs):
        if 'diff' in argv:
            return subprocess.CompletedProcess(argv, 1, stdout=b'', stderr=b'synthetic failure')
        return original_run(argv, *args, **kwargs)

    monkeypatch.setattr(summary.subprocess, 'run', fail_diff)
    status, out, err = invoke(summary, monkeypatch, capsys)
    assert status != 0
    assert 'No diff detected' not in out
    assert err or 'error' in out.lower()


def test_explicit_base_is_honored_and_reported(repository, summary, monkeypatch, capsys):
    _, local_sha, remote_sha = repository
    status, out, err = invoke(summary, monkeypatch, capsys, '--base', local_sha)
    assert status == 0, err
    assert local_sha in out and 'merge-base' in out.lower()
    assert 'integrated-policy.md' in out
    assert 'warning' in (out + err).lower() and remote_sha in (out + err)
    for path in ('proposal.md', 'staged.md', 'tracked.md', 'untracked.md'):
        assert path in out


def test_missing_remote_ref_uses_local_main_with_warning(repository, summary, monkeypatch, capsys):
    root, local_sha, _ = repository
    git(root, 'update-ref', '-d', 'refs/remotes/origin/main')
    status, out, err = invoke(summary, monkeypatch, capsys)
    assert status == 0, err
    assert 'main' in out and local_sha in out
    assert 'warning' in (out + err).lower()
    assert 'integrated-policy.md' in out
    assert 'staged.md' in out and 'tracked.md' in out and 'untracked.md' in out


def test_invalid_explicit_base_fails_closed_without_false_no_diff(repository, summary, monkeypatch, capsys):
    status, out, err = invoke(summary, monkeypatch, capsys, '--base', 'refs/heads/not-real')
    assert status != 0
    assert 'No diff detected' not in out
    assert err or 'error' in out.lower()


def test_non_ancestor_base_reports_merge_base_and_warning(repository, summary, monkeypatch, capsys):
    root, _, common = repository
    tree = git(root, 'rev-parse', f'{common}^{{tree}}')
    advanced_base = git(root, 'commit-tree', tree, '-p', common, '-m', 'another synthetic base')
    status, out, err = invoke(summary, monkeypatch, capsys, '--base', advanced_base)
    assert status == 0, err
    assert advanced_base in out and common in out
    assert 'merge-base' in out.lower() and 'warning' in (out + err).lower()
    assert 'proposal.md' in out and 'integrated-policy.md' not in out


def test_no_available_default_base_fails_closed(repository, summary, monkeypatch, capsys):
    root, _, _ = repository
    git(root, 'update-ref', '-d', 'refs/remotes/origin/main')
    git(root, 'update-ref', '-d', 'refs/heads/main')
    status, out, err = invoke(summary, monkeypatch, capsys)
    assert status != 0
    assert 'No diff detected' not in out
    assert err or 'error' in out.lower()


def test_disconnected_base_fails_closed(repository, summary, monkeypatch, capsys):
    root, _, _ = repository
    tree = git(root, 'rev-parse', 'HEAD^{tree}')
    unrelated = git(root, 'commit-tree', tree, '-m', 'unrelated synthetic root')
    status, out, err = invoke(summary, monkeypatch, capsys, '--base', unrelated)
    assert status != 0
    assert 'No diff detected' not in out
    assert err or 'error' in out.lower()


def test_unavailable_git_repository_fails_closed(summary, monkeypatch, capsys, tmp_path):
    not_repo = tmp_path / 'not-a-git-repository'
    not_repo.mkdir()
    monkeypatch.setattr(summary, 'ROOT', not_repo)
    status, out, err = invoke(summary, monkeypatch, capsys)
    assert status != 0
    assert 'No diff detected' not in out
    assert err or 'error' in out.lower()


def test_renames_across_contexts_report_both_original_and_destination(
    tmp_path, summary, monkeypatch, capsys
):
    root = tmp_path / 'synthetic-renames'
    root.mkdir()
    git(root, 'init', '-q', '-b', 'main')
    git(root, 'config', 'user.email', 'test@example.invalid')
    git(root, 'config', 'user.name', 'Synthetic Test')
    (root / 'memories/people').mkdir(parents=True)
    (root / 'memories/projects').mkdir(parents=True)
    old_committed = 'memories/people/committed\tinput.md'
    old_staged = 'memories/people/staged input.md'
    new_committed = 'memories/projects/committed output.md'
    new_staged = 'memories/projects/staged\toutput.md'
    for path in (old_committed, old_staged):
        (root / path).write_text('synthetic content\n')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'synthetic base')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    git(root, 'switch', '-qc', 'wiki/rename-proposal')
    git(root, 'mv', old_committed, new_committed)
    git(root, 'commit', '-qm', 'synthetic committed rename')
    git(root, 'mv', old_staged, new_staged)
    (root / new_staged).write_text('synthetic unstaged edit\n')
    monkeypatch.setattr(summary, 'ROOT', root)
    status, out, err = invoke(summary, monkeypatch, capsys)
    assert status == 0, err
    for path in (old_committed, old_staged, new_committed, new_staged):
        assert f'`{path}`' in out
    assert f'`D` `{old_committed}`' in out
    assert f'`D` `{old_staged}`' in out
    assert f'`A` `{new_committed}`' in out
    assert f'`M/A` `{new_staged}`' in out or f'`A/M` `{new_staged}`' in out
