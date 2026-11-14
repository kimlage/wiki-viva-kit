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


@pytest.mark.parametrize('duplicate', ['root', 'nested'])
def test_new_claim_rejects_ambiguous_duplicate_yaml_keys(project, duplicate):
    def body(base):
        content = report_content(base)
        if duplicate == 'root':
            return content.replace('information_requirements:', 'information_requirements: []\ninformation_requirements:', 1)
        return content.replace('    max_age_days: 30', '    max_age_days: 60\n    max_age_days: 30', 1)
    with pytest.raises(FolderIntegrationError, match='requirement migration'):
        created_preflight(project, body)


def setup_existing(project, *, prior_age='30', duplicate_prior=False):
    put(project, 'a/source.md', '---\namount: 5\n---\nSynthetic source\n')
    prior = report_content('', pinned=False).replace('max_age_days: 30', f'max_age_days: {prior_age}')
    if duplicate_prior:
        prior = prior.replace('information_requirements:', 'information_requirements: []\ninformation_requirements:', 1)
    put(project, 'a/report.md', prior); commit(project)
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


def existing_preflight(project, *, mutate=False, remove_source_report=False, prior_age='30', proposed_age='30', duplicate_prior=False):
    policy, base, packet, result = setup_existing(project, prior_age=prior_age, duplicate_prior=duplicate_prior)
    content = (report_content('', pinned=False).replace('Synthetic interpretation', 'Revised interpretation')
               .replace('max_age_days: 30', f'max_age_days: {proposed_age}'))
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


def test_existing_claim_rejects_ambiguous_prior_yaml(project):
    with pytest.raises(FolderIntegrationError, match='requirement migration'):
        existing_preflight(project, duplicate_prior=True)


@pytest.mark.parametrize(('prior_age', 'proposed_age'), [('30.0', '30'), ('30', '30.0'), ('true', '1')])
def test_existing_claim_rejects_type_changes_even_when_python_values_compare_equal(project, prior_age, proposed_age):
    with pytest.raises(FolderIntegrationError, match='requirement migration'):
        existing_preflight(project, prior_age=prior_age, proposed_age=proposed_age)


def test_existing_claim_rejects_incomplete_report(project):
    with pytest.raises(FolderIntegrationError, match='exact reported read'):
        existing_preflight(project, remove_source_report=True)


@pytest.mark.parametrize(('path', 'version'), [
    ('a/report.md', 'prior'), ('a/report.md', 'proposed'),
    ('a/secondary.md', 'prior'), ('a/secondary.md', 'proposed'),
    (None, None),
])
def test_projection_comparison_requires_unique_yaml_without_requirements(project, path, version):
    def content(body, duplicate=False):
        extra = 'source_refs: [source-other]\n' if duplicate else ''
        return '---\npage_type: claim\n' + extra + 'source_refs: [source-original]\n---\n' + body + '\n'

    paths = ('a/report.md', 'a/secondary.md')
    for selected in paths:
        put(project, selected, content('Prior', selected == path and version == 'prior'))
    commit(project)
    base = git(project, 'rev-parse', 'HEAD')
    policy = load_folder_policy_v2(project, base)
    evidence = [{'path': selected, 'producer_folder': 'a', 'reason': 'whole prior claim',
                 'use': 'interpret', 'classification': 'synthetic'} for selected in paths]
    packet = build_folder_packet_v2(project, policy, 'a', 30000, content_revision=base,
             index_path='a/index.md', task_id='projection-unique', goal='review', output=paths[0],
             integrator='independent', evidence=evidence)
    git(project, 'checkout', '-qb', 'wiki/unique-projections')
    for selected in paths:
        put(project, selected, content('Revised', selected == path and version == 'proposed'))
    git(project, 'add', '-A'); git(project, 'commit', '-qm', 'revise selected claims')
    result = {'schema_version': 'wiki.folder-task-result/v2', 'status': 'completed',
              'task_id': packet['task_id'], 'context_id': packet['context_id'], 'packet_digest': packet['packet_digest'],
              'observed': [{'path': r['path'], 'kind': r['kind'], 'revision': r['revision'], 'sha256': r['sha256'],
                            'section': r.get('section'), 'field': r.get('field')} for r in packet['inputs']],
              'changes': [{'path': selected, 'action': 'modified'} for selected in paths]}
    kwargs = dict(base=base, head=git(project, 'rev-parse', 'HEAD'), branch='wiki/unique-projections',
                  packet=packet, result=result)
    if path is None:
        assert preflight_folder_v2(project, policy, **kwargs)['state'] == 'independent_review_required'
    else:
        with pytest.raises(FolderIntegrationError, match='projection comparison unavailable'):
            preflight_folder_v2(project, policy, **kwargs)


