"""Synthetic selected command-reference check, not integral audit evidence."""
import pytest
import yaml

from tests.test_audit_r1_inventory import git, repo
from tests.test_audit_secrets_selection_worktree import _approve_fixture, _args, _inventory
from tests.test_wiki_audit import _load_wiki_audit
from wiki_core import audit_worktree_selection as selected
from wiki_core.config import config_from_mapping
from wiki_core.context_policy import PolicyError


def _setup(repo, *, reference='docs/commands.md', deny=False, ignored=False):
    root, _, _, _ = repo
    config_path = root / 'wiki.config.yaml'
    config = yaml.safe_load(config_path.read_text())
    config['paths'] = {'command_reference_page': reference}
    config_path.write_text(yaml.safe_dump(config))
    if ignored:
        with (root / '.gitignore').open('a') as stream:
            stream.write(reference + '\n')
    target = root / reference
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('Reference: wiki_example.py\n')
    (root / 'wiki_example.py').write_text('# synthetic command\n')
    root, base = _approve_fixture(repo, clear_deny=not deny)
    return root, base, config_from_mapping(yaml.safe_load((root / 'wiki.config.yaml').read_text()))


@pytest.mark.parametrize('ignored', [False, True])
def test_command_reference_executes_selected_check_and_includes_ignored_reference(repo, monkeypatch, ignored):
    root, base, config = _setup(repo, ignored=ignored)
    args = _args(root, base)
    snapshot = _inventory(args)
    plan = selected.plan_command_reference(snapshot, config)
    assert plan['ignored_reference_selected'] is ignored
    assert plan['reference'] in {item['path'] for item in plan['selection']['inputs']}
    result = selected.run_worktree_command_reference(**args, inventory_sha256=snapshot['inventory_sha256'],
        plan_sha256=plan['plan_sha256'], admit=lambda _: True)
    assert result['state'] == 'completed'
    audit = _load_wiki_audit()
    monkeypatch.setattr(audit, 'ROOT', root)
    audit._audit_git_inventory.cache_clear()
    audit.tracked_files.cache_clear()
    expected = []
    audit.audit_command_reference(expected, config)
    assert result['diagnostics'] == expected
    assert result['global_audit'] == 'not_performed'
    assert result['gate_state'] == 'blocked_incomplete_coverage'


def test_denied_reference_refuses_before_body(repo, monkeypatch):
    root, base, config = _setup(repo, reference='restricted/commands.md', deny=True)
    snapshot = _inventory(_args(root, base))
    monkeypatch.setattr(selected, '_worktree_bytes', lambda *_: pytest.fail('body opened'))
    with pytest.raises(PolicyError, match='selection unavailable'):
        selected.plan_command_reference(snapshot, config)


def test_missing_reference_refuses_before_body(repo, monkeypatch):
    root, base, config = _setup(repo)
    (root / 'docs/commands.md').unlink()
    snapshot = _inventory(_args(root, base))
    monkeypatch.setattr(selected, '_worktree_bytes', lambda *_: pytest.fail('body opened'))
    with pytest.raises(PolicyError, match='command reference selection unavailable'):
        selected.plan_command_reference(snapshot, config)


def test_reference_host_refusal_and_wrong_plan_precede_body(repo, monkeypatch):
    root, base, config = _setup(repo)
    args = _args(root, base)
    snapshot = _inventory(args)
    plan = selected.plan_command_reference(snapshot, config)
    monkeypatch.setattr(selected, '_worktree_bytes', lambda *_: pytest.fail('body opened'))
    with pytest.raises(PolicyError, match='host admission unavailable'):
        selected.run_worktree_command_reference(**args, inventory_sha256=snapshot['inventory_sha256'],
            plan_sha256=plan['plan_sha256'], admit=lambda _: False)
    with pytest.raises(PolicyError, match='selection changed'):
        selected.run_worktree_command_reference(**args, inventory_sha256=snapshot['inventory_sha256'],
            plan_sha256='0' * 64, admit=lambda _: True)


def test_reference_known_denied_alias_refuses_before_body(repo, monkeypatch):
    root, base, config = _setup(repo, deny=True)
    (root / 'docs/commands.md').write_bytes((root / 'restricted/denied.json').read_bytes())
    git(root, 'add', 'docs/commands.md')
    snapshot = _inventory(_args(root, base))
    assert any(row['path'] == 'docs/commands.md' and row['oid'] in snapshot['denied_oid_aliases']
               for row in snapshot['index'])
    monkeypatch.setattr(selected, '_worktree_bytes', lambda *_: pytest.fail('body opened'))
    with pytest.raises(PolicyError, match='command reference selection unavailable'):
        selected.plan_command_reference(snapshot, config)


def test_candidate_config_does_not_authorize_reference(repo):
    root, base, config = _setup(repo)
    (root / 'wiki.config.yaml').write_text((root / 'wiki.config.yaml').read_text() + '\n# candidate\n')
    args = _args(root, base)
    snapshot = _inventory(args)
    plan = selected.plan_command_reference(snapshot, config)
    result = selected.run_worktree_command_reference(**args, inventory_sha256=snapshot['inventory_sha256'],
        plan_sha256=plan['plan_sha256'], admit=lambda _: True)
    assert result['state'] == 'partial' and result['check_progress'] == 'not_started'
    assert result['global_audit'] == 'not_performed'
