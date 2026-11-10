"""Synthetic checks for metadata-first historical audit selection.

These tests cover literal path selection, not contextual authorization: a deny
inside the selected memory root still needs independent host authorization.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import scripts.wiki_audit as audit
from wiki_core.context_packet import qualify_folder_context
from wiki_core.context_policy import load_policy


def git(root: Path, *args: str) -> str:
    return subprocess.run(['git', '-C', str(root), *args], check=True,
                          text=True, capture_output=True).stdout.strip()


@pytest.fixture
def synthetic_history(tmp_path, monkeypatch):
    root = tmp_path / 'synthetic-wiki'
    root.mkdir()
    git(root, 'init', '-q')
    git(root, 'config', 'user.name', 'Synthetic fixture')
    git(root, 'config', 'user.email', 'synthetic@example.invalid')
    for directory in ('memories/actions', 'memories/projects', 'memories/sources', 'restricted'):
        (root / directory).mkdir(parents=True, exist_ok=True)
    (root / 'AGENTS.md').write_text('# Synthetic root instructions\n', encoding='utf-8')
    (root / 'index.md').write_text('# Synthetic root index\n', encoding='utf-8')
    config = {'context_access': {'.': {'owner': 'Synthetic owner', 'policy': {
        'read': ['self'], 'write': ['self'], 'capabilities': [], 'publication': [],
        'deny': {'read': ['self/restricted']},
    }}}}
    (root / 'wiki.config.yaml').write_text(yaml.safe_dump(config), encoding='utf-8')
    contents = {
        'memories/actions/broken.md': '---\npage_id: action-broken\npage_type: action\nbroken: [\n---\n',
        'memories/projects/action [literal].md': '---\npage_id: action-outside-directory\npage_type: action # comment\n---\nSynthetic.\n',
        'memories/sources/source.md': '---\npage_id: source-synthetic\npage_type: source\n---\nSynthetic.\n',
        'memories/sources/fonte ação [1].md': '---\npage_id: source-unicode\npage_type: source\n---\nSynthetic.\n',
        'memories/projects/ordinary.md': '---\npage_id: note-synthetic\npage_type: note\n---\nSynthetic.\n',
        'restricted/denied.json': '{"text":"page_type: action"}\n',
        'restricted/denied.md': '---\npage_id: source-denied\npage_type: source\n---\nSynthetic.\n',
    }
    for rel, body in contents.items():
        (root / rel).write_text(body, encoding='utf-8')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'synthetic approved baseline')
    base = git(root, 'rev-parse', 'HEAD')
    git(root, 'update-ref', 'refs/remotes/origin/main', base)
    monkeypatch.setattr(audit, 'ROOT', root)
    for fn in (audit._audit_base_ref, audit._text_at_audit_base,
               audit._base_action_candidate_texts_by_path, audit._base_action_texts_by_page_id,
               audit._malformed_base_actions, audit._base_source_texts_by_page_id):
        fn.cache_clear()
    yield SimpleNamespace(root=root, base=base, contents=contents, config=config)
    for fn in (audit._audit_base_ref, audit._text_at_audit_base,
               audit._base_action_candidate_texts_by_path, audit._base_action_texts_by_page_id,
               audit._malformed_base_actions, audit._base_source_texts_by_page_id):
        fn.cache_clear()


def record_git_greps(monkeypatch):
    original = subprocess.run
    calls = []
    def observed(argv, *args, **kwargs):
        if isinstance(argv, (list, tuple)) and 'grep' in argv:
            calls.append(tuple(str(value) for value in argv))
        return original(argv, *args, **kwargs)
    monkeypatch.setattr(subprocess, 'run', observed)
    return calls


def test_historical_search_limits_real_git_to_literal_memory_paths(synthetic_history, monkeypatch):
    case = synthetic_history
    policy = load_policy(case.root, case.base, 'wiki.config.yaml')
    qualify_folder_context(case.root, policy, '.', '.', 'index.md', 100_000)
    assert not policy.permits('.', 'read', 'restricted/denied.json')
    assert not policy.permits('.', 'read', 'restricted/denied.md')
    calls = record_git_greps(monkeypatch)
    original_read = audit._history_text
    body_reads = []
    def observed_history_read(base, path):
        body_reads.append(path)
        return original_read(base, path)
    monkeypatch.setattr(audit, '_history_text', observed_history_read)
    actions = audit._action_candidate_texts_by_path_at_ref(case.base)
    sources = audit._base_source_texts_by_page_id()
    assert 'memories/projects/action [literal].md' in actions
    assert 'memories/actions/broken.md' in actions
    malformed = audit._malformed_actions_from_candidates(actions)
    assert malformed['memories/actions/broken.md'] == 'action-broken'
    ids = audit._action_texts_by_page_id_from_candidates(actions)
    assert ids['action-outside-directory'][0][0] == 'memories/projects/action [literal].md'
    assert sources['source-synthetic'][0][0] == 'memories/sources/source.md'
    assert sources['source-unicode'][0][0] == 'memories/sources/fonte ação [1].md'
    assert body_reads and all(path.startswith('memories/') for path in body_reads)
    assert not any(path.startswith('restricted/') for path in body_reads)
    assert len(calls) >= 2
    for call in calls:
        assert '--' in call
        pathspecs = call[call.index('--') + 1:]
        assert pathspecs, 'an empty pathspec must never search the complete tree'
        assert all(path.startswith(':(literal)memories/') and path.endswith('.md') for path in pathspecs)
        assert all('restricted/' not in path for path in pathspecs)
    assert any(':(literal)memories/projects/action [literal].md' in call for call in calls)
    assert any(':(literal)memories/sources/fonte ação [1].md' in call for call in calls)


def test_empty_selection_never_invokes_git_grep(synthetic_history, monkeypatch):
    calls = record_git_greps(monkeypatch)
    assert not audit._grep_selected_history(synthetic_history.base, r'page_type[[:space:]]*:', [])
    assert calls == []


def test_nonmatching_grep_is_not_a_coverage_failure(synthetic_history):
    paths = ['memories/projects/ordinary.md']
    assert not audit._grep_selected_history(synthetic_history.base, r'NEVER_MATCH_SYNTHETIC_4321', paths)


@pytest.mark.skipif(os.name == 'nt', reason='literal backslash is a separator on Windows')
def test_git_path_with_literal_backslash_fails_before_grep(synthetic_history, monkeypatch):
    """A POSIX Git name must not change meaning as a Windows path separator."""
    case = synthetic_history
    rel = 'memories/projects/back\\slash.md'
    try:
        (case.root / rel).write_text('---\npage_type: action\n---\nSynthetic.\n', encoding='utf-8')
    except OSError as exc:
        pytest.skip(f'filesystem rejects a literal backslash: {type(exc).__name__}')
    git(case.root, 'add', '--', rel)
    git(case.root, 'commit', '-qm', 'synthetic literal backslash')
    revision = git(case.root, 'rev-parse', 'HEAD')
    calls = record_git_greps(monkeypatch)
    with pytest.raises(audit.AuditPathBoundaryError):
        audit._action_candidate_texts_by_path_at_ref(revision)
    assert calls == []
    with pytest.raises(audit.AuditPathBoundaryError):
        audit._grep_selected_history(revision, r'page_type[[:space:]]*:', [rel])
    assert calls == []


def test_tree_metadata_failure_is_unavailable_not_empty_success(synthetic_history):
    with pytest.raises(audit.AuditPathBoundaryError):
        audit._historical_markdown_paths('0' * len(synthetic_history.base), 'memories/')


def test_git_grep_error_is_unavailable_not_empty_success(synthetic_history, monkeypatch):
    original = subprocess.run
    def failed(argv, *args, **kwargs):
        if isinstance(argv, (list, tuple)) and 'grep' in argv:
            return subprocess.CompletedProcess(argv, 128, stdout=b'', stderr=b'synthetic git error')
        return original(argv, *args, **kwargs)
    monkeypatch.setattr(subprocess, 'run', failed)
    with pytest.raises(audit.AuditPathBoundaryError):
        audit._grep_selected_history(synthetic_history.base, r'page_type[[:space:]]*:',
                                     ['memories/projects/ordinary.md'])


def test_deny_inside_memory_root_requires_independent_authority(synthetic_history, monkeypatch):
    case = synthetic_history
    path = case.root / 'memories' / 'internal' / 'denied.md'
    path.parent.mkdir()
    path.write_text('---\npage_id: action-denied\npage_type: action\n---\nSynthetic.\n', encoding='utf-8')
    case.config['context_access']['.']['policy']['deny']['read'].append('self/memories/internal')
    (case.root / 'wiki.config.yaml').write_text(yaml.safe_dump(case.config), encoding='utf-8')
    git(case.root, 'add', '.')
    git(case.root, 'commit', '-qm', 'synthetic deny inside memory root')
    revision = git(case.root, 'rev-parse', 'HEAD')
    git(case.root, 'update-ref', 'refs/remotes/origin/main', revision)
    policy = load_policy(case.root, revision, 'wiki.config.yaml')
    qualify_folder_context(case.root, policy, '.', '.', 'index.md', 100_000)
    assert not policy.permits('.', 'read', 'memories/internal/denied.md')
    paths = audit._historical_markdown_paths(revision, 'memories/')
    assert 'memories/internal/denied.md' in paths
    # Selection is path-scoped only. Do not run its content search without an
    # independently authorized host; this is NOT a contextual deny filter.


def test_main_reports_unavailable_and_fails_even_without_check(synthetic_history, monkeypatch, capsys):
    """A Git search failure must not turn a selected check into success."""
    case = synthetic_history
    original = subprocess.run

    def failed(argv, *args, **kwargs):
        if isinstance(argv, (list, tuple)) and 'grep' in argv:
            return subprocess.CompletedProcess(argv, 128, stdout=b'', stderr=b'synthetic error')
        return original(argv, *args, **kwargs)

    def selected_check(_ctx):
        audit._grep_selected_history(case.base, r'page_type[[:space:]]*:',
                                     ['memories/projects/ordinary.md'])

    monkeypatch.setattr(subprocess, 'run', failed)
    monkeypatch.setattr(audit, 'CHECKS', (('action_state_transitions', selected_check),))
    monkeypatch.setattr(audit, 'CHECK_NAMES', ('action_state_transitions',))
    monkeypatch.setattr('sys.argv', ['wiki_audit.py', '--only', 'action_state_transitions'])
    assert audit.main() != 0
    output = capsys.readouterr().out.lower()
    assert 'coverage unavailable' in output and 'checks not completed' in output
    assert '0 error(s)' not in output
