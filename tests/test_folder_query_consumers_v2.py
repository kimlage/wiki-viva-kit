"""Durable, scoped query declarations with explicit reported history."""
from copy import deepcopy

import pytest
import yaml

from tests.test_folder_query_v2 import project, fixture_query, put, git, commit
from tests.test_folder_query_packet_v2 import result_for
from wiki_core.context_policy import PolicyError
from wiki_core.context_selection import requirement_query
from wiki_core.folder_coordination_v2 import FolderHostBinding
from wiki_core.folder_query_consumers_v2 import reassess_query_consumers
from wiki_core.folder_query_packet_v2 import build_folder_query_packet_v2, preflight_folder_query_v2
from wiki_core.folder_query_requirements_v2 import query_requirements, same_json


def test_query_projection_compares_json_types():
    assert not same_json({'filter': True}, {'filter': 1})
    assert same_json({'filter': 1, 'other': 'x'}, {'other': 'x', 'filter': 1})


def test_reported_query_is_projected_and_selectively_reassessed(project, monkeypatch):
    policy, base_packet, query = fixture_query(project)
    packet = build_folder_query_packet_v2(project, policy, base_packet=base_packet, queries=[query])
    req = query_requirements(packet['queries'], 30)[0]
    before = git(project, 'rev-parse', 'HEAD')
    original = git(project, 'branch', '--show-current')
    git(project, 'checkout', '-qb', 'wiki/durable-query')
    text = '---\n' + yaml.safe_dump({'page_type':'claim',
        'information_requirements':[req]}, sort_keys=False) + '---\nInterpretation\n'
    put(project, 'a/result.md', text)
    git(project, 'add', '-A'); git(project, 'commit', '-qm', 'query consumer')
    head = git(project, 'rev-parse', 'HEAD')
    result = result_for(packet, [{'path':'a/result.md', 'action':'created'}])
    outcome = preflight_folder_query_v2(project, policy, base=before, head=head,
        branch='wiki/durable-query', packet=packet, result=result)
    assert outcome['requirements_handling']['count'] == 1
    altered_req = deepcopy(req); altered_req['selected_digest'] = '0' * 64
    put(project, 'a/result.md', '---\n' + yaml.safe_dump({'page_type':'claim',
        'information_requirements':[altered_req]}, sort_keys=False) + '---\nInterpretation\n')
    git(project, 'add', 'a/result.md'); git(project, 'commit', '--amend', '-qm', 'altered query declaration')
    with pytest.raises(ValueError):
        preflight_folder_query_v2(project, policy, base=before, head=git(project, 'rev-parse', 'HEAD'),
            branch='wiki/durable-query', packet=packet, result=result)
    put(project, 'a/result.md', text)
    git(project, 'add', 'a/result.md'); git(project, 'commit', '--amend', '-qm', 'query consumer')
    head = git(project, 'rev-parse', 'HEAD')
    with pytest.raises(PolicyError):
        requirement_query(req)
    git(project, 'checkout', '-q', original)
    git(project, 'merge', '--ff-only', 'wiki/durable-query')
    git(project, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    put(project, 'a/items/two.md', '---\npage_id: two\nstatus: active\namount: 22\n---\nSource two\n')
    commit(project); current = git(project, 'rev-parse', 'HEAD')
    binding = FolderHostBinding(project, ('a',))
    report = {'target':'a/result.md', 'query_id':req['query_id'], 'packet':packet,
              'result':result, 'integrated_revision':head}
    common = {'folder':'a', 'approved_revision':current, 'candidates':['a/result.md']}
    out = reassess_query_consumers(project, binding, changed_paths=['a/items/two.md'],
                                   reports=[report], **common)
    assert out['consumers'][0]['state'] == 'review_pending'
    assert out['consumers'][0]['query_state'] == 'changed'
    assert out['consumers'][0]['read_verification'] == 'reported_not_independently_verified'
    assert not reassess_query_consumers(project, binding, changed_paths=['a/unrelated.md'],
                                         reports=[], **common)['consumers']
    assert reassess_query_consumers(project, binding, changed_paths=['a/items/two.md'],
             reports=[], **common)['consumers'][0]['state'] == 'declared_without_report'
    altered = deepcopy(report); altered['packet']['queries'][0]['receipt']['selected_digest'] = '0' * 64
    with pytest.raises(ValueError):
        reassess_query_consumers(project, binding, changed_paths=['a/items/two.md'],
                                 reports=[altered], **common)
    with pytest.raises(ValueError):
        reassess_query_consumers(project, FolderHostBinding(project, ('a/aux/b',)),
                                 changed_paths=['a/items/two.md'], reports=[report], **common)
    controls = project / 'wiki-context-controls.yaml'
    data = yaml.safe_load(controls.read_text())
    data['controls']['a']['policy']['deny'] = {'read':['a/items']}
    controls.write_text(yaml.safe_dump(data)); commit(project)
    denied = git(project, 'rev-parse', 'HEAD')
    from wiki_core.repository_reader import RepositoryReader
    original_read = RepositoryReader.read
    def guard(reader, path, *args, **kwargs):
        if path.startswith('a/items/'):
            pytest.fail('query member opened after authority revocation')
        return original_read(reader, path, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', guard)
    with pytest.raises(ValueError):
        reassess_query_consumers(project, binding, folder='a', approved_revision=denied,
            candidates=['a/result.md'], changed_paths=['a/items/two.md'], reports=[report])


def test_two_query_envelope_replays_whole_report_and_reassesses_each_scope(project, monkeypatch):
    from wiki_core.folder_packet_v2 import build_folder_packet_v2
    from wiki_core.folder_policy_v2 import load_folder_policy_v2
    _, _, first = fixture_query(project)
    put(project, 'a/other/one.md', '---\npage_id: other-one\nstatus: active\namount: 31\n---\nOther\n')
    commit(project)
    before = git(project, 'rev-parse', 'HEAD')
    policy = load_folder_policy_v2(project, before)
    base = build_folder_packet_v2(project, policy, 'a', 100000, index_path='a/index.md',
        content_revision=before, task_id='two-query', goal='review', output='a/result.md', integrator='reviewer')
    second = deepcopy(first); second['reason'] = 'second selection'; second['query']['scope'] = 'a/other'
    packet = build_folder_query_packet_v2(project, policy, base_packet=base, queries=[first, second])
    reqs = query_requirements(packet['queries'], 30)
    result = result_for(packet, [{'path':'a/result.md', 'action':'created'}])
    original = git(project, 'branch', '--show-current')
    git(project, 'checkout', '-qb', 'wiki/two-queries')
    put(project, 'a/result.md', '---\npage_type: claim\n---\nMissing query declarations\n')
    git(project, 'add', 'a/result.md'); git(project, 'commit', '-qm', 'missing query declarations')
    with pytest.raises(ValueError):
        preflight_folder_query_v2(project, policy, base=before, head=git(project, 'rev-parse', 'HEAD'),
                                  branch='wiki/two-queries', packet=packet, result=result)
    put(project, 'a/result.md', '---\n' + yaml.safe_dump({'page_type':'claim',
        'information_requirements':reqs}, sort_keys=False) + '---\nTwo synthetic interpretations\n')
    git(project, 'add', 'a/result.md'); git(project, 'commit', '--amend', '-qm', 'query consumer')
    integrated = git(project, 'rev-parse', 'HEAD')
    assert preflight_folder_query_v2(project, policy, base=before, head=integrated,
        branch='wiki/two-queries', packet=packet, result=result)['requirements_handling']['count'] == 2
    from wiki_core.folder_coordination_v2 import prepare_folder_preflight
    base_result = {'schema_version':'wiki.folder-task-result/v2', 'status':'completed',
        'task_id':base['task_id'], 'context_id':base['context_id'], 'packet_digest':base['packet_digest'],
        'observed':[{'path':row['path'], 'kind':row['kind'], 'revision':row['revision'], 'sha256':row['sha256'],
                     'section':row.get('section'), 'field':row.get('field')} for row in base['inputs']],
        'changes':result['changes']}
    binding = FolderHostBinding(project, ('a',))
    payload = {'folder':'a', 'approved_revision':before, 'base':before, 'head':integrated,
               'branch':'wiki/two-queries', 'packet':base, 'result':base_result,
               'query_packet':packet, 'query_result':result}
    assert prepare_folder_preflight(project, binding, payload)['preflight']['state'] == 'independent_review_required'
    divergent = deepcopy(payload); divergent['query_result']['changes'] = []
    with pytest.raises(ValueError):
        prepare_folder_preflight(project, binding, divergent)
    git(project, 'checkout', '-q', original)
    git(project, 'merge', '--ff-only', 'wiki/two-queries')
    git(project, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    put(project, 'a/items/one.md', '---\npage_id: one\nstatus: active\namount: 12\n---\nUpdated\n')
    put(project, 'a/other/one.md', '---\npage_id: other-one\nstatus: active\namount: 32\n---\nUpdated\n')
    commit(project); current = git(project, 'rev-parse', 'HEAD')
    reports = [{'target':'a/result.md', 'query_id':req['query_id'], 'packet':packet,
                'result':result, 'integrated_revision':integrated} for req in reqs]
    common = {'folder':'a', 'approved_revision':current, 'candidates':['a/result.md']}
    for i, changed in enumerate(('a/items/one.md', 'a/other/one.md')):
        out = reassess_query_consumers(project, binding, changed_paths=[changed], reports=[reports[i]], **common)
        assert [(row['query_id'], row['query_state'], row['state']) for row in out['consumers']] == [
            (reqs[i]['query_id'], 'changed', 'review_pending')]
    together = reassess_query_consumers(project, binding, changed_paths=['a/items/one.md', 'a/other/one.md'],
                                       reports=reports, **common)
    assert len(together['consumers']) == 2
    incomplete = deepcopy(reports[0]); incomplete['result']['observed_queries'].pop()
    with pytest.raises(ValueError):
        reassess_query_consumers(project, binding, changed_paths=['a/items/one.md'], reports=[incomplete], **common)
    forged = deepcopy(reports[0]); forged['packet']['queries'][1]['receipt']['selected_digest'] = '0' * 64
    with pytest.raises(ValueError):
        reassess_query_consumers(project, binding, changed_paths=['a/items/one.md'], reports=[forged], **common)
    controls = project / 'wiki-context-controls.yaml'
    data = yaml.safe_load(controls.read_text()); data['controls']['a']['policy']['deny'] = {'read':['a/other']}
    controls.write_text(yaml.safe_dump(data)); commit(project)
    from wiki_core.repository_reader import RepositoryReader
    read = RepositoryReader.read
    def guard(reader, path, *args, **kwargs):
        if path.startswith('a/items/'):
            pytest.fail('query member opened before authority for the whole envelope')
        return read(reader, path, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', guard)
    with pytest.raises(ValueError):
        reassess_query_consumers(project, binding, folder='a', approved_revision=git(project, 'rev-parse', 'HEAD'),
            candidates=['a/result.md'], changed_paths=['a/items/one.md'], reports=[reports[0]])


def test_existing_consumer_cannot_append_duplicate_query_id(project):
    from wiki_core.folder_packet_v2 import build_folder_packet_v2
    from wiki_core.folder_policy_v2 import load_folder_policy_v2
    policy, base, query = fixture_query(project)
    old_packet = build_folder_query_packet_v2(project, policy, base_packet=base, queries=[query])
    old_req = query_requirements(old_packet['queries'], 30)[0]
    put(project, 'a/result.md', '---\n' + yaml.safe_dump({'page_type':'claim',
        'information_requirements':[old_req]}, sort_keys=False) + '---\nPrior\n')
    commit(project); before = git(project, 'rev-parse', 'HEAD')
    policy = load_folder_policy_v2(project, before)
    evidence = [{'path':'a/result.md', 'producer_folder':'a', 'reason':'prior output',
                 'use':'interpret', 'classification':'synthetic'}]
    base = build_folder_packet_v2(project, policy, 'a', 100000, index_path='a/index.md',
        content_revision=before, task_id='duplicate', goal='review', output='a/result.md',
        integrator='reviewer', evidence=evidence)
    packet = build_folder_query_packet_v2(project, policy, base_packet=base, queries=[query])
    new_req = query_requirements(packet['queries'], 30)[0]
    assert old_req['query_id'] == new_req['query_id']
    git(project, 'checkout', '-qb', 'wiki/duplicate-query')
    put(project, 'a/result.md', '---\n' + yaml.safe_dump({'page_type':'claim',
        'information_requirements':[old_req, new_req]}, sort_keys=False) + '---\nModified\n')
    git(project, 'add', 'a/result.md'); git(project, 'commit', '-qm', 'duplicated query')
    result = result_for(packet, [{'path':'a/result.md', 'action':'modified'}])
    with pytest.raises(ValueError):
        preflight_folder_query_v2(project, policy, base=before, head=git(project, 'rev-parse', 'HEAD'),
                                  branch='wiki/duplicate-query', packet=packet, result=result)
