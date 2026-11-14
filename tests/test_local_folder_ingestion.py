"""Physical folder entry is context selection, not an access grant."""
import json
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

from tests.test_ingestion_budget import approved
from wiki_core.config import load_config
from wiki_core.ingest import run
from wiki_core.llm import context_pass


def test_worktree_chain_override_and_index_are_delivered(approved):
    root, source, _, _ = approved
    (root / 'area' / 'child').mkdir(parents=True)
    (root / 'area' / 'AGENTS.md').write_text('Untracked parent guidance')
    (root / 'area' / 'child' / 'AGENTS.md').write_text('Fallback guidance')
    (root / 'area' / 'child' / 'AGENTS.override.md').write_text('Override guidance')
    (root / 'area' / 'child' / 'index.md').write_text('Local index content')
    result = run(str(source), 'system', root, load_config(root), entry_folder='area/child', record_score=False)
    assert not result.blocked
    package = json.loads((root / result.request_path).read_text())['block_context_package']
    documents = package['documents']
    refs = [item['path'] for item in documents]
    assert refs[:4] == ['AGENTS.md', 'area/AGENTS.md', 'area/child/AGENTS.override.md', 'area/child/index.md']
    assert 'area/child/AGENTS.md' not in refs
    assert documents[2]['text'] == 'Override guidance' and documents[3]['text'] == 'Local index content'
    assert all(len(row['content_sha256']) == 64 for row in documents[:4])
    assert package['policy_mode'] == 'legacy_working_tree_compatibility'
    assert package['policy_enforced'] is False


def test_root_override_does_not_open_shadowed_root_instructions(approved, monkeypatch):
    root, _, _, _ = approved
    (root / 'AGENTS.override.md').write_text('Root override')
    (root / 'area').mkdir(exist_ok=True)
    (root / 'area' / 'AGENTS.md').write_text('Local guidance')
    (root / 'area' / 'index.md').write_text('Local index')
    original = Path.read_text
    def guarded(path, *args, **kwargs):
        if path == root / 'AGENTS.md':
            pytest.fail('shadowed root instructions opened')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', guarded)
    package = context_pass.ingestion_block_context(root, load_config(root), {}, [], entry_folder='area')
    refs = [row['path'] for row in package['documents']]
    assert refs[:3] == ['AGENTS.override.md', 'area/AGENTS.md', 'area/index.md']
    assert 'AGENTS.md' not in refs


def test_missing_index_fails_before_global_context_and_does_not_fallback(approved, monkeypatch):
    root, _, _, _ = approved
    (root / 'area').mkdir(exist_ok=True)
    (root / 'area' / 'AGENTS.md').write_text('Local guidance')
    import wiki_core.template_blocks as blocks
    monkeypatch.setattr(blocks, 'load_block_world', lambda *_args: pytest.fail('global context opened'))
    with pytest.raises(ValueError, match='index unavailable'):
        context_pass.ingestion_block_context(root, load_config(root), {}, [], entry_folder='area')


@pytest.mark.parametrize('marker', ['file', 'directory', 'symlink'])
def test_nested_repository_or_symlink_is_not_opened(approved, monkeypatch, marker):
    root, _, _, _ = approved
    outer = root / 'independent'
    outer.mkdir()
    (outer / 'index.md').write_text('not to open')
    if marker == 'directory':
        (outer / '.git').mkdir()
    elif marker == 'file':
        (outer / '.git').write_text('gitdir: elsewhere')
    else:
        other = root / 'alias'
        other.symlink_to(outer, target_is_directory=True)
        outer = other
    original = Path.open
    def guarded(path, *args, **kwargs):
        if path.name == 'index.md' and path.parent == outer:
            pytest.fail('nested repository or symlink content opened')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guarded)
    with pytest.raises(ValueError):
        context_pass.ingestion_block_context(root, load_config(root), {}, [], entry_folder=outer.name)


def test_relative_root_and_nested_cwd_selection(approved, monkeypatch):
    root, _, _, _ = approved
    (root / 'area').mkdir(exist_ok=True)
    (root / 'area' / 'AGENTS.md').write_text('Local guidance')
    (root / 'area' / 'index.md').write_text('Local index')
    monkeypatch.chdir(root / 'area')
    folder, index = context_pass.local_entry_selection(Path('..'), None, None, cwd=Path.cwd(),
        approved_revision=None, policy_context=None)
    assert (folder, index) == ('area', None)
    package = context_pass.ingestion_block_context(Path('..'), load_config(Path('..')), {}, [], entry_folder=folder)
    assert 'area/index.md' in [item['path'] for item in package['documents']]


