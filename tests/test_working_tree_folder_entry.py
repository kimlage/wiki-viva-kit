"""Synthetic working-tree context; no native loading or authorization claimed."""
import json
import sys
from pathlib import Path

import pytest

from tests.test_ingestion_budget import approved, git, load_script
from wiki_core.config import load_config
from wiki_core.ingest import run
from wiki_core.paths import WikiPaths
from wiki_core.working_tree_folder import read_folder_entry


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
            '--record-result', str(result_file)]
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
    assert llm.main() == 0
    capsys.readouterr()
    assert (WikiPaths(root, load_config(root)).llm_cache / (row['cache_key'] + '.json')).exists()
    # Explicit source recording also recovers the selection from the retained request.
    monkeypatch.setattr(sys, 'argv', [*args, '--source', str(source)])
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


def test_different_entry_is_blocked_before_any_existing_artifact_is_replaced(approved):
    root, source, _, _ = approved
    for folder in ('area/one', 'area/two'):
        put(root, folder + '/AGENTS.md', 'Instructions for ' + folder + '\n')
        put(root, folder + '/index.md', 'Index for ' + folder + '\n')
    config = load_config(root)
    first = run(str(source), 'system', root, config, entry_folder='area/one', record_score=False)
    assert not first.blocked and first.request_path
    paths = WikiPaths(root, config)
    retained = [root / first.request_path, root / first.manifest_path, root / first.chunks_path,
                root / first.text_path, paths.indexes / 'wiki.sqlite']
    before = {path:path.read_bytes() for path in retained}
    second = run(str(source), 'system', root, config, entry_folder='area/two', record_score=False)
    assert second.blocked and second.request_path is None
    assert {path:path.read_bytes() for path in retained} == before
    # An old entry point cannot overwrite the new kind of retained request either.
    legacy = run(str(source), 'system', root, config, record_score=False)
    assert legacy.blocked and legacy.request_path is None
    assert {path:path.read_bytes() for path in retained} == before