@pytest.mark.parametrize(('path', 'kind'), [
    ('a/report.md', 'root'), ('a/report.md', 'nested'),
    ('a/secondary.md', 'root'), ('a/secondary.md', 'nested'), (None, None),
])
def test_new_claim_requires_unique_yaml_without_requirements(project, path, kind):
    def content(duplicate):
        if duplicate == 'root':
            extra = 'source_refs: [source-prior]\nsource_refs: null\n'
        elif duplicate == 'nested':
            extra = 'metadata:\n  key: first\n  key: null\n'
        else:
            extra = 'source_refs: []\nmetadata:\n  key: first\n'
        return '---\npage_type: claim\n' + extra + '---\nSynthetic claim\n'

    base = git(project, 'rev-parse', 'HEAD')
    policy = load_folder_policy_v2(project, base)
    packet = build_folder_packet_v2(project, policy, 'a', 30000, content_revision=base,
        index_path='a/index.md', task_id='new-unique', goal='review', output='a/report.md',
        integrator='independent')
    git(project, 'checkout', '-qb', 'wiki/new-unique')
    paths = ('a/report.md', 'a/secondary.md')
    for selected in paths:
        put(project, selected, content(kind if selected == path else None))
    git(project, 'add', '-A'); git(project, 'commit', '-qm', 'new claims')
    result = {'schema_version':'wiki.folder-task-result/v2', 'status':'completed',
        'task_id':packet['task_id'], 'context_id':packet['context_id'], 'packet_digest':packet['packet_digest'],
        'observed':[{'path':row['path'], 'kind':row['kind'], 'revision':row['revision'], 'sha256':row['sha256'],
                     'section':row.get('section'), 'field':row.get('field')} for row in packet['inputs']],
        'changes':[{'path':selected, 'action':'created'} for selected in paths]}
    kwargs = dict(base=base, head=git(project, 'rev-parse', 'HEAD'), branch='wiki/new-unique',
                  packet=packet, result=result)
    if path is None:
        assert preflight_folder_v2(project, policy, **kwargs)['state'] == 'independent_review_required'
    else:
        with pytest.raises(FolderIntegrationError, match='projection comparison unavailable'):
            preflight_folder_v2(project, policy, **kwargs)


@pytest.mark.parametrize('action', ['created', 'modified', 'deleted'])
@pytest.mark.parametrize('kind', ['plain', 'alias', 'cycle'])
def test_claim_changes_reject_yaml_aliases_and_cycles(project, action, kind):
    def claim(which):
        if which == 'alias':
            extra = 'synthetic: &value [first]\nother: *value\n'
        elif which == 'cycle':
            extra = 'synthetic: &value\n  loop: *value\n'
        else:
            extra = 'synthetic: [first]\nother: [first]\n'
        return '---\npage_type: claim\n' + extra + '---\nClaim\n'

    target = 'a/report.md'
    if action != 'created':
        put(project, target, claim(kind if action == 'deleted' else 'plain'))
        commit(project)
    base = git(project, 'rev-parse', 'HEAD'); policy = load_folder_policy_v2(project, base)
    evidence = [] if action == 'created' else [{'path':target, 'producer_folder':'a',
        'reason':'prior claim', 'use':'interpret', 'classification':'synthetic'}]
    packet = build_folder_packet_v2(project, policy, 'a', 30000, content_revision=base,
        index_path='a/index.md', task_id='alias-check', goal='review', output=target,
        integrator='independent', evidence=evidence)
    git(project, 'checkout', '-qb', 'wiki/alias-check')
    if action == 'deleted':
        (project / target).unlink()
    else:
        put(project, target, claim(kind) + 'Revised\n')
    git(project, 'add', '-A'); git(project, 'commit', '-qm', 'synthetic change')
    result = {'schema_version':'wiki.folder-task-result/v2', 'status':'completed',
        'task_id':packet['task_id'], 'context_id':packet['context_id'], 'packet_digest':packet['packet_digest'],
        'observed':[{'path':row['path'], 'kind':row['kind'], 'revision':row['revision'], 'sha256':row['sha256'],
                     'section':row.get('section'), 'field':row.get('field')} for row in packet['inputs']],
        'changes':[{'path':target, 'action':action}]}
    kwargs = dict(base=base, head=git(project, 'rev-parse', 'HEAD'), branch='wiki/alias-check',
                  packet=packet, result=result)
    if kind == 'plain':
        assert preflight_folder_v2(project, policy, **kwargs)['state'] == 'independent_review_required'
    else:
        with pytest.raises(FolderIntegrationError, match='projection comparison unavailable'):
            preflight_folder_v2(project, policy, **kwargs)


@pytest.mark.parametrize('extra', [
    'source_refs: [source-prior]\nsource_refs: null\n',
    'metadata:\n  key: first\n  key: null\n',
    'synthetic: &value [first]\nother: *value\n',
    'synthetic: &value\n  loop: *value\n',
])
def test_frontmatter_validator_rejects_ambiguous_mappings_and_aliases(extra):
    from wiki_core.folder_integration_v2 import _require_unique_frontmatter
    with pytest.raises(FolderIntegrationError, match='projection comparison unavailable'):
        _require_unique_frontmatter({'text':'---\npage_type: claim\n' + extra + '---\nSynthetic claim\n'})


def test_new_claim_deep_frontmatter_returns_controlled_reader_error(project):
    from wiki_core.repository_reader import RepositoryReadError
    marker = 'synthetic-private-value'
    text = ('---\npage_type: claim\ndeep:\n'
            + ''.join('  ' * (i + 1) + 'key:\n' for i in range(1100))
            + '  ' * 1101 + marker + '\n---\nBody\n')
    with pytest.raises(RepositoryReadError, match='frontmatter exceeds nesting limit') as exc:
        created_preflight(project, lambda _base: text)
    assert marker not in str(exc.value)