def test_root_index_is_explicit_and_approved_cwd_does_not_change_policy(approved):
    root, _, sha, _ = approved
    with pytest.raises(ValueError, match='explicit index'):
        context_pass.ingestion_block_context(root, load_config(root), {}, [], entry_folder='.')
    (root / 'README.md').write_text('Root index')
    package = context_pass.ingestion_block_context(root, load_config(root), {}, [],
                                                    entry_folder='.', entry_index='README.md')
    assert 'README.md' in [item['path'] for item in package['documents']]
    assert context_pass.local_entry_selection(root, None, None, cwd=root / 'memories',
        approved_revision=sha, policy_context='root') == (None, None)


def test_cli_uses_nested_cwd_and_fails_without_index(approved):
    root, source, _, _ = approved
    area = root / 'area'
    area.mkdir(exist_ok=True)
    (area / 'AGENTS.md').write_text('Entry guidance')
    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_ingest.py'
    command = [sys.executable, str(script), '--root', str(root), '--source', str(source),
               '--context', 'system', '--dry-run', '--no-score']
    first = subprocess.run(command, cwd=area, capture_output=True, text=True)
    assert first.returncode == 2 and json.loads(first.stdout)['blocked']
    (area / 'index.md').write_text('Entry index')
    second = subprocess.run(command, cwd=area, capture_output=True, text=True)
    assert second.returncode == 0 and not json.loads(second.stdout)['blocked']


@pytest.mark.parametrize('options', [
    {'approved_revision': 'a' * 40},
    {'policy_context': 'root'},
    {'approved_revision': 'a' * 40, 'policy_context': 'root', 'entry_folder': 'area'},
])
def test_direct_adapter_rejects_retired_v1_before_reading(tmp_path, monkeypatch, options):
    from wiki_core.config import WikiConfig
    monkeypatch.setattr(Path, 'open', lambda *_a, **_k: pytest.fail('retired v1 opened a file'))
    with pytest.raises(context_pass.ContextRequestBlocked, match='v1 entry is retired') as error:
        context_pass.ingestion_block_context(tmp_path, WikiConfig(), {}, [], **options)
    assert error.value.code == 'v1_ingestion_retired'


def test_second_folder_preserves_existing_source_capture_and_request(approved):
    root, source, _, _ = approved
    for folder in ('one', 'two'):
        (root / folder).mkdir()
        (root / folder / 'AGENTS.md').write_text(f'{folder} guidance')
        (root / folder / 'index.md').write_text(f'{folder} index')
    config = load_config(root)
    first = run(str(source), 'system', root, config, entry_folder='one', record_score=False)
    assert not first.blocked
    retained = [root / first.manifest_path, root / first.text_path, root / first.chunks_path, root / first.request_path]
    before = [path.read_bytes() for path in retained]
    second = run(str(source), 'system', root, config, entry_folder='two', record_score=False)
    assert not second.blocked
    assert second.source_id == first.source_id
    assert second.request_path != first.request_path
    assert (root / second.request_path).is_file()
    assert [path.read_bytes() for path in retained] == before


def test_changed_instruction_blocks_before_any_artifact_write(approved, monkeypatch):
    from wiki_core.ingest import pipeline
    root, source, _, _ = approved
    (root / 'area').mkdir(exist_ok=True)
    instruction = root / 'area' / 'AGENTS.md'
    instruction.write_text('Original guidance')
    (root / 'area' / 'index.md').write_text('Index')
    original = pipeline.build_context_request
    def changed(*args, **kwargs):
        value = original(*args, **kwargs)
        instruction.write_text('Changed guidance')
        return value
    monkeypatch.setattr(pipeline, 'build_context_request', changed)
    result = run(str(source), 'system', root, load_config(root), entry_folder='area', record_score=False)
    assert result.blocked and not result.written and result.request_path is None


def test_pass_cli_does_not_replace_retained_folder_request(approved):
    root, source, _, _ = approved
    (root / 'area').mkdir(exist_ok=True)
    (root / 'area' / 'AGENTS.md').write_text('Local guidance')
    (root / 'area' / 'index.md').write_text('Index')
    first = run(str(source), 'system', root, load_config(root), entry_folder='area', record_score=False)
    assert not first.blocked
    retained = root / first.request_path
    before = retained.read_bytes()
    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_llm_context_pass.py'
    result = subprocess.run([sys.executable, str(script), '--root', str(root), '--source', str(source),
        '--context', 'system', '--folder', 'area', '--emit-request'], capture_output=True, text=True)
    assert result.returncode == 0
    assert result.stdout.strip() == first.request_path
    assert retained.read_bytes() == before


