"""Separate collection anchor through the regular v2 query lifecycle."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
import yaml
from jsonschema import validate

from tests.test_folder_policy_v2 import project, put, commit, git
from tests.test_folder_query_packet_v2 import query_claim
from wiki_core.folder_packet_v2 import build_folder_packet_v2
from wiki_core.folder_policy_v2 import load_folder_policy_v2
from wiki_core.folder_query_packet_v2 import build_folder_query_packet_v2, preflight_folder_query_v2, _query_observations
from wiki_core.folder_query_history_v2 import assess_folder_query_history_v2
from wiki_core.folder_query_requirements_v2 import query_requirements
from wiki_core.repository_reader import RepositoryReader


def fixture(repo):
    put(repo, 'a/index.md', 'Context index\n')
    put(repo, 'a/collection.md', '---\npage_id: catalog\npage_type: source_catalog\n---\nCollection contract\n')
    put(repo, 'a/items/one.md', '---\npage_id: one\nstatus: active\namount: 11\n---\nFirst\n')
    commit(repo); policy = load_folder_policy_v2(repo, 'HEAD')
    base = build_folder_packet_v2(repo, policy, 'a', 50000, index_path='a/index.md', content_revision='HEAD',
                                  task_id='synthetic', goal='review', output='a/result.md', integrator='independent')
    req = {'target':'a/collection.md', 'reason':'synthetic', 'use':'interpret', 'classification':'synthetic',
           'query':{'scope':'a/items', 'filters':{'status':'active'}, 'field':'amount',
                    'max_enumerated':20, 'max_matches':10, 'max_scan_bytes':100000}}
    return policy, base, req


def report(packet):
    base = packet['base_packet']
    observed = [{'path':r['path'], 'kind':r['kind'], 'revision':r['revision'], 'sha256':r['sha256'],
                 'section':r.get('section'), 'field':r.get('field')} for r in base['inputs']]
    return {'schema_version':'wiki.folder-query-task-result/v2', 'status':'completed',
            'task_id':base['task_id'], 'context_id':base['context_id'], 'packet_digest':packet['packet_digest'],
            'observed':observed + _query_observations(packet),
            'observed_queries':[q['receipt']['query_id'] for q in packet['queries']],
            'changes':[{'path':'a/result.md', 'action':'created'}]}


def test_separate_anchor_main_flow_history_and_schemas(project):
    policy, base, req = fixture(project); before = git(project, 'rev-parse', 'HEAD')
    packet = build_folder_query_packet_v2(project, policy, base_packet=base, queries=[req])
    query = packet['queries'][0]
    assert query['anchor']['path'] == req['target'] and query['anchor']['text'].endswith('Collection contract\n')
    assert query['selected'][0]['text'] == '11'
    assert query_requirements([query], 30)[0]['query_index'] == 'a/index.md'
    git(project, 'checkout', '-qb', 'wiki/separate-anchor')
    put(project, 'a/result.md', query_claim(packet)); git(project, 'add', '-A'); git(project, 'commit', '-qm', 'proposal')
    integrated = git(project, 'rev-parse', 'HEAD'); result = report(packet)
    outcome = preflight_folder_query_v2(project, policy, base=before, head=integrated,
                                        branch='wiki/separate-anchor', packet=packet, result=result)
    assert outcome['state'] == 'independent_review_required'
    schemas = Path(__file__).resolve().parents[1] / 'docs/references/schemas'
    for name, value in [('wiki-folder-query-task-context-v2.schema.json', packet),
                        ('wiki-folder-query-task-result-v2.schema.json', result)]:
        validate(value, json.loads((schemas / name).read_text()))
    missing = deepcopy(result); missing['observed'] = [row for row in missing['observed'] if row['kind'] != 'query_anchor']
    with pytest.raises(ValueError):
        preflight_folder_query_v2(project, policy, base=before, head=integrated,
                                  branch='wiki/separate-anchor', packet=packet, result=missing)
    git(project, 'update-ref', 'refs/remotes/origin/main', integrated)
    current = load_folder_policy_v2(project, 'HEAD')
    from wiki_core.folder_coordination_v2 import FolderHostBinding
    from wiki_core.folder_query_consumers_v2 import reassess_query_consumers
    pending = reassess_query_consumers(project, FolderHostBinding(project, ('a',)), folder='a',
        approved_revision=integrated, candidates=['a/result.md'], changed_paths=['a/index.md'], reports=[])
    assert pending['consumers'][0]['state'] == 'declared_without_report'
    unchanged = assess_folder_query_history_v2(project, current, packet=packet, result=result, integrated_revision=integrated)
    assert unchanged['query_state'] == 'unchanged'
    put(project, 'a/collection.md', '---\npage_id: catalog\npage_type: source_catalog\n---\nRevised\n'); commit(project)
    current = load_folder_policy_v2(project, 'HEAD')
    changed = assess_folder_query_history_v2(project, current, packet=packet, result=result, integrated_revision=integrated)
    assert changed['query_state'] == 'changed'
    put(project, 'a/index.md', 'Context index revised\n'); commit(project)
    current = load_folder_policy_v2(project, 'HEAD')
    with pytest.raises(ValueError):
        assess_folder_query_history_v2(project, current, packet=packet, result=result, integrated_revision=integrated)


def test_separate_anchor_denied_before_packet_body_and_historical_replay(project, monkeypatch):
    policy, base, req = fixture(project)
    packet = build_folder_query_packet_v2(project, policy, base_packet=base, queries=[req])
    put(project, 'a/result.md', query_claim(packet)); commit(project); integrated = git(project, 'rev-parse', 'HEAD')
    conf = project / 'wiki-context-controls.yaml'; data = yaml.safe_load(conf.read_text())
    data['controls']['a']['policy']['deny'] = {'read':['a/collection.md']}
    conf.write_text(yaml.safe_dump(data)); commit(project); current = load_folder_policy_v2(project, 'HEAD')
    metadata = deepcopy(base); metadata['policy_revision'] = metadata['content_revision'] = current.policy_revision
    original = RepositoryReader.read
    def sentinel(self, path, *args, **kwargs):
        if path != 'wiki-context-controls.yaml': raise AssertionError('body opened before anchor authority')
        return original(self, path, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', sentinel)
    with pytest.raises(ValueError):
        build_folder_query_packet_v2(project, current, base_packet=metadata, queries=[req])
    with pytest.raises(ValueError):
        assess_folder_query_history_v2(project, current, packet=packet, result=report(packet), integrated_revision=integrated)


def test_separate_anchor_change_rejected_before_proposal_body(project, monkeypatch):
    policy, base, req = fixture(project); before = git(project, 'rev-parse', 'HEAD')
    packet = build_folder_query_packet_v2(project, policy, base_packet=base, queries=[req])
    git(project, 'checkout', '-qb', 'wiki/change-anchor'); put(project, 'a/collection.md', 'Changed\n')
    git(project, 'add', '-A'); git(project, 'commit', '-qm', 'proposal'); head = git(project, 'rev-parse', 'HEAD')
    original = RepositoryReader.read
    def sentinel(self, path, *args, **kwargs):
        if self.revision == head and path == 'a/collection.md': raise AssertionError('proposed anchor opened')
        return original(self, path, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', sentinel)
    with pytest.raises(ValueError):
        preflight_folder_query_v2(project, policy, base=before, head=head, branch='wiki/change-anchor',
                                  packet=packet, result=report(packet))


def test_separate_anchor_bounds_and_owner_fail_closed(project, monkeypatch):
    policy, base, req = fixture(project)
    cases = []
    sibling = deepcopy(req); sibling['target'] = 'a/aux/b/index.md'; cases.append(sibling)
    bounded = deepcopy(req); bounded['query']['max_scan_bytes'] = 1; cases.append(bounded)
    secret = deepcopy(req); secret['reason'] = 'https://example.invalid/?X-Goog-Signature=synthetic'; cases.append(secret)
    for case in cases:
        with pytest.raises(ValueError):
            build_folder_query_packet_v2(project, policy, base_packet=base, queries=[case])
    original = RepositoryReader.read
    def sentinel(self, path, *args, **kwargs):
        if path != 'wiki-context-controls.yaml': raise AssertionError('body opened before all query authorities')
        return original(self, path, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', sentinel)
    with pytest.raises(ValueError):
        build_folder_query_packet_v2(project, policy, base_packet=base, queries=[req, sibling])


def test_separate_index_is_an_impact_trigger():
    from wiki_core.information_impact import affected_dynamic_queries
    requirement = {'target':'a/collection.md', 'query_index':'a/index.md', 'query':{'scope':'a/items'}}
    edge = {'source':'a/result.md', 'target':'a/collection.md', 'type':'operational_prerequisite',
            'direction':'directed', 'basis':'frontmatter', 'path':'a/result.md',
            'field':'information_requirements', 'requirement':requirement}
    graph = {'edges':[edge]}
    affected = affected_dynamic_queries(graph, graph, {'a/index.md'}, set())
    assert {row['path'] for row in affected} == {'a/result.md'}
