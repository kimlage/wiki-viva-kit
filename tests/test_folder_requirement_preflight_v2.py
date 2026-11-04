"""Narrow current declarations checked against reported v2 inputs."""
from copy import deepcopy

import pytest

from tests.test_folder_policy_v2 import project, put, git, commit, proposal_v2
from wiki_core.folder_integration_v2 import FolderIntegrationError, preflight_folder_v2
from wiki_core.folder_packet_v2 import build_folder_packet_v2
from wiki_core.folder_policy_v2 import load_folder_policy_v2


def report_content(revision, *, source='a/source.md', field='field:amount', temporal='current',
                   classification='synthetic', use='interpret', pinned=True, suffix=''):
    pin = f'    consumed_revision: "{revision}"\n' if pinned else ''
    return ('---\npage_type: claim\ninformation_requirements:\n  - target: ' + source
            + f'\n    fields: ["{field}"]\n    temporal: {temporal}\n    max_age_days: 30\n'
            + f'    classification: {classification}\n    use: {use}\n' + pin + suffix
            + '---\nSynthetic interpretation\n')


def created_preflight(project, body):
    policy, base, _, packet, result = proposal_v2(project)
    put(project, 'a/report.md', body(base))
    git(project, 'add', '-A'); git(project, 'commit', '-qm', 'declared source')
    return preflight_folder_v2(project, policy, base=base, head=git(project, 'rev-parse', 'HEAD'),
                               branch='wiki/folder-task', packet=packet, result=result)


def test_new_claim_with_current_pinned_reported_source_is_review_candidate(project):
    out = created_preflight(project, lambda base: report_content(base))
    assert out['state'] == 'independent_review_required'
    assert out['requirements_handling'] == {
        'coverage': 'explicit_current_reported_selections_only', 'count': 1,
        'freshness': 'not_assessed', 'legacy_receipt_migration': 'not_performed'}
    assert out['read_coverage'] == 'reported_not_independently_verified'
    assert out['merge'] == 'not_performed'


def test_new_requirement_defaults_match_existing_contract(project):
    policy, base, _, _, _ = proposal_v2(project)
    packet = build_folder_packet_v2(project, policy, 'a', 20000, index_path='a/index.md',
             content_revision=base, task_id='defaults', goal='review', output='a/report.md',
             integrator='independent', evidence=[{'path': 'a/source.md', 'producer_folder': 'a',
             'reason': 'source', 'use': 'interpret', 'classification': 'internal', 'field': 'amount'}])
    result = {'schema_version': 'wiki.folder-task-result/v2', 'status': 'completed',
              'task_id': packet['task_id'], 'context_id': packet['context_id'], 'packet_digest': packet['packet_digest'],
              'observed': [{'path': r['path'], 'kind': r['kind'], 'revision': r['revision'], 'sha256': r['sha256'],
                            'section': r.get('section'), 'field': r.get('field')} for r in packet['inputs']],
              'changes': [{'path': 'a/report.md', 'action': 'created'}]}
    content = report_content(base).replace('    classification: synthetic\n', '').replace('    use: interpret\n', '')
    put(project, 'a/report.md', content)
    git(project, 'add', '-A'); git(project, 'commit', '-qm', 'default requirement')
    out = preflight_folder_v2(project, policy, base=base, head=git(project, 'rev-parse', 'HEAD'),
                               branch='wiki/folder-task', packet=packet, result=result)
    assert out['requirements_handling']['count'] == 1


@pytest.mark.parametrize('variant', ['unpinned', 'old_pin', 'wrong_field', 'wrong_source',
                                     'wrong_classification', 'wrong_use', 'historical', 'legacy_field',
                                     'query', 'uncovered_second_field'])
def test_new_claim_rejects_unmatched_or_unqualified_declarations(project, variant):
    def body(base):
        kwargs = {
            'unpinned': {'pinned': False}, 'old_pin': {'revision': '0' * 40},
            'wrong_field': {'field': 'field:other'}, 'wrong_source': {'source': 'a/index.md'},
            'wrong_classification': {'classification': 'internal'}, 'wrong_use': {'use': 'summarize'},
            'historical': {'temporal': 'historical'}, 'legacy_field': {'field': 'amount'},
            'query': {'suffix': '    query: unsupported\n'},
            'uncovered_second_field': {'field': 'field:amount", "field:other'},
        }[variant]
        return report_content(**({'revision': base} | kwargs))
    with pytest.raises(FolderIntegrationError, match='requirement migration'):
        created_preflight(project, body)


@pytest.mark.parametrize('invalid_value', ['null', 'false', '0'])
def test_new_claim_rejects_malformed_empty_requirement_values(project, invalid_value):
    with pytest.raises(FolderIntegrationError, match='requirement migration'):
        created_preflight(project, lambda _base: '---\npage_type: claim\ninformation_requirements: '
                          + invalid_value + '\n---\nSynthetic\n')


def setup_existing(project):
    put(project, 'a/source.md', '---\namount: 5\n---\nSynthetic source\n')
    put(project, 'a/report.md', report_content('', pinned=False)); commit(project)
    base = git(project, 'rev-parse', 'HEAD'); policy = load_folder_policy_v2(project, base)
    evidence = [
        {'path': 'a/source.md', 'producer_folder': 'a', 'reason': 'source', 'use': 'interpret',
         'classification': 'synthetic', 'field': 'amount'},
        {'path': 'a/report.md', 'producer_folder': 'a', 'reason': 'prior output', 'use': 'interpret',
         'classification': 'synthetic'},
    ]
    packet = build_folder_packet_v2(project, policy, 'a', 30000, content_revision=base,
             index_path='a/index.md', task_id='existing', goal='review', output='a/report.md',
             integrator='independent', evidence=evidence)
    git(project, 'checkout', '-qb', 'wiki/preserve-requirements')
    result = {'schema_version': 'wiki.folder-task-result/v2', 'status': 'completed',
              'task_id': packet['task_id'], 'context_id': packet['context_id'], 'packet_digest': packet['packet_digest'],
              'observed': [{'path': r['path'], 'kind': r['kind'], 'revision': r['revision'], 'sha256': r['sha256'],
                            'section': r.get('section'), 'field': r.get('field')} for r in packet['inputs']],
              'changes': [{'path': 'a/report.md', 'action': 'modified'}]}
    return policy, base, packet, result


def existing_preflight(project, *, mutate=False, remove_source_report=False):
    policy, base, packet, result = setup_existing(project)
    content = report_content('', pinned=False).replace('Synthetic interpretation', 'Revised interpretation')
    if mutate:
        content = content.replace('max_age_days: 30', 'max_age_days: 60')
    put(project, 'a/report.md', content)
    git(project, 'add', '-A'); git(project, 'commit', '-qm', 'update claim')
    if remove_source_report:
        result = deepcopy(result)
        result['observed'] = [row for row in result['observed'] if row['path'] != 'a/source.md']
    return preflight_folder_v2(project, policy, base=base, head=git(project, 'rev-parse', 'HEAD'),
                               branch='wiki/preserve-requirements', packet=packet, result=result)


def test_existing_claim_preserves_declaration_and_requires_current_evidence(project):
    out = existing_preflight(project)
    assert out['requirements_handling']['count'] == 1
    assert out['requirements_handling']['freshness'] == 'not_assessed'


def test_existing_claim_rejects_changed_declaration(project):
    with pytest.raises(FolderIntegrationError, match='requirement migration'):
        existing_preflight(project, mutate=True)


def test_existing_claim_rejects_incomplete_report(project):
    with pytest.raises(FolderIntegrationError, match='exact reported read'):
        existing_preflight(project, remove_source_report=True)
