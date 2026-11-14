"""Native proposals distinguish editor state from documentary read inputs."""
from __future__ import annotations

import json

import pytest
import yaml

from tests.test_admin_commands import _execute, _plan
from tests.test_normal_proposal_admission import prepared, _git, _sha, _state
from wiki_core.config import load_config
from wiki_core.web import normal_proposal


def _commit_inputs(root, params, *extra):
    _git(root, "add", "memories", "wiki.config.yaml", *extra)
    _git(root, "commit", "-m", "Add synthetic documentary inputs and editor state")
    path = root / params["material_path"]
    value = json.loads(path.read_text())
    value["base_head"] = _git(root, "rev-parse", "HEAD")
    path.write_text(json.dumps(value))
    params["material_sha256"] = _sha(path.read_bytes())


def _material(root, params, edit):
    path = root / params["material_path"]
    value = json.loads(path.read_text())
    edit(value)
    path.write_text(json.dumps(value))
    params["material_sha256"] = _sha(path.read_bytes())


def test_tracked_obsidian_state_is_not_read_or_copied_into_preview(prepared, monkeypatch):
    srv, root, params, unlock, _clock = prepared
    editor = root / "memories/.obsidian"
    editor.mkdir()
    for name in ("app", "appearance", "core-plugins", "graph", "workspace"):
        (editor / (name + ".json")).write_text('{"synthetic_editor_state": true}')
    _commit_inputs(root, params)
    before = _state(root)
    approved_main = _git(root, "rev-parse", "main")
    original_bytes = normal_proposal._bytes
    original_render = normal_proposal._render_c2
    reads = []

    def read_document(where, ref):
        reads.append(ref)
        return original_bytes(where, ref)

    def render_without_editor(where, *args, **kwargs):
        assert not (where / "memories/.obsidian").exists()
        return original_render(where, *args, **kwargs)

    monkeypatch.setattr(normal_proposal, "_bytes", read_document)
    monkeypatch.setattr(normal_proposal, "_render_c2", render_without_editor)
    preview = normal_proposal.preview_proposal(root, srv.server.config, params)
    assert all(".obsidian" not in ref.split("/") for ref in reads)
    assert all(".obsidian" not in ref.split("/") for ref in preview["readset"])
    assert "memories/index.md" in preview["outputs"]
    assert _state(root) == before
    token = unlock()
    status, plan = _plan(srv, token, "wiki.proposal.prepare", params=params)
    assert status == 200, plan
    status, executed = _execute(srv, token, plan, confirmation=plan["plan"]["confirmation"]["text"])
    assert status == 200 and executed["output"]["prepared"], executed
    assert not executed["output"]["published"]
    assert _git(root, "rev-parse", "main") == approved_main
    assert _git(root, "rev-parse", "HEAD") != before["head"]
    assert {ref: value for ref, value in _state(root)["files"].items() if ".obsidian/" in ref} == {
        ref: value for ref, value in before["files"].items() if ".obsidian/" in ref}
    assert all(".obsidian" not in ref.split("/") for ref in reads)



@pytest.mark.parametrize("marker_kind", ["none", "file", "directory"])
def test_parent_tracked_document_respects_nested_repository_boundary(prepared, monkeypatch, marker_kind):
    srv, root, params, _unlock, _clock = prepared
    nested = root / "memories/nested"
    nested.mkdir()
    target = nested / "page.md"
    target.write_text("Synthetic tracked parent content\n")
    _commit_inputs(root, params)
    ref = "memories/nested/page.md"
    assert ref in _git(root, "ls-files").splitlines()
    marker = nested / ".git"
    if marker_kind == "directory":
        marker.mkdir()
    elif marker_kind == "file":
        marker.write_text("gitdir: synthetic\n")
    before = _state(root)
    reads = []
    original_entry = normal_proposal._worktree_entry

    def guarded_entry(where, mode, selected):
        if selected == ref:
            reads.append(selected)
            if marker_kind != "none":
                pytest.fail("nested tracked body opened before its repository boundary")
        return original_entry(where, mode, selected)

    monkeypatch.setattr(normal_proposal, "_worktree_entry", guarded_entry)
    if marker_kind == "none":
        preview = normal_proposal.preview_proposal(root, srv.server.config, params)
        assert ref in reads and ref in preview["readset"]
    else:
        with pytest.raises(normal_proposal.ProposalError, match="proposal_path_crosses_repository_boundary"):
            normal_proposal.preview_proposal(root, srv.server.config, params)
        assert not reads
    assert target.read_text() == "Synthetic tracked parent content\n"
    assert _state(root) == before


