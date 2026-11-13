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


def test_identity_covers_contract_including_empty_chunks_and_excludes_cache_status():
    from wiki_core.folder_request_identity_v2 import folder_request_identity
    request = {'context_binding_version':2, 'source_id':'source-synthetic', 'chunks':[],
               'instructions':'Read A', 'result_required_keys':['a'], 'model_profile':'one',
               'prompt_version':'v4', 'schema_version':'v1', 'pending_llm_calls':0, 'cached_calls':0}
    first = folder_request_identity(request)
    for key, value in [('instructions','Read B'), ('result_required_keys',['b']),
                       ('model_profile','two'), ('prompt_version','v5'), ('schema_version','v2')]:
        assert folder_request_identity({**request, key:value}) != first
    assert folder_request_identity({**request, 'pending_llm_calls':1, 'byte_accounting':{'request_bytes':99}}) == first


def test_request_selection_preserves_legacy_names_and_exact_folder_identity(project):
    from wiki_core.folder_request_identity_v2 import folder_request_identity, folder_request_path
    from wiki_core.llm.context_pass import emitted_request_path
    from wiki_core.paths import WikiPaths

    config = load_config(project)
    paths = WikiPaths(project, config)
    assert emitted_request_path(paths, 'source-synthetic') == (
        paths.extraction_events / 'source-synthetic-llm-context-request.json')
    with pytest.raises(ValueError):
        emitted_request_path(paths, '../outside')
    request = {'context_binding_version': 2, 'source_id': 'source-synthetic', 'chunks': []}
    request['folder_request_id'] = folder_request_identity(request)
    assert request['folder_request_id'] == '7f904689a390fed22981dd2dac31f2e8b5e956c572f8e9795e884875a8d2fb97'
    expected_name = ('folder-497d4504fc95d5e7c76a8431e21364b8b58e1573f6527b14ed816e533376cd2d-'
                     '7f904689a390fed22981dd2dac31f2e8b5e956c572f8e9795e884875a8d2fb97-llm-context-request.json')
    for folder in ('a', 'b'):
        scoped = FolderWikiPaths(project, config, folder)
        assert emitted_request_path(scoped, request['source_id'], folder_request=request) == folder_request_path(scoped, request)
        assert emitted_request_path(scoped, request['source_id'], folder_request=request).name == expected_name
        with pytest.raises(ValueError):
            emitted_request_path(scoped, 'different-source', folder_request=request)
        with pytest.raises(ValueError):
            emitted_request_path(scoped, request['source_id'], folder_request={**request, 'folder_request_id': '0' * 64})


def test_consolidation_requires_exact_retained_request(project, monkeypatch, tmp_path, capsys):
    from tests.test_folder_consolidate_v2 import fixture_inputs, metadata
    from wiki_core.consolidate import prepare_folder_consolidation
    from wiki_core.folder_capture_v2 import validate_recorded_request
    from wiki_core.folder_request_identity_v2 import folder_request_path
    binding, request, results = fixture_inputs(project, monkeypatch, tmp_path, capsys, raw=True)
    paths = FolderWikiPaths(project, load_config(project), 'a')
    path = folder_request_path(paths, request)
    kwargs = dict(candidates=[], max_age_days=30, page_metadata=metadata())
    assert prepare_folder_consolidation(project, binding, request, results, **kwargs)['markdown']
    original = path.read_bytes()
    altered = deepcopy(request); altered['instructions'] += ' changed'
    path.write_text(json.dumps(altered))
    with pytest.raises(ValueError): validate_recorded_request(project, request['block_context_package'], request)
    with pytest.raises(ValueError): prepare_folder_consolidation(project, binding, request, results, **kwargs)
    path.unlink()
    with pytest.raises(ValueError): validate_recorded_request(project, request['block_context_package'], request)
    with pytest.raises(ValueError): prepare_folder_consolidation(project, binding, request, results, **kwargs)
    path.write_bytes(original)
    without_id = dict(request); without_id.pop('folder_request_id')
    for invalid in (without_id, {**request, 'folder_request_id':'0'*64}):
        with pytest.raises(ValueError): validate_recorded_request(project, request['block_context_package'], invalid)


