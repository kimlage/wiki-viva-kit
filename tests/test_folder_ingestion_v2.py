"""Synthetic folder-bound ingestion request preview; no model is run."""
import importlib.util
import json
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
from wiki_core.paths import WikiPaths


def setup(project):
    put(project, '.gitignore', 'data/derived/\n')
    put(project, 'wiki.config.yaml', 'repo_id: synthetic-folder-ingestion\nowner_label: Synthetic\nroot_entity:\n  page: a/root.md\n')
    put(project, 'a/root.md', '---\npage_id: synthetic-root\npage_type: root_entity\n---\nSynthetic root\n')
    put(project, 'a/source.md', '# Synthetic source\n\n' + ('An authorized synthetic observation.\n' * 90))
    commit(project)
    sha = git(project, 'rev-parse', 'HEAD')
    selection = FolderIngestionSelection(FolderHostBinding(project, ('a',)), 'a', 'a/index.md', 'a/result.md')
    return sha, selection


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
    assert [row['path'] for row in packet['inputs']] == ['AGENTS.md', 'a/AGENTS.md', 'a/index.md', 'a/root.md']
    assert request['source_authorization']['version'] == 'folder/v2'
    assert request['source_authorization']['ref'] == 'a/source.md'
    assert 'result recording and integration are not available' in request['instructions']
    assert not result_matches_request({}, request, request['chunks'][0])
    relabelled = {**request, 'context_binding_version': 1}
    assert not result_matches_request({}, relabelled, request['chunks'][0])

    # Even a result matching an emitted key cannot be recorded as a v1 result.
    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_llm_context_pass.py'
    spec = importlib.util.spec_from_file_location('folder_preview_record', script)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    data = tmp_path / 'result.json'
    data.write_text(json.dumps({'cache_key': request['chunks'][0]['cache_key']}))
    assert module._record_results(WikiPaths(project, load_config(project)), str(data)) == 2
    assert json.loads(capsys.readouterr().out)['error_code'] == 'folder_result_recording_unavailable'
    assert not (WikiPaths(project, load_config(project)).llm_cache / (request['chunks'][0]['cache_key'] + '.json')).exists()


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
    assert not WikiPaths(project, load_config(project)).derived_root.exists()


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
    assert not WikiPaths(project, load_config(project)).derived_root.exists()


def test_cli_prepares_folder_request_without_running_a_model(project):
    sha, _ = setup(project)
    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_ingest.py'
    call = subprocess.run([sys.executable, str(script), '--root', str(project),
        '--source', 'a/source.md', '--context', 'system', '--approved-revision', sha,
        '--folder-context', 'a', '--folder-index', 'a/index.md', '--folder-output', 'a/result.md'],
        capture_output=True, text=True)
    assert call.returncode == 0, call.stderr
    result = json.loads(call.stdout)
    request = json.loads((project / result['request_path']).read_text())
    assert request['block_context_package']['output'] == 'a/result.md'
    assert request['context_binding_version'] == 2