def test_proposal_pins_selected_local_cache_not_legacy_cache(prepared, monkeypatch):
    from wiki_core.input_stage import LOCAL_FOLDER_INPUT_STATUS
    from wiki_core.paths import WikiPaths
    srv, root, params, _unlock, _clock = prepared
    paths = WikiPaths(root, srv.server.config)
    paths.extraction_events.mkdir(parents=True, exist_ok=True)
    local = paths.llm_cache / 'local-folder'
    local.mkdir(parents=True, exist_ok=True)
    key = 'a' * 64
    (paths.extraction_events / 'source-example-llm-context-request.json').write_text(json.dumps({
        'source_id': 'source-example', 'input_stage_status': LOCAL_FOLDER_INPUT_STATUS,
        'chunks': [{'cache_key': key}]}))
    (local / f'{key}.json').write_text('{"local": true}')
    (paths.llm_cache / f'{key}.json').write_text('{"legacy": true}')
    monkeypatch.setattr(normal_proposal, '_render_c2', lambda *_args, **_kwargs: {})
    preview = normal_proposal.preview_proposal(root, srv.server.config, params)
    assert (local / f'{key}.json').relative_to(root).as_posix() in preview['readset']
    assert (paths.llm_cache / f'{key}.json').relative_to(root).as_posix() not in preview['readset']


@pytest.mark.parametrize("suffix", ["md", "json", "txt", "xml", "log"])
def test_documentary_inputs_remain_pinned_at_native_effect(prepared, suffix):
    srv, root, params, unlock, _clock = prepared
    target = root / ("memories/context." + suffix)
    target.write_text("Synthetic documentary input.\n")
    _commit_inputs(root, params)
    target.write_text("Already modified documentary input.\n")
    token = unlock()
    status, plan = _plan(srv, token, "wiki.proposal.prepare", params=params)
    assert status == 200, plan
    status_before = _git(root, "status", "--porcelain")
    target.write_text("Changed again with the same Git status.\n")
    assert _git(root, "status", "--porcelain") == status_before
    before = _state(root)
    status, denied = _execute(srv, token, plan, confirmation=plan["plan"]["confirmation"]["text"])
    assert status == 409 and denied["error_code"] == "admin_plan_stale", denied
    assert denied["failed_preconditions"] == ["proposal_planned_readset_changed"]
    assert _state(root) == before


def test_editor_state_cannot_be_an_explicit_document_target(prepared):
    srv, root, params, _unlock, _clock = prepared
    path = root / params["material_path"]
    value = json.loads(path.read_text())
    value["documents"].append({"path": "memories/.obsidian/app.json",
                               "before_sha256": None, "after_text": "{}"})
    path.write_text(json.dumps(value))
    params["material_sha256"] = _sha(path.read_bytes())
    before = _state(root)
    with pytest.raises(normal_proposal.ProposalError, match="proposal_path_not_eligible"):
        normal_proposal.preview_proposal(root, srv.server.config, params)
    assert _state(root) == before


@pytest.mark.parametrize("ref", ["memories/.obsidian/context.md", "memories/.other/app.json"])
def test_hidden_documentary_inputs_are_still_refused(prepared, ref):
    srv, root, params, _unlock, _clock = prepared
    target = root / ref
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("Synthetic hidden input.\n")
    _commit_inputs(root, params)
    before = _state(root)
    with pytest.raises(normal_proposal.ProposalError, match="proposal_path_not_eligible"):
        normal_proposal.preview_proposal(root, srv.server.config, params)
    assert _state(root) == before


def test_retired_pointer_cannot_change_policy(prepared):
    srv, root, params, _unlock, _clock = prepared
    _material(root, params, lambda material: material.update(freshness_pointer={}))
    before = _state(root)
    with pytest.raises(normal_proposal.ProposalError):
        normal_proposal.preview_proposal(root, srv.server.config, params)
    assert _state(root) == before


