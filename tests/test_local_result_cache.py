"""Local folder results cannot be satisfied through legacy cache writes."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from tests.test_ingestion_budget import approved, execute
from wiki_core.config import load_config
from wiki_core.ingest import run
from wiki_core.llm.context_pass import (context_fingerprint, read_matching_result,
                                        result_cache_for_request, result_matches_request)
from wiki_core.paths import WikiPaths


def module(name):
    path = Path(__file__).resolve().parents[1] / 'scripts' / f'{name}.py'
    spec = importlib.util.spec_from_file_location('local_cache_' + name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def result_for(request, row):
    fixture = Path(__file__).parent / 'fixtures/e2e/context_pass_result.sample.json'
    return {**json.loads(fixture.read_text()), 'perspectives': {
        key: {'status': 'extracted'} for key in request.get('perspectives_required', [])},
        **{key: request[key] for key in ('source_id', 'prompt_version', 'schema_version', 'model_profile')},
        **{key: row[key] for key in ('cache_key', 'chunk_id', 'context_sha256', 'chunk_hash_sha256')}}


@pytest.mark.parametrize('allow_unrequested', [False, True])
def test_legacy_paths_do_not_satisfy_local_request(approved, monkeypatch, tmp_path, capsys, allow_unrequested):
    from wiki_core.consolidate import deep_read_complete
    root, source, _, _ = approved
    (root / 'area').mkdir(exist_ok=True)
    (root / 'area/AGENTS.md').write_text('Local guidance')
    (root / 'area/index.md').write_text('Local index')
    config = load_config(root)
    prepared = run(str(source), 'system', root, config, entry_folder='area', record_score=False)
    assert not prepared.blocked
    request = json.loads((root / prepared.request_path).read_text())
    row = request['chunks'][0]
    result = result_for(request, row)
    assert result_matches_request(result, request, row, recording=True)
    changed_status = {**request, 'input_stage_status': 'legacy'}
    assert context_fingerprint(request, row['provenance']) != context_fingerprint(changed_status, row['provenance'])
    payload = tmp_path / 'result.json'
    payload.write_text(json.dumps(result))
    cli = module('wiki_llm_context_pass')
    monkeypatch.chdir(root)
    monkeypatch.setattr(sys, 'argv', ['wiki_llm_context_pass.py', '--root', str(root), '--context', 'system',
        '--record-result', str(payload), *(['--allow-unrequested'] if allow_unrequested else [])])
    assert cli.main() == (0 if allow_unrequested else 2)
    capsys.readouterr()
    paths = WikiPaths(root, config)
    legacy = paths.llm_cache / f"{row['cache_key']}.json"
    assert legacy.exists() is allow_unrequested
    legacy_bytes = legacy.read_bytes() if legacy.exists() else None
    assert read_matching_result(paths.llm_cache, request, row, root=root) is None
    assert not deep_read_complete(request, paths.llm_cache, root=root)

    unique = {}
    for selected in request['chunks']:
        unique.setdefault(selected['cache_key'], result_for(request, selected))
    payload.write_text(json.dumps(list(unique.values())))
    monkeypatch.setattr(sys, 'argv', ['wiki_llm_context_pass.py', '--root', str(root), '--source', str(source),
        '--context', 'system', '--folder', 'area', '--record-result', str(payload)])
    assert cli.main() == 0
    capsys.readouterr()
    assert read_matching_result(paths.llm_cache, request, row, root=root) == result
    with pytest.raises(ValueError, match='local_result_root_unavailable'):
        read_matching_result(paths.llm_cache, request, row)
    assert deep_read_complete(request, paths.llm_cache, root=root)
    assert (result_cache_for_request(paths.llm_cache, request) / f"{row['cache_key']}.json").is_file()
    audit = module('wiki_audit')
    monkeypatch.setattr(audit, 'ROOT', root)
    errors, warnings = [], []
    audit.audit_context_pass_gate(errors, config, warnings)
    audit.audit_llm_cache_metadata(errors, config)
    assert not errors
    from wiki_core.quality import build_quality_report
    report = build_quality_report(root, config)
    telemetry = next(item for item in report['cost_telemetry']['source_costs'] if item['source_id'] == request['source_id'])
    assert telemetry['cached_calls'] == len(request['chunks']) and telemetry['pending_calls'] == 0
    if legacy_bytes is not None:
        assert legacy.read_bytes() == legacy_bytes


def test_existing_approved_v1_result_still_uses_same_bytes_and_location(approved):
    root, _, _, _ = approved
    produced = execute(approved)
    assert not produced.blocked
    request = json.loads((root / produced.request_path).read_text())
    row = request['chunks'][0]
    result = result_for(request, row)
    assert result_matches_request(result, request, row, recording=True)
    paths = WikiPaths(root, load_config(root))
    path = paths.llm_cache / f"{row['cache_key']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(result, ensure_ascii=False, sort_keys=True).encode()
    path.write_bytes(raw)
    assert result_cache_for_request(paths.llm_cache, request) == paths.llm_cache
    assert read_matching_result(paths.llm_cache, request, row, root=root) == result
    assert path.read_bytes() == raw


def test_local_write_requires_matching_request_and_revalidation(approved):
    from wiki_core.llm.context_pass import write_result
    root, source, _, _ = approved
    (root / 'area').mkdir(exist_ok=True)
    (root / 'area/AGENTS.md').write_text('Local guidance')
    (root / 'area/index.md').write_text('Local index')
    config = load_config(root)
    produced = run(str(source), 'system', root, config, entry_folder='area', record_score=False)
    request = json.loads((root / produced.request_path).read_text())
    result = result_for(request, request['chunks'][0])
    cache = WikiPaths(root, config).llm_cache
    with pytest.raises(ValueError, match='bound recording'):
        write_result(cache, result, request=request, preserve_existing=True)
    def denied():
        raise ValueError('synthetic revalidation failure')
    with pytest.raises(ValueError, match='revalidation failure'):
        write_result(cache, result, request=request, preserve_existing=True, before_write=denied)
    assert not (cache / 'local-folder').exists()


@pytest.mark.parametrize('boundary', ['symlink', 'git_file', 'git_directory'])
def test_unsafe_local_cache_is_unavailable_not_zero(approved, monkeypatch, tmp_path_factory, capsys, boundary):
    from tests.test_operation_compile import _load_module
    from wiki_core.consolidate import pending_consolidations
    root, source, _, _ = approved
    (root / 'area').mkdir(exist_ok=True)
    (root / 'area/AGENTS.md').write_text('Local guidance')
    (root / 'area/index.md').write_text('Local index')
    config = load_config(root)
    produced = run(str(source), 'system', root, config, entry_folder='area', record_score=False)
    assert not produced.blocked
    request = json.loads((root / produced.request_path).read_text())
    row = request['chunks'][0]
    paths = WikiPaths(root, config)
    assert read_matching_result(paths.llm_cache, request, row, root=root) is None
    local_cache = paths.llm_cache / 'local-folder'
    local_cache.parent.mkdir(parents=True, exist_ok=True)
    if boundary == 'symlink':
        external = tmp_path_factory.mktemp('external-cache')
        (external / f"{row['cache_key']}.json").write_text('must not open')
        local_cache.symlink_to(external, target_is_directory=True)
    else:
        local_cache.mkdir()
        if boundary == 'git_file':
            (local_cache / '.git').write_text('gitdir: elsewhere')
        else:
            (local_cache / '.git').mkdir()
        (local_cache / f"{row['cache_key']}.json").write_text('must not open')
    target = local_cache / f"{row['cache_key']}.json"
    original = Path.read_text
    def guarded(path, *args, **kwargs):
        if path == target:
            pytest.fail('unsafe cache body opened')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', guarded)
    with pytest.raises(ValueError):
        read_matching_result(paths.llm_cache, request, row, root=root)
    with pytest.raises(ValueError):
        pending_consolidations(root, config)
    cli = module('wiki_consolidate')
    monkeypatch.setattr(cli, 'ROOT', root)
    monkeypatch.setattr(sys, 'argv', ['wiki_consolidate.py', '--check'])
    assert cli.main() == 2
    captured = capsys.readouterr()
    assert '"total": 0' not in captured.out
    compile_mod = _load_module()
    page = compile_mod.build_page(root, config)
    assert 'Sources awaiting consolidation: unavailable' in page
    assert 'Sources awaiting consolidation: 0' not in page


def test_two_contexts_retain_results_events_and_gates(approved, monkeypatch, tmp_path, capsys):
    import datetime
    from wiki_core.consolidate import pending_consolidations
    from wiki_core.quality import build_quality_report
    root, source, _, _ = approved
    config = load_config(root)
    paths = WikiPaths(root, config)
    cli = module('wiki_llm_context_pass')
    consolidate = module('wiki_consolidate')
    audit = module('wiki_audit')
    gc = module('wiki_gc')
    monkeypatch.setattr(consolidate, 'ROOT', root)
    monkeypatch.setattr(audit, 'ROOT', root)
    monkeypatch.chdir(root)
    results = []
    for folder in ('one', 'two'):
        (root / folder).mkdir()
        (root / folder / 'index.md').write_text(f'{folder} index')
        (root / folder / 'AGENTS.md').write_text(f'{folder} guidance')
        produced = run(str(source), 'system', root, config, entry_folder=folder, record_score=False)
        assert not produced.blocked
        request = json.loads((root / produced.request_path).read_text())
        unique = {row['cache_key']: result_for(request, row) for row in request['chunks']}
        payload = tmp_path / f'{folder}-results.json'
        payload.write_text(json.dumps(list(unique.values())))
        monkeypatch.setattr(sys, 'argv', ['wiki_llm_context_pass.py', '--root', str(root), '--source', str(source),
            '--context', 'system', '--folder', folder, '--record-result', str(payload)])
        assert cli.main() == 0
        capsys.readouterr()
        results.append((produced, request))
    assert results[0][0].source_id == results[1][0].source_id
    assert results[0][1]['folder_request_id'] != results[1][1]['folder_request_id']
    assert {p['folder_request_id'] for p in pending_consolidations(root, config)} == {
        request['folder_request_id'] for _, request in results}
    errors, warnings = [], []
    audit.audit_context_pass_gate(errors, config, warnings)
    assert not errors
    report = build_quality_report(root, config)
    telemetry = [item for item in report['cost_telemetry']['source_costs'] if item['source_id'] == results[0][0].source_id]
    assert len(telemetry) == 2 and all(item['pending_calls'] == 0 for item in telemetry)
    assert report['summary']['chunks_total'] == len(results[0][1]['chunks'])
    assert report['summary']['interpretation_chunks'] == 2 * len(results[0][1]['chunks'])
    assert report['summary']['cache_reuse_rate'] == 1
    assert not gc.find_orphans(paths, {'some-other-live-source'}, wiki_root=root)

    paths.ingest_events_dir.mkdir(parents=True, exist_ok=True)
    legacy_event = paths.ingest_events_dir / 'legacy.md'
    legacy_event.write_text(f'---\nsource_id: {results[0][0].source_id}\nconsolidated_into:\n  - old-page\n---\n')
    assert len(pending_consolidations(root, config)) == 2
    legacy_event.unlink()
    common = dict(emit_event=True, packet=True, source_page=None, context='system',
                  date=datetime.date(2026, 11, 4), force=False)
    # Missing source identity fails before either output is written.
    assert consolidate.consolidate_one(results[0][0].source_id, source_ref=None,
        request_path=results[0][0].request_path, **common) == 1
    assert not list(paths.extraction_events.glob('*-integration-packet.json'))
    assert not list(paths.ingest_events_dir.glob('*.md'))
    for produced, request in results:
        assert consolidate.consolidate_one(produced.source_id, source_ref='source-test',
            request_path=produced.request_path, **common) == 0
    events = list(paths.ingest_events_dir.glob('*.md'))
    assert len(events) == 2
    assert all(request['folder_request_id'] in event.read_text() for (_, request), event in
               zip(sorted(results, key=lambda r: r[1]['folder_request_id']), sorted(events)))
    assert len(pending_consolidations(root, config)) == 2


def test_two_contexts_refuse_divergent_or_partial_capture_without_replacing_wip(approved):
    root, source, _, _ = approved
    config = load_config(root)
    for folder in ('one', 'two'):
        (root / folder).mkdir()
        (root / folder / 'index.md').write_text(f'{folder} index')
        (root / folder / 'AGENTS.md').write_text(f'{folder} guidance')
    first = run(str(source), 'system', root, config, entry_folder='one', record_score=False)
    capture = root / first.chunks_path
    request = root / first.request_path
    original = capture.read_bytes()
    existing_request = request.read_bytes()
    payload = json.loads(original)
    payload['chunks'][0]['text'] = 'Different uncommitted work'
    capture.write_text(json.dumps(payload))
    changed = capture.read_bytes()
    second = run(str(source), 'system', root, config, entry_folder='two', record_score=False)
    assert second.blocked and capture.read_bytes() == changed and request.read_bytes() == existing_request
    capture.unlink()
    second = run(str(source), 'system', root, config, entry_folder='two', record_score=False)
    assert second.blocked and not capture.exists() and request.read_bytes() == existing_request


def test_local_consolidation_rejects_changed_context_and_vanished_result(approved, monkeypatch, tmp_path, capsys):
    import datetime
    import wiki_core.consolidate as core
    root, source, _, _ = approved
    config = load_config(root)
    folder = root / 'area'
    folder.mkdir()
    (folder / 'index.md').write_text('index')
    instruction = folder / 'AGENTS.md'
    instruction.write_text('guidance')
    produced = run(str(source), 'system', root, config, entry_folder='area', record_score=False)
    request = json.loads((root / produced.request_path).read_text())
    cli, consolidate = module('wiki_llm_context_pass'), module('wiki_consolidate')
    monkeypatch.setattr(consolidate, 'ROOT', root)
    monkeypatch.chdir(root)
    payload = tmp_path / 'results.json'
    payload.write_text(json.dumps(list({row['cache_key']: result_for(request, row) for row in request['chunks']}.values())))
    monkeypatch.setattr(sys, 'argv', ['wiki_llm_context_pass.py', '--root', str(root), '--source', str(source),
        '--context', 'system', '--folder', 'area', '--record-result', str(payload)])
    assert cli.main() == 0
    capsys.readouterr()
    paths = WikiPaths(root, config)
    paths.ingest_events_dir.mkdir(parents=True, exist_ok=True)
    args = dict(emit_event=True, packet=True, source_page=None, source_ref='source-test', context='system',
                date=datetime.date(2026, 11, 4), force=False, request_path=produced.request_path)
    instruction.write_text('changed')
    assert consolidate.consolidate_one(produced.source_id, **args) == 1
    assert not list(paths.ingest_events_dir.glob('*.md'))
    assert not list(paths.extraction_events.glob('*-integration-packet.json'))
    instruction.write_text('guidance')
    original = core.read_matching_result
    reads = 0
    def vanish(*args, **kwargs):
        nonlocal reads
        reads += 1
        return original(*args, **kwargs) if reads <= len(request['chunks']) else None
    monkeypatch.setattr(core, 'read_matching_result', vanish)
    with pytest.raises(ValueError, match='disappeared'):
        consolidate.consolidate_one(produced.source_id, **args)
    assert not list(paths.ingest_events_dir.glob('*.md'))
    assert not list(paths.extraction_events.glob('*-integration-packet.json'))


def test_explicit_legacy_request_remains_selectable_alongside_local(approved):
    root, source, _, _ = approved
    legacy = execute(approved)
    assert not legacy.blocked
    original = (root / legacy.request_path).read_bytes()
    (root / 'area').mkdir()
    (root / 'area/index.md').write_text('index')
    (root / 'area/AGENTS.md').write_text('guidance')
    local = run(str(source), 'system', root, load_config(root), entry_folder='area', record_score=False)
    assert not local.blocked and local.source_id == legacy.source_id
    paths = WikiPaths(root, load_config(root))
    consolidate = module('wiki_consolidate')
    with pytest.raises(ValueError, match='select an exact'):
        consolidate._request_for(paths, legacy.source_id)
    assert consolidate._request_for(paths, legacy.source_id, legacy.request_path) == json.loads(original)
    assert consolidate._request_for(paths, local.source_id, local.request_path)['folder_request_id']
    assert (root / legacy.request_path).read_bytes() == original


def test_invalid_retained_identity_never_closes_local_gate(approved, monkeypatch):
    from wiki_core.consolidate import pending_consolidations
    root, source, _, _ = approved
    (root / 'area').mkdir()
    (root / 'area/index.md').write_text('index')
    (root / 'area/AGENTS.md').write_text('guidance')
    config = load_config(root)
    prepared = run(str(source), 'system', root, config, entry_folder='area', record_score=False)
    retained = root / prepared.request_path
    data = json.loads(retained.read_text())
    data['source_id'] = 'another-source'
    retained.write_text(json.dumps(data))
    audit = module('wiki_audit')
    monkeypatch.setattr(audit, 'ROOT', root)
    errors, warnings = [], []
    audit.audit_context_pass_gate(errors, config, warnings)
    assert errors
    with pytest.raises(ValueError):
        pending_consolidations(root, config)


def test_local_packet_reads_only_selected_candidates_and_no_fts(approved, monkeypatch):
    import wiki_core.consolidate as core
    root, _, _, _ = approved
    config = load_config(root)
    paths = WikiPaths(root, config)
    candidate = root / 'candidate.md'
    candidate.write_text('---\npage_id: selected\npage_type: claim\ntitle: Synthetic claim\n---\n# Claim\n')
    excluded = root / 'excluded.md'
    excluded.write_text('unselected sentinel')
    original_open = Path.open
    def guarded(path, *args, **kwargs):
        if path == excluded:
            pytest.fail('opened unselected page')
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guarded)
    monkeypatch.setattr(core, 'wiki_markdown_files', lambda *_a, **_kw: pytest.fail('catalog scanned'))
    monkeypatch.setattr(core, 'search', lambda *_a, **_kw: pytest.fail('FTS opened'))
    aggregated = {'source_id': 'synthetic', 'claims': [{'claim': 'Synthetic claim'}]}
    packet = core.build_packet(aggregated, root, config, paths, candidates=['candidate.md'])
    assert packet['impact']['coverage'] == 'explicit_candidates_only'
    assert packet['warnings'] and packet['claims'][0]['related'] == []
    assert core.build_packet(aggregated, root, config, paths, candidates=[])['impact']['coverage'] == 'explicit_candidates_only'
    # Validate all selections before opening even the first valid candidate.
    outside = root.parent / (root.name + '-outside.md')
    outside.write_text('outside sentinel')
    (root / 'link.md').symlink_to(outside)
    def no_candidate_open(path, *args, **kwargs):
        if path == candidate or path == outside:
            pytest.fail('candidate body opened before all paths were validated')
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', no_candidate_open)
    with pytest.raises(ValueError):
        core.build_packet(aggregated, root, config, paths, candidates=['candidate.md', 'link.md'])


@pytest.mark.parametrize('root_mode', ['named', 'parent'])
def test_retained_request_relative_root_paths(approved, monkeypatch, root_mode):
    from wiki_core.consolidate import pending_consolidations
    from wiki_core.llm.context_pass import load_local_request, local_request_path, retain_local_request
    root, source, _, _ = approved
    (root / 'area').mkdir()
    (root / 'area/index.md').write_text('index')
    (root / 'area/AGENTS.md').write_text('guidance')
    config = load_config(root)
    produced = run(str(source), 'system', root, config, entry_folder='area', record_score=False)
    request = json.loads((root / produced.request_path).read_text())
    if root_mode == 'named':
        monkeypatch.chdir(root.parent)
        relative_root = Path(root.name)
    else:
        monkeypatch.chdir(root / 'area')
        relative_root = Path('..')
    paths = WikiPaths(relative_root, config)
    retained = local_request_path(paths, request)
    assert retain_local_request(paths, request) == retained
    assert load_local_request(paths, retained) == request
    assert load_local_request(paths, retained.relative_to(relative_root)) == request
    assert pending_consolidations(relative_root, config) == []
    with pytest.raises(ValueError):
        load_local_request(paths, relative_root / 'other' / '..' / retained.relative_to(relative_root))


def test_methodology_rejects_mutated_or_empty_local_request(approved, monkeypatch):
    root, source, _, _ = approved
    (root / 'area').mkdir()
    (root / 'area/index.md').write_text('index')
    (root / 'area/AGENTS.md').write_text('guidance')
    config = load_config(root)
    produced = run(str(source), 'system', root, config, entry_folder='area', record_score=False)
    retained = root / produced.request_path
    request = json.loads(retained.read_text())
    request['chunks'] = []
    retained.write_text(json.dumps(request))
    methodology = module('wiki_check_methodology_coverage')
    monkeypatch.setattr(methodology, 'ROOT', root)
    checks = methodology.check_llm_context_pass(WikiPaths(root, config), config)
    assert len(checks) == 1 and not checks[0]['ok']


def test_empty_explicit_request_does_not_scan(approved, monkeypatch):
    root, _, _, _ = approved
    paths = WikiPaths(root, load_config(root))
    cli = module('wiki_consolidate')
    monkeypatch.setattr(cli, 'load_requests', lambda *_a, **_k: pytest.fail('global requests scanned'))
    with pytest.raises(ValueError, match='empty'):
        cli._request_for(paths, 'source-synthetic', '')


def test_shared_capture_keeps_original_context_and_requests_distinguish_contexts(approved):
    root, source, _, _ = approved
    config = load_config(root)
    results = []
    for folder, context in [('one', 'context-a'), ('two', 'context-b')]:
        (root / folder).mkdir()
        (root / folder / 'index.md').write_text(f'{folder} index')
        (root / folder / 'AGENTS.md').write_text(f'{folder} guidance')
        produced = run(str(source), context, root, config, entry_folder=folder, record_score=False)
        assert not produced.blocked
        results.append((produced, json.loads((root / produced.request_path).read_text())))
    first, second = results
    assert first[0].source_id == second[0].source_id
    assert first[1]['source_context'] == 'context-a' and second[1]['source_context'] == 'context-b'
    assert json.loads((root / first[0].manifest_path).read_text())['context'] == 'context-a'
    assert first[1]['folder_request_id'] != second[1]['folder_request_id']


def test_duplicate_contextual_events_never_hide_pending_work(approved, monkeypatch, capsys):
    import hashlib
    import wiki_core.consolidate as core
    root, source, _, _ = approved
    (root / 'area').mkdir()
    (root / 'area/index.md').write_text('index')
    (root / 'area/AGENTS.md').write_text('guidance')
    config = load_config(root)
    produced = run(str(source), 'system', root, config, entry_folder='area', record_score=False)
    request = json.loads((root / produced.request_path).read_text())
    paths = WikiPaths(root, config)
    paths.ingest_events_dir.mkdir(parents=True, exist_ok=True)
    source_digest = hashlib.sha256(produced.source_id.encode()).hexdigest()
    request_id = request['folder_request_id']
    prefix = f'---\nsource_id: {produced.source_id}\nfolder_request_id: {request_id}\n'
    older = paths.ingest_events_dir / f'2026-11-01-{source_digest}-{request_id}.md'
    newer = paths.ingest_events_dir / f'2026-11-02-{source_digest}-{request_id}.md'
    older.write_text(prefix + 'consolidated_into:\n  - complete-page\n---\n')
    newer.write_text(prefix + 'consolidated_into: []\n---\n')
    monkeypatch.setattr(core, 'deep_read_complete', lambda *_a, **_k: True)
    with pytest.raises(ValueError, match='ambiguous'):
        core.pending_consolidations(root, config)
    cli = module('wiki_consolidate')
    monkeypatch.setattr(cli, 'ROOT', root)
    monkeypatch.setattr(sys, 'argv', ['wiki_consolidate.py', '--check'])
    assert cli.main() == 2
    output = capsys.readouterr()
    assert 'ambiguous' in output.err and '"total": 0' not in output.out
    assert older.is_file() and newer.is_file()
