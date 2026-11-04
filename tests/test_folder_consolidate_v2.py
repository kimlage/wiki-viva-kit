"""Folder consolidation preview is bounded, explicit and does not write."""
import pytest

from tests.test_folder_policy_v2 import project, put, git, commit
from wiki_core.folder_coordination_v2 import FolderHostBinding, prepare_folder_packet
from wiki_core.consolidate import prepare_folder_consolidation
from wiki_core.frontmatter import parse_frontmatter


def fixture_inputs(project, monkeypatch):
    put(project, 'a/source.md', 'Synthetic source\n')
    put(project, 'a/candidate.md', 'An explicitly selected context page\n')
    put(project, 'a/aux/b/other.md', 'Synthetic other owner\n')
    commit(project)
    sha = git(project, 'rev-parse', 'HEAD')
    binding = FolderHostBinding(project, ('a',))
    packet = prepare_folder_packet(project, binding, {'folder':'a','approved_revision':sha,'content_revision':sha,
        'task': {'index_path':'a/index.md','task_id':'synth','goal':'review','output':'a/new.md',
                 'integrator':'reviewer','max_bytes':30000,
                 'evidence':[{'path':'a/source.md','producer_folder':'a','reason':'source',
                              'use':'interpretation','classification':'source'}]}})['packet']
    request = {'context_binding_version':2,'block_context_package':packet,
               'source_authorization':{'source_kind':'git','canonical_ref':'a/source.md'},
               'source_id':'synthetic','chunks':[{'cache_key':'x'}]}
    results = [{'claims':[{'claim':'Reported synthetic claim'}], 'quadrants':{}}]
    # This file tests preview orchestration. The ingestion route separately
    # tests matching results and binds their hash/provenance; the synthetic
    # end-to-end fixture must exercise the real matcher after integration.
    import wiki_core.llm.context_pass as cp
    monkeypatch.setattr(cp, 'result_matches_request', lambda result, req, row, recording=False: recording and result in results)
    return binding, request, results


def test_preview_only_uses_selected_pages_and_returns_reviewable_markdown(project, monkeypatch):
    import wiki_core.consolidate as module
    binding, request, results = fixture_inputs(project, monkeypatch)
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
    assert 'Reported synthetic claim' in body
    assert not (project / 'a/new.md').exists()
    assert git(project, 'status', '--porcelain') == before


def test_wrong_owner_and_existing_output_are_rejected(project, monkeypatch):
    binding, request, results = fixture_inputs(project, monkeypatch)
    with pytest.raises(ValueError, match='unavailable or unauthorized'):
        prepare_folder_consolidation(project, binding, request, results, candidates=['a/aux/b/other.md'], max_age_days=30)
    put(project, 'a/new.md', 'Existing work to preserve\n')
    with pytest.raises(ValueError, match='unavailable or unauthorized'):
        prepare_folder_consolidation(project, binding, request, results, candidates=[], max_age_days=30)
    assert (project / 'a/new.md').read_text() == 'Existing work to preserve\n'


def test_unmatched_result_and_raw_source_are_rejected(project, monkeypatch):
    binding, request, results = fixture_inputs(project, monkeypatch)
    with pytest.raises(ValueError):
        prepare_folder_consolidation(project, binding, request, [], candidates=[], max_age_days=30)
    request['source_authorization']['source_kind'] = 'staged_raw'
    with pytest.raises(ValueError):
        prepare_folder_consolidation(project, binding, request, results, candidates=[], max_age_days=30)
