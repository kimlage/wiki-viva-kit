"""Folder query content is delivered before deep-read identity is calculated."""
import json
import os
from pathlib import Path
import subprocess
import sys
from copy import deepcopy

import pytest
import yaml

from tests.test_folder_policy_v2 import project, put, commit, git
from tests.test_folder_ingestion_v2 import setup, _recording_cli, _synthetic_result
from wiki_core.config import load_config
from wiki_core.ingest import run
from wiki_core.llm.context_pass import context_input_size, result_matches_request
from wiki_core.paths import FolderWikiPaths


def setup_query(project):
    _, selection = setup(project)
    put(project, 'a/index.md', '---\npage_id: synthetic-catalog\npage_type: source_catalog\n---\nCollection\n')
    put(project, 'a/items/one.md', '---\npage_id: one\nstatus: active\namount: 11\n---\nSynthetic\n')
    commit(project)
    sha = git(project, 'rev-parse', 'HEAD')
    query = {'target':'a/index.md', 'reason':'synthetic', 'use':'interpret', 'classification':'synthetic',
             'query':{'scope':'a/items', 'filters':{'status':'active'}, 'field':'amount',
                      'max_enumerated':20, 'max_matches':10, 'max_scan_bytes':100000}}
    return sha, selection, query


def test_query_selection_is_delivered_before_recording_and_binds_cache(project, monkeypatch, tmp_path, capsys):
    sha, selection, query = setup_query(project)
    source = str(project / 'a/source.md')
    plain = run(source, 'system', project, load_config(project), approved_revision=sha,
                folder_selection=selection)
    plain_request = json.loads((project / plain.request_path).read_text())
    captured = run(source, 'system', project, load_config(project), approved_revision=sha,
                   folder_selection=selection, folder_queries=[query])
    assert not captured.blocked and captured.written
    request = json.loads((project / captured.request_path).read_text())
    envelope = request['folder_query_packet']
    assert envelope['base_packet'] == request['block_context_package']
    assert envelope['queries'][0]['selected'][0]['text'] == '11'
    assert request['chunks'][0]['cache_key'] != plain_request['chunks'][0]['cache_key']
    assert request['byte_accounting']['context_bytes'] == context_input_size(request)
    result = _synthetic_result(request)
    assert result_matches_request(result, request, request['chunks'][0], recording=True)
    tampered = deepcopy(request)
    tampered['folder_query_packet']['queries'][0]['selected'][0]['text'] = 'different'
    assert not result_matches_request(result, tampered, tampered['chunks'][0], recording=True)

    query_file = tmp_path / 'selected-queries.json'
    query_file.write_text(json.dumps([query]))
    module = _recording_cli(project, sha, request, monkeypatch, tmp_path)
    original_argv = list(sys.argv)
    assert module.main() == 2  # Omitting the selection cannot record a query-bound result.
    capsys.readouterr()
    cache = FolderWikiPaths(project, load_config(project), 'a').llm_cache / 'folder-v2' / (result['cache_key'] + '.json')
    assert not cache.exists()
    changed = deepcopy(query); changed['query']['filters']['status'] = 'other'
    query_file.write_text(json.dumps([changed]))
    monkeypatch.setattr(sys, 'argv', [*original_argv, '--folder-queries', str(query_file)])
    assert module.main() == 2
    capsys.readouterr()
    assert not cache.exists()
    query_file.write_text(json.dumps([query]))
    assert module.main() == 0
    capsys.readouterr()
    assert cache.exists()


def test_query_revocation_blocks_preparation_and_previous_result(project):
    sha, selection, query = setup_query(project)
    source = str(project / 'a/source.md')
    first = run(source, 'system', project, load_config(project), approved_revision=sha,
                folder_selection=selection, folder_queries=[query])
    assert not first.blocked
    request = json.loads((project / first.request_path).read_text())
    put(project, 'a/items/one.md', '---\npage_id: one\nstatus: active\namount: 12\n---\nSynthetic\n')
    commit(project)
    newer = git(project, 'rev-parse', 'HEAD')
    second = run(source, 'system', project, load_config(project), approved_revision=newer,
                 folder_selection=selection, folder_queries=[query])
    assert not second.blocked
    updated = json.loads((project / second.request_path).read_text())
    assert updated['folder_query_packet']['queries'][0]['selected'][0]['text'] == '12'
    assert updated['chunks'][0]['cache_key'] != request['chunks'][0]['cache_key']
    assert not result_matches_request(_synthetic_result(request), updated, updated['chunks'][0], recording=True)
    controls = project / 'wiki-context-controls.yaml'
    value = yaml.safe_load(controls.read_text())
    value['controls']['a']['policy']['deny'] = {'read':['a/items']}
    controls.write_text(yaml.safe_dump(value))
    commit(project)
    current = git(project, 'rev-parse', 'HEAD')
    old = run(source, 'system', project, load_config(project), approved_revision=sha,
              folder_selection=selection, folder_queries=[query])
    denied = run(source, 'system', project, load_config(project), approved_revision=current,
                 folder_selection=selection, folder_queries=[query])
    assert old.blocked and denied.blocked and not old.written and not denied.written
    assert json.loads((project / second.request_path).read_text()) == updated


def test_query_selection_without_folder_fails_closed(project):
    sha, _, query = setup_query(project)
    result = run(str(project / 'a/source.md'), 'system', project, load_config(project),
                 approved_revision=sha, policy_context='root', folder_queries=[query])
    assert result.blocked and not result.written


def test_empty_source_never_silently_discards_queries(project):
    _, selection, query = setup_query(project)
    put(project, 'a/source.md', '')
    commit(project)
    result = run(str(project / 'a/source.md'), 'system', project, load_config(project),
                 approved_revision=git(project, 'rev-parse', 'HEAD'), folder_selection=selection,
                 folder_queries=[query])
    assert result.blocked and not result.written and result.context_error_code == 'folder_query_source_empty'


def test_ingest_cli_delivers_selected_query(project, tmp_path):
    sha, _, query = setup_query(project)
    selected = tmp_path / 'queries.json'
    selected.write_text(json.dumps([query]))
    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_ingest.py'
    proc = subprocess.run([sys.executable, str(script), '--root', str(project), '--source', 'a/source.md',
        '--context', 'system', '--approved-revision', sha, '--folder-context', 'a',
        '--folder-index', 'a/index.md', '--folder-output', 'a/result.md', '--folder-queries', str(selected)],
        capture_output=True, text=True, env={**os.environ, 'WIKI_FOLDER_INGEST_HOST_ROOT':str(project),
                                             'WIKI_FOLDER_INGEST_HOST_FOLDERS':'a'})
    assert proc.returncode == 0, proc.stderr
    request = json.loads((project / json.loads(proc.stdout)['request_path']).read_text())
    assert request['folder_query_packet']['queries'][0]['selected'][0]['text'] == '11'
