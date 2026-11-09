"""Synthetic multi-owner preflight and explicit semantic-boundary coverage."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml
from jsonschema import validate

from tests.test_action_transition import _write_action
from tests.test_context_flow import (
    folder_requirements_policy, folder_requirements_setup, git, repo,
)
from wiki_core.action_transition import _parse_document, transition_action_page
from wiki_core.context_integration import IntegrationError
from wiki_core.context_packet import build_packet
from wiki_core.coordination_context import CoordinationBinding


@pytest.fixture
def proposal(repo, request):
    """Three owners, three real paths and one coherent synthetic log rule."""
    folder_requirements_setup(repo)
    variant = getattr(request, 'param', None)
    if variant == 'deny_write':
        config_path = repo / 'wiki.config.yaml'
        config = yaml.safe_load(config_path.read_text())
        config['context_access']['finance/tax']['policy']['deny'] = {
            'write': ['finance/tax/interpretation.md']}
        config_path.write_text(yaml.safe_dump(config))
    if variant == 'query_change':
        from tests.test_context_dynamic_selection import page
        (repo / 'finance/costs/index.md').write_text(
            '---\npage_id: synthetic-collection\npage_type: source_catalog\n---\n# Collection\n')
        page(repo, 'first.md')
    (repo / '.gitignore').write_text('data/derived/\n')
    generated = _write_action(repo)
    action = repo / 'finance/tax/interpretation.md'
    action.write_text(generated.read_text())
    generated.unlink()
    (repo / 'synthetic-log.md').write_text('# Synthetic log\n\n- Baseline.\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'synthetic action and log baseline')
    git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    base = git(repo, 'rev-parse', 'HEAD')
    policy = folder_requirements_policy(repo)
    binding = CoordinationBinding(('.', 'finance/costs', 'finance/tax'),
                                  'refs/remotes/origin/main', 'wiki.config.yaml')
    paths = {'.': 'synthetic-log.md', 'finance/costs': 'finance/costs/result.md',
             'finance/tax': 'finance/tax/interpretation.md'}
    participants = []
    for index, (context, path) in enumerate(paths.items()):
        kwargs = {}
        if variant == 'query_change' and context == 'finance/costs':
            from tests.test_context_dynamic_selection import query
            kwargs['queries'] = [query()]
        packet = build_packet(repo, policy, context, base, [], 100000,
                              task_id=f'synthetic-{index}', goal='review synthetic work',
                              output=path, integrator='independent reviewer',
                              entry_folder=context, trusted_binding=binding, **kwargs)
        result = {'schema_version': 'wiki.task-result/v1', 'status': 'completed',
                  'task_id': packet['task_id'], 'context_id': context,
                  'packet_digest': packet['packet_digest'],
                  'changes': [{'path': path, 'action': 'modified'}],
                  'read_coverage': {'observed_refs': packet['declared_read_set'],
                                    'missing': packet['coverage']['missing']},
                  'blockers': []}
        if packet.get('query_selections'):
            result['read_coverage']['observed_queries'] = [q['query_id'] for q in packet['query_selections']]
        participants.append({'context_id': context, 'packet': packet, 'result': result})
    branch = 'wiki/synthetic-joint'
    git(repo, 'checkout', '-qb', branch)
    domain = repo / paths['finance/costs']
    domain.write_text('Synthetic domain revision two.\n')
    before = hashlib.sha256(action.read_bytes()).hexdigest()
    receipt = transition_action_page(repo, action, 'in_progress', expected_sha256=before,
                                     recorded_at='2026-10-27T01:00:00Z')
    log = repo / paths['.']
    log.write_text(log.read_text() + '\n- Domain: revision two; action: '
                   + receipt.receipt_id + '\n')
    if variant == 'query_change':
        from tests.test_context_dynamic_selection import page
        page(repo, 'first.md', amount=99)
        participants[1]['result']['changes'].append(
            {'path': 'finance/costs/items/first.md', 'action': 'modified'})
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'coherent multi-owner proposal')
    return {'root': repo, 'policy': policy, 'binding': binding, 'base': base,
            'head': git(repo, 'rev-parse', 'HEAD'), 'branch': branch,
            'participants': participants, 'paths': paths}


def run(proposal, **override):
    # Import at runtime so this test module can be collected while the
    # independently developed composite entry point is being integrated.
    from wiki_core.context_integration import preflight_composite
    args = {key: proposal[key] for key in ('base', 'head', 'branch', 'participants')}
    args['trusted_binding'] = proposal['binding']
    args.update(override)
    return preflight_composite(proposal['root'], proposal['policy'], **args)


def semantic_log_is_coherent(domain: str, action: str, log: str) -> bool:
    """Fixture-owned business rule, deliberately not a preflight assertion."""
    values, _ = _parse_document(action)
    history = values.get('action_state_history') or []
    return (domain == 'Synthetic domain revision two.\n'
            and values.get('action_state') == 'in_progress' and bool(history)
            and f"Domain: revision two; action: {history[-1]['receipt_id']}" in log)


def test_coherent_multi_owner_diff_is_only_a_review_candidate(proposal):
    result = run(proposal)
    schema_path = Path(__file__).resolve().parents[1] / 'docs/references/schemas/wiki-context-integration-composite-v1.schema.json'
    validate(result, json.loads(schema_path.read_text()))
    assert result['state'] == 'independent_review_required'
    assert result['review'] == result['gates'] == result['merge'] == 'not_performed'
    assert result['base'] == proposal['base'] and result['head'] == proposal['head']
    assert result['branch'] == proposal['branch'] and result['changes_count'] == 3
    assert {p['context_id'] for p in result['participants']} == set(proposal['paths'])
    assert len(result['diff_sha256']) == 64
    root, paths = proposal['root'], proposal['paths']
    assert semantic_log_is_coherent((root / paths['finance/costs']).read_text(),
                                    (root / paths['finance/tax']).read_text(),
                                    (root / paths['.']).read_text())
    # Splitting the domain edit from the other files breaks the test-owned
    # rule; preflight does not itself certify the rule or approve a split.
    assert not semantic_log_is_coherent((root / paths['finance/costs']).read_text(),
        git(root, 'show', proposal['base'] + ':' + paths['finance/tax']) + '\n',
        git(root, 'show', proposal['base'] + ':' + paths['.']) + '\n')
    # Separate single-owner checks must still inspect the complete diff.
    from wiki_core.context_integration import preflight
    for part in proposal['participants'][:2]:
        with pytest.raises(IntegrationError):
            preflight(root, proposal['policy'], context_id=part['context_id'],
                      base=proposal['base'], head=proposal['head'], branch=proposal['branch'],
                      packet=part['packet'], result=part['result'], trusted_binding=proposal['binding'])


@pytest.mark.parametrize('mutation', ['missing_owner', 'duplicate_owner', 'duplicate_path',
                                      'wrong_owner', 'wrong_status', 'packet_swap',
                                      'wrong_digest', 'missing_coverage'])
def test_composition_refuses_incomplete_conflicting_or_unbound_inputs(proposal, mutation):
    participants = copy.deepcopy(proposal['participants'])
    if mutation == 'missing_owner':
        participants.pop()
    elif mutation == 'duplicate_owner':
        participants.append(copy.deepcopy(participants[0]))
    elif mutation == 'duplicate_path':
        participants[0]['result']['changes'].append(copy.deepcopy(participants[0]['result']['changes'][0]))
    elif mutation == 'wrong_owner':
        participants[0]['result']['changes'][0]['path'] = proposal['paths']['finance/costs']
    elif mutation == 'wrong_status':
        participants[0]['result']['changes'][0]['action'] = 'created'
    elif mutation == 'packet_swap':
        participants[0]['packet'] = participants[1]['packet']
    elif mutation == 'wrong_digest':
        participants[0]['result']['packet_digest'] = '0' * 64
    elif mutation == 'missing_coverage':
        participants[0]['result']['read_coverage']['observed_refs'] = []
    with pytest.raises((IntegrationError, ValueError)):
        run(proposal, participants=participants)


def test_unbound_participant_and_moved_branch_or_base_fail_closed(proposal):
    restricted = CoordinationBinding(('.', 'finance/costs'),
                                     'refs/remotes/origin/main', 'wiki.config.yaml')
    with pytest.raises((IntegrationError, ValueError)):
        run(proposal, trusted_binding=restricted)
    with pytest.raises((IntegrationError, ValueError)):
        run(proposal, head=proposal['base'])
    git(proposal['root'], 'update-ref', 'refs/remotes/origin/main', proposal['head'])
    with pytest.raises((IntegrationError, ValueError)):
        run(proposal)


@pytest.mark.parametrize('proposal', ['deny_write'], indirect=True)
def test_owner_binding_does_not_replace_current_write_permission(proposal):
    assert not proposal['policy'].permits('finance/tax', 'write', proposal['paths']['finance/tax'])
    with pytest.raises((IntegrationError, ValueError)):
        run(proposal)


def test_binding_failures_and_participant_limit_precede_content_open(proposal, monkeypatch):
    from wiki_core.repository_reader import RepositoryReader
    monkeypatch.setattr(RepositoryReader, 'read', lambda *a, **kw: pytest.fail('opened context body'))
    monkeypatch.setattr(RepositoryReader, '_document', lambda *a, **kw: pytest.fail('opened context document'))
    restricted = CoordinationBinding(('.', 'finance/costs'),
                                     'refs/remotes/origin/main', 'wiki.config.yaml')
    for binding in (None, restricted):
        with pytest.raises((IntegrationError, ValueError)):
            run(proposal, trusted_binding=binding)
    with pytest.raises((IntegrationError, ValueError)):
        run(proposal, participants=[proposal['participants'][0]] * 65)


def test_policy_or_instruction_change_is_not_qualified(proposal):
    root = proposal['root']
    rule = root / 'AGENTS.md'
    rule.write_text(rule.read_text() + '\nSynthetic instruction mutation.\n')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'propose forbidden policy change')
    participants = copy.deepcopy(proposal['participants'])
    participants[0]['result']['changes'].append({'path': 'AGENTS.md', 'action': 'modified'})
    with pytest.raises((IntegrationError, ValueError)):
        run(proposal, head=git(root, 'rev-parse', 'HEAD'), participants=participants)


def test_ref_moving_between_participants_cannot_qualify(proposal, monkeypatch):
    import wiki_core.context_integration as module
    original = module._preflight
    calls = []
    def moving(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(True)
        if len(calls) == 1:
            git(proposal['root'], 'update-ref', 'refs/heads/' + proposal['branch'], proposal['base'])
        return result
    monkeypatch.setattr(module, '_preflight', moving)
    with pytest.raises((IntegrationError, ValueError)):
        run(proposal)
    assert calls == [True]


@pytest.mark.parametrize('proposal', ['query_change'], indirect=True)
def test_query_revalidation_sees_complete_proposed_tree(proposal, monkeypatch):
    import wiki_core.context_integration as module
    original = module.revalidate_packet_queries
    observed = []
    def recording(policy, packet, source, target, **kwargs):
        if packet['context_id'] == 'finance/costs':
            observed.append(target.revision)
        return original(policy, packet, source, target, **kwargs)
    monkeypatch.setattr(module, 'revalidate_packet_queries', recording)
    with pytest.raises((IntegrationError, ValueError)):
        run(proposal)
    assert proposal['head'] in observed


@pytest.mark.parametrize('kind', ['cycle', 'oversize', 'invalid_type'])
def test_unbounded_or_invalid_input_is_refused_before_copy_or_git(proposal, monkeypatch, kind):
    import wiki_core.context_integration as module
    bad = copy.deepcopy(proposal['participants'][:1])
    if kind == 'cycle':
        bad[0]['loop'] = bad
    elif kind == 'oversize':
        bad[0]['extra'] = 'x' * 1_500_000
    else:
        bad[0]['extra'] = object()
    monkeypatch.setattr(module, 'deepcopy', lambda *_: pytest.fail('copied invalid input'))
    monkeypatch.setattr(module, '_git', lambda *_: pytest.fail('used Git for invalid input'))
    with pytest.raises(IntegrationError, match='composite preflight unavailable'):
        run(proposal, participants=bad)


def test_rejection_does_not_disclose_untrusted_path(proposal):
    participants = copy.deepcopy(proposal['participants'])
    sentinel = 'synthetic-sensitive-name-not-for-output.md'
    participants[0]['result']['changes'][0]['path'] = sentinel
    with pytest.raises(IntegrationError) as error:
        run(proposal, participants=participants)
    assert sentinel not in str(error.value)


def test_composite_cli_requires_bound_host_and_strict_bounded_json(proposal, tmp_path):
    kit = Path(__file__).resolve().parents[1]
    selection = tmp_path / 'participants.json'
    selection.write_text(json.dumps(proposal['participants']))
    cmd = [sys.executable, str(kit / 'scripts/wiki_context_flow.py'), '--repo', str(proposal['root']),
           '--approved-revision', proposal['base'], 'preflight-composite', '--base', proposal['base'],
           '--head', proposal['head'], '--branch', proposal['branch'], '--participants', str(selection)]
    env = {key: value for key, value in os.environ.items() if not key.startswith('WIKI_COORDINATION_')}
    env.update(WIKI_COORDINATION_ALLOWED_CONTEXTS='.,finance/costs,finance/tax',
               WIKI_COORDINATION_CONTEXT_MODE='folder',
               WIKI_COORDINATION_TRUSTED_REF='refs/remotes/origin/main')
    result = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['state'] == 'independent_review_required'

    no_binding = {key: value for key, value in env.items() if not key.startswith('WIKI_COORDINATION_')}
    missing_input = cmd[:-1] + [str(tmp_path / 'never-read.json')]
    result = subprocess.run(missing_input, env=no_binding, capture_output=True, text=True, check=False)
    assert result.returncode != 0 and 'host binding required' in result.stderr
    assert 'never-read.json' not in result.stderr

    selection.write_text('[{"context_id":"first","context_id":"second"}]')
    duplicate = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
    assert duplicate.returncode != 0 and 'participant input unavailable' in duplicate.stderr
    selection.write_bytes(b' ' * 8_000_001)
    oversized = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
    assert oversized.returncode != 0 and 'participant input unavailable' in oversized.stderr
    selection.write_text(json.dumps(proposal['participants']))
    link = tmp_path / 'participants-symlink.json'
    link.symlink_to(selection)
    for unsafe in (link, tmp_path):
        refused = subprocess.run(cmd[:-1] + [str(unsafe)], env=env, capture_output=True, text=True, check=False)
        assert refused.returncode != 0 and 'participant input unavailable' in refused.stderr
    legacy = dict(env, WIKI_COORDINATION_CONTEXT_MODE='v1',
                  WIKI_COORDINATION_ALLOWED_CONTEXTS='costs,tax')
    refused = subprocess.run(cmd, env=legacy, capture_output=True, text=True, check=False)
    assert refused.returncode != 0 and 'folder coordination host binding required' in refused.stderr
    wrong_ref = dict(env, WIKI_COORDINATION_TRUSTED_REF='refs/heads/' + proposal['branch'])
    divergent = subprocess.run(cmd, env=wrong_ref, capture_output=True, text=True, check=False)
    assert divergent.returncode != 0


@pytest.mark.parametrize('kind', ['symlink', 'gitlink', 'restricted', 'regular'])
@pytest.mark.parametrize('operation', ['delete', 'modify'])
def test_old_and_new_git_modes_are_checked_in_single_and_composite_preflight(repo, kind, operation, monkeypatch):
    """A deleted unsupported Git entry must not evade proposed-tree checks."""
    from wiki_core.context_integration import preflight, preflight_composite

    folder_requirements_setup(repo)
    path = ('finance/tax/synthetic-submodule' if kind == 'gitlink' else
            'finance/tax/.env.synthetic' if kind == 'restricted' else 'finance/tax/synthetic-entry.md')
    target = repo / path
    original = (repo / 'finance/tax/interpretation.md').read_bytes()
    if kind == 'symlink':
        target.symlink_to('interpretation.md')
    elif kind in ('regular', 'restricted'):
        target.write_text('Synthetic regular source.\n')
    git(repo, 'add', '.')
    if kind == 'restricted':
        git(repo, 'add', '-f', path)
    if kind == 'gitlink':
        git(repo, 'update-index', '--add', '--cacheinfo',
            f'160000,{git(repo, "rev-parse", "HEAD")},{path}')
    git(repo, 'commit', '-qm', 'synthetic baseline entry')
    git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    base = git(repo, 'rev-parse', 'HEAD')
    policy = folder_requirements_policy(repo)
    binding = CoordinationBinding(('finance/costs', 'finance/tax'),
                                  'refs/remotes/origin/main', 'wiki.config.yaml')
    output_paths = {'finance/tax': path, 'finance/costs': 'finance/costs/result.md'}
    packets = {context: build_packet(repo, policy, context, base, [], 100000,
               task_id='modes-' + str(index), goal='synthetic mode validation', output=ref,
               integrator='independent reviewer', entry_folder=context, trusted_binding=binding)
               for index, (context, ref) in enumerate(output_paths.items())}
    if kind == 'restricted':
        from wiki_core.repository_reader import RepositoryReader
        original_read = RepositoryReader.read
        def no_restricted_read(reader, ref, *args, **kwargs):
            assert ref != path, 'restricted content was opened'
            return original_read(reader, ref, *args, **kwargs)
        monkeypatch.setattr(RepositoryReader, 'read', no_restricted_read)

    def mutate():
        if operation == 'delete':
            if kind == 'gitlink':
                git(repo, 'update-index', '--force-remove', path)
            else:
                target.unlink()
        elif kind == 'gitlink':
            git(repo, 'update-index', '--cacheinfo', f'160000,{base},{path}')
        elif kind == 'symlink':
            target.unlink()
            target.symlink_to('source.md')
        else:
            target.write_text('Synthetic regular changed.\n')

    def part(context, change):
        packet = packets[context]
        return {'context_id': context, 'packet': packet,
                'result': {'schema_version': 'wiki.task-result/v1', 'status': 'completed',
                           'task_id': packet['task_id'], 'context_id': context,
                           'packet_digest': packet['packet_digest'], 'changes': [change],
                           'read_coverage': {'observed_refs': packet['declared_read_set'],
                                             'missing': packet['coverage']['missing']}, 'blockers': []}}

    change = {'path': path, 'action': 'deleted' if operation == 'delete' else 'modified'}
    git(repo, 'checkout', '-qb', 'wiki/synthetic-single-mode')
    mutate()
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'single-owner mode change')
    single = part('finance/tax', change)
    args = dict(context_id='finance/tax', base=base, head=git(repo, 'rev-parse', 'HEAD'),
                branch='wiki/synthetic-single-mode', packet=single['packet'], result=single['result'],
                trusted_binding=binding)
    if kind == 'regular':
        assert preflight(repo, policy, **args)['state'] == 'independent_review_required'
    else:
        with pytest.raises(IntegrationError):
            preflight(repo, policy, **args)

    git(repo, 'checkout', '-qb', 'wiki/synthetic-composite-mode', base)
    mutate()
    (repo / output_paths['finance/costs']).write_text('Updated synthetic domain.\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'composite mode change')
    parts = [part('finance/tax', change), part('finance/costs',
             {'path': output_paths['finance/costs'], 'action': 'modified'})]
    args = dict(base=base, head=git(repo, 'rev-parse', 'HEAD'), branch='wiki/synthetic-composite-mode',
                participants=parts, trusted_binding=binding)
    if kind == 'regular':
        assert preflight_composite(repo, policy, **args)['state'] == 'independent_review_required'
        omitted = copy.deepcopy(parts)
        omitted[0]['result']['changes'] = []
        with pytest.raises(IntegrationError):
            preflight_composite(repo, policy, **{**args, 'participants': omitted})
    else:
        with pytest.raises(IntegrationError):
            preflight_composite(repo, policy, **args)
    assert (repo / 'finance/tax/interpretation.md').read_bytes() == original
