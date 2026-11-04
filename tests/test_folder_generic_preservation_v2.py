"""Generic edits preserve prior provenance without renewing it."""
from copy import deepcopy

import pytest
import yaml

from tests.test_folder_multi_provenance_v2 import prior_raw, prior_repo
from tests.test_folder_policy_v2 import project, put, git, commit
from wiki_core.folder_integration_v2 import FolderIntegrationError, preflight_folder_v2
from wiki_core.folder_packet_v2 import build_folder_packet_v2
from wiki_core.folder_policy_v2 import load_folder_policy_v2


@pytest.mark.parametrize('kind', ['raw', 'repository'])
def test_generic_body_edit_preserves_older_requirements_and_provenance(project, kind):
    put(project, 'a/old-source.md', '---\npage_id: source-earlier\npage_type: source\n---\nSource\n')
    projection = prior_raw() if kind == 'raw' else prior_repo()
    metadata = {'page_type':'claim', 'source_refs':['source-earlier'], **projection,
        'information_requirements':[{'target':'a/old-source.md', 'fields':['*'], 'temporal':'current',
          'max_age_days':30, 'consumed_revision':'0'*40, 'use':'interpretation', 'classification':'source'}]}
    def content(values, body):
        return '---\n' + yaml.safe_dump(values, sort_keys=False) + '---\n' + body + '\n'
    put(project, 'a/result.md', content(metadata, 'Original'))
    commit(project); base = git(project, 'rev-parse', 'HEAD'); policy = load_folder_policy_v2(project, base)
    packet = build_folder_packet_v2(project, policy, 'a', 50000, content_revision=base,
        index_path='a/index.md', task_id='generic-edit', goal='review body', output='a/result.md',
        integrator='independent', evidence=[{'path':'a/result.md', 'producer_folder':'a',
        'reason':'prior output', 'use':'context', 'classification':'context'}])
    git(project, 'checkout', '-qb', 'wiki/generic-edit')
    put(project, 'a/result.md', content(metadata, 'Revised'))
    git(project, 'add', 'a/result.md'); git(project, 'commit', '-qm', 'body edit')
    result = {'schema_version':'wiki.folder-task-result/v2', 'status':'completed',
        'task_id':packet['task_id'], 'context_id':packet['context_id'], 'packet_digest':packet['packet_digest'],
        'observed':[{'path':r['path'], 'kind':r['kind'], 'revision':r['revision'], 'sha256':r['sha256'],
                     'section':r.get('section'), 'field':r.get('field')} for r in packet['inputs']],
        'changes':[{'path':'a/result.md', 'action':'modified'}]}
    common = {'base':base, 'head':git(project, 'rev-parse', 'HEAD'), 'branch':'wiki/generic-edit',
              'packet':packet, 'result':result}
    outcome = preflight_folder_v2(project, policy, **common)
    assert outcome['state'] == 'independent_review_required' and outcome['merge'] == 'not_performed'
    assert outcome['prior_requirements_handling'] == 'preserved_not_revalidated'
    assert outcome['prior_ingestion_provenance'] == {
        'capture':'preserved_not_revalidated' if kind == 'raw' else 'absent',
        'repository':'preserved_not_revalidated' if kind == 'repository' else 'absent'}
    for mutation in ('requirement', 'projection', 'references'):
        altered = deepcopy(metadata)
        if mutation == 'requirement': altered['information_requirements'][0]['max_age_days'] = 31
        elif mutation == 'references': altered['source_refs'] = []
        elif kind == 'raw': altered['source_authorization']['source_sha256'] = 'f'*64
        else: altered['independent_repo_read']['content_sha256'] = 'f'*64
        put(project, 'a/result.md', content(altered, 'Revised'))
        git(project, 'add', 'a/result.md'); git(project, 'commit', '--amend', '-qm', 'altered prior provenance')
        with pytest.raises(FolderIntegrationError):
            preflight_folder_v2(project, policy, **{**common, 'head':git(project, 'rev-parse', 'HEAD')})


def test_query_preflight_reports_unrevalidated_secondary_requirements(project):
    from tests.test_folder_query_v2 import fixture_query
    from tests.test_folder_query_packet_v2 import result_for
    from wiki_core.folder_query_packet_v2 import build_folder_query_packet_v2, preflight_folder_query_v2
    from wiki_core.folder_query_requirements_v2 import query_requirements
    _, _, query = fixture_query(project)
    put(project, 'a/old-source.md', 'Old source\n')
    old_requirement = {'target':'a/old-source.md', 'fields':['*'], 'temporal':'current',
        'max_age_days':30, 'consumed_revision':'0'*40, 'use':'interpret', 'classification':'synthetic'}
    def secondary(body):
        return '---\n' + yaml.safe_dump({'page_type':'claim', 'information_requirements':[old_requirement]},
                                         sort_keys=False) + '---\n' + body + '\n'
    put(project, 'a/secondary.md', secondary('Original')); commit(project)
    base = git(project, 'rev-parse', 'HEAD'); policy = load_folder_policy_v2(project, base)
    packet = build_folder_packet_v2(project, policy, 'a', 100000, content_revision=base,
        index_path='a/index.md', task_id='secondary-query', goal='review', output='a/result.md',
        integrator='independent', evidence=[{'path':'a/secondary.md', 'producer_folder':'a',
        'reason':'prior secondary', 'use':'interpret', 'classification':'synthetic'}])
    envelope = build_folder_query_packet_v2(project, policy, base_packet=packet, queries=[query])
    git(project, 'checkout', '-qb', 'wiki/secondary-query')
    put(project, 'a/result.md', '---\n' + yaml.safe_dump({'page_type':'claim',
        'information_requirements':query_requirements(envelope['queries'], 30)}, sort_keys=False) + '---\nResult\n')
    put(project, 'a/secondary.md', secondary('Revised'))
    git(project, 'add', '-A'); git(project, 'commit', '-qm', 'query and secondary')
    result = result_for(envelope, [{'path':'a/result.md', 'action':'created'},
                                   {'path':'a/secondary.md', 'action':'modified'}])
    out = preflight_folder_query_v2(project, policy, base=base, head=git(project, 'rev-parse', 'HEAD'),
                                    branch='wiki/secondary-query', packet=envelope, result=result)
    assert out['prior_requirements_handling'] == 'preserved_not_revalidated'
