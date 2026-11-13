"""Synthetic folder-bound ingestion request preview; no model is run."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.test_folder_policy_v2 import project, put, git, commit
from wiki_core.config import load_config
from wiki_core.folder_coordination_v2 import FolderHostBinding
from wiki_core.folder_ingestion_v2 import FolderIngestionSelection
from wiki_core.ingest import run
from wiki_core.llm.context_pass import result_matches_request
from wiki_core.paths import WikiPaths, FolderWikiPaths


def setup(project):
    put(project, '.gitignore', 'data/derived/\n')
    put(project, 'wiki.config.yaml', 'repo_id: synthetic-folder-ingestion\nowner_label: Synthetic\nroot_entity:\n  page: a/root.md\n')
    put(project, 'a/root.md', '---\npage_id: synthetic-root\npage_type: root_entity\n---\nSynthetic root\n')
    put(project, 'a/source.md', '# Synthetic source\n\n' + ('An authorized synthetic observation.\n' * 90))
    commit(project)
    sha = git(project, 'rev-parse', 'HEAD')
    selection = FolderIngestionSelection(FolderHostBinding(project, ('a',)), 'a', 'a/index.md', 'a/result.md')
    return sha, selection


def test_shared_host_binding_rejects_ambiguous_json(tmp_path):
    from wiki_core.folder_ingestion_v2 import host_binding_from_environment
    host = {'WIKI_FOLDER_INGEST_HOST_ROOT': str(tmp_path), 'WIKI_FOLDER_INGEST_HOST_FOLDERS': 'a'}
    allowed = [['a', str(tmp_path / 'clone'), 'example.test/group/repo', 'guide.md']]
    binding = host_binding_from_environment({**host, 'WIKI_FOLDER_INGEST_HOST_REPOSITORIES': json.dumps(allowed)})
    assert binding.independent_repos == (('a', tmp_path / 'clone', 'example.test/group/repo', 'guide.md'),)
    # A duplicate object key is ambiguous even if the resulting keys could be
    # interpreted as a valid binding tuple.
    duplicate = '[{' + ','.join(json.dumps(k) + ':0' for k in
        ('a', str(tmp_path / 'clone'), 'example.test/group/repo', 'guide.md', 'a')) + '}]'
    for invalid in (duplicate, '[NaN]'):
        with pytest.raises(ValueError):
            host_binding_from_environment({**host, 'WIKI_FOLDER_INGEST_HOST_REPOSITORIES': invalid})


def test_folder_request_includes_native_lineage_selected_index_and_real_output(project, tmp_path, capsys):
    sha, selection = setup(project)
    result = run(str(project / 'a/source.md'), 'system', project, load_config(project),
                 approved_revision=sha, folder_selection=selection)
    assert not result.blocked and result.written and result.request_path
    request = json.loads((project / result.request_path).read_text())
    packet = request['block_context_package']
    assert request['context_binding_version'] == 2
    assert packet['schema_version'] == 'wiki.folder-task-context/v2'
    assert packet['context_folder'] == 'a' and packet['index_path'] == 'a/index.md'
    assert packet['output'] == 'a/result.md'
    assert [row['path'] for row in packet['inputs']] == ['AGENTS.md', 'a/AGENTS.md', 'a/index.md', 'a/source.md', 'a/root.md']
    assert request['source_authorization']['version'] == 'folder/v2'
    assert request['source_authorization']['ref'] == 'a/source.md'
    assert request['source_authorization']['source_revision'] == sha
    source_row = next(row for row in packet['inputs'] if row['kind'] == 'evidence' and row['path'] == 'a/source.md')
    assert source_row['document_sha256'] == request['source_hash_sha256'] == request['source_authorization']['source_sha256']
    assert 'rebuild and revalidate' in request['instructions']
    assert not result_matches_request({}, request, request['chunks'][0])
    relabelled = {**request, 'context_binding_version': 1}
    assert not result_matches_request({}, relabelled, request['chunks'][0])

    # A result matching an emitted key requires the current folder-bound request.
    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_llm_context_pass.py'
    spec = importlib.util.spec_from_file_location('folder_preview_record', script)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    data = tmp_path / 'result.json'
    data.write_text(json.dumps({'cache_key': request['chunks'][0]['cache_key']}))
    assert module._record_results(FolderWikiPaths(project, load_config(project), 'a'), str(data)) == 2
    assert json.loads(capsys.readouterr().out)['error_code'] == 'approved_context_revalidation_required'
    assert not (FolderWikiPaths(project, load_config(project), 'a').llm_cache / (request['chunks'][0]['cache_key'] + '.json')).exists()


def test_unbound_folder_or_output_are_refused_before_source_read(project, monkeypatch):
    sha, selection = setup(project)
    source = project / 'a/source.md'
    original_open = Path.open
    def guard(path, *args, **kwargs):
        if path == source:
            pytest.fail('source opened before authorization')
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guard)
    wrong_folder = FolderIngestionSelection(FolderHostBinding(project, ('a/aux/b',)), 'a', 'a/index.md', 'a/result.md')
    wrong_output = FolderIngestionSelection(selection.host, 'a', 'a/index.md', 'a/aux/b/result.md')
    wrong_index = FolderIngestionSelection(selection.host, 'a', 'a/not-declared.md', 'a/result.md')
    for selected in (wrong_folder, wrong_output, wrong_index):
        result = run(str(source), 'system', project, load_config(project),
                     approved_revision=sha, folder_selection=selected)
        assert result.blocked and not result.written
        assert result.context_error_code == 'folder_source_unavailable'
    too_small = run(str(source), 'system', project, load_config(project),
                    approved_revision=sha, folder_selection=selection, context_max_bytes=1)
    assert too_small.blocked and not too_small.written


def test_v1_context_and_v2_folder_cannot_be_combined(project):
    sha, selection = setup(project)
    result = run(str(project / 'a/source.md'), 'system', project, load_config(project),
                 approved_revision=sha, policy_context='a', folder_selection=selection)
    assert result.blocked and not result.written and result.context_error_code == 'ambiguous_policy'


def test_known_context_omission_blocks_v2_before_persisting(project):
    sha, selection = setup(project)
    result = run(str(project / 'a/source.md'), 'system', project, load_config(project),
                 approved_revision=sha, folder_selection=selection, omit_root_entity=True)
    assert result.blocked and not result.written
    assert result.context_error_code == 'context_preparation_unavailable'
    assert not FolderWikiPaths(project, load_config(project), 'a').derived_root.exists()


def test_source_denial_precedes_read(project, monkeypatch):
    import yaml
    _, selection = setup(project)
    controls_path = project / 'wiki-context-controls.yaml'
    controls = yaml.safe_load(controls_path.read_text())
    controls['controls']['a']['policy']['deny'] = {'read': ['a/source.md']}
    controls_path.write_text(yaml.safe_dump(controls)); commit(project)
    sha = git(project, 'rev-parse', 'HEAD')
    source = project / 'a/source.md'
    original_open = Path.open
    def guard(path, *args, **kwargs):
        if path == source:
            pytest.fail('denied source opened')
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guard)
    result = run(str(source), 'system', project, load_config(project),
                 approved_revision=sha, folder_selection=selection)
    assert result.blocked and not result.written


def test_nested_git_source_requires_explicit_repository_access(project, monkeypatch):
    sha, selection = setup(project)
    clone = project / 'a/clone'
    clone.mkdir()
    git(project, 'init', '-q', str(clone))
    source = clone / 'source.md'
    source.write_text('A separate repository source\n')
    original_open = Path.open
    def guard(path, *args, **kwargs):
        if path == source:
            pytest.fail('nested repository source opened through wiki ingestion')
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guard)
    result = run(str(source), 'system', project, load_config(project),
                 approved_revision=sha, folder_selection=selection)
    assert result.blocked and not result.written


def test_existing_output_and_context_index_are_not_accepted(project, monkeypatch):
    sha, selection = setup(project)
    source = project / 'a/source.md'
    existing = project / 'a/result.md'
    existing.write_text('Untracked work to preserve\n')
    original_open = Path.open
    def guard(path, *args, **kwargs):
        if path == source:
            pytest.fail('source opened before destination was qualified')
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guard)
    for output in ('a/result.md', 'a/index.md', 'a/source.md', 'a/.git/config'):
        selected = FolderIngestionSelection(selection.host, 'a', 'a/index.md', output)
        result = run(str(source), 'system', project, load_config(project),
                     approved_revision=sha, folder_selection=selected)
        assert result.blocked and not result.written
    assert existing.read_text() == 'Untracked work to preserve\n'


def test_approved_ref_move_during_extraction_blocks_persistence(project, monkeypatch):
    import wiki_core.ingest.pipeline as pipeline
    sha, selection = setup(project)
    original_extract = pipeline.extract_source
    def move_ref(*args, **kwargs):
        result = original_extract(*args, **kwargs)
        git(project, 'update-ref', 'refs/remotes/origin/main', 'HEAD^')
        return result
    monkeypatch.setattr(pipeline, 'extract_source', move_ref)
    result = run(str(project / 'a/source.md'), 'system', project, load_config(project),
                 approved_revision=sha, folder_selection=selection)
    assert result.blocked and not result.written
    assert not FolderWikiPaths(project, load_config(project), 'a').derived_root.exists()


def test_cli_prepares_folder_request_without_running_a_model(project):
    sha, _ = setup(project)
    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_ingest.py'
    call = subprocess.run([sys.executable, str(script), '--root', str(project),
        '--source', 'a/source.md', '--context', 'system', '--approved-revision', sha,
        '--folder-context', 'a', '--folder-output', 'a/result.md'],
        capture_output=True, text=True, env={**os.environ, 'WIKI_FOLDER_INGEST_HOST_ROOT': str(project),
                                            'WIKI_FOLDER_INGEST_HOST_FOLDERS': 'a'})
    assert call.returncode == 0, call.stderr
    result = json.loads(call.stdout)
    request = json.loads((project / result['request_path']).read_text())
    assert request['block_context_package']['output'] == 'a/result.md'
    assert request['context_binding_version'] == 2


def _synthetic_result(request):
    template = json.loads((Path(__file__).resolve().parents[1] / 'tests/fixtures/e2e/context_pass_result.sample.json').read_text())
    row = request['chunks'][0]
    return {**template, **{key: request[key] for key in ('source_id', 'prompt_version', 'schema_version', 'model_profile')},
            **{key: row[key] for key in ('cache_key', 'chunk_id', 'context_sha256', 'chunk_hash_sha256')},
            'perspectives_required': request['perspectives_required'],
            'perspectives': {key: {'status': 'extracted'} for key in request['perspectives_required']}}


def _recording_cli(project, sha, request, monkeypatch, tmp_path, *, source='a/source.md', source_ref=None):
    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_llm_context_pass.py'
    spec = importlib.util.spec_from_file_location('folder_recording_cli', script)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    result_file = tmp_path / 'synthetic-result.json'
    result_file.write_text(json.dumps(_synthetic_result(request)))
    monkeypatch.setenv('WIKI_FOLDER_INGEST_HOST_ROOT', str(project))
    monkeypatch.setenv('WIKI_FOLDER_INGEST_HOST_FOLDERS', 'a')
    argv = ['wiki_llm_context_pass.py', '--root', str(project),
        '--source', source, '--context', 'system', '--approved-revision', sha,
        '--folder-context', 'a', '--folder-output', 'a/result.md',
        '--record-result', str(result_file)]
    if source_ref is not None:
        argv += ['--folder-source-ref', source_ref]
    monkeypatch.setattr(sys, 'argv', argv)
    return module


def test_v2_synthetic_result_records_and_is_reused_only_with_current_binding(project, monkeypatch, tmp_path, capsys):
    sha, selection = setup(project)
    initial = run(str(project / 'a/source.md'), 'system', project, load_config(project),
                  approved_revision=sha, folder_selection=selection)
    request = json.loads((project / initial.request_path).read_text())
    result = _synthetic_result(request)
    assert result_matches_request(result, request, request['chunks'][0], recording=True)
    assert not result_matches_request(result, {**request, 'context_binding_version': 1}, request['chunks'][0])
    altered = {**request, 'source_authorization': {**request['source_authorization'], 'folder': 'other'}}
    assert not result_matches_request(result, altered, request['chunks'][0])
    altered_hash = {**request, 'source_authorization': {**request['source_authorization'], 'source_sha256': '0' * 64}}
    assert not result_matches_request(result, altered_hash, request['chunks'][0])
    altered_packet = {**request, 'block_context_package': {**request['block_context_package'],
        'inputs': [row for row in request['block_context_package']['inputs'] if row.get('path') != 'a/source.md']}}
    assert not result_matches_request(result, altered_packet, request['chunks'][0])
    # A legacy/unrequested cache entry cannot satisfy a folder-v2 request.
    from wiki_core.llm.context_pass import write_result
    legacy_cache = WikiPaths(project, load_config(project)).llm_cache
    write_result(legacy_cache, result)
    before_recording = run(str(project / 'a/source.md'), 'system', project, load_config(project),
                           approved_revision=sha, folder_selection=selection, write=False)
    assert before_recording.pending_llm_calls == initial.pending_llm_calls
    module = _recording_cli(project, sha, request, monkeypatch, tmp_path)
    assert module.main() == 0
    assert json.loads(capsys.readouterr().out)['count'] == 1
    cached = FolderWikiPaths(project, load_config(project), 'a').llm_cache / 'folder-v2' / (request['chunks'][0]['cache_key'] + '.json')
    assert cached.exists()
    from wiki_core.llm.cache import cache_summary
    assert cache_summary(legacy_cache, root=project)['cache_files'] == 1
    assert cache_summary(FolderWikiPaths(project, load_config(project), 'a').llm_cache, root=project)['cache_files'] == 1
    repeated = run(str(project / 'a/source.md'), 'system', project, load_config(project),
                   approved_revision=sha, folder_selection=selection, write=False)
    assert not repeated.blocked and repeated.pending_llm_calls == initial.pending_llm_calls - 1


def test_v2_recording_revocation_at_write_fence_preserves_cache(project, monkeypatch, tmp_path, capsys):
    sha, selection = setup(project)
    initial = run(str(project / 'a/source.md'), 'system', project, load_config(project),
                  approved_revision=sha, folder_selection=selection)
    request = json.loads((project / initial.request_path).read_text())
    module = _recording_cli(project, sha, request, monkeypatch, tmp_path)
    original = module.revalidate_ingestion_source
    calls = 0
    def revoke_before_write(guard, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 3:
            git(project, 'update-ref', 'refs/remotes/origin/main', 'HEAD^')
        return original(guard, **kwargs)
    monkeypatch.setattr(module, 'revalidate_ingestion_source', revoke_before_write)
    assert module.main() == 2
    assert json.loads(capsys.readouterr().out)['blocked']
    assert calls == 3
    cached = FolderWikiPaths(project, load_config(project), 'a').llm_cache / 'folder-v2' / (request['chunks'][0]['cache_key'] + '.json')
    assert not cached.exists()


def test_folder_result_cache_symlink_is_refused(project, monkeypatch, tmp_path, capsys):
    sha, selection = setup(project)
    initial = run(str(project / 'a/source.md'), 'system', project, load_config(project),
                  approved_revision=sha, folder_selection=selection)
    request = json.loads((project / initial.request_path).read_text())
    outside = tmp_path / 'outside-cache'; outside.mkdir()
    cache = FolderWikiPaths(project, load_config(project), 'a').llm_cache
    (cache / 'folder-v2').symlink_to(outside, target_is_directory=True)
    module = _recording_cli(project, sha, request, monkeypatch, tmp_path)
    assert module.main() == 2
    assert json.loads(capsys.readouterr().out)['blocked']
    assert list(outside.iterdir()) == []


def test_folder_capture_artifact_symlink_is_refused_before_writes(project, tmp_path):
    sha, selection = setup(project)
    paths = FolderWikiPaths(project, load_config(project), 'a')
    paths.derived_root.mkdir(parents=True)
    outside = tmp_path / 'outside-chunks'; outside.mkdir()
    paths.chunks.symlink_to(outside, target_is_directory=True)
    result = run(str(project / 'a/source.md'), 'system', project, load_config(project),
                 approved_revision=sha, folder_selection=selection)
    assert result.blocked and not result.written
    assert list(outside.iterdir()) == [] and not paths.source_manifests.exists()


def test_emit_request_refuses_symlinked_events_ancestor(project, monkeypatch, tmp_path, capsys):
    sha, selection = setup(project)
    initial = run(str(project / 'a/source.md'), 'system', project, load_config(project),
                  approved_revision=sha, folder_selection=selection)
    request = json.loads((project / initial.request_path).read_text())
    module = _recording_cli(project, sha, request, monkeypatch, tmp_path)
    args = sys.argv
    args[args.index('--record-result'):] = ['--emit-request']
    paths = FolderWikiPaths(project, load_config(project), 'a')
    outside = tmp_path / 'external-events'
    paths.extraction_events.rename(outside)
    paths.extraction_events.symlink_to(outside, target_is_directory=True)
    before = {path.name: path.read_bytes() for path in outside.iterdir()}
    assert module.main() == 2
    assert json.loads(capsys.readouterr().out)['blocked']
    assert {path.name: path.read_bytes() for path in outside.iterdir()} == before


def test_folder_cache_read_requires_root_and_rejects_symlinked_ancestor(project, monkeypatch, tmp_path, capsys):
    from wiki_core.llm.context_pass import read_matching_result
    sha, selection = setup(project)
    initial = run(str(project / 'a/source.md'), 'system', project, load_config(project),
                  approved_revision=sha, folder_selection=selection)
    request = json.loads((project / initial.request_path).read_text())
    module = _recording_cli(project, sha, request, monkeypatch, tmp_path)
    assert module.main() == 0
    capsys.readouterr()
    paths = FolderWikiPaths(project, load_config(project), 'a')
    row = request['chunks'][0]
    assert read_matching_result(paths.llm_cache, request, row) is None
    assert read_matching_result(paths.llm_cache, request, row, root=project) is not None
    outside = tmp_path / 'moved-derived'
    paths.derived_root.rename(outside)
    paths.derived_root.symlink_to(outside, target_is_directory=True)
    original = Path.open
    def guarded(path, *args, **kwargs):
        if path.name == row['cache_key'] + '.json':
            pytest.fail('cache body opened through symlinked ancestor')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guarded)
    assert read_matching_result(paths.llm_cache, request, row, root=project) is None


def test_gitignored_raw_does_not_acquire_fictitious_revision(project):
    sha, selection = setup(project)
    put(project, '.gitignore', 'data/derived/\na/raw/\n')
    commit(project)
    sha = git(project, 'rev-parse', 'HEAD')
    put(project, 'a/raw/source.md', 'Synthetic staged RAW\n')
    result = run(str(project / 'a/raw/source.md'), 'system', project, load_config(project),
                 approved_revision=sha, folder_selection=selection)
    assert result.blocked and not result.written
    assert result.context_error_code == 'folder_source_revision_unavailable'


def test_modified_worktree_source_does_not_inherit_approved_blob_revision(project):
    sha, selection = setup(project)
    put(project, 'a/source.md', 'Modified but not approved source\n')
    result = run(str(project / 'a/source.md'), 'system', project, load_config(project),
                 approved_revision=sha, folder_selection=selection)
    assert result.blocked and not result.written
    assert result.context_error_code == 'folder_source_revision_changed'


def test_raw_local_bytes_are_bound_to_explicit_source_page_without_claiming_external_verification(project, monkeypatch, tmp_path, capsys):
    _, selection = setup(project)
    put(project, '.gitignore', 'data/derived/\na/raw/\n')
    put(project, 'a/source-page.md', '---\npage_id: raw-source\npage_type: source\nplatform: drive\nsource_locator: synthetic-item\n---\nSource\n')
    commit(project); sha = git(project, 'rev-parse', 'HEAD')
    put(project, 'a/raw/source.md', '# Synthetic RAW\n\n' + ('Unverified local observation.\n' * 80))
    selected = FolderIngestionSelection(selection.host, 'a', 'a/index.md', 'a/result.md', 'a/source-page.md')
    first = run(str(project / 'a/raw/source.md'), 'system', project, load_config(project),
                approved_revision=sha, folder_selection=selected)
    assert not first.blocked and first.written
    request = json.loads((project / first.request_path).read_text())
    auth = request['source_authorization']
    assert auth['source_kind'] == 'staged_raw' and auth['source_revision'] is None
    assert auth['canonical_ref'] == 'a/source-page.md' and auth['canonical_revision'] == sha
    assert auth['association'] == 'caller_selected_unverified'
    assert auth['external_origin_verification'] == auth['external_freshness'] == 'not_verified'
    assert auth['source_sha256'] == request['source_hash_sha256']
    source_rows = [r for r in request['block_context_package']['inputs'] if r.get('kind') == 'evidence' and r.get('classification') == 'source']
    assert len(source_rows) == 1 and source_rows[0]['path'] == 'a/source-page.md'
    assert 'external origin and freshness are not verified' in request['instructions']
    chunks = json.loads((project / first.chunks_path).read_text())
    assert chunks['source_origin_id'] == auth['source_origin']['id']
    assert chunks['source_hash_sha256'] == auth['source_sha256'] and chunks['extraction_complete'] is True
    module = _recording_cli(project, sha, request, monkeypatch, tmp_path,
                            source='a/raw/source.md', source_ref='a/source-page.md')
    assert module.main() == 0
    assert json.loads(capsys.readouterr().out)['count'] == 1


def test_raw_source_page_requires_authorized_unambiguous_canonical_locator(project, monkeypatch):
    from wiki_core.repository_reader import RepositoryReader
    _, selection = setup(project)
    put(project, '.gitignore', 'data/derived/\na/raw/\n')
    put(project, 'a/incomplete-source.md', '---\npage_id: incomplete\npage_type: source\nplatform: drive\n---\nSource\n')
    commit(project); sha = git(project, 'rev-parse', 'HEAD')
    put(project, 'a/raw/source.md', 'Synthetic RAW\n')
    raw = project / 'a/raw/source.md'
    original_open = Path.open
    original_read = RepositoryReader.read
    def guarded_open(path, *args, **kwargs):
        if path == raw: pytest.fail('RAW opened before source page qualification')
        return original_open(path, *args, **kwargs)
    def guarded_read(self, path, *args, **kwargs):
        if path == 'a/aux/b/index.md': pytest.fail('unapproved other-owner page opened')
        return original_read(self, path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guarded_open)
    monkeypatch.setattr(RepositoryReader, 'read', guarded_read)
    for source_ref in ('a/incomplete-source.md', 'a/aux/b/index.md'):
        selected = FolderIngestionSelection(selection.host, 'a', 'a/index.md', 'a/result.md', source_ref)
        result = run(str(raw), 'system', project, load_config(project),
                     approved_revision=sha, folder_selection=selected)
        assert result.blocked and not result.written


def test_raw_bytes_changed_at_record_fence_do_not_replace_cache(project, monkeypatch, tmp_path, capsys):
    _, selection = setup(project)
    put(project, '.gitignore', 'data/derived/\na/raw/\n')
    put(project, 'a/source-page.md', '---\npage_id: raw-source\npage_type: source\nplatform: drive\nsource_locator: synthetic-item\n---\nSource\n')
    commit(project); sha = git(project, 'rev-parse', 'HEAD')
    raw = project / 'a/raw/source.md'
    put(project, 'a/raw/source.md', '# Synthetic RAW\n\n' + ('Original local observation.\n' * 60))
    selected = FolderIngestionSelection(selection.host, 'a', 'a/index.md', 'a/result.md', 'a/source-page.md')
    first = run(str(raw), 'system', project, load_config(project), approved_revision=sha, folder_selection=selected)
    request = json.loads((project / first.request_path).read_text())
    module = _recording_cli(project, sha, request, monkeypatch, tmp_path,
                            source='a/raw/source.md', source_ref='a/source-page.md')
    original = module.revalidate_ingestion_source
    calls = 0
    def change_raw(guard, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 3:
            raw.write_text('Changed local RAW\n')
        return original(guard, **kwargs)
    monkeypatch.setattr(module, 'revalidate_ingestion_source', change_raw)
    assert module.main() == 2
    assert json.loads(capsys.readouterr().out)['blocked'] and calls == 3
    cached = FolderWikiPaths(project, load_config(project), 'a').llm_cache / 'folder-v2' / (request['chunks'][0]['cache_key'] + '.json')
    assert not cached.exists()


@pytest.mark.parametrize('field,value', [('source_origin_id', 'different-origin'), ('extraction_complete', False)])
def test_v2_recording_refuses_unbound_or_incomplete_chunks(project, monkeypatch, tmp_path, capsys, field, value):
    sha, selection = setup(project)
    initial = run(str(project / 'a/source.md'), 'system', project, load_config(project),
                  approved_revision=sha, folder_selection=selection)
    request = json.loads((project / initial.request_path).read_text())
    path = project / initial.chunks_path
    data = json.loads(path.read_text()); data[field] = value; path.write_text(json.dumps(data))
    module = _recording_cli(project, sha, request, monkeypatch, tmp_path)
    assert module.main() == 2
    assert json.loads(capsys.readouterr().out)['blocked']
    cached = FolderWikiPaths(project, load_config(project), 'a').llm_cache / 'folder-v2' / (request['chunks'][0]['cache_key'] + '.json')
    assert not cached.exists()


def test_v2_recording_refuses_rehashed_chunks_that_do_not_derive_from_source(project, monkeypatch, tmp_path, capsys):
    from wiki_core.ids import sha256_text
    sha, selection = setup(project)
    initial = run(str(project / 'a/source.md'), 'system', project, load_config(project),
                  approved_revision=sha, folder_selection=selection)
    request = json.loads((project / initial.request_path).read_text())
    path = project / initial.chunks_path
    data = json.loads(path.read_text())
    data['chunks'][0]['text'] += '\nSynthetic tampering\n'
    data['chunks'][0]['hash_sha256'] = sha256_text(data['chunks'][0]['text'])
    path.write_text(json.dumps(data))
    module = _recording_cli(project, sha, request, monkeypatch, tmp_path)
    assert module.main() == 2
    assert json.loads(capsys.readouterr().out)['blocked']
    cached = FolderWikiPaths(project, load_config(project), 'a').llm_cache / 'folder-v2' / (request['chunks'][0]['cache_key'] + '.json')
    assert not cached.exists()


def test_cli_folder_selection_never_creates_its_own_host_binding(project):
    sha, _ = setup(project)
    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_ingest.py'
    env = {key: value for key, value in os.environ.items()
           if key not in {'WIKI_FOLDER_INGEST_HOST_ROOT', 'WIKI_FOLDER_INGEST_HOST_FOLDERS'}}
    call = subprocess.run([sys.executable, str(script), '--root', str(project),
        '--source', 'a/source.md', '--context', 'system', '--approved-revision', sha,
        '--folder-context', 'a', '--folder-index', 'a/index.md', '--folder-output', 'a/result.md'],
        capture_output=True, text=True, env=env)
    assert call.returncode == 2
    assert not FolderWikiPaths(project, load_config(project), 'a').derived_root.exists()


@pytest.mark.parametrize('with_source_config', [False, True])
def test_folder_request_builder_is_final_for_capture_and_cli_emission(project, tmp_path, monkeypatch, capsys, with_source_config):
    """The common builder already binds the complete folder request."""
    from copy import deepcopy
    from wiki_core.folder_request_identity_v2 import folder_request_identity
    import wiki_core.ingest.pipeline as pipeline

    sha, selection = setup(project)
    if with_source_config:
        put(project, 'a/source.md', '---\npage_id: source-synthetic\npage_type: source\nconfig_ref: a/source-config.md\n---\nSynthetic observation.\n')
        put(project, 'a/source-config.md', '---\npage_id: config-synthetic\npage_type: source_config\n---\nSynthetic configuration.\n')
        commit(project); sha = git(project, 'rev-parse', 'HEAD')
    observed = []
    original = pipeline.build_context_request
    def capture(*args, **kwargs):
        request = original(*args, **kwargs)
        observed.append(deepcopy(request))
        return request
    monkeypatch.setattr(pipeline, 'build_context_request', capture)
    result = run(str(project/'a/source.md'), 'system', project, load_config(project),
                 approved_revision=sha, folder_selection=selection)
    assert not result.blocked and result.request_path
    actual = json.loads((project/result.request_path).read_text())
    assert actual == observed[-1]
    assert actual['folder_request_id'] == folder_request_identity(actual)
    assert ('source_config_ref' in actual) is with_source_config
    if with_source_config:
        assert actual['source_config_ref'] == 'a/source-config.md'
        assert actual['source_config_perspectives_applied'] is True

    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_llm_context_pass.py'
    spec = importlib.util.spec_from_file_location('folder_request_final', script)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    original_cli = module.build_context_request
    cli_observed = []
    def capture_cli(*args, **kwargs):
        request = original_cli(*args, **kwargs)
        cli_observed.append(deepcopy(request))
        return request
    monkeypatch.setattr(module, 'build_context_request', capture_cli)
    monkeypatch.setenv('WIKI_FOLDER_INGEST_HOST_ROOT', str(project))
    monkeypatch.setenv('WIKI_FOLDER_INGEST_HOST_FOLDERS', 'a')
    monkeypatch.setattr(sys, 'argv', ['wiki_llm_context_pass.py', '--root', str(project), '--source', str(project/'a/source.md'),
        '--context', 'system', '--approved-revision', sha, '--folder-context', 'a', '--folder-index', 'a/index.md',
        '--folder-output', 'a/result.md', '--emit-request'])
    assert module.main() == 0
    emitted = project / capsys.readouterr().out.strip()
    assert json.loads(emitted.read_text()) == cli_observed[-1]
    assert cli_observed[-1]['folder_request_id'] == folder_request_identity(cli_observed[-1])
