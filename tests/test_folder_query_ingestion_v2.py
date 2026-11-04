"""Composition of recorded ingestion and query evidence in one preflight."""
import json
import os
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
import pytest

from tests.test_folder_consolidate_v2 import fixture_inputs, metadata
from tests.test_folder_policy_v2 import project, put, git, commit
from tests.test_folder_query_packet_v2 import result_for
from wiki_core.consolidate import prepare_folder_consolidation


def test_query_and_raw_ingestion_share_host_bound_preflight(project, monkeypatch, tmp_path, capsys):
    binding, request, results = fixture_inputs(project, monkeypatch, tmp_path, capsys,
                                                raw=True, with_query=True)
    base_packet = request['block_context_package']
    base = base_packet['policy_revision']
    query = {'target':'a/index.md', 'reason':'synthetic', 'use':'interpret',
             'classification':'synthetic', 'query':{'scope':'a/items',
             'filters':{'status':'active'}, 'field':'amount', 'max_enumerated':20,
             'max_matches':10, 'max_scan_bytes':100000}}
    request_path = tmp_path / 'request.json'
    queries_path = tmp_path / 'queries.json'
    packet_path = tmp_path / 'packet.json'
    result_path = tmp_path / 'result.json'
    request_path.write_text(json.dumps(request))
    queries_path.write_text(json.dumps([query]))
    scripts = Path(__file__).resolve().parents[1] / 'scripts'
    common = [sys.executable, str(scripts / 'wiki_context.py'), '--repo', str(project),
              '--approved-revision', base]
    packed = subprocess.run(common + ['attach-queries', 'a', '--index', 'a/index.md',
                '--source-request', str(request_path), '--queries', str(queries_path)],
                capture_output=True, text=True)
    assert packed.returncode == 0, packed.stderr
    packet = json.loads(packed.stdout)
    assert packet['base_packet'] == base_packet
    assert packet == request['folder_query_packet']
    assert packet['queries'][0]['selected'][0]['text'] == '11'
    packet_path.write_text(json.dumps(packet))

    result = result_for(packet, [{'path':base_packet['output'], 'action':'created'}])
    preview = prepare_folder_consolidation(project, binding, request, results,
        candidates=[], max_age_days=30, page_metadata=metadata(), query_packet=packet, query_result=result)
    from wiki_core.frontmatter import parse_frontmatter
    requirements = parse_frontmatter(preview['markdown'])[0]['information_requirements']
    query_requirement = next(row for row in requirements if row.get('query_contract'))
    assert query_requirement['query_id'] == packet['queries'][0]['receipt']['query_id']
    assert query_requirement['query_reason'] == 'synthetic'
    git(project, 'checkout', '-qb', 'wiki/query-raw')
    put(project, preview['output'], preview['markdown'])
    git(project, 'add', preview['output']); git(project, 'commit', '-qm', 'synthetic proposal')
    head = git(project, 'rev-parse', 'HEAD')
    result_path.write_text(json.dumps(result))
    command = [sys.executable, str(scripts / 'wiki_context_flow.py'), '--repo', str(project),
               '--approved-revision', base, 'preflight', '--folder', 'a', '--index', 'a/index.md',
               '--base', base, '--head', head, '--branch', 'wiki/query-raw',
               '--packet', str(packet_path), '--result', str(result_path)]
    env = dict(os.environ, WIKI_FOLDER_INGEST_HOST_ROOT=str(project), WIKI_FOLDER_INGEST_HOST_FOLDERS='a')
    assert subprocess.run(command, env=env, capture_output=True).returncode != 0
    checked = subprocess.run(command + ['--source-request', str(request_path)], env=env,
                             capture_output=True, text=True)
    assert checked.returncode == 0, checked.stderr
    outcome = json.loads(checked.stdout)
    assert outcome['state'] == 'independent_review_required'
    assert outcome['requirements_handling']['count'] == 2
    assert outcome['capture_handling'] == {'local_bytes':'matched', 'external_origin':'not_verified',
                                           'external_freshness':'not_verified', 'execution':'not_proven'}
    from jsonschema import validate
    schema = scripts.parent / 'docs/references/schemas/wiki-folder-query-preflight-v2.schema.json'
    validate(outcome, json.loads(schema.read_text()))

    wrong_host = dict(env, WIKI_FOLDER_INGEST_HOST_FOLDERS='a/aux/b')
    assert subprocess.run(command + ['--source-request', str(request_path)], env=wrong_host,
                          capture_output=True).returncode != 0
    omitted_query = deepcopy(result)
    omitted_query['observed_queries'] = []
    result_path.write_text(json.dumps(omitted_query))
    assert subprocess.run(command + ['--source-request', str(request_path)], env=env,
                          capture_output=True).returncode != 0
    result_path.write_text(json.dumps(result))
    changed = deepcopy(request)
    changed['source_authorization']['source_sha256'] = '0' * 64
    request_path.write_text(json.dumps(changed))
    assert subprocess.run(command + ['--source-request', str(request_path)], env=env,
                          capture_output=True).returncode != 0
    request_path.write_text(json.dumps(request))
    put(project, 'a/raw/source.md', 'Changed after the recorded capture\n')
    assert subprocess.run(command + ['--source-request', str(request_path)], env=env,
                          capture_output=True).returncode != 0


