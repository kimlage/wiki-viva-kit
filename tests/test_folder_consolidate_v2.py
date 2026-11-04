"""Folder consolidation preview: explicit recorded synthetic results, no writes."""
import json

import pytest

from tests.test_folder_policy_v2 import project, put, git, commit
from tests.test_folder_ingestion_v2 import setup, _synthetic_result, _recording_cli
from wiki_core.config import load_config
from wiki_core.consolidate import prepare_folder_consolidation
from wiki_core.folder_ingestion_v2 import FolderIngestionSelection
from wiki_core.frontmatter import parse_frontmatter
from wiki_core.ingest import run


def fixture_inputs(project, monkeypatch, tmp_path, capsys, *, raw=False):
    put(project, 'a/candidate.md', 'An explicitly selected context page\n')
    put(project, 'a/aux/b/other.md', 'Synthetic other owner\n')
    sha, selection = setup(project)
    source = 'a/source.md'
    source_ref = None
    if raw:
        put(project, '.gitignore', 'data/derived/\na/raw/\n')
        put(project, 'a/source-page.md', '---\npage_id: raw-source\npage_type: source\n'
            'platform: drive\nsource_locator: synthetic-item\n---\nSynthetic source page\n')
        commit(project); sha = git(project, 'rev-parse', 'HEAD')
        source = 'a/raw/source.md'; source_ref = 'a/source-page.md'
        put(project, source, '# Synthetic RAW\n\n' + ('Unverified local observation.\n' * 80))
        selection = FolderIngestionSelection(selection.host, 'a', 'a/index.md', 'a/result.md', source_ref)
    initial = run(str(project / source), 'system', project, load_config(project),
                  approved_revision=sha, folder_selection=selection)
    assert not initial.blocked and initial.written
    request = json.loads((project / initial.request_path).read_text())
    assert len(request['chunks']) == 1
    result = _synthetic_result(request)
    module = _recording_cli(project, sha, request, monkeypatch, tmp_path,
                            source=source, source_ref=source_ref)
    assert module.main() == 0
    assert json.loads(capsys.readouterr().out)['count'] == 1
    return selection.host, request, [result]


def test_preview_only_uses_selected_pages_and_returns_reviewable_markdown(project, monkeypatch, tmp_path, capsys):
    import wiki_core.consolidate as module
    binding, request, results = fixture_inputs(project, monkeypatch, tmp_path, capsys)
    monkeypatch.setattr(module, '_page_catalog', lambda *_: pytest.fail('global catalog used'))
    monkeypatch.setattr(module, 'search', lambda *_args, **_kwargs: pytest.fail('global FTS used'))
    before = git(project, 'status', '--porcelain')
    out = prepare_folder_consolidation(project, binding, request, results, candidates=['a/candidate.md'], max_age_days=30)
    assert out['state'] == 'independent_review_required'
    assert out['write'] == out['merge'] == out['preflight'] == 'not_performed'
    assert out['reads'] == 'reported_not_independently_verified'
    assert [row['path'] for row in out['selected_pages']] == ['a/candidate.md']
    fm, body = parse_frontmatter(out['markdown'])
    assert fm['page_type'] == 'claim'
    assert fm['information_requirements'][0]['target'] == 'a/source.md'
    assert fm['information_requirements'][0]['consumed_revision'] == request['block_context_package']['policy_revision']
    assert results[0]['claims'][0] in body
    assert not (project / 'a/result.md').exists()
    assert git(project, 'status', '--porcelain') == before


def test_wrong_owner_and_existing_output_are_rejected(project, monkeypatch, tmp_path, capsys):
    binding, request, results = fixture_inputs(project, monkeypatch, tmp_path, capsys)
    with pytest.raises(ValueError, match='unavailable or unauthorized'):
        prepare_folder_consolidation(project, binding, request, results, candidates=['a/aux/b/other.md'], max_age_days=30)
    put(project, 'a/result.md', 'Existing work to preserve\n')
    with pytest.raises(ValueError, match='unavailable or unauthorized'):
        prepare_folder_consolidation(project, binding, request, results, candidates=[], max_age_days=30)
    assert (project / 'a/result.md').read_text() == 'Existing work to preserve\n'


def test_unmatched_result_and_changed_source_are_rejected(project, monkeypatch, tmp_path, capsys):
    binding, request, results = fixture_inputs(project, monkeypatch, tmp_path, capsys)
    with pytest.raises(ValueError):
        prepare_folder_consolidation(project, binding, request, [], candidates=[], max_age_days=30)
    put(project, 'a/source.md', 'Changed after recording\n')
    with pytest.raises(ValueError):
        prepare_folder_consolidation(project, binding, request, results, candidates=[], max_age_days=30)


def test_raw_preview_preserves_unverified_association_and_rechecks_bytes(project, monkeypatch, tmp_path, capsys):
    binding, request, results = fixture_inputs(project, monkeypatch, tmp_path, capsys, raw=True)
    out = prepare_folder_consolidation(project, binding, request, results, candidates=[], max_age_days=30)
    fm, body = parse_frontmatter(out['markdown'])
    assert fm['information_requirements'][0]['target'] == 'a/source-page.md'
    assert 'caller_selected_unverified' in body and 'not_verified' in body
    assert request['source_authorization']['source_revision'] is None
    put(project, 'a/raw/source.md', 'Changed after recording\n')
    with pytest.raises(ValueError):
        prepare_folder_consolidation(project, binding, request, results, candidates=[], max_age_days=30)


def test_folder_preview_cli_reads_only_supplied_json_and_does_not_write(project, monkeypatch, tmp_path, capsys):
    import importlib.util
    import io
    import sys
    from pathlib import Path
    _binding, request, results = fixture_inputs(project, monkeypatch, tmp_path, capsys)
    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_consolidate.py'
    spec = importlib.util.spec_from_file_location('synthetic_folder_consolidate_cli', script)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'ROOT', project)
    monkeypatch.setattr(sys, 'argv', ['wiki_consolidate.py', '--folder-preview',
                                     '--folder-candidate', 'a/candidate.md', '--max-age-days', '30'])
    class Input:
        buffer = io.BytesIO(json.dumps({'request':request, 'results':results}).encode())
    monkeypatch.setattr(sys, 'stdin', Input())
    assert module.main() == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview['state'] == 'independent_review_required'
    assert preview['output'] == 'a/result.md' and preview['write'] == 'not_performed'
    assert not (project / 'a/result.md').exists()