def test_selected_context_preserves_existing_cached_result(tmp_path):
    fixture = Path(__file__).parent / 'fixtures/e2e/context_pass_result.sample.json'
    result = json.loads(fixture.read_text())
    result['cache_key'] = 'a' * 64
    path = context_pass.write_result(tmp_path, result, preserve_existing=True)
    before = path.read_bytes()
    assert context_pass.write_result(tmp_path, result, preserve_existing=True) == path
    with pytest.raises(ValueError, match='preserved'):
        context_pass.write_result(tmp_path, {**result, 'produced_by': 'different'}, preserve_existing=True)
    assert path.read_bytes() == before


@pytest.mark.parametrize('body', ['', 'regular source'])
def test_missing_index_is_blocked_before_source_or_extractor(approved, monkeypatch, body):
    from wiki_core.ingest import pipeline
    root, source, _, _ = approved
    source.write_text(body)
    (root / 'area').mkdir(exist_ok=True)
    (root / 'area' / 'AGENTS.md').write_text('Local guidance')
    monkeypatch.setattr(pipeline, 'build_manifest', lambda *_args, **_kwargs: pytest.fail('source opened'))
    monkeypatch.setattr(pipeline, 'extract_source', lambda *_args, **_kwargs: pytest.fail('source extracted'))
    result = run(str(source), 'system', root, load_config(root), entry_folder='area')
    assert result.blocked and not result.written


@pytest.mark.parametrize('body', ['', 'regular source'])
def test_folder_input_does_not_inspect_global_context_or_index(approved, monkeypatch, body):
    from wiki_core.ingest import pipeline
    import wiki_core.template_blocks as blocks
    root, source, _, _ = approved
    source.write_text(body)
    (root / 'area').mkdir(exist_ok=True)
    (root / 'area' / 'AGENTS.md').write_text('Local guidance')
    (root / 'area' / 'index.md').write_text('Local index')
    def forbidden(*_args, **_kwargs):
        pytest.fail('unselected global content opened')
    monkeypatch.setattr(pipeline, 'find_source_config', forbidden)
    monkeypatch.setattr(pipeline, 'input_context_for_source', forbidden)
    monkeypatch.setattr(blocks, 'load_block_world', forbidden)
    monkeypatch.setattr(pipeline, 'index_source', forbidden)
    monkeypatch.setattr(pipeline, 'record_event', forbidden)
    result = run(str(source), 'system', root, load_config(root), entry_folder='area')
    assert not result.blocked and result.chunks_indexed == 0 and result.score_event_id is None
    if body:
        request = json.loads((root / result.request_path).read_text())
        assert request['input_stage_status'] == 'local_folder_only_source_configuration_unresolved'
        assert 'linked sources not inspected' in request['block_context_package']['unresolved_context_refs']


@pytest.mark.parametrize('location', ['index', 'instruction', 'source', 'source_body'])
def test_signed_url_is_rejected_without_persistence(approved, location):
    root, source, _, _ = approved
    (root / 'area').mkdir(exist_ok=True)
    instruction = root / 'area' / 'AGENTS.md'
    index = root / 'area' / 'index.md'
    instruction.write_text('Local guidance')
    index.write_text('Local index')
    signed = 'https://example.invalid/file?X-Amz-Signature=synthetic-only'
    if location == 'index':
        index.write_text(signed)
    elif location == 'instruction':
        instruction.write_text(signed)
    elif location == 'source':
        source = signed
    else:
        source.write_text(signed)
    result = run(str(source), 'system', root, load_config(root), entry_folder='area')
    assert result.blocked and not result.written and signed not in json.dumps(result.to_dict())


def test_signed_result_is_not_cached(tmp_path):
    fixture = Path(__file__).parent / 'fixtures/e2e/context_pass_result.sample.json'
    result = json.loads(fixture.read_text())
    result['cache_key'] = 'a' * 64
    result['claims'] = ['https://example.invalid/file?X-Amz-Signature=synthetic-only']
    with pytest.raises(ValueError, match='access secret'):
        context_pass.write_result(tmp_path, result, preserve_existing=True)
    assert not list(tmp_path.glob('*.json'))


def test_signed_index_selector_is_never_echoed_or_opened(approved, monkeypatch):
    from wiki_core.ingest import pipeline
    root, source, _, _ = approved
    (root / 'area').mkdir(exist_ok=True)
    (root / 'area' / 'AGENTS.md').write_text('Local guidance')
    selector = 'area/index.md?token=synthetic-only'
    monkeypatch.setattr(pipeline, 'build_manifest', lambda *_args, **_kwargs: pytest.fail('source opened'))
    result = run(str(source), 'system', root, load_config(root), entry_folder='area', entry_index=selector)
    assert result.blocked and not result.written and selector not in json.dumps(result.to_dict())


