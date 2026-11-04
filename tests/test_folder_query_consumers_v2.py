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