def test_consolidation_runs_native_writer_and_pins_canonical_source(prepared):
    from tests.test_action_consolidation import PARAGRAPH
    from wiki_core.action_transition import _parse_document, _consolidated_body
    srv, root, params, unlock, _clock = prepared
    material = json.loads((root / params['material_path']).read_text())
    action = root / material['action']['page_ref']
    action.write_text(action.read_text() + '\n' + PARAGRAPH + '\n')
    canonical = action.with_name('canonical.md')
    canonical.write_text(action.read_text().replace('action-server-synthetic', 'action-canonical'))
    _commit_inputs(root, params)
    before = action.read_text(); fm, body = _parse_document(before)
    records = [{'paragraph':PARAGRAPH,'canonical_ref':canonical.relative_to(root).as_posix(),
                'canonical_sha256':_sha(canonical.read_bytes()),'label':'Canonical evidence'}]
    def update(value):
        value['action'].update(expected_sha256=_sha(action.read_bytes()),
            body=_consolidated_body(body, records), consolidations=records)
    _material(root, params, update)
    token = unlock()
    status, plan = _plan(srv, token, 'wiki.proposal.prepare', params=params)
    assert status == 200, plan
    status, result = _execute(srv, token, plan, confirmation=plan['plan']['confirmation']['text'])
    assert status == 200, result
    after, updated_body = _parse_document(action.read_text())
    assert after['updated_at'] == fm['updated_at']
    assert PARAGRAPH not in updated_body and '(canonical.md)' in updated_body
    assert after['action_state_history'][-1]['kind'] == 'body_consolidation'


@pytest.mark.parametrize('folder', ['team/research', 'team/research/nested'])
def test_local_action_proposal_uses_same_writer_and_cas_without_global_actions(prepared, folder):
    from wiki_core.frontmatter import parse_frontmatter
    srv, root, params, unlock, _clock = prepared
    material = json.loads((root / params['material_path']).read_text())
    old = root / material['action']['page_ref']
    target = root / f'memories/{folder}/actions/{old.name}'
    target.parent.mkdir(parents=True)
    old.rename(target)
    old.parent.rmdir()
    ref = target.relative_to(root).as_posix()
    before, _ = parse_frontmatter(target)
    _material(root, params, lambda value: value['action'].update(page_ref=ref))
    _commit_inputs(root, params)
    token = unlock()
    status, plan = _plan(srv, token, 'wiki.proposal.prepare', params=params)
    assert status == 200, plan
    status, result = _execute(srv, token, plan, confirmation=plan['plan']['confirmation']['text'])
    assert status == 200 and result['output']['prepared'], result
    assert not result['output']['published'] and not old.exists()
    after, _ = parse_frontmatter(target)
    for key in ('page_id', 'context', 'owner_kind', 'owner_ref'):
        assert after.get(key) == before.get(key)
    assert after['action_state_history'][-1]['kind'] == 'body_integration'
    assert 'Reviewed synthetic result.' in target.read_text()
    stable = target.read_bytes()
    # A fresh material bound to the current HEAD but the old action digest is stale.
    _material(root, params, lambda value: value.update(base_head=_git(root, 'rev-parse', 'HEAD')))
    with pytest.raises(normal_proposal.ProposalError, match='proposal_action_revision_mismatch'):
        normal_proposal.preview_proposal(root, srv.server.config, params)
    assert target.read_bytes() == stable


@pytest.mark.parametrize('boundary', ['outside-collection', 'escape', 'symlink', 'nested-git'])
def test_proposal_action_selection_refuses_invalid_local_route(prepared, monkeypatch, boundary):
    srv, root, params, _unlock, _clock = prepared
    material = json.loads((root / params['material_path']).read_text())
    original = root / material['action']['page_ref']
    target = root / ('memories/team/nested/actions/task.md' if boundary != 'outside-collection'
                     else 'memories/team/nested/task.md')
    target.parent.mkdir(parents=True)
    original.rename(target)
    _commit_inputs(root, params)
    ref = target.relative_to(root).as_posix()
    if boundary == 'escape':
        ref = 'memories/../' + ref
    elif boundary == 'symlink':
        target.rename(target.with_name('saved.md'))
        target.symlink_to(target.with_name('saved.md'))
    elif boundary == 'nested-git':
        (target.parent.parent / '.git').mkdir()
    _material(root, params, lambda value: value['action'].update(page_ref=ref))
    before = _state(root)
    monkeypatch.setattr(normal_proposal, '_write_action', lambda *a, **k: pytest.fail('native writer reached'))
    original_entry = normal_proposal._worktree_entry
    def guarded_entry(where, mode, selected):
        if boundary in {'symlink', 'nested-git'} and selected == target.relative_to(root).as_posix():
            pytest.fail('body read across a rejected boundary')
        return original_entry(where, mode, selected)
    monkeypatch.setattr(normal_proposal, '_worktree_entry', guarded_entry)
    with pytest.raises((normal_proposal.ProposalError, ValueError)):
        normal_proposal.preview_proposal(root, srv.server.config, params)
    assert _state(root) == before
