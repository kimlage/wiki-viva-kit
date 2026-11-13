"""Folder captures do not inspect shared indexes or ledgers."""
import json
import sys
import yaml

from tests.test_folder_policy_v2 import project, put, commit, git
from tests.test_folder_ingestion_v2 import setup, _recording_cli
from wiki_core.config import load_config
from wiki_core.folder_coordination_v2 import FolderHostBinding
from wiki_core.folder_ingestion_v2 import FolderIngestionSelection, validate_folder_artifact_paths
from wiki_core.ingest import run
from wiki_core.paths import FolderWikiPaths, WikiPaths


def test_folder_capture_does_not_touch_global_index_or_score(project, monkeypatch):
    import wiki_core.ingest.pipeline as pipeline
    sha, selection = setup(project)
    paths = WikiPaths(project, load_config(project))
    paths.indexes.mkdir(parents=True)
    database = paths.indexes / 'wiki.sqlite'
    database.write_bytes(b'global index sentinel')
    ledger = paths.derived_root / 'score-events.jsonl'
    ledger.write_text('global ledger sentinel\n')
    monkeypatch.setattr(pipeline, 'index_source', lambda *_: (_ for _ in ()).throw(AssertionError('global index accessed')))
    monkeypatch.setattr(pipeline, 'record_event', lambda *_, **__: (_ for _ in ()).throw(AssertionError('global ledger accessed')))
    result = run(str(project / 'a/source.md'), 'system', project, load_config(project),
                 approved_revision=sha, folder_selection=selection)
    assert result.written and not result.blocked and result.chunks_indexed == 0 and result.score_event_id is None
    assert 'global index or score ledger' in ' '.join(result.warnings)
    assert database.read_bytes() == b'global index sentinel'
    assert ledger.read_text() == 'global ledger sentinel\n'


def test_folder_stream_cursor_is_blocked_before_capture(project):
    sha, selection = setup(project)
    result = run(str(project / 'a/source.md'), 'system', project, load_config(project),
                 approved_revision=sha, folder_selection=selection, stream_id='example')
    assert result.blocked and not result.written
    assert result.context_error_code == 'folder_stream_cursor_unavailable'
    assert not WikiPaths(project, load_config(project)).derived_root.exists()


def test_two_authorized_contexts_keep_same_source_artifacts_distinct(project, monkeypatch, tmp_path, capsys):
    setup(project)
    put(project, 'b/AGENTS.md', 'Context b\n')
    put(project, 'b/index.md', 'Context b index\n')
    controls_path = project / 'wiki-context-controls.yaml'
    controls = yaml.safe_load(controls_path.read_text())
    grants = [{'from_context':'a', 'to_context':'b', 'selector':path,
               'use':'interpretation', 'classification':classification, 'expires':'2099-01-01'}
              for path, classification in [('a/source.md', 'source'), ('a/root.md', 'context')]]
    controls['controls']['a']['exports'] = grants
    controls['controls']['b'] = {'policy':{'read':['self', 'a/source.md', 'a/root.md'], 'write':['self']},
                                 'imports':grants, 'exports':[]}
    controls_path.write_text(yaml.safe_dump(controls))
    commit(project)
    sha = git(project, 'rev-parse', 'HEAD')
    host = FolderHostBinding(project, ('a', 'b'))
    first_selection = FolderIngestionSelection(host, 'a', 'a/index.md', 'a/result.md')
    second_selection = FolderIngestionSelection(host, 'b', 'b/index.md', 'b/result.md')
    config = load_config(project)
    source = str(project / 'a/source.md')
    first = run(source, 'system', project, config, approved_revision=sha, folder_selection=first_selection)
    assert first.written and not first.blocked
    first_request = json.loads((project / first.request_path).read_text())
    first_files = {rel:(project / rel).read_bytes() for rel in
                   (first.manifest_path, first.text_path, first.chunks_path, first.request_path)}
    legacy = WikiPaths(project, config)
    legacy.extraction_events.mkdir(parents=True)
    legacy_request = legacy.extraction_events / (first.source_id + '-llm-context-request.json')
    legacy_request.write_text('legacy request sentinel\n')
    second = run(source, 'system', project, config, approved_revision=sha, folder_selection=second_selection)
    assert second.written and not second.blocked
    assert first.source_id == second.source_id and first.request_path != second.request_path
    assert all((project / rel).read_bytes() == content for rel, content in first_files.items())
    second_request = json.loads((project / second.request_path).read_text())
    assert first_request['chunks'][0]['cache_key'] != second_request['chunks'][0]['cache_key']
    assert first_request['block_context_package']['context_folder'] == 'a'
    assert second_request['block_context_package']['context_folder'] == 'b'

    module = _recording_cli(project, sha, first_request, monkeypatch, tmp_path)
    assert module.main() == 0
    capsys.readouterr()
    first_cache = FolderWikiPaths(project, config, 'a').llm_cache / 'folder-v2' / (first_request['chunks'][0]['cache_key'] + '.json')
    assert first_cache.is_file()
    module = _recording_cli(project, sha, second_request, monkeypatch, tmp_path)
    args = list(sys.argv)
    for flag, value in [('--folder-context','b'), ('--folder-output','b/result.md')]:
        args[args.index(flag) + 1] = value
    args.extend(['--folder-index', 'b/index.md'])
    monkeypatch.setattr(sys, 'argv', args)
    monkeypatch.setenv('WIKI_FOLDER_INGEST_HOST_FOLDERS', 'a,b')
    assert module.main() == 0
    capsys.readouterr()
    second_cache = FolderWikiPaths(project, config, 'b').llm_cache / 'folder-v2' / (second_request['chunks'][0]['cache_key'] + '.json')
    assert first_cache.is_file() and second_cache.is_file()
    assert legacy_request.read_text() == 'legacy request sentinel\n'


def test_folder_validator_rejects_legacy_artifact_namespace(project):
    import pytest
    with pytest.raises(ValueError, match='folder-scoped artifact namespace required'):
        validate_folder_artifact_paths(project, WikiPaths(project, load_config(project)), 'synthetic')


def test_folder_recording_rejects_legacy_artifact_namespace(project, capsys):
    from scripts.wiki_llm_context_pass import _record_results
    packet = {'schema_version':'wiki.folder-task-context/v2', 'context_folder':'a'}
    request = {'source_id':'synthetic', 'context_binding_version':2, 'block_context_package':packet}
    result = _record_results(WikiPaths(project, load_config(project)), 'nonexistent-payload.json',
                             current_request=request, before_write=lambda: None)
    assert result == 2
    assert json.loads(capsys.readouterr().out)['blocked']
