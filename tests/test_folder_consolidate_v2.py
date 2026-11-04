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


def test_synthetic_ingestion_to_proposal_and_reassessment(project, monkeypatch, tmp_path, capsys):
    """Synthetic Git merge models a gate; it is not a real independent review."""
    from wiki_core.folder_coordination_v2 import prepare_folder_preflight
    from wiki_core.folder_reassessment_host_v2 import prepare_folder_reassessment
    binding, request, results = fixture_inputs(project, monkeypatch, tmp_path, capsys)
    packet = request['block_context_package']
    base = packet['policy_revision']
    original_branch = git(project, 'branch', '--show-current')
    preview = prepare_folder_consolidation(project, binding, request, results, candidates=['a/candidate.md'], max_age_days=30)
    assert preview['write'] == 'not_performed' and not (project / preview['output']).exists()

    git(project, 'checkout', '-qb', 'wiki/synthetic-ingestion')
    put(project, preview['output'], preview['markdown'])
    git(project, 'add', preview['output']); git(project, 'commit', '-qm', 'synthetic proposal')
    head = git(project, 'rev-parse', 'HEAD')
    report = {'schema_version':'wiki.folder-task-result/v2', 'status':'completed',
              'task_id':packet['task_id'], 'context_id':packet['context_id'], 'packet_digest':packet['packet_digest'],
              'observed':[{'path':row['path'], 'kind':row['kind'], 'revision':row['revision'],
                           'sha256':row['sha256'], 'section':row.get('section'), 'field':row.get('field')}
                          for row in packet['inputs']],
              'changes':[{'path':preview['output'], 'action':'created'}]}
    checked = prepare_folder_preflight(project, binding, {'folder':'a', 'approved_revision':base,
                'base':base, 'head':head, 'branch':'wiki/synthetic-ingestion', 'packet':packet, 'result':report})
    assert checked['preflight']['state'] == 'independent_review_required'
    assert checked['preflight']['requirements_handling']['count'] == 1
    assert checked['preflight']['merge'] == 'not_performed'
    # The following synthetic approval and Git merge exercise plumbing only.
    # They are not evidence of a human/agent review or an operational merge.
    assert git(project, 'rev-parse', 'wiki/synthetic-ingestion') == head
    git(project, 'checkout', '-q', original_branch); git(project, 'merge', '--ff-only', 'wiki/synthetic-ingestion')
    git(project, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    assert (project / preview['output']).read_text() == preview['markdown']

    put(project, 'a/source.md', '# Synthetic changed source\n\n' + ('A changed observation.\n' * 90))
    git(project, 'add', 'a/source.md'); git(project, 'commit', '-qm', 'synthetic source update')
    git(project, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    outcome = prepare_folder_reassessment(project, binding, {'folder':'a',
        'approved_revision':git(project, 'rev-parse', 'HEAD'), 'source':'a/source.md',
        'candidates':[preview['output']], 'reports':[{'target':preview['output'], 'section':None,
        'field':None, 'packet':packet, 'result':report}]})['reassessment']
    assert outcome['consumers'][0]['state'] == 'review_pending'
    assert outcome['consumers'][0]['impact']['verification'] == 'reported_not_independently_verified'
    assert (project / preview['output']).read_text() == preview['markdown']