def test_deeply_encoded_context_blocks_without_rechecking_or_echoing(approved, monkeypatch):
    from wiki_core.ingest import pipeline
    root, source, _, _ = approved
    (root / 'area').mkdir(exist_ok=True)
    (root / 'area' / 'AGENTS.md').write_text('Local guidance')
    (root / 'area' / 'index.md').write_text('Local index')
    encoded = '%41'
    for _ in range(9):
        encoded = encoded.replace('%', '%25')
    monkeypatch.setattr(pipeline, 'build_manifest', lambda *_args, **_kwargs: pytest.fail('source opened'))
    result = run(str(source), encoded, root, load_config(root), entry_folder='area')
    assert result.blocked and not result.written and result.context == ''
    assert encoded not in json.dumps(result.to_dict())


@pytest.mark.parametrize('kind', ['git_file', 'git_directory', 'symlink'])
def test_selected_source_never_opens_nested_repo_or_symlink(approved, monkeypatch, kind):
    from wiki_core.ingest import pipeline
    root, _, _, _ = approved
    (root / 'area').mkdir(exist_ok=True)
    (root / 'area' / 'AGENTS.md').write_text('Local guidance')
    (root / 'area' / 'index.md').write_text('Local index')
    nested = root / 'nested'
    nested.mkdir()
    (nested / 'source.md').write_text('must not be opened')
    if kind == 'git_file':
        (nested / '.git').write_text('gitdir: elsewhere')
    elif kind == 'git_directory':
        (nested / '.git').mkdir()
    else:
        (root / 'linked').symlink_to(nested, target_is_directory=True)
        nested = root / 'linked'
    monkeypatch.setattr(pipeline, 'build_manifest', lambda *_args, **_kwargs: pytest.fail('source opened'))
    result = run(str(nested / 'source.md'), 'system', root, load_config(root), entry_folder='area')
    assert result.blocked and not result.written


def test_auxiliary_without_index_inherits_nearest_indexed_context(approved):
    root, source, _, _ = approved
    (root / 'area' / 'aux').mkdir(parents=True)
    (root / 'area' / 'AGENTS.md').write_text('Parent guidance')
    (root / 'area' / 'index.md').write_text('Parent index')
    (root / 'area' / 'aux' / 'AGENTS.md').write_text('Auxiliary guidance')
    result = run(str(source), 'system', root, load_config(root), entry_folder='area/aux')
    assert not result.blocked
    package = json.loads((root / result.request_path).read_text())['block_context_package']
    assert package['entry_folder'] == 'area/aux'
    assert package['entry_index'] == 'area/index.md'
    assert [d['path'] for d in package['documents']] == [
        'AGENTS.md', 'area/AGENTS.md', 'area/aux/AGENTS.md', 'area/index.md']


def test_external_local_source_stays_blocked(approved, tmp_path_factory):
    root, _, _, _ = approved
    (root / 'area').mkdir(exist_ok=True)
    (root / 'area' / 'AGENTS.md').write_text('Local guidance')
    (root / 'area' / 'index.md').write_text('Local index')
    external = tmp_path_factory.mktemp('external-source') / 'source.md'
    external.write_text('external')
    result = run(str(external), 'system', root, load_config(root), entry_folder='area')
    assert result.blocked and not result.written


def test_pass_cli_checks_index_before_source(approved, monkeypatch):
    root, source, _, _ = approved
    (root / 'area').mkdir(exist_ok=True)
    (root / 'area' / 'AGENTS.md').write_text('Local guidance')
    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_llm_context_pass.py'
    spec = importlib.util.spec_from_file_location('local_folder_pass_test', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'build_manifest', lambda *_args, **_kwargs: pytest.fail('source opened'))
    monkeypatch.setattr(sys, 'argv', [str(script), '--root', str(root), '--source', str(source),
                                    '--context', 'system', '--folder', 'area', '--check'])
    assert module.main() == 2