@pytest.mark.parametrize('field', ['instructions', 'result_required_keys'])
def test_new_semantic_contract_cannot_reuse_old_folder_result(project, monkeypatch, tmp_path, capsys, field):
    from tests.test_folder_consolidate_v2 import fixture_inputs
    from wiki_core.folder_request_identity_v2 import folder_request_identity, retain_folder_request, write_folder_result
    from wiki_core.llm.context_pass import context_fingerprint, read_matching_result
    from wiki_core.llm.cache import cache_key
    _binding, request, results = fixture_inputs(project, monkeypatch, tmp_path, capsys, raw=True)
    paths = FolderWikiPaths(project, load_config(project), 'a')
    changed = deepcopy(request)
    if field == 'instructions': changed[field] += ' A new instruction.'
    else: changed[field].append('new_required_field')
    row = changed['chunks'][0]
    row['context_sha256'] = context_fingerprint(changed, row['provenance'])
    row['cache_key'] = cache_key(row['chunk_hash_sha256'], changed['prompt_version'], changed['schema_version'],
                                 changed['model_profile'], context_sha256=row['context_sha256'])
    changed['folder_request_id'] = folder_request_identity(changed)
    assert row['cache_key'] != request['chunks'][0]['cache_key']
    assert not result_matches_request(results[0], changed, row, recording=True)
    assert read_matching_result(paths.llm_cache, changed, row, root=project) is None
    retained = retain_folder_request(project, paths, changed)
    assert retained.exists() and retained != retain_folder_request(project, paths, request)
    updated = {**results[0], 'cache_key':row['cache_key'], 'context_sha256':row['context_sha256']}
    if field == 'result_required_keys':
        assert not result_matches_request(updated, changed, row, recording=True)
        updated['new_required_field'] = 'synthetic'
    assert result_matches_request(updated, changed, row, recording=True)
    write_folder_result(paths.llm_cache/'folder-v2', updated)
    assert read_matching_result(paths.llm_cache, changed, row, root=project) == updated


def test_folder_retention_limits_reject_before_writing(project, tmp_path):
    from wiki_core.folder_request_identity_v2 import write_folder_result
    from wiki_core.llm.context_pass import ContextRequestBlocked, enforce_request_budget
    with pytest.raises(ContextRequestBlocked, match='2000000'):
        enforce_request_budget({'context_binding_version':2, 'chunks':[]}, request_max_bytes=2_000_001)
    template = json.loads((Path(__file__).resolve().parents[1] / 'tests/fixtures/e2e/context_pass_result.sample.json').read_text())
    result = {**template, 'cache_key':'a'*64, 'source_id':'source-synthetic', 'chunk_id':'chunk',
              'claims':['x' * 2_000_000]}
    cache = tmp_path/'result-cache'
    with pytest.raises(ContextRequestBlocked, match='2000000'):
        write_folder_result(cache, result)
    assert not cache.exists()


def test_interrupted_publication_leaves_no_final_or_temporary_file(tmp_path, monkeypatch):
    import os
    from wiki_core.folder_request_identity_v2 import write_folder_result
    template = json.loads((Path(__file__).resolve().parents[1] / 'tests/fixtures/e2e/context_pass_result.sample.json').read_text())
    result = {**template, 'cache_key':'a'*64, 'source_id':'source-synthetic', 'chunk_id':'chunk'}
    def failed_link(*args, **kwargs): raise OSError('synthetic interruption')
    monkeypatch.setattr(os, 'link', failed_link)
    cache = tmp_path/'result-cache'
    with pytest.raises(OSError): write_folder_result(cache, result)
    assert list(cache.iterdir()) == []


