"""Add source-bound provenance without reinterpreting prior projections."""
import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import validate

from tests.test_folder_policy_v2 import project, put, git
from tests.test_folder_consolidate_v2 import fixture_inputs, metadata
from wiki_core.consolidate import prepare_folder_consolidation
from wiki_core.folder_coordination_v2 import prepare_folder_preflight
from wiki_core.folder_source_provenance_v2 import add_projection, selected_projection, FIELD
from wiki_core.frontmatter import parse_frontmatter


def prior_raw():
    return {'source_authorization':{'source_kind':'staged_raw', 'ref':'a/raw/old.md', 'source_revision':None,
        'source_sha256':'1'*64, 'source_origin':{'kind':'repository_path'}, 'canonical_ref':'a/old-source.md',
        'canonical_revision':'0'*40, 'canonical_sha256':'2'*64, 'association':'caller_selected_unverified',
        'external_origin_verification':'not_verified', 'external_freshness':'not_verified'}}


def prior_repo():
    return {'independent_repo_source_ref':'a/old-source.md', 'independent_repo_read':{
        'identity':'example.test/group/old', 'revision':'1'*40, 'path':'guide.md', 'blob':'2'*40,
        'document_sha256':'3'*64, 'content_sha256':'4'*64, 'section':None, 'field':None}}


@pytest.mark.parametrize('prior_kind,new_kind', [('raw','raw'), ('raw','repo'), ('repo','raw'), ('repo','repo')])
def test_projection_is_additive_and_source_specific(prior_kind, new_kind):
    prior = prior_raw() if prior_kind == 'raw' else prior_repo()
    metadata_old = {**prior, 'information_requirements':[
        {'target':'a/old-source.md', 'fields':['*'], 'temporal':'current', 'max_age_days':30,
         'consumed_revision':'0'*40, 'use':'interpretation', 'classification':'source'}]}
    auth = {'source_kind':'staged_raw', 'ref':'a/raw/new.md', 'source_revision':None,
        'source_sha256':'5'*64, 'source_origin':{'kind':'repository_path'}, 'canonical_ref':'a/new-source.md',
        'canonical_revision':'6'*40, 'canonical_sha256':'7'*64, 'association':'caller_selected_unverified',
        'external_origin_verification':'not_verified', 'external_freshness':'not_verified'}
    if new_kind == 'repo':
        auth = {'source_kind':'git', 'canonical_ref':'a/new-source.md', 'canonical_revision':'6'*40,
                'independent_repo_read':{'repository':{'identity':'example.test/group/new'}, 'revision':'8'*40,
                    'path':'guide.md', 'blob':'9'*40, 'document_sha256':'a'*64, 'content_sha256':'b'*64,
                    'section':None, 'field':None}}
    projection = add_projection(metadata_old, auth)
    for key, value in prior.items(): assert projection[key] == value
    final = {**metadata_old, **projection, 'information_requirements':[*metadata_old['information_requirements'],
        {'target':'a/new-source.md', 'fields':['*'], 'temporal':'current', 'max_age_days':30,
         'consumed_revision':'6'*40, 'use':'interpretation', 'classification':'source'}]}
    old_selected = selected_projection(final, 'a/old-source.md')
    new_selected = selected_projection(final, 'a/new-source.md')
    assert old_selected == prior
    assert ('source_authorization' in new_selected) == (new_kind == 'raw')
    assert ('independent_repo_read' in new_selected) == (new_kind == 'repo')
    assert selected_projection(final, 'a/unrelated.md') == {}
    schema = json.loads((Path(__file__).resolve().parents[1] / 'docs/references/schemas/wiki-folder-source-provenance-v2.schema.json').read_text())
    validate(final[FIELD], schema)
    changed = deepcopy(final); changed[FIELD]['entries'].append(deepcopy(changed[FIELD]['entries'][0]))
    with pytest.raises(ValueError): selected_projection(changed, 'a/new-source.md')
    changed = deepcopy(final); changed['information_requirements'][-1]['consumed_revision'] = 'f'*40
    with pytest.raises(ValueError): selected_projection(changed, 'a/new-source.md')


