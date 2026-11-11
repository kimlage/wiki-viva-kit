"""Synthetic host binding for integrator reads, never actor authentication."""
from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from tests.test_context_flow import folder_requirements_setup, git, repo
from tests.test_context_multi_owner_preflight import proposal
from wiki_core import audit_r1_inventory as r1
from wiki_core.context_integration import IntegrationError, preflight
from wiki_core.context_policy import PolicyError, load_policy
from wiki_core.coordination_context import CoordinationBinding, ProtectedCoordinationError, prepare_packet


@pytest.fixture
def bound_integrator(repo, request):
    folder_requirements_setup(repo)
    config_path = repo / 'wiki.config.yaml'
    config = yaml.safe_load(config_path.read_text())
    for context in ('.', 'finance/tax'):
        config['context_access'][context]['policy'] = copy.deepcopy(config['context_access'][context]['policy'])
    # A synthetic old context-isolation deny and a distinct protected deny.
    variant = getattr(request, 'param', None)
    if variant == 'history':
        config.setdefault('paths', {})['memory_root'] = 'finance'
    root_deny = 'self' if variant in ('root_deny', 'bootstrap_deny') else 'self/finance/tax'
    root_denies = [root_deny]
    if variant == 'bootstrap_deny':
        root_denies.append('self/AGENTS.md')
    root_deny_policy = {'read': root_denies}
    if variant == 'capability_deny':
        root_deny_policy['capabilities'] = ['audit.integrator_read']
    config['context_access']['.']['policy']['deny'] = root_deny_policy
    tax_denies = ['self/private.md']
    if variant == 'overlap':
        tax_denies.append('self')
    config['context_access']['finance/tax']['policy']['deny'] = {'read': tax_denies}
    config_path.write_text(yaml.safe_dump(config))
    if variant != 'history':
        (repo / 'finance/tax/private.md').write_text('Synthetic confidential body.\n')
    if variant == 'ignore':
        (repo / 'finance/tax/.gitignore').write_text('synthetic-cache/\n')
    (repo / 'finance/tax/credentials').mkdir()
    (repo / 'finance/tax/credentials/synthetic.txt').write_text('Synthetic protected path.\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'synthetic approved read boundaries')
    git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    base = git(repo, 'rev-parse', 'HEAD')
    policy = load_policy(repo, base, 'wiki.config.yaml')
    contexts = tuple(sorted(policy.contexts))
    git(repo, 'checkout', '-qb', 'wiki/synthetic-integrator')
    binding = CoordinationBinding(contexts, 'refs/remotes/origin/main', 'wiki.config.yaml',
        integrator_read_context='.', integrator_policy_revision=base,
        context_isolation_denies=(('.', '.' if variant in ('root_deny', 'bootstrap_deny') else 'finance/tax'),))
    return repo, base, binding, contexts


def snapshot(case, binding=None, context='.'):
    root, base, default, _contexts = case
    return r1.inventory(root, binding or default, context_id=context,
        approved_revision=base, base=base, head=base, branch='wiki/synthetic-integrator',
        normative_paths=['wiki.config.yaml'])


def test_host_bound_integrator_selects_all_contexts_without_exposing_secrets(bound_integrator):
    root, base, binding, contexts = bound_integrator
    inventory = snapshot(bound_integrator)
    authorization = {row['path']: row['current_policy'] for row in inventory['authorization']}
    for path in ('index.md', 'finance/costs/result.md', 'finance/tax/source.md'):
        assert authorization[path] == 'permitted'
    assert authorization['finance/tax/private.md'] == 'denied'
    assert authorization['finance/tax/credentials/synthetic.txt'] == 'denied'
    assert inventory['integrator_read']['principal_identity'] == 'external_not_verified'
    assert inventory['integrator_read']['classification_authority'] == 'external_not_verified'
    assert inventory['integrator_read']['write_authority'] == 'not_granted'

    requested = [{'kind': 'worktree', 'path': path} for path in sorted(inventory['physical']['files'])
                 if authorization[path] == 'permitted']
    selection = r1.select(inventory, requested)
    assert selection['integrator_read']['context_isolation_denies'] == [['.', 'finance/tax']]
    assert selection['integrator_read']['principal_identity'] == 'external_not_verified'
    policy = load_policy(root, base, 'wiki.config.yaml')
    assert {policy.owner_of(item['path']) for item in selection['inputs']} == set(contexts)
    # A fake host decision demonstrates the in-process call, not a credential.
    output = r1.scan_selected(root, binding, context_id='.', approved_revision=base,
        base=base, head=base, branch='wiki/synthetic-integrator', requested=requested,
        inventory_sha256=inventory['inventory_sha256'], selection_sha256=selection['selection_sha256'],
        normative_paths=['wiki.config.yaml'], admit=lambda _selection: True)
    assert output['state'] == 'completed' and output['scanned_count'] == len(requested)
    assert output['host_admission'] == 'not_verified' and output['global_audit'] == 'not_performed'
    assert output['reader_mode'] == 'host_integrator' and output['principal_identity'] == 'external_not_verified'
    assert output['gate_coverage'] == 'not_verified'


def test_executor_binding_and_environment_do_not_inherit_integrator_read(bound_integrator, monkeypatch):
    _root, base, _binding, contexts = bound_integrator
    executor = CoordinationBinding(contexts, 'refs/remotes/origin/main', 'wiki.config.yaml')
    result = snapshot(bound_integrator, executor)
    rows = {row['path']: row['current_policy'] for row in result['authorization']}
    assert rows['finance/costs/result.md'] == rows['finance/tax/source.md'] == 'denied'
    own_selection = r1.select(result, [{'kind': 'worktree', 'path': 'index.md'}])
    assert 'integrator_read' not in own_selection
    monkeypatch.setattr(r1, '_worktree_bytes', lambda *_: pytest.fail('denied body read'))
    with pytest.raises(PolicyError, match='selection unavailable'):
        r1.select(result, [{'kind': 'worktree', 'path': 'finance/costs/result.md'}])
    env = {'WIKI_COORDINATION_ALLOWED_CONTEXTS': ','.join(contexts),
           'WIKI_COORDINATION_TRUSTED_REF': 'refs/remotes/origin/main',
           'WIKI_COORDINATION_INTEGRATOR_CONTEXT': '.'}
    assert CoordinationBinding.from_environment(env).integrator_read_context is None


def test_untrusted_packet_cannot_choose_integrator_binding(bound_integrator, monkeypatch):
    root, base, _binding, contexts = bound_integrator
    executor = CoordinationBinding(contexts, 'refs/remotes/origin/main', 'wiki.config.yaml')
    monkeypatch.setattr('wiki_core.coordination_context._policy',
                        lambda *_: pytest.fail('policy read before invalid payload refusal'))
    payload = {'context_id': '.', 'approved_revision': base, 'content_revision': base,
               'entry_folder': '.', 'task': {}, 'integrator_read_context': '.'}
    with pytest.raises(ProtectedCoordinationError, match='coordination_invalid_request'):
        prepare_packet(root, executor, payload)


def test_integrator_binding_refuses_unclassified_deny_and_protected_path(bound_integrator, monkeypatch):
    inventory = snapshot(bound_integrator)
    monkeypatch.setattr(r1, '_worktree_bytes', lambda *_: pytest.fail('denied body read'))
    for path in ('finance/tax/private.md', 'finance/tax/credentials/synthetic.txt'):
        with pytest.raises(PolicyError, match='selection unavailable'):
            r1.select(inventory, [{'kind': 'worktree', 'path': path}])


@pytest.mark.parametrize('bound_integrator', ['overlap'], indirect=True)
def test_identical_deny_scope_from_another_owner_is_not_implicitly_classified(bound_integrator, monkeypatch):
    inventory = snapshot(bound_integrator)
    monkeypatch.setattr(r1, '_worktree_bytes', lambda *_: pytest.fail('unclassified body read'))
    with pytest.raises(PolicyError, match='selection unavailable'):
        r1.select(inventory, [{'kind': 'worktree', 'path': 'finance/tax/source.md'}])


def test_unclassified_context_deny_is_not_overridden(bound_integrator, monkeypatch):
    _root, _base, binding, _contexts = bound_integrator
    inventory = snapshot(bound_integrator, replace(binding, context_isolation_denies=()))
    monkeypatch.setattr(r1, '_worktree_bytes', lambda *_: pytest.fail('unclassified body read'))
    with pytest.raises(PolicyError, match='selection unavailable'):
        r1.select(inventory, [{'kind': 'worktree', 'path': 'finance/tax/source.md'}])


@pytest.mark.parametrize('bound_integrator', ['ignore'], indirect=True)
def test_classified_integrator_can_qualify_foreign_ignore_bootstrap(bound_integrator):
    inventory = snapshot(bound_integrator)
    rows = {row['path']: row['current_policy'] for row in inventory['authorization']}
    assert rows['finance/tax/.gitignore'] == 'permitted'
    assert inventory['bootstrap_authority'] == 'external_not_verified'


def test_integrator_context_need_not_be_root(bound_integrator):
    root, base, binding, _contexts = bound_integrator
    child_binding = replace(binding, integrator_read_context='finance/costs')
    inventory = snapshot(bound_integrator, child_binding, context='finance/costs')
    rows = {row['path']: row['current_policy'] for row in inventory['authorization']}
    assert rows['finance/tax/source.md'] == 'permitted'
    policy = load_policy(root, base, 'wiki.config.yaml')
    assert not policy._permits_unqualified('finance/costs', 'read', 'finance/tax/interpretation.md')
    assert rows['finance/tax/interpretation.md'] == 'permitted'
    assert rows['finance/tax/private.md'] == 'denied'
    assert rows['finance/tax/credentials/synthetic.txt'] == 'denied'
    assert inventory['integrator_read']['principal_identity'] == 'external_not_verified'


@pytest.mark.parametrize('bound_integrator', ['root_deny'], indirect=True)
def test_classified_root_isolation_can_qualify_bootstrap_but_not_specific_deny(bound_integrator, monkeypatch):
    inventory = snapshot(bound_integrator)
    rows = {row['path']: row['current_policy'] for row in inventory['authorization']}
    assert rows['finance/tax/source.md'] == 'permitted'
    assert rows['finance/tax/private.md'] == 'denied'
    assert rows['finance/tax/credentials/synthetic.txt'] == 'denied'
    monkeypatch.setattr(r1, '_worktree_bytes', lambda *_: pytest.fail('specific denied body read'))
    with pytest.raises(PolicyError, match='selection unavailable'):
        r1.select(inventory, [{'kind': 'worktree', 'path': 'finance/tax/private.md'}])


@pytest.mark.parametrize('bound_integrator', ['bootstrap_deny'], indirect=True)
def test_specific_bootstrap_deny_refuses_before_instruction_body(bound_integrator, monkeypatch):
    from wiki_core.repository_reader import RepositoryReader

    original = RepositoryReader._document
    def guard(reader, path, *args, **kwargs):
        if path == 'AGENTS.md':
            pytest.fail('specifically denied bootstrap body opened')
        return original(reader, path, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, '_document', guard)
    with pytest.raises(PolicyError, match='context body not authorized'):
        snapshot(bound_integrator)


def test_integrator_binding_refuses_stale_or_unclassified_authority(bound_integrator, monkeypatch):
    _root, _base, binding, _contexts = bound_integrator
    monkeypatch.setattr(r1, '_worktree_bytes', lambda *_: pytest.fail('body read before refusal'))
    with pytest.raises(PolicyError, match='binding unavailable'):
        snapshot(bound_integrator, replace(binding, integrator_policy_revision='0' * 40))
    with pytest.raises(PolicyError, match='classification unavailable'):
        snapshot(bound_integrator, replace(binding,
            context_isolation_denies=(('.', 'finance/tax/private.md'),)))
    with pytest.raises(PolicyError, match='binding unavailable'):
        snapshot(bound_integrator, replace(binding, contexts=('.', 'finance/costs')))


@pytest.mark.parametrize('bound_integrator', ['capability_deny'], indirect=True)
def test_integrator_binding_preserves_specific_capability_deny(bound_integrator, monkeypatch):
    monkeypatch.setattr(r1, '_worktree_bytes', lambda *_: pytest.fail('body read despite capability deny'))
    with pytest.raises(PolicyError, match='binding unavailable'):
        snapshot(bound_integrator)


def test_integrator_read_binding_does_not_grant_cross_owner_write(proposal):
    binding = replace(proposal['binding'], integrator_read_context='.',
                      integrator_policy_revision=proposal['base'])
    root_part = next(part for part in proposal['participants'] if part['context_id'] == '.')
    with pytest.raises(IntegrationError, match='write outside context'):
        preflight(proposal['root'], proposal['policy'], context_id='.', base=proposal['base'],
                  head=proposal['head'], branch=proposal['branch'], packet=root_part['packet'],
                  result=root_part['result'], trusted_binding=binding)


@pytest.mark.parametrize('bound_integrator', ['history'], indirect=True)
def test_integrator_binding_reaches_existing_history_route_only_after_host_admission(bound_integrator, monkeypatch):
    import scripts.wiki_audit as audit

    root, base, binding, _contexts = bound_integrator
    monkeypatch.setattr(audit, 'ROOT', root)
    params = {'context_id': '.', 'approved_revision': base, 'base': base, 'head': base,
              'branch': 'wiki/synthetic-integrator', 'normative_paths': ['wiki.config.yaml'],
              'check': 'source_lifecycle_transitions', 'trusted_binding': binding}
    proposed = audit.audit_context_bound_history(**params, plan_only=True)
    assert proposed['state'] == 'selection_only' and proposed['global_audit'] == 'not_performed'
    assert proposed['plan']['selection']['integrator_read']['principal_identity'] == 'external_not_verified'
    names = {row['path'] for row in proposed['plan']['selection']['inputs']}
    assert 'finance/costs/result.md' in names and 'finance/tax/source.md' in names
    execution = {'inventory_sha256': proposed['inventory_sha256'],
                 'plan_sha256': proposed['plan']['plan_sha256']}
    original = audit._grep_selected_history
    calls = []
    def observe(*args):
        calls.append(True)
        return original(*args)
    monkeypatch.setattr(audit, '_grep_selected_history', observe)
    with pytest.raises(ValueError, match='host admission unavailable'):
        audit.audit_context_bound_history(**params, **execution)
    with pytest.raises(PolicyError, match='admission unavailable'):
        audit.audit_context_bound_history(**params, **execution, host_admit=lambda _plan: False)
    assert not calls
    admissions = []
    def synthetic_host(plan):
        admissions.append(plan['plan_sha256'])
        return True
    result = audit.audit_context_bound_history(**params, **execution, host_admit=synthetic_host)
    assert calls and admissions and result['search'] == 'completed' and result['state'] == 'partial'
    assert result['gate_state'] == 'blocked_incomplete_coverage' and result['global_audit'] == 'not_performed'
