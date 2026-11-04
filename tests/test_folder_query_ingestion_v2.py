"""Composition of recorded ingestion and query evidence in one preflight."""
import json
import os
from copy import deepcopy
from pathlib import Path
import subprocess
import sys

from tests.test_folder_consolidate_v2 import fixture_inputs, metadata
from tests.test_folder_policy_v2 import project, put, git
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