def test_ambiguous_legacy_repository_is_not_reassigned():
    prior = prior_repo(); prior.pop('independent_repo_source_ref')
    with pytest.raises(ValueError, match='association unavailable'):
        add_projection(prior, {'source_kind':'git', 'canonical_ref':'a/new.md', 'canonical_revision':'0'*40})


def test_new_claim_rejects_unbound_additional_provenance(project, monkeypatch, tmp_path, capsys):
    import yaml
    from wiki_core.folder_coordination_v2 import FolderCoordinationError
    binding, request, results = fixture_inputs(project, monkeypatch, tmp_path, capsys, raw=True)
    preview = prepare_folder_consolidation(project, binding, request, results, candidates=[], max_age_days=30,
                                           page_metadata=metadata())
    fm, body = parse_frontmatter(preview['markdown'])
    fm[FIELD] = {'schema_version':'wiki.folder-source-provenance/v2', 'entries':[]}
    packet = request['block_context_package']; base = packet['policy_revision']
    git(project, 'checkout', '-qb', 'wiki/unbound-provenance')
    put(project, packet['output'], '---\n' + yaml.safe_dump(fm, sort_keys=False) + '---\n' + body)
    git(project, 'add', packet['output']); git(project, 'commit', '-qm', 'unbound provenance')
    result = {'schema_version':'wiki.folder-task-result/v2', 'status':'completed', 'task_id':packet['task_id'],
        'context_id':packet['context_id'], 'packet_digest':packet['packet_digest'],
        'observed':[{'path':r['path'], 'kind':r['kind'], 'revision':r['revision'], 'sha256':r['sha256'],
                     'section':r.get('section'), 'field':r.get('field')} for r in packet['inputs']],
        'changes':[{'path':packet['output'], 'action':'added'}]}
    with pytest.raises(FolderCoordinationError):
        prepare_folder_preflight(project, binding, {'folder':'a', 'approved_revision':base, 'base':base,
            'head':git(project, 'rev-parse', 'HEAD'), 'branch':'wiki/unbound-provenance',
            'packet':packet, 'result':result, 'source_request':request})