def test_conflicting_result_batch_reports_failure_after_first_result(project, monkeypatch, tmp_path, capsys):
    sha, selection = setup(project)
    prepared = run(str(project/'a/source.md'), 'system', project, load_config(project),
                   approved_revision=sha, folder_selection=selection)
    request = json.loads((project/prepared.request_path).read_text())
    first = _synthetic_result(request); second = deepcopy(first)
    second['claims'] = ['Different synthetic interpretation.']
    cli = _recording_cli(project, sha, request, monkeypatch, tmp_path)
    (tmp_path/'synthetic-result.json').write_text(json.dumps([first, second]))
    assert cli.main() == 2
    assert json.loads(capsys.readouterr().out)['error_code'] == 'folder_result_conflict'
    cache = FolderWikiPaths(project, load_config(project), 'a').llm_cache/'folder-v2'/f"{first['cache_key']}.json"
    assert json.loads(cache.read_text()) == first


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
    assert plain.request_path != captured.request_path
    assert plain_request['folder_request_id'] != request['folder_request_id']
    assert json.loads((project / plain.request_path).read_text()) == plain_request
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
    plain_module = _recording_cli(project, sha, plain_request, monkeypatch, tmp_path)
    assert plain_module.main() == 0
    capsys.readouterr()
    plain_cache = FolderWikiPaths(project, load_config(project), 'a').llm_cache / 'folder-v2' / (plain_request['chunks'][0]['cache_key'] + '.json')
    assert plain_cache.exists()
    retained = plain_cache.read_bytes()
    assert plain_module.main() == 0
    capsys.readouterr()
    different = _synthetic_result(plain_request)
    different['claims'] = ['Another synthetic interpretation.']
    (tmp_path / 'synthetic-result.json').write_text(json.dumps(different))
    assert plain_module.main() == 2
    assert json.loads(capsys.readouterr().out)['error_code'] == 'folder_result_conflict'
    assert plain_cache.read_bytes() == retained
    before_reemit = (project / plain.request_path).read_bytes()
    repeated = run(source, 'system', project, load_config(project), approved_revision=sha,
                   folder_selection=selection)
    assert repeated.request_path == plain.request_path
    assert (project / plain.request_path).read_bytes() == before_reemit
    assert json.loads((project / plain.request_path).read_text()) == plain_request
    assert json.loads((project / captured.request_path).read_text()) == request
    old_location = (project / captured.request_path).parent / (request['source_id'] + '-llm-context-request.json')
    old_location.write_text(json.dumps(request))
    (project / captured.request_path).unlink()
    module = _recording_cli(project, sha, request, monkeypatch, tmp_path)
    monkeypatch.setattr(sys, 'argv', [*sys.argv, '--folder-queries', str(query_file)])
    assert module.main() == 2


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


def test_distinct_destinations_preserve_and_record_both_requests(project, monkeypatch, tmp_path, capsys):
    from dataclasses import replace
    sha, selection = setup(project)
    config = load_config(project)
    source = str(project / 'a/source.md')
    first = run(source, 'system', project, config, approved_revision=sha, folder_selection=selection)
    other = replace(selection, output_path='a/another-result.md')
    second = run(source, 'system', project, config, approved_revision=sha, folder_selection=other)
    assert not first.blocked and not second.blocked and first.request_path != second.request_path
    first_request = json.loads((project / first.request_path).read_text())
    second_request = json.loads((project / second.request_path).read_text())
    assert first_request['source_id'] == second_request['source_id']
    assert first_request['folder_request_id'] != second_request['folder_request_id']
    cli = _recording_cli(project, sha, second_request, monkeypatch, tmp_path)
    argv = list(sys.argv); argv[argv.index('--folder-output') + 1] = other.output_path
    monkeypatch.setattr(sys, 'argv', argv)
    assert cli.main() == 0
    capsys.readouterr()
    cli = _recording_cli(project, sha, first_request, monkeypatch, tmp_path)
    assert cli.main() == 0
    capsys.readouterr()
    assert json.loads((project / first.request_path).read_text()) == first_request
    assert json.loads((project / second.request_path).read_text()) == second_request


def test_query_selection_without_folder_fails_closed(project):
    sha, _, query = setup_query(project)
    result = run(str(project / 'a/source.md'), 'system', project, load_config(project),
                 approved_revision=sha, policy_context='root', folder_queries=[query])
    assert result.blocked and not result.written


def test_query_file_rejects_ambiguous_or_empty_input(tmp_path):
    from wiki_core.folder_ingestion_v2 import load_folder_queries
    path = tmp_path / 'queries.json'
    for content in ('[]', '[{"target":"a", "target":"b"}]', '{}'):
        path.write_text(content)
        with pytest.raises(ValueError):
            load_folder_queries(path)


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
