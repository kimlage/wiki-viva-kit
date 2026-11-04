"""Synthetic working-tree context; no native loading or authorization claimed."""
import json
import sys
from pathlib import Path

import pytest

from tests.test_ingestion_budget import approved, git, load_script
from wiki_core.config import load_config
from wiki_core.ingest import run
from wiki_core.paths import WikiPaths
from wiki_core.folder_context import read_folder_entry


def put(root, ref, text):
    path = root / ref
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def test_folder_entry_delivers_working_tree_and_rechecks_before_recording(approved, monkeypatch, capsys):
    root, source, _, _ = approved
    put(root, 'area/AGENTS.md', 'Area instructions in working tree\n')
    put(root, 'area/index.md', 'Other index; do not include\n')
    put(root, 'area/child/AGENTS.md', 'Ignored regular instruction\n')
    put(root, 'area/child/AGENTS.override.md', 'Selected override, not committed\n')
    put(root, 'area/child/index.md', 'Selected index, not committed\n')
    import wiki_core.input_stage as input_stage
    import wiki_core.ingest.pipeline as pipeline
    def forbidden(*args, **kwargs):
        raise AssertionError('global source or root catalog was opened')
    monkeypatch.setattr(input_stage, 'compile_input_stage', forbidden)
    monkeypatch.setattr(pipeline, 'find_source_config', forbidden)
    result = run(str(source), 'system', root, load_config(root), entry_folder='area/child', record_score=False)
    assert not result.blocked and result.request_path
    request = json.loads((root / result.request_path).read_text())
    package = request['block_context_package']
    assert package['policy_mode'] == 'working_tree_folder_entry' and not package['policy_enforced']
    assert [(row['path'], row['text']) for row in package['documents']] == [
        ('AGENTS.md', 'Obedeça toda a regra; preserve a revisão independente.\n'),
        ('area/AGENTS.md', 'Area instructions in working tree\n'),
        ('area/child/AGENTS.override.md', 'Selected override, not committed\n'),
        ('area/child/index.md', 'Selected index, not committed\n')]
    assert request['root_entity'] == {} and request['target_pages'] == []
    assert 'not automatically resolved' in package['limitations'][1]
    row = request['chunks'][0]
    template = json.loads((Path(__file__).parent / 'fixtures/e2e/context_pass_result.sample.json').read_text())
    recorded = {**template, **{key:request[key] for key in ('source_id', 'prompt_version', 'schema_version', 'model_profile')},
                **{key:row[key] for key in ('cache_key', 'chunk_id', 'context_sha256', 'chunk_hash_sha256')},
                'perspectives_required':[], 'perspectives':{}}
    result_file = root / 'result.json'; result_file.write_text(json.dumps(recorded))
    llm = load_script('wiki_llm_context_pass')
    args = ['wiki_llm_context_pass.py', '--mode', 'working-tree', '--root', str(root), '--context', 'system',
            '--record-result', str(result_file), '--source', str(source), '--request', str(root / result.request_path)]
    monkeypatch.setattr(sys, 'argv', args)
    put(root, 'area/child/AGENTS.override.md', 'Changed override\n')
    assert llm.main() == 2
    assert not (WikiPaths(root, load_config(root)).llm_cache / (row['cache_key'] + '.json')).exists()
    capsys.readouterr()
    put(root, 'area/child/AGENTS.override.md', 'Selected override, not committed\n')
    put(root, 'area/AGENTS.override.md', 'New, more specific override\n')
    assert llm.main() == 2
    capsys.readouterr()
    (root / 'area/AGENTS.override.md').unlink()
    original_source = source.read_text()
    source.write_text(original_source + 'Changed after capture.\n')
    assert llm.main() == 2
    assert not (WikiPaths(root, load_config(root)).llm_cache / (row['cache_key'] + '.json')).exists()
    capsys.readouterr()
    source.write_text(original_source)
    assert llm.main() == 0
    capsys.readouterr()
    assert (WikiPaths(root, load_config(root)).llm_cache / (row['cache_key'] + '.json')).exists()
    # Repeating the same exact request/result remains idempotent.
    monkeypatch.setattr(sys, 'argv', args)
    assert llm.main() == 0
    capsys.readouterr()


def test_folder_entry_rejects_outside_index_symlinks_and_nested_git(tmp_path):
    put(tmp_path, 'a/AGENTS.md', 'Rules\n'); put(tmp_path, 'a/index.md', 'Index\n')
    put(tmp_path, 'elsewhere.md', 'Outside\n')
    with pytest.raises(ValueError):
        read_folder_entry(tmp_path, 'a', 'elsewhere.md', max_bytes=5000)
    with pytest.raises(ValueError):
        read_folder_entry(tmp_path, 'a', 'a/index.md', max_bytes=1)
    (tmp_path / 'a/link.md').symlink_to(tmp_path / 'elsewhere.md')
    with pytest.raises(ValueError):
        read_folder_entry(tmp_path, 'a', 'a/link.md', max_bytes=5000)
    put(tmp_path, 'a/nested/.git', 'gitdir: ignored\n')
    put(tmp_path, 'a/nested/AGENTS.md', 'Independent instructions\n')
    put(tmp_path, 'a/nested/index.md', 'Independent index\n')
    with pytest.raises(ValueError):
        read_folder_entry(tmp_path, 'a/nested', 'a/nested/index.md', max_bytes=5000)



