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
