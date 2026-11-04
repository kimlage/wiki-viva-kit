"""Folder captures do not inspect shared indexes or ledgers."""
from tests.test_folder_policy_v2 import project
from tests.test_folder_ingestion_v2 import setup
from wiki_core.config import load_config
from wiki_core.ingest import run
from wiki_core.paths import WikiPaths


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