def test_pass_cli_never_loads_global_source_or_context(approved, monkeypatch):
    import wiki_core.template_blocks as blocks
    root, source, _, _ = approved
    (root / 'area').mkdir(exist_ok=True)
    (root / 'area' / 'AGENTS.md').write_text('Local guidance')
    (root / 'area' / 'index.md').write_text('Local index')
    first = run(str(source), 'system', root, load_config(root), entry_folder='area', record_score=False)
    assert not first.blocked
    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_llm_context_pass.py'
    spec = importlib.util.spec_from_file_location('local_folder_pass_scope_test', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    def forbidden(*_args, **_kwargs):
        pytest.fail('unselected global content opened')
    monkeypatch.setattr(module, 'find_source_config', forbidden)
    monkeypatch.setattr(module, 'input_context_for_source', forbidden)
    monkeypatch.setattr(blocks, 'load_block_world', forbidden)
    monkeypatch.setattr(sys, 'argv', [str(script), '--root', str(root), '--source', str(source),
                                    '--context', 'system', '--folder', 'area', '--check'])
    assert module.main() == 1


def test_local_result_recording_selects_only_current_request(approved, monkeypatch, tmp_path):
    from wiki_core.paths import WikiPaths
    root, _, _, _ = approved
    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_llm_context_pass.py'
    spec = importlib.util.spec_from_file_location('local_folder_record_test', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    payload = tmp_path / 'result.json'
    payload.write_text(json.dumps({'cache_key': 'a' * 64}))
    calls = []
    def selected_only(_paths, *, sizes, source_id):
        calls.append(source_id)
        return []
    monkeypatch.setattr(module, '_emitted_requests', selected_only)
    request = {'source_id': 'source-selected', 'chunks': [], 'block_context_package': {}}
    assert module._record_results(WikiPaths(root, load_config(root)), str(payload),
        current_request=request, preserve_existing=True) == 2
    assert calls == ['source-selected']


def test_source_replaced_with_symlink_is_not_reopened_at_persistence_fence(approved, monkeypatch, tmp_path_factory):
    from wiki_core.ingest import pipeline
    root, source, _, _ = approved
    (root / 'area').mkdir(exist_ok=True)
    (root / 'area' / 'AGENTS.md').write_text('Local guidance')
    (root / 'area' / 'index.md').write_text('Local index')
    external = tmp_path_factory.mktemp('external-fence') / 'source.md'
    external.write_bytes(source.read_bytes())
    original_request = pipeline.build_context_request
    original_manifest = pipeline.build_manifest
    def mutate(*args, **kwargs):
        request = original_request(*args, **kwargs)
        source.unlink()
        source.symlink_to(external)
        return request
    def guarded_manifest(value, *args, **kwargs):
        if Path(value).is_symlink():
            pytest.fail('reopened source through a symlink')
        return original_manifest(value, *args, **kwargs)
    monkeypatch.setattr(pipeline, 'build_context_request', mutate)
    monkeypatch.setattr(pipeline, 'build_manifest', guarded_manifest)
    result = run(str(source), 'system', root, load_config(root), entry_folder='area', record_score=False)
    assert result.blocked and result.written is False and result.request_path is None


def test_local_write_failure_reports_unknown_partial_without_path(approved, monkeypatch):
    from wiki_core.ingest import pipeline
    from wiki_core.paths import WikiPaths
    root, source, _, _ = approved
    (root / 'area').mkdir(exist_ok=True)
    (root / 'area' / 'AGENTS.md').write_text('Local guidance')
    (root / 'area' / 'index.md').write_text('Local index')
    config = load_config(root)
    paths = WikiPaths(root, config)
    original = pipeline.write_source_artifact
    def fail_after_manifest(path, *args, **kwargs):
        if path.parent == paths.source_text:
            raise OSError('synthetic-sensitive-path-must-not-escape')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(pipeline, 'write_source_artifact', fail_after_manifest)
    result = run(str(source), 'system', root, config, entry_folder='area', record_score=False)
    assert result.blocked and result.written is False and result.partial_effects == 'unknown'
    assert result.context_error_code == 'local_persistence_partial'
    assert 'partial' in json.dumps(result.blockers).lower()
    assert 'synthetic-sensitive-path' not in json.dumps(result.to_dict())
    assert list(paths.source_manifests.glob('*.json'))


def test_pass_cli_does_not_follow_source_symlink_at_revalidation(approved, monkeypatch, tmp_path_factory):
    root, source, _, _ = approved
    (root / 'area').mkdir(exist_ok=True)
    (root / 'area' / 'AGENTS.md').write_text('Local guidance')
    (root / 'area' / 'index.md').write_text('Local index')
    first = run(str(source), 'system', root, load_config(root), entry_folder='area', record_score=False)
    assert not first.blocked
    retained = root / first.request_path
    before = retained.read_bytes()
    external = tmp_path_factory.mktemp('external-pass-fence') / 'source.md'
    external.write_bytes(source.read_bytes())
    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_llm_context_pass.py'
    spec = importlib.util.spec_from_file_location('local_folder_pass_fence_test', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original_request, original_manifest = module.build_context_request, module.build_manifest
    def mutate(*args, **kwargs):
        request = original_request(*args, **kwargs)
        source.unlink()
        source.symlink_to(external)
        return request
    def guarded_manifest(value, *args, **kwargs):
        if Path(value).is_symlink():
            pytest.fail('reopened source through a symlink')
        return original_manifest(value, *args, **kwargs)
    monkeypatch.setattr(module, 'build_context_request', mutate)
    monkeypatch.setattr(module, 'build_manifest', guarded_manifest)
    monkeypatch.setattr(sys, 'argv', [str(script), '--root', str(root), '--source', str(source),
                                    '--context', 'system', '--folder', 'area', '--emit-request'])
    assert module.main() == 2
    assert retained.read_bytes() == before


def test_result_batch_failure_reports_completed_first_result(approved, monkeypatch, capsys, tmp_path):
    from wiki_core.paths import WikiPaths
    root, _, _, _ = approved
    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_llm_context_pass.py'
    spec = importlib.util.spec_from_file_location('local_folder_batch_failure_test', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    key = 'a' * 64
    request = {'source_id': 'source-selected', 'chunks': [{'cache_key': key}], 'block_context_package': {}}
    payload = tmp_path / 'batch.json'
    payload.write_text(json.dumps([{'cache_key': key}, {'cache_key': 'invalid'}]))
    def requests(_paths, *, sizes, source_id):
        sizes[id(request)] = 1
        return [request]
    def write(cache, _result, **_kwargs):
        cache.mkdir(parents=True, exist_ok=True)
        output = cache / f'{key}.json'
        output.write_text('{}')
        return output
    monkeypatch.setattr(module, '_emitted_requests', requests)
    monkeypatch.setattr(module, 'result_matches_request', lambda *_args, **_kwargs: True)
    monkeypatch.setattr(module, 'write_result', write)
    assert module._record_results(WikiPaths(root, load_config(root)), str(payload),
        current_request=request, preserve_existing=True) == 2
    assert 'after 1 completed result(s)' in capsys.readouterr().err


@pytest.mark.parametrize('kind', ['missing', 'invalid', 'duplicate', 'unreadable'])
def test_local_result_input_failure_is_opaque(approved, monkeypatch, capsys, tmp_path, kind):
    from wiki_core.paths import WikiPaths
    root, _, _, _ = approved
    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_llm_context_pass.py'
    spec = importlib.util.spec_from_file_location('local_result_input_failure_test', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    payload = tmp_path / 'synthetic-sensitive-input.json'
    if kind != 'missing':
        payload.write_text('{"duplicate": 1, "duplicate": 2}' if kind == 'duplicate' else '{invalid')
    if kind == 'unreadable':
        original = Path.open
        def fail(path, *args, **kwargs):
            if path == payload:
                raise PermissionError(f'sensitive path: {payload}')
            return original(path, *args, **kwargs)
        monkeypatch.setattr(Path, 'open', fail)
    request = {'source_id': 'source-selected', 'chunks': [], 'block_context_package': {}}
    assert module._record_results(WikiPaths(root, load_config(root)), str(payload),
        current_request=request, preserve_existing=True) == 2
    captured = capsys.readouterr()
    assert 'local_result_unavailable' in captured.out
    assert str(payload) not in captured.out + captured.err
    assert 'Traceback' not in captured.out + captured.err


def test_local_path_reuses_boundary_guard_for_terminal_folder_and_relative_root(approved, monkeypatch):
    from wiki_core.traversal import require_wiki_path
    root, source, _, _ = approved
    (root / 'area').mkdir(exist_ok=True)
    monkeypatch.chdir(root / 'area')
    assert require_wiki_path(Path('..'), '.') == root
    assert require_wiki_path(Path('..'), 'source.md') == source
    for unsafe in ('../outside', '.git/config', 'secrets/file.md'):
        with pytest.raises(ValueError):
            require_wiki_path(Path('..'), unsafe)
    nested = root / 'nested-terminal'
    nested.mkdir()
    (nested / '.git').write_text('gitdir: elsewhere')
    with pytest.raises(ValueError):
        require_wiki_path(Path('..'), 'nested-terminal')


def test_local_capture_does_not_replace_file_created_after_preflight(approved, monkeypatch):
    from wiki_core.ingest import pipeline
    from wiki_core.paths import WikiPaths
    root, source, _, _ = approved
    (root / 'area').mkdir()
    (root / 'area/index.md').write_text('Index')
    (root / 'area/AGENTS.md').write_text('Guidance')
    config = load_config(root)
    original = pipeline.write_manifest
    competitor = b'concurrent uncommitted capture\n'
    def appear(manifest, directory, **kwargs):
        path = directory / f"{manifest['source_id']}.json"
        path.write_bytes(competitor)
        return original(manifest, directory, **kwargs)
    monkeypatch.setattr(pipeline, 'write_manifest', appear)
    result = run(str(source), 'system', root, config, entry_folder='area', record_score=False)
    assert result.blocked and result.partial_effects == 'unknown'
    captures = list(WikiPaths(root, config).source_manifests.glob('*.json'))
    assert len(captures) == 1 and captures[0].read_bytes() == competitor


def test_local_request_over_retention_limit_blocks_before_persistence(approved):
    from wiki_core.paths import WikiPaths
    root, source, _, _ = approved
    (root / 'area').mkdir(exist_ok=True)
    (root / 'area/AGENTS.md').write_text('Guidance')
    (root / 'area/index.md').write_text('Index')
    # No pathological encoding: the complete request is over the 2 MB
    # retention limit while still within the caller's 3 MB request budget.
    source.write_text('word ' * 410_000)
    config = load_config(root)
    result = run(str(source), 'system', root, config, entry_folder='area', record_score=False,
                 request_max_bytes=3_000_000)
    assert result.blocked and not result.written and result.request_path is None
    assert result.context_error_code == 'request_budget_exceeded'
    assert '2000000' in json.dumps(result.blockers)
    assert not WikiPaths(root, config).derived_root.exists()


def test_local_request_with_larger_budget_is_readable_when_under_retention_limit(approved):
    from wiki_core.llm.context_pass import load_local_request
    from wiki_core.paths import WikiPaths
    root, source, _, _ = approved
    (root / 'area').mkdir(exist_ok=True)
    (root / 'area/AGENTS.md').write_text('Guidance')
    (root / 'area/index.md').write_text('Index')
    config = load_config(root)
    result = run(str(source), 'system', root, config, entry_folder='area', record_score=False,
                 request_max_bytes=3_000_000)
    assert not result.blocked and result.request_path
    paths = WikiPaths(root, config)
    request = load_local_request(paths, root / result.request_path)
    assert request['request_limits']['request_max_bytes'] == 3_000_000


def test_auxiliary_index_without_instructions_is_not_an_implicit_context(approved, monkeypatch):
    root, _, _, _ = approved
    auxiliary = root / 'area/aux'
    auxiliary.mkdir(parents=True)
    (root / 'area/AGENTS.md').write_text('Area guidance')
    (root / 'area/index.md').write_text('Area index')
    child_index = auxiliary / 'index.md'
    child_index.write_text('Unselected child index')
    original = Path.open
    def guard(path, *args, **kwargs):
        if path == child_index:
            pytest.fail('opened unselected child index')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guard)
    package = context_pass.ingestion_block_context(root, load_config(root), {}, [], entry_folder='area/aux')
    assert package['entry_folder'] == 'area/aux' and package['entry_index'] == 'area/index.md'
    assert child_index.relative_to(root).as_posix() not in [d['path'] for d in package['documents']]


def test_auxiliary_override_and_new_child_context_revalidation(approved):
    root, _, _, _ = approved
    auxiliary = root / 'area/aux'
    auxiliary.mkdir(parents=True)
    (root / 'area/AGENTS.md').write_text('Area guidance')
    (root / 'area/index.md').write_text('Area index')
    (auxiliary / 'AGENTS.md').write_text('Shadowed')
    (auxiliary / 'AGENTS.override.md').write_text('Auxiliary override')
    config = load_config(root)
    initial = context_pass.ingestion_block_context(root, config, {}, [], entry_folder='area/aux')
    assert initial['entry_folder'] == 'area/aux' and initial['entry_index'] == 'area/index.md'
    assert [d['path'] for d in initial['documents']] == [
        'AGENTS.md', 'area/AGENTS.md', 'area/aux/AGENTS.override.md', 'area/index.md']
    (auxiliary / 'index.md').write_text('Child context index')
    current = context_pass.ingestion_block_context(root, config, {}, [], entry_folder='area/aux')
    assert current['entry_index'] == 'area/aux/index.md'
    with pytest.raises(ValueError, match='outside'):
        context_pass.ingestion_block_context(root, config, {}, [], entry_folder='area/aux',
                                             entry_index=initial['entry_index'])


def test_nested_folder_can_select_root_index_explicitly_without_implicit_root(approved):
    root, _, _, _ = approved
    auxiliary = root / 'aux'
    auxiliary.mkdir()
    (root / 'index.md').write_text('Root context index')
    config = load_config(root)
    with pytest.raises(ValueError, match='index unavailable'):
        context_pass.ingestion_block_context(root, config, {}, [], entry_folder='aux')
    selected = context_pass.ingestion_block_context(root, config, {}, [], entry_folder='aux', entry_index='index.md')
    assert selected['entry_folder'] == 'aux' and selected['entry_index'] == 'index.md'


@pytest.mark.parametrize('boundary', ['git_file', 'git_directory', 'symlink'])
def test_auxiliary_discovery_refuses_repository_boundaries_before_opening(approved, monkeypatch, boundary):
    root, source, _, _ = approved
    area = root / 'area'
    area.mkdir()
    (area / 'AGENTS.md').write_text('Area guidance')
    (area / 'index.md').write_text('Area index')
    auxiliary = area / 'aux'
    if boundary == 'symlink':
        other = root / 'outside'
        other.mkdir()
        (other / 'AGENTS.md').write_text('Never open')
        auxiliary.symlink_to(other, target_is_directory=True)
    else:
        auxiliary.mkdir()
        (auxiliary / 'AGENTS.md').write_text('Never open')
        if boundary == 'git_file':
            (auxiliary / '.git').write_text('gitdir: elsewhere')
        else:
            (auxiliary / '.git').mkdir()
    from wiki_core.ingest import pipeline
    monkeypatch.setattr(pipeline, 'build_manifest', lambda *_a, **_kw: pytest.fail('source opened'))
    result = run(str(source), 'system', root, load_config(root), entry_folder='area/aux', record_score=False)
    assert result.blocked and not result.written


def test_invalid_explicit_index_does_not_fall_back_to_ancestor(approved):
    root, _, _, _ = approved
    auxiliary = root / 'area/aux'
    auxiliary.mkdir(parents=True)
    (root / 'area/AGENTS.md').write_text('Area guidance')
    (root / 'area/index.md').write_text('Area index')
    with pytest.raises(ValueError, match='qualified context'):
        context_pass.ingestion_block_context(root, load_config(root), {}, [], entry_folder='area/aux',
                                             entry_index='area/aux/missing.md')


def test_explicit_child_index_without_local_instructions_is_not_a_context(approved, monkeypatch):
    root, _, _, _ = approved
    auxiliary = root / 'area/aux'
    auxiliary.mkdir(parents=True)
    (root / 'area/AGENTS.md').write_text('Area guidance')
    (root / 'area/index.md').write_text('Area index')
    child = auxiliary / 'index.md'
    child.write_text('Not a context')
    original = Path.open
    def guard(path, *args, **kwargs):
        if path == child:
            pytest.fail('opened index without qualified context')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guard)
    with pytest.raises(ValueError, match='qualified context'):
        context_pass.ingestion_block_context(root, load_config(root), {}, [], entry_folder='area/aux',
                                             entry_index='area/aux/index.md')


def test_cli_from_auxiliary_preserves_physical_folder_and_ancestor_index(approved):
    root, source, _, _ = approved
    auxiliary = root / 'area/aux'
    auxiliary.mkdir(parents=True)
    (root / 'area/AGENTS.md').write_text('Area guidance')
    (root / 'area/index.md').write_text('Area index')
    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_ingest.py'
    result = subprocess.run([sys.executable, str(script), '--root', str(root), '--source', str(source),
        '--context', 'system', '--no-score'], cwd=auxiliary, capture_output=True, text=True)
    assert result.returncode == 0
    request = json.loads((root / json.loads(result.stdout)['request_path']).read_text())
    package = request['block_context_package']
    assert package['entry_folder'] == 'area/aux' and package['entry_index'] == 'area/index.md'


def test_context_emerging_during_ingestion_blocks_before_write(approved, monkeypatch):
    from wiki_core.ingest import pipeline
    from wiki_core.paths import WikiPaths
    root, source, _, _ = approved
    auxiliary = root / 'area/aux'
    auxiliary.mkdir(parents=True)
    (root / 'area/AGENTS.md').write_text('Area guidance')
    (root / 'area/index.md').write_text('Area index')
    (auxiliary / 'AGENTS.override.md').write_text('Auxiliary guidance')
    original = pipeline.build_context_request
    def add_child_context(*args, **kwargs):
        request = original(*args, **kwargs)
        (auxiliary / 'index.md').write_text('New context index')
        return request
    monkeypatch.setattr(pipeline, 'build_context_request', add_child_context)
    config = load_config(root)
    result = run(str(source), 'system', root, config, entry_folder='area/aux', record_score=False)
    assert result.blocked and not result.written
    assert not WikiPaths(root, config).derived_root.exists()


def test_local_request_source_mismatch_blocks_before_capture_persistence(approved, monkeypatch):
    from wiki_core.ingest import pipeline
    from wiki_core.paths import WikiPaths

    root, source, _, _ = approved
    (root / 'area').mkdir()
    (root / 'area/AGENTS.md').write_text('Guidance')
    (root / 'area/index.md').write_text('Index')
    config = load_config(root)
    builder = pipeline.build_context_request

    def inconsistent(*args, **kwargs):
        request = builder(*args, **kwargs)
        request['source_id'] = 'synthetic-other-source'
        request['folder_request_id'] = context_pass.local_request_identity(request)
        return request

    monkeypatch.setattr(pipeline, 'build_context_request', inconsistent)
    result = run(str(source), 'system', root, config, entry_folder='area', record_score=False)
    assert result.blocked and not result.written
    assert result.request_path is None
    assert result.context_error_code == 'local_request_source_mismatch'
    assert not WikiPaths(root, config).derived_root.exists()