@pytest.mark.parametrize('with_repo', [False, True])
def test_query_and_existing_destination_are_both_bound_before_result(project, monkeypatch, tmp_path, capsys, with_repo):
    from wiki_core.folder_query_packet_v2 import preflight_folder_query_v2
    from wiki_core.folder_policy_v2 import load_folder_policy_v2
    from wiki_core.llm.context_pass import result_matches_request
    from wiki_core.frontmatter import parse_frontmatter
    binding, request, results = fixture_inputs(project, monkeypatch, tmp_path, capsys,
                                                existing=True, with_query=True, with_repo=with_repo)
    base = request['block_context_package']; packet = request['folder_query_packet']
    assert packet['queries'][0]['selected'][0]['text'] == '11'
    assert len([row for row in base['inputs'] if row['path'] == base['output']]) == 1
    assert request['source_authorization']['existing_output_sha256']
    assert result_matches_request(results[0], request, request['chunks'][0], recording=True)
    for mutate in ('omit_query', 'change_query', 'omit_existing', 'change_existing'):
        changed = deepcopy(request)
        if mutate == 'omit_query': changed.pop('folder_query_packet')
        if mutate == 'change_query': changed['folder_query_packet']['queries'][0]['selected'][0]['text'] = '12'
        if mutate == 'omit_existing': changed['source_authorization'].pop('existing_output_sha256')
        if mutate == 'change_existing': changed['source_authorization']['existing_output_sha256'] = '0' * 64
        assert not result_matches_request(results[0], changed, changed['chunks'][0], recording=True)
    result = result_for(packet, [{'path':base['output'], 'action':'modified'}])
    preview = prepare_folder_consolidation(project, binding, request, results, candidates=[],
        max_age_days=30, page_metadata=metadata(), query_packet=packet, query_result=result)
    fm, body = parse_frontmatter(preview['markdown'])
    assert 'Existing claim content preserved.' in body
    assert 'Synthetic selected amount: 11' in body
    assert any(row.get('query_id') == packet['queries'][0]['receipt']['query_id']
               for row in fm['information_requirements'])
    old_branch = git(project, 'branch', '--show-current')
    git(project, 'checkout', '-qb', 'wiki/query-existing-ingestion')
    put(project, base['output'], preview['markdown'])
    git(project, 'add', base['output']); git(project, 'commit', '-qm', 'synthetic query integration')
    head = git(project, 'rev-parse', 'HEAD')
    policy = load_folder_policy_v2(project, base['policy_revision'])
    kwargs = {'base':base['policy_revision'], 'head':head, 'branch':'wiki/query-existing-ingestion',
              'packet':packet, 'result':result, 'binding':binding, 'source_request':request}
    checked = preflight_folder_query_v2(project, policy, **kwargs)
    assert checked['state'] == 'independent_review_required'
    assert checked['requirements_handling']['count'] == 2
    assert checked['modified_ingestion_bodies'][0]['semantic_review'] == 'independent_review_required'
    if with_repo:
        assert checked['repository_handling'] == {'selection':'matched_request',
            'remote_authentication':'not_verified', 'execution':'not_proven'}
    from jsonschema import validate
    schema = Path(__file__).resolve().parents[1] / 'docs/references/schemas/wiki-folder-query-preflight-v2.schema.json'
    validate(checked, json.loads(schema.read_text()))
    from wiki_core.folder_coordination_v2 import prepare_folder_preflight
    base_result = {'schema_version':'wiki.folder-task-result/v2', 'status':'completed',
        'task_id':base['task_id'], 'context_id':base['context_id'], 'packet_digest':base['packet_digest'],
        'observed':[{'path':row['path'], 'kind':row['kind'], 'revision':row['revision'], 'sha256':row['sha256'],
                     'section':row.get('section'), 'field':row.get('field')} for row in base['inputs']],
        'changes':[{'path':base['output'], 'action':'modified'}]}
    with pytest.raises(ValueError):
        prepare_folder_preflight(project, binding, {'folder':'a', 'approved_revision':base['policy_revision'],
            'base':base['policy_revision'], 'head':head, 'branch':'wiki/query-existing-ingestion',
            'packet':base, 'result':base_result, 'source_request':request})
    bad = deepcopy(request); bad.pop('folder_query_packet')
    with pytest.raises(ValueError):
        preflight_folder_query_v2(project, policy, **{**kwargs, 'source_request':bad})
    other = deepcopy(request); other['source_authorization']['existing_output_sha256'] = '0' * 64
    with pytest.raises(ValueError):
        preflight_folder_query_v2(project, policy, **{**kwargs, 'source_request':other})
    assert git(project, 'branch', '--show-current') != old_branch
    git(project, 'checkout', '-q', old_branch)
    git(project, 'merge', '--ff-only', 'wiki/query-existing-ingestion')
    git(project, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    put(project, 'a/items/one.md', '---\npage_id: one\nstatus: active\namount: 12\n---\nChanged\n')
    commit(project)
    from wiki_core.folder_query_consumers_v2 import reassess_query_consumers
    query_id = packet['queries'][0]['receipt']['query_id']
    report = {'target':base['output'], 'query_id':query_id, 'packet':packet,
              'result':result, 'integrated_revision':head}
    impact = reassess_query_consumers(project, binding, folder='a', approved_revision=git(project, 'rev-parse', 'HEAD'),
        candidates=[base['output']], changed_paths=['a/items/one.md'], reports=[report])
    assert impact['consumers'][0]['state'] == 'review_pending'
    assert impact['consumers'][0]['query_state'] == 'changed'
