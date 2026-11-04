"""A source may have multiple semantic requests without changing v1/v2 receipts."""
import importlib.util
import json
import datetime as dt
from pathlib import Path

import pytest

from tests.test_folder_policy_v2 import project
from wiki_core.config import load_config
from wiki_core.paths import WikiPaths


@pytest.fixture
def inputs(project):
    from wiki_core.folder_request_identity_v2 import request_identity, request_identity_path
    paths = WikiPaths(project, load_config(project))
    paths.extraction_events.mkdir(parents=True, exist_ok=True)
    paths.ingest_events_dir.mkdir(parents=True, exist_ok=True)
    first = {'context_binding_version': 1, 'source_id': 'source-example', 'chunks': [],
             'block_context_package': {'documents': [{'path': 'a/index.md'}]}}
    second = {**first, 'block_context_package': {'documents': [{'path': 'b/index.md'}]}}
    for request in (first, second):
        request['folder_request_id'] = request_identity(request)
        request_identity_path(paths, request['source_id'], request['folder_request_id']).write_text(json.dumps(request))
    spec = importlib.util.spec_from_file_location('wiki_consolidate_selection',
        Path(__file__).resolve().parents[1] / 'scripts/wiki_consolidate.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return paths, module, first, second


def test_request_selection_requires_disambiguation(inputs):
    from wiki_core.folder_request_identity_v2 import request_identity
    paths, module, first, second = inputs
    with pytest.raises(ValueError, match='ambiguous'):
        module._request_for(paths, 'source-example')
    assert module._request_for(paths, 'source-example', request_id=request_identity(first)) == first
    assert module._request_for(paths, 'source-example', request_id=request_identity(second)) == second
    assert module._request_for(paths, 'source-example', request_id='0' * 64) is None
    with pytest.raises(ValueError):
        module._request_for(paths, 'source-example', request_id='../outside')


def test_event_selection_distinguishes_requests_and_preserves_legacy(inputs):
    from wiki_core.consolidate import find_event_for_source
    from wiki_core.folder_request_identity_v2 import request_identity
    paths, _, first, second = inputs
    legacy = paths.ingest_events_dir / '2026-11-04-source-example.md'
    legacy.write_text('---\nsource_id: source-example\n---\nlegacy\n')
    assert find_event_for_source(paths, 'source-example', root=paths.root) == legacy
    assert find_event_for_source(paths, 'source-example', request_id=request_identity(first), root=paths.root) is None
    event = paths.ingest_events_dir / f'2026-11-04-source-example-{request_identity(first)}.md'
    event.write_text(f'---\nsource_id: source-example\nfolder_request_id: {request_identity(first)}\n---\nfirst\n')
    assert find_event_for_source(paths, 'source-example', request_id=request_identity(first), root=paths.root) == event
    assert find_event_for_source(paths, 'source-example', request_id=request_identity(second), root=paths.root) is None


def test_request_identity_keeps_v2_digest_and_accepts_pre_binding_legacy():
    from wiki_core.folder_request_identity_v2 import folder_request_identity, request_identity
    v2 = {'context_binding_version': 2, 'source_id': 'source-synthetic', 'chunks': []}
    expected = '7f904689a390fed22981dd2dac31f2e8b5e956c572f8e9795e884875a8d2fb97'
    assert request_identity(v2) == folder_request_identity(v2) == expected
    legacy = {'source_id': 'source-synthetic', 'chunks': []}
    assert len(request_identity(legacy)) == 64
    with pytest.raises(ValueError):
        folder_request_identity(legacy)


def test_multiple_matching_events_are_not_silently_selected(inputs):
    from wiki_core.consolidate import find_event_for_source
    from wiki_core.folder_request_identity_v2 import request_identity
    paths, _, first, _ = inputs
    selected = request_identity(first)
    for date in ('2026-11-03', '2026-11-04'):
        (paths.ingest_events_dir / f'{date}-source-example-{selected}.md').write_text(
            f'---\nsource_id: source-example\nfolder_request_id: {selected}\n---\n')
    with pytest.raises(ValueError, match='ambiguous'):
        find_event_for_source(paths, 'source-example', request_id=selected, root=paths.root)


def test_pending_gate_does_not_close_other_request_from_same_source(inputs, monkeypatch):
    import wiki_core.consolidate as consolidate
    from wiki_core.folder_request_identity_v2 import request_identity
    paths, _, first, second = inputs
    monkeypatch.setattr(consolidate, 'deep_read_complete', lambda *_args, **_kwargs: True)
    selected = request_identity(first)
    (paths.ingest_events_dir / f'first-{selected}.md').write_text(
        f'---\nsource_id: source-example\nfolder_request_id: {selected}\nconsolidated_into: [page]\n---\n')
    pending = consolidate.pending_consolidations(paths.root, paths.config)
    assert pending == [{'source_id': 'source-example', 'request_id': request_identity(second), 'state': 'missing_event'}]


def test_legacy_event_does_not_close_either_ambiguous_request(inputs, monkeypatch):
    import wiki_core.consolidate as consolidate
    from wiki_core.folder_request_identity_v2 import request_identity
    paths, _, first, second = inputs
    monkeypatch.setattr(consolidate, 'deep_read_complete', lambda *_args, **_kwargs: True)
    (paths.ingest_events_dir / 'legacy.md').write_text(
        '---\nsource_id: source-example\nconsolidated_into: [page]\n---\n')
    pending = consolidate.pending_consolidations(paths.root, paths.config)
    assert {item['request_id'] for item in pending} == {request_identity(first), request_identity(second)}
    assert all(item['state'] == 'missing_event' for item in pending)


def test_single_identified_request_cannot_be_closed_by_legacy_event(inputs, monkeypatch):
    import wiki_core.consolidate as consolidate
    from wiki_core.folder_request_identity_v2 import request_identity, request_identity_path
    paths, _, first, second = inputs
    request_identity_path(paths, second['source_id'], request_identity(second)).unlink()
    monkeypatch.setattr(consolidate, 'deep_read_complete', lambda *_args, **_kwargs: True)
    (paths.ingest_events_dir / 'legacy.md').write_text(
        '---\nsource_id: source-example\nconsolidated_into: [page]\n---\n')
    assert consolidate.pending_consolidations(paths.root, paths.config) == [
        {'source_id': 'source-example', 'request_id': request_identity(first), 'state': 'missing_event'}]


def test_single_unidentified_legacy_request_keeps_existing_event(inputs, monkeypatch):
    import wiki_core.consolidate as consolidate
    from wiki_core.folder_request_identity_v2 import request_identity, request_identity_path
    paths, _, first, second = inputs
    for request in (first, second):
        request_identity_path(paths, request['source_id'], request_identity(request)).unlink()
    legacy = {key: value for key, value in first.items() if key != 'folder_request_id'}
    (paths.extraction_events / 'source-example-llm-context-request.json').write_text(json.dumps(legacy))
    (paths.ingest_events_dir / 'legacy.md').write_text(
        '---\nsource_id: source-example\nconsolidated_into: [page]\n---\n')
    monkeypatch.setattr(consolidate, 'deep_read_complete', lambda *_args, **_kwargs: True)
    assert consolidate.pending_consolidations(paths.root, paths.config) == []


def test_legacy_and_identified_requests_can_be_selected_independently(inputs, monkeypatch):
    from wiki_core.consolidate import find_event_for_source
    from wiki_core.folder_request_identity_v2 import request_identity, request_identity_path
    paths, module, first, second = inputs
    selected_id = request_identity(first)
    request_identity_path(paths, first['source_id'], selected_id).unlink()
    legacy = {key: value for key, value in first.items() if key != 'folder_request_id'}
    legacy_path = paths.extraction_events / 'source-example-llm-context-request.json'
    legacy_path.write_text(json.dumps(legacy))
    assert module._request_for(paths, 'source-example', request_id=selected_id) == legacy
    assert module._request_for(paths, 'source-example', request_id=request_identity(second)) == second
    monkeypatch.setattr(module, 'ROOT', paths.root)
    monkeypatch.setattr(module, 'deep_read_complete', lambda *_args, **_kwargs: True)
    monkeypatch.setattr(module, 'aggregate_results', lambda req, *_args, **_kwargs: {'source_id': req['source_id']})
    monkeypatch.setattr(module, 'build_packet', lambda *_args, **_kwargs: {'impact': {}})
    assert module.consolidate_one('source-example', request_id=selected_id, emit_event=True,
        packet=False, source_page=None, source_ref='source-page', context='system',
        date=dt.date(2026, 11, 4), force=False) == 0
    assert find_event_for_source(paths, 'source-example', request_id=selected_id, root=paths.root)
    assert json.loads(legacy_path.read_text()) == legacy
    # A present but invalid identity-qualified file cannot fall back to legacy.
    request_identity_path(paths, first['source_id'], selected_id).write_text('{"source_id":"different"}')
    with pytest.raises(ValueError, match='request differs'):
        module._request_for(paths, 'source-example', request_id=selected_id)


def test_exact_selection_does_not_open_other_request_or_event(inputs, monkeypatch):
    from wiki_core.consolidate import find_event_for_source
    from wiki_core.folder_request_identity_v2 import request_identity, request_identity_path
    paths, module, first, second = inputs
    other_request = request_identity_path(paths, second['source_id'], request_identity(second))
    other_event = paths.ingest_events_dir / f'other-{request_identity(second)}.md'
    other_event.write_text(f'---\nsource_id: source-example\nfolder_request_id: {request_identity(second)}\n---\n')
    original_open = Path.open
    def guarded_open(path, *args, **kwargs):
        if path in (other_request, other_event):
            raise AssertionError('unselected body was opened')
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guarded_open)
    assert module._request_for(paths, 'source-example', request_id=request_identity(first)) == first
    assert find_event_for_source(paths, 'source-example', request_id=request_identity(first), root=paths.root) is None