def test_two_context_requests_retain_results_and_remain_distinct_in_gc_and_audit(approved, monkeypatch, capsys):
    root, source, _, _ = approved
    source.write_text('Small synthetic source.\n', encoding='utf-8')
    for folder in ('area/one', 'area/two'):
        put(root, folder + '/AGENTS.md', 'Instructions for ' + folder + '\n')
        put(root, folder + '/index.md', 'Index for ' + folder + '\n')
    config = load_config(root)
    import wiki_core.ingest.pipeline as pipeline
    def no_global(*args, **kwargs):
        raise AssertionError('global FTS or score was accessed')
    monkeypatch.setattr(pipeline, 'index_source', no_global)
    monkeypatch.setattr(pipeline, 'record_event', no_global)
    first = run(str(source), 'system', root, config, entry_folder='area/one')
    assert not first.blocked and first.request_path
    first_path = root / first.request_path; original = first_path.read_bytes()
    capture = [root / first.manifest_path, root / first.text_path, root / first.chunks_path]
    original_capture = {path:path.read_bytes() for path in capture}
    decoy = WikiPaths(root, config).chunks / 'other-origin.json'
    decoy.write_text('{not a selected capture', encoding='utf-8')
    original_open = Path.open
    def selected_only(path, *args, **kwargs):
        if path == decoy:
            raise AssertionError('another source capture was opened')
        return original_open(path, *args, **kwargs)
    with monkeypatch.context() as local:
        local.setattr(Path, 'open', selected_only)
        second = run(str(source), 'other', root, config, entry_folder='area/two')
    decoy.unlink()
    assert not second.blocked and second.request_path and first.request_path != second.request_path
    assert first_path.read_bytes() == original
    assert {path:path.read_bytes() for path in capture} == original_capture
    assert first.chunks_indexed == second.chunks_indexed == 0
    assert first.score_event_id is None and second.score_event_id is None
    requests = [json.loads((root / item.request_path).read_text()) for item in (first, second)]
    assert requests[0]['source_id'] == requests[1]['source_id']
    assert requests[0]['folder_request_id'] != requests[1]['folder_request_id']
    assert requests[0]['chunks'][0]['cache_key'] != requests[1]['chunks'][0]['cache_key']
    paths = WikiPaths(root, config)
    gc = load_script('wiki_gc')
    assert all(root / item.request_path not in gc.find_orphans(paths, {first.source_id}).get('extraction-events', [])
               for item in (first, second))
    audit = load_script('wiki_audit'); monkeypatch.setattr(audit, 'ROOT', root)
    errors = []; audit.audit_context_pass_gate(errors, config)
    assert len([item for item in errors if 'pending LLM pass' in item]) == 2
    row = requests[0]['chunks'][0]
    template = json.loads((Path(__file__).parent / 'fixtures/e2e/context_pass_result.sample.json').read_text())
    recorded = {**template, **{key:requests[0][key] for key in ('source_id','prompt_version','schema_version','model_profile')},
                **{key:row[key] for key in ('cache_key','chunk_id','context_sha256','chunk_hash_sha256')},
                'perspectives_required':[], 'perspectives':{}}
    result_file = root / 'result.json'; result_file.write_text(json.dumps(recorded))
    llm = load_script('wiki_llm_context_pass')
    monkeypatch.setattr(sys, 'argv', ['wiki_llm_context_pass.py', '--mode', 'working-tree', '--root', str(root),
        '--context', 'system', '--source', str(source), '--request', str(first_path), '--record-result', str(result_file)])
    assert llm.main() == 0
    capsys.readouterr()
    errors = []; audit.audit_context_pass_gate(errors, config)
    pending = [item for item in errors if 'pending LLM pass' in item]
    assert len(pending) == 1 and Path(second.request_path).name in pending[0]
    from wiki_core.quality import build_quality_report
    quality = build_quality_report(root, config)
    rows = quality['cost_telemetry']['source_costs']
    assert {(row.get('context_folder'), row['cached_calls'], row['pending_calls']) for row in rows} == {
        ('area/one', 1, 0), ('area/two', 0, 1)}
    assert quality['summary']['chunks_total'] == 1
    assert quality['summary']['cache_reuse_rate'] == 0.5
    assert first_path.read_bytes() == original
    second_row = requests[1]['chunks'][0]
    second_result = {**template, **{key:requests[1][key] for key in ('source_id','prompt_version','schema_version','model_profile')},
                     **{key:second_row[key] for key in ('cache_key','chunk_id','context_sha256','chunk_hash_sha256')},
                     'perspectives_required':[], 'perspectives':{}}
    result_file.write_text(json.dumps(second_result))
    monkeypatch.setattr(sys, 'argv', ['wiki_llm_context_pass.py', '--mode', 'working-tree', '--root', str(root),
        '--context', 'other', '--source', str(source), '--request', str(root / second.request_path), '--record-result', str(result_file)])
    assert llm.main() == 0
    capsys.readouterr()
    import datetime as dt
    from wiki_core.consolidate import find_event_for_source, pending_consolidations
    events = paths.ingest_events_dir; events.mkdir(parents=True, exist_ok=True)
    for folder in ('area/one', 'area/two'):
        put(root, folder + '/candidate.md', '---\npage_id: ' + folder.replace('/', '-') + '\npage_type: claim\n---\nSynthetic\n')
    import wiki_core.consolidate as core
    def no_global(*args, **kwargs):
        raise AssertionError('global catalog or FTS was accessed')
    monkeypatch.setattr(core, 'wiki_markdown_files', no_global)
    monkeypatch.setattr(core, 'search', no_global)
    monkeypatch.setattr(core, 'current_page_signature', no_global)
    consolidate = load_script('wiki_consolidate'); monkeypatch.setattr(consolidate, 'ROOT', root)
    common = dict(emit_event=True, packet=False, source_page=None, source_ref='source-synthetic',
                  context='system', date=dt.date(2026, 11, 4), force=False)
    assert consolidate.consolidate_one(first.source_id, **common) == 1  # Exact scoped request required.
    capsys.readouterr()
    put(root, 'area/one/AGENTS.md', 'Changed after the recorded read\n')
    assert consolidate.consolidate_one(first.source_id, request_path=first.request_path, **common) == 1
    assert not list(events.glob('*.md'))
    capsys.readouterr()
    put(root, 'area/one/AGENTS.md', 'Instructions for area/one\n')
    for item, folder, context in ((first, 'area/one', 'system'), (second, 'area/two', 'other')):
        assert consolidate.consolidate_one(first.source_id, request_path=item.request_path,
                                           candidates=[folder + '/candidate.md'], **{**common, 'context':context}) == 0
        capsys.readouterr()
    first_event = find_event_for_source(paths, first.source_id, requests[0]['folder_request_id'])
    second_event = find_event_for_source(paths, first.source_id, requests[1]['folder_request_id'])
    assert first_event and second_event and first_event != second_event
    assert requests[0]['folder_request_id'] in first_event.read_text()
    assert requests[1]['folder_request_id'] in second_event.read_text()
    assert 'impact_coverage: explicit_candidates_only' in first_event.read_text()
    assert 'verified_at:' not in first_event.read_text() and 'captured_at:' not in first_event.read_text()
    first_event.write_text(first_event.read_text().replace('consolidated_into: []', 'consolidated_into: [page-first]'))
    pending = pending_consolidations(root, config)
    assert len(pending) == 1 and pending[0]['folder_request_id'] == requests[1]['folder_request_id']
    def no_body(*args, **kwargs):
        raise AssertionError('candidate opened before every selected path was validated')
    monkeypatch.setattr(core, 'parse_frontmatter', no_body)
    with pytest.raises(ValueError):
        core.build_packet({}, root, config, paths, candidates=['area/one/candidate.md', 'area/one/missing.md'])
    # A divergent prior capture is WIP: reject without changing any artifact or request.
    chunks_path = root / first.chunks_path
    altered = json.loads(chunks_path.read_text()); altered['chunks'][0]['text'] = 'Unrelated WIP'
    chunks_path.write_text(json.dumps(altered))
    protected = [first_path, root / second.request_path, *capture]
    before = {path:path.read_bytes() for path in protected}
    rejected = run(str(source), 'system', root, config, entry_folder='area/one')
    assert rejected.blocked and not rejected.written
    assert rejected.context_error_code == 'working_tree_capture_conflict'
    assert {path:path.read_bytes() for path in protected} == before


@pytest.mark.parametrize('mode', ['folder', 'v1'])
def test_working_tree_entry_cannot_replace_an_approved_mode(mode, approved, monkeypatch):
    root, source, sha, _ = approved
    script = load_script('wiki_ingest')
    args = ['wiki_ingest.py', '--root', str(root), '--source', str(source), '--context', 'system',
            '--mode', mode, '--approved-revision', sha, '--entry-folder', 'area']
    args += ['--policy-context', 'root'] if mode == 'v1' else [
        '--folder-context', 'area', '--folder-index', 'area/index.md', '--folder-output', 'area/claim.md']
    monkeypatch.setattr(sys, 'argv', args)
    with pytest.raises(SystemExit) as error:
        script.main()
    assert error.value.code == 2


def test_explicit_candidate_with_ambiguous_frontmatter_is_rejected(tmp_path):
    from wiki_core.config import WikiConfig
    from wiki_core.consolidate import build_packet
    put(tmp_path, 'a/page.md', '---\npage_id: first\npage_id: second\npage_type: claim\n---\nBody\n')
    with pytest.raises(ValueError):
        build_packet({}, tmp_path, WikiConfig(), WikiPaths(tmp_path, WikiConfig()), candidates=['a/page.md'])
