"""Secondary changes cannot silently erase prior provenance."""
from copy import deepcopy

import pytest
import yaml

from tests.test_folder_policy_v2 import project, put, git, commit
from wiki_core.folder_packet_v2 import build_folder_packet_v2
from wiki_core.folder_policy_v2 import load_folder_policy_v2
from wiki_core.folder_integration_v2 import FolderIntegrationError, preflight_folder_v2


@pytest.mark.parametrize('field', ['source_authorization', 'independent_repo_read',
    'independent_repo_additional_reads', 'independent_repo_source_ref', 'folder_source_provenance', 'source_refs',
    'malformed_source_refs'])
def test_secondary_projection_removal_is_rejected(project, field):
    value = ['source-synthetic'] if field == 'source_refs' else 'malformed' if field == 'malformed_source_refs' else {'synthetic':'prior'}
    key = 'source_refs' if field == 'malformed_source_refs' else field
    metadata = {'page_type':'claim', key:value}
    put(project, 'a/secondary.md', '---\n' + yaml.safe_dump(metadata) + '---\nPrior\n')
    commit(project); base = git(project, 'rev-parse', 'HEAD')
    policy = load_folder_policy_v2(project, base)
    packet = build_folder_packet_v2(project, policy, 'a', 50000, index_path='a/index.md', content_revision=base,
        task_id='secondary', goal='review', output='a/result.md', integrator='reviewer',
        evidence=[{'path':'a/secondary.md', 'producer_folder':'a', 'reason':'prior',
                   'use':'interpret', 'classification':'synthetic'}])
    git(project, 'checkout', '-qb', 'wiki/secondary')
    put(project, 'a/result.md', '---\npage_type: claim\n---\nResult\n')
    put(project, 'a/secondary.md', '---\npage_type: claim\n---\nProjection removed\n')
    git(project, 'add', '-A'); git(project, 'commit', '-qm', 'secondary altered')
    head = git(project, 'rev-parse', 'HEAD')
    result = {'schema_version':'wiki.folder-task-result/v2', 'status':'completed', 'task_id':packet['task_id'],
        'context_id':packet['context_id'], 'packet_digest':packet['packet_digest'],
        'observed':[{'path':r['path'], 'kind':r['kind'], 'revision':r['revision'], 'sha256':r['sha256'],
                     'section':r.get('section'), 'field':r.get('field')} for r in packet['inputs']],
        'changes':[{'path':'a/result.md', 'action':'created'}, {'path':'a/secondary.md', 'action':'modified'}]}
    common = {'base':base, 'head':head, 'branch':'wiki/secondary', 'packet':packet, 'result':result}
    with pytest.raises(FolderIntegrationError, match='prior ingestion projections changed'):
        preflight_folder_v2(project, policy, **common)
    if field == 'source_refs':
        put(project, 'a/secondary.md', '---\n' + yaml.safe_dump(metadata) + '---\nBody updated\n')
        git(project, 'add', 'a/secondary.md'); git(project, 'commit', '--amend', '-qm', 'secondary preserved')
        assert preflight_folder_v2(project, policy, **{**common, 'head':git(project, 'rev-parse', 'HEAD')})['state'] == 'independent_review_required'
    (project / 'a/secondary.md').unlink()
    git(project, 'add', '-A'); git(project, 'commit', '--amend', '-qm', 'secondary deleted')
    deleted = deepcopy(result); deleted['changes'][1]['action'] = 'deleted'
    with pytest.raises(FolderIntegrationError, match='v2 requirement migration'):
        preflight_folder_v2(project, policy, **{**common, 'head':git(project, 'rev-parse', 'HEAD'), 'result':deleted})


@pytest.mark.parametrize('duplicate', [False, True])
def test_deletion_checks_unique_prior_frontmatter_with_empty_refs(project, duplicate):
    first = 'source_refs: [source-prior]\n' if duplicate else ''
    put(project, 'a/secondary.md', '---\npage_type: claim\n' + first + 'source_refs: []\n---\nPrior\n')
    commit(project); base = git(project, 'rev-parse', 'HEAD')
    policy = load_folder_policy_v2(project, base)
    packet = build_folder_packet_v2(project, policy, 'a', 50000, index_path='a/index.md', content_revision=base,
        task_id='delete-secondary', goal='review', output='a/result.md', integrator='reviewer',
        evidence=[{'path':'a/secondary.md', 'producer_folder':'a', 'reason':'prior',
                   'use':'interpret', 'classification':'synthetic'}])
    git(project, 'checkout', '-qb', 'wiki/delete-secondary')
    put(project, 'a/result.md', '---\npage_type: claim\n---\nResult\n')
    (project / 'a/secondary.md').unlink()
    git(project, 'add', '-A'); git(project, 'commit', '-qm', 'delete selected claim')
    result = {'schema_version':'wiki.folder-task-result/v2', 'status':'completed', 'task_id':packet['task_id'],
        'context_id':packet['context_id'], 'packet_digest':packet['packet_digest'],
        'observed':[{'path':r['path'], 'kind':r['kind'], 'revision':r['revision'], 'sha256':r['sha256'],
                     'section':r.get('section'), 'field':r.get('field')} for r in packet['inputs']],
        'changes':[{'path':'a/result.md', 'action':'created'}, {'path':'a/secondary.md', 'action':'deleted'}]}
    kwargs = dict(base=base, head=git(project, 'rev-parse', 'HEAD'), branch='wiki/delete-secondary',
                  packet=packet, result=result)
    if duplicate:
        with pytest.raises(FolderIntegrationError, match='projection comparison unavailable'):
            preflight_folder_v2(project, policy, **kwargs)
    else:
        assert preflight_folder_v2(project, policy, **kwargs)['state'] == 'independent_review_required'


def test_secondary_with_empty_source_refs_can_be_deleted(project):
    put(project, 'a/secondary.md', '---\npage_type: claim\nsource_refs: []\n---\nPrior\n')
    commit(project); base = git(project, 'rev-parse', 'HEAD')
    policy = load_folder_policy_v2(project, base)
    packet = build_folder_packet_v2(project, policy, 'a', 50000, index_path='a/index.md', content_revision=base,
        task_id='empty-ref', goal='review', output='a/result.md', integrator='reviewer',
        evidence=[{'path':'a/secondary.md', 'producer_folder':'a', 'reason':'prior',
                   'use':'interpret', 'classification':'synthetic'}])
    git(project, 'checkout', '-qb', 'wiki/empty-source-refs')
    put(project, 'a/result.md', '---\npage_type: claim\n---\nResult\n')
    (project / 'a/secondary.md').unlink()
    git(project, 'add', '-A'); git(project, 'commit', '-qm', 'delete empty references')
    result = {'schema_version':'wiki.folder-task-result/v2', 'status':'completed', 'task_id':packet['task_id'],
        'context_id':packet['context_id'], 'packet_digest':packet['packet_digest'],
        'observed':[{'path':r['path'], 'kind':r['kind'], 'revision':r['revision'], 'sha256':r['sha256'],
                     'section':r.get('section'), 'field':r.get('field')} for r in packet['inputs']],
        'changes':[{'path':'a/result.md', 'action':'created'}, {'path':'a/secondary.md', 'action':'deleted'}]}
    assert preflight_folder_v2(project, policy, base=base, head=git(project, 'rev-parse', 'HEAD'),
        branch='wiki/empty-source-refs', packet=packet, result=result)['state'] == 'independent_review_required'