def test_request_id_does_not_authorize_symlinked_request(inputs, tmp_path_factory, monkeypatch):
    from wiki_core.folder_request_identity_v2 import request_identity, request_identity_path
    paths, module, first, _ = inputs
    external = tmp_path_factory.mktemp('external-request') / 'external-request.json'
    external.write_text(json.dumps(first))
    link = request_identity_path(paths, first['source_id'], request_identity(first))
    link.unlink()
    link.symlink_to(external)
    original_open = Path.open
    def tracked_open(path, *args, **kwargs):
        if path == link or path == external:
            raise AssertionError('external request body was opened')
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', tracked_open)
    with pytest.raises(ValueError):
        module._request_for(paths, 'source-example', request_id=request_identity(first))


def test_unreadable_request_inventory_cannot_hide_ambiguity(inputs):
    from wiki_core.consolidate import pending_consolidations
    from wiki_core.folder_request_identity_v2 import request_identity
    paths, module, first, _ = inputs
    (paths.extraction_events / 'unknown-llm-context-request.json').write_text('{broken')
    assert module._request_for(paths, 'source-example', request_id=request_identity(first)) == first
    with pytest.raises(ValueError, match='inventory unavailable'):
        module._request_for(paths, 'source-example')
    with pytest.raises(ValueError, match='inventory unavailable'):
        pending_consolidations(paths.root, paths.config)


