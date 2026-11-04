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
    assert read_matching_result(paths.llm_cache, request, row) is None
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
