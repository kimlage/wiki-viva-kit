"""Physical folder entry is context selection, not an access grant."""
import json
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


def test_approved_adapter_is_unchanged_and_rejects_mixed_selection(approved, monkeypatch):
    root, _, sha, _ = approved
    expected = {'approved': True}
    monkeypatch.setattr(context_pass, '_approved_ingestion_context', lambda *_args: expected)
    assert context_pass.ingestion_block_context(root, load_config(root), {}, [],
        approved_revision=sha, policy_context='root') == expected
    with pytest.raises(ValueError, match='cannot replace'):
        context_pass.ingestion_block_context(root, load_config(root), {}, [],
            approved_revision=sha, policy_context='root', entry_folder='area')


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
    assert second.blocked and second.context_error_code == 'existing_source_context_conflict'
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
    assert result.returncode == 2
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