@pytest.mark.parametrize('body', ['{"source_id":"one","source_id":"two"}', '{"source_id":"one","n":NaN}'])
def test_global_inventory_rejects_ambiguous_json(inputs, body):
    from wiki_core.consolidate import pending_consolidations
    paths, module, _, _ = inputs
    (paths.extraction_events / 'unknown-llm-context-request.json').write_text(body)
    with pytest.raises(ValueError, match='inventory unavailable'):
        module._request_for(paths, 'source-example')
    with pytest.raises(ValueError, match='inventory unavailable'):
        pending_consolidations(paths.root, paths.config)


def test_consolidation_keeps_two_context_events_and_preserves_existing_work(inputs, monkeypatch):
    from wiki_core.folder_request_identity_v2 import request_identity
    from wiki_core.consolidate import find_event_for_source
    paths, module, first, second = inputs
    monkeypatch.setattr(module, 'ROOT', paths.root)
    monkeypatch.setattr(module, 'deep_read_complete', lambda *_args, **_kwargs: True)
    monkeypatch.setattr(module, 'aggregate_results', lambda request, *_args, **_kwargs: {'source_id': request['source_id']})
    monkeypatch.setattr(module, 'build_packet', lambda *_args, **_kwargs: {'impact': {}})
    args = dict(emit_event=True, packet=True, source_page=None, source_ref='source-page',
                context='system', date=dt.date(2026, 11, 4), force=False)
    ids = [request_identity(first), request_identity(second)]
    for selected in ids:
        assert module.consolidate_one('source-example', request_id=selected, **args) == 0
    events = [find_event_for_source(paths, 'source-example', request_id=value, root=paths.root) for value in ids]
    assert all(events) and events[0] != events[1]
    original = [path.read_bytes() for path in events]
    assert module.consolidate_one('source-example', request_id=ids[0], **{**args, 'force': True}) == 1
    assert [path.read_bytes() for path in events] == original
    packet = paths.extraction_events / f'{module._source_slug("source-example", bounded=True)}-{ids[0]}-integration-packet.json'
    packet.write_text('unfinished work')
    with pytest.raises(ValueError, match='packet differs'):
        module.consolidate_one('source-example', request_id=ids[0], **{**args, 'force': True})
    assert packet.read_text() == 'unfinished work'
    with pytest.raises(ValueError, match='ambiguous'):
        module.consolidate_one('source-example', **args)