@pytest.mark.parametrize('prior_kind,new_kind', [('raw','raw'), ('raw','repo'), ('repo','raw'), ('repo','repo')])
def test_existing_claim_accepts_new_source_but_preserves_prior(project, monkeypatch, tmp_path, capsys, prior_kind, new_kind):
    prior = prior_raw() if prior_kind == 'raw' else prior_repo()
    binding, request, results = fixture_inputs(project, monkeypatch, tmp_path, capsys, existing=True,
        raw=new_kind == 'raw', with_repo=new_kind == 'repo', prior_projection=prior)
    preview = prepare_folder_consolidation(project, binding, request, results, candidates=[], max_age_days=30,
                                           page_metadata=metadata())
    fm, body = parse_frontmatter(preview['markdown'])
    for key, value in prior.items(): assert fm[key] == value
    assert len(fm[FIELD]['entries']) == 1 and 'Existing claim content preserved.' in body
    source = request['source_authorization']['canonical_ref']
    assert selected_projection(fm, source)
    packet = request['block_context_package']; base = packet['policy_revision']
    original_branch = git(project, 'branch', '--show-current')
    git(project, 'checkout', '-qb', 'wiki/multi-provenance')
    put(project, packet['output'], preview['markdown'])
    git(project, 'add', packet['output']); git(project, 'commit', '-qm', 'synthetic proposal')
    head = git(project, 'rev-parse', 'HEAD')
    result = {'schema_version':'wiki.folder-task-result/v2', 'status':'completed', 'task_id':packet['task_id'],
        'context_id':packet['context_id'], 'packet_digest':packet['packet_digest'],
        'observed':[{'path':r['path'], 'kind':r['kind'], 'revision':r['revision'], 'sha256':r['sha256'],
                     'section':r.get('section'), 'field':r.get('field')} for r in packet['inputs']],
        'changes':[{'path':packet['output'], 'action':'modified'}]}
    payload = {'folder':'a', 'approved_revision':base, 'base':base, 'head':head,
               'branch':'wiki/multi-provenance', 'packet':packet, 'result':result, 'source_request':request}
    outcome = prepare_folder_preflight(project, binding, payload)
    assert outcome['preflight']['state'] == 'independent_review_required'
    if prior_kind == 'raw' and new_kind == 'raw':
        import yaml
        from wiki_core.folder_coordination_v2 import FolderCoordinationError
        for mutation in ('prior', 'missing', 'duplicate'):
            tampered = deepcopy(fm)
            if mutation == 'prior': tampered['source_authorization']['source_sha256'] = 'f'*64
            elif mutation == 'missing': tampered.pop(FIELD)
            else: tampered[FIELD]['entries'].append(deepcopy(tampered[FIELD]['entries'][0]))
            put(project, packet['output'], '---\n' + yaml.safe_dump(tampered, sort_keys=False) + '---\n' + body)
            git(project, 'add', packet['output']); git(project, 'commit', '--amend', '-qm', 'synthetic altered proposal')
            with pytest.raises(FolderCoordinationError):
                prepare_folder_preflight(project, binding, {**payload, 'head':git(project, 'rev-parse', 'HEAD')})
        put(project, packet['output'], preview['markdown'])
        git(project, 'add', packet['output']); git(project, 'commit', '--amend', '-qm', 'synthetic restored proposal')
        payload['head'] = git(project, 'rev-parse', 'HEAD')
        assert prepare_folder_preflight(project, binding, payload)['preflight']['state'] == 'independent_review_required'
        wrong = deepcopy(request); wrong['source_authorization']['source_sha256'] = '0'*64
        with pytest.raises(FolderCoordinationError):
            prepare_folder_preflight(project, binding, {**payload, 'source_request':wrong})
    git(project, 'checkout', '-q', original_branch)
    git(project, 'merge', '--ff-only', 'wiki/multi-provenance')
    git(project, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    from wiki_core.folder_reassessment_host_v2 import prepare_folder_reassessment
    current = git(project, 'rev-parse', 'HEAD')
    report = {'target':packet['output'], 'section':None, 'field':None, 'packet':packet, 'result':result}
    reassessment = {'folder':'a', 'approved_revision':current, 'source':source,
                    'candidates':[packet['output']], 'reports':[report], 'source_request':request}
    if new_kind == 'raw':
        put(project, 'a/raw/source.md', 'Changed synthetic RAW after integration\n')
    else:
        clone = project / 'a/clone'
        put(clone, 'guide.md', 'Changed synthetic repository source\n')
        git(clone, 'add', 'guide.md'); git(clone, 'commit', '-qm', 'new source revision')
        receipt = request['source_authorization']['independent_repo_read']
        report['repo_read'] = {**receipt, 'text':request['independent_repo_content']}
        reassessment['independent_repo'] = {'root':str(clone), 'identity':receipt['repository']['identity'],
                                             'revision':git(clone, 'rev-parse', 'HEAD'), 'path':receipt['path']}
    checked = prepare_folder_reassessment(project, binding, reassessment)['reassessment']
    assert checked['consumers'][0]['state'] == 'review_pending'
    assert (project / packet['output']).read_text() == preview['markdown']
    old = prepare_folder_reassessment(project, binding, {'folder':'a', 'approved_revision':current,
          'source':'a/old-source.md', 'candidates':[packet['output']], 'reports':[]})['reassessment']
    expected = 'blocked_raw_capture_unavailable' if prior_kind == 'raw' else 'blocked_repository_request_unavailable'
    assert old['consumers'][0]['state'] == expected
