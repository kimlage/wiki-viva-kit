"""Synthetic worktree old-paths check; no global audit or host proof."""
import pytest

from tests.test_audit_r1_inventory import git, repo, run
from tests.test_audit_secrets_selection_worktree import _approve_fixture, _args, _inventory
from tests.test_wiki_audit import _load_wiki_audit
from wiki_core import audit_worktree_selection as selected
from wiki_core.audit_r1_inventory import SelectedReads
from wiki_core.context_policy import PolicyError


def test_old_paths_executes_registered_check_with_admitted_bodies(repo, monkeypatch):
    root, base = _approve_fixture(repo, clear_deny=True)
    old = root / 'docs/2026/synthetic.md'
    old.parent.mkdir(parents=True)
    old.write_text('Synthetic docs/memories/reference.\n')
    args = _args(root, base)
    snapshot = _inventory(args)
    plan = selected.plan_old_paths(snapshot)
    audit = _load_wiki_audit()
    monkeypatch.setattr(audit, 'ROOT', root)
    audit._audit_git_inventory.cache_clear()
    audit.tracked_files.cache_clear()
    assert plan['metadata_names'] == audit.tracked_files()
    result = selected.run_worktree_old_paths(**args, inventory_sha256=snapshot['inventory_sha256'],
        plan_sha256=plan['plan_sha256'], admit=lambda _: True)
    assert result['state'] == 'failed'
    expected = []
    audit.audit_old_paths(expected, audit.WikiConfig())
    assert result['diagnostics'] == expected
    assert any('old docs path is still tracked' in error for error in expected)
    assert result['global_audit'] == 'not_performed'
    assert result['gate_state'] == 'blocked_incomplete_coverage'


def test_old_paths_denied_markdown_refuses_before_bodies(repo, monkeypatch):
    root, _, _, _ = repo
    (root / 'restricted/denied.md').write_text('Synthetic protected text.\n')
    snapshot = run(repo)
    monkeypatch.setattr(selected, '_worktree_bytes', lambda *_: pytest.fail('body opened'))
    with pytest.raises(PolicyError, match='selection unavailable'):
        selected.plan_old_paths(snapshot)


def test_old_paths_known_index_alias_refuses_before_bodies(repo, monkeypatch):
    root, _, _, _ = repo
    (root / 'allowed.md').write_bytes((root / 'restricted/denied.json').read_bytes())
    git(root, 'add', 'allowed.md')
    snapshot = run(repo)
    assert any(row['path'] == 'allowed.md' and row['oid'] in snapshot['denied_oid_aliases']
               for row in snapshot['index'])
    monkeypatch.setattr(selected, '_worktree_bytes', lambda *_: pytest.fail('body opened'))
    with pytest.raises(PolicyError, match='old paths selection unavailable'):
        selected.plan_old_paths(snapshot)


def test_old_paths_incomplete_direct_reader_refuses_before_processing(tmp_path):
    audit = _load_wiki_audit()
    reads = SelectedReads(tmp_path, {'files': {'one.md': {}, 'two.md': {}}, 'directories': []},
                          {'one.md': b'Synthetic first body.'})
    errors = []
    with pytest.raises(RuntimeError, match='body outside admitted selection'):
        audit.audit_old_paths(errors, audit.WikiConfig(), reads=reads, selected_names=['one.md', 'two.md'])
    assert errors == []


def test_old_paths_missing_tracked_metadata_blocks_selection(repo, monkeypatch):
    root, base = _approve_fixture(repo, clear_deny=True)
    git(root, 'rm', '-q', 'restricted/denied.json')
    snapshot = _inventory(_args(root, base))
    monkeypatch.setattr(selected, '_worktree_bytes', lambda *_: pytest.fail('body opened'))
    with pytest.raises(PolicyError, match='old paths selection unavailable'):
        selected.plan_old_paths(snapshot)


def test_old_paths_denied_admission_precedes_selected_reads(repo, monkeypatch):
    root, base = _approve_fixture(repo, clear_deny=True)
    args = _args(root, base)
    snapshot = _inventory(args)
    plan = selected.plan_old_paths(snapshot)
    monkeypatch.setattr(selected, '_worktree_bytes', lambda *_: pytest.fail('body opened'))
    with pytest.raises(PolicyError, match='host admission unavailable'):
        selected.run_worktree_old_paths(**args, inventory_sha256=snapshot['inventory_sha256'],
            plan_sha256=plan['plan_sha256'], admit=lambda _: False)


def test_old_paths_nontext_markdown_is_partial(repo):
    root, base = _approve_fixture(repo, clear_deny=True)
    (root / 'synthetic.md').write_bytes(b'\xffsynthetic')
    args = _args(root, base)
    snapshot = _inventory(args)
    plan = selected.plan_old_paths(snapshot)
    result = selected.run_worktree_old_paths(**args, inventory_sha256=snapshot['inventory_sha256'],
        plan_sha256=plan['plan_sha256'], admit=lambda _: True)
    assert result['state'] == 'partial'
    assert result['check_progress'] == 'not_started'
    assert result['source_body_attempts_may_have_read_bytes'] == result['source_bodies_validated'] + 1
    assert result['source_bodies_validated'] < len(plan['selection']['inputs'])
    assert result['body_validation'] == 'filesystem_metadata_and_supported_text_only'
    assert result['global_audit'] == 'not_performed'