def test_changed_request_blocks_before_packet_or_event(inputs, monkeypatch):
    from wiki_core.folder_request_identity_v2 import request_identity, request_identity_path
    paths, module, first, _ = inputs
    monkeypatch.setattr(module, 'ROOT', paths.root)
    monkeypatch.setattr(module, 'deep_read_complete', lambda *_args, **_kwargs: True)
    monkeypatch.setattr(module, 'aggregate_results', lambda request, *_args, **_kwargs: {'source_id': request['source_id']})
    def mutate(*_args, **_kwargs):
        request_identity_path(paths, first['source_id'], request_identity(first)).write_text(json.dumps({**first, 'instructions': 'changed'}))
        return {'impact': {}}
    monkeypatch.setattr(module, 'build_packet', mutate)
    with pytest.raises(ValueError, match='request'):
        module.consolidate_one('source-example', request_id=request_identity(first), emit_event=True,
            packet=True, source_page=None, source_ref='source-page', context='system',
            date=dt.date(2026, 11, 4), force=False)
    assert not list(paths.extraction_events.glob('*-integration-packet.json'))
    assert not list(paths.ingest_events_dir.glob('*.md'))


def test_long_source_id_uses_bounded_names_and_keeps_original_in_event(inputs, monkeypatch):
    from wiki_core.consolidate import find_event_for_source
    from wiki_core.folder_request_identity_v2 import request_identity, request_identity_path
    paths, module, _, _ = inputs
    source_id = 's' * 190
    request = {'context_binding_version': 1, 'source_id': source_id, 'chunks': []}
    request['folder_request_id'] = request_identity(request)
    request_identity_path(paths, source_id, request['folder_request_id']).write_text(json.dumps(request))
    monkeypatch.setattr(module, 'ROOT', paths.root)
    monkeypatch.setattr(module, 'deep_read_complete', lambda *_args, **_kwargs: True)
    monkeypatch.setattr(module, 'aggregate_results', lambda req, *_args, **_kwargs: {'source_id': req['source_id']})
    monkeypatch.setattr(module, 'build_packet', lambda *_args, **_kwargs: {'impact': {}})
    assert module.consolidate_one(source_id, emit_event=True, packet=True, source_page=None,
        source_ref='source-page', context='system', date=dt.date(2026, 11, 4), force=False) == 0
    event = find_event_for_source(paths, source_id, request_id=request['folder_request_id'], root=paths.root)
    assert event is not None and len(event.name.encode()) < 255
    assert f'source_id: {source_id}' in event.read_text()
    assert any(len(path.name.encode()) < 255 for path in paths.extraction_events.glob('*-integration-packet.json'))


def test_disappeared_result_blocks_before_packet_or_event(inputs, monkeypatch):
    import wiki_core.consolidate as consolidate
    from wiki_core.folder_request_identity_v2 import request_identity, request_identity_path
    paths, module, first, _ = inputs
    request = {**first, 'chunks': [{'chunk_id': 'chunk', 'source_id': first['source_id'],
        'chunk_hash_sha256': 'a' * 64, 'context_sha256': 'b' * 64, 'cache_key': 'c' * 64}]}
    request['folder_request_id'] = request_identity(request)
    request_identity_path(paths, request['source_id'], request['folder_request_id']).write_text(json.dumps(request))
    monkeypatch.setattr(module, 'ROOT', paths.root)
    monkeypatch.setattr(module, 'deep_read_complete', lambda *_args, **_kwargs: True)
    monkeypatch.setattr(consolidate, 'read_matching_result', lambda *_args, **_kwargs: None)
    with pytest.raises(ValueError, match='results unavailable'):
        module.consolidate_one(request['source_id'], request_id=request['folder_request_id'],
            emit_event=True, packet=True, source_page=None, source_ref='source-page',
            context='system', date=dt.date(2026, 11, 4), force=False)
    assert not list(paths.extraction_events.glob('*-integration-packet.json'))
    assert not list(paths.ingest_events_dir.glob('*.md'))
