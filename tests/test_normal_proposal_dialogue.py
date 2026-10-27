"""Comment-only proposals keep native routing, CAS and revocable admission."""
from __future__ import annotations

import json

import pytest

from tests.test_admin_commands import _execute, _plan
from tests.test_normal_proposal_admission import prepared, _git, _sha, _state
from wiki_core.frontmatter import parse_frontmatter
from wiki_core.web.admin.sessions import ADMIN_SESSION_HEADER


POLICY = """schema_version: wiki_coordination.v1
profiles:
  research:
    label: Research
    scope: Synthetic commentary only; no runtime execution permission.
    action_ids: [action-server-synthetic]
"""


def _save(root, params, material):
    path = root / params["material_path"]
    path.write_text(json.dumps(material))
    params["material_sha256"] = _sha(path.read_bytes())


def _comment(prepared, *, policy=POLICY, c2=()):
    _srv, root, params, _unlock, _clock = prepared
    if policy is not None:
        (root / "wiki.coordination.yaml").write_text(policy)
        _git(root, "add", "wiki.coordination.yaml")
        _git(root, "commit", "-m", "Bind synthetic action commentary route")
    material = json.loads((root / params["material_path"]).read_text())
    action = material["action"]
    for key in ("body", "contribution", "recorded_at"):
        action.pop(key)
    action["transition"] = {
        "next_state": "open", "recorded_at": material["generated_at"],
        "dialogue_event": {"event_id": "received-comment-0001", "kind": "comment",
                           "text": "Existing result received; normative changes remain unintegrated.",
                           "coordinator": "research"},
    }
    material.update(base_head=_git(root, "rev-parse", "HEAD"), documents=[], c2=list(c2))
    _save(root, params, material)
    return material


def _execute_plan(srv, token, plan):
    return _execute(srv, token, plan, confirmation=plan["plan"]["confirmation"]["text"])


@pytest.mark.parametrize("c2", [[], ["operation"]])
def test_comment_only_native_prepare_preserves_body_contract_and_identity(prepared, c2):
    srv, root, params, unlock, _clock = prepared
    material = _comment(prepared, c2=c2)
    path = root / material["action"]["page_ref"]
    before, body = parse_frontmatter(path)
    approved_main = _git(root, "rev-parse", "main")
    token = unlock()
    status, plan = _plan(srv, token, "wiki.proposal.prepare", params=params)
    assert status == 200, plan
    status, result = _execute_plan(srv, token, plan)
    assert status == 200 and result["ok"] and result["output"]["prepared"], result
    after, after_body = parse_frontmatter(path)
    assert after_body == body
    for key in before.keys() - {"action_dialogue", "action_state_history", "updated_at"}:
        assert after[key] == before[key]
    assert after["action_state"] == "open"
    assert len(after["action_dialogue"]) == 1
    event = after["action_dialogue"][0]
    assert event["actor"] == "operator" and event["coordinator"] == "research"
    assert event["before_sha256"] == material["action"]["expected_sha256"]
    receipt = after["action_state_history"][-1]
    assert receipt["kind"] == "comment" and receipt["support_fields"] == ["action_dialogue"]
    assert after["updated_at"] == before["updated_at"]
    assert receipt["from"] == receipt["to"] == "open" and "contribution" not in receipt
    for key in ("run_id", "effect_key"):
        assert result["output"][key] == material["action"][key]
    assert result["output"]["material_sha256"] == params["material_sha256"]
    assert not result["output"]["published"]
    assert _git(root, "rev-parse", "main") == approved_main
    committed = _state(root)
    status, replay = _execute_plan(srv, token, plan)
    assert status == 409 and replay["error_code"] == "admin_plan_already_executed"
    assert _state(root) == committed


@pytest.mark.parametrize("where,key,value", [
    ("event", "actor", "coordinator:research"),
    ("event", "at", "2026-10-25T05:00:00Z"),
    ("event", "before_sha256", "a" * 64),
    ("transition", "dialogue_actor", "operator"),
    ("transition", "page_edit", {"body": "Forged replacement"}),
    ("action", "dialogue_actor", "operator"),
])
def test_comment_material_cannot_supply_trusted_actor_or_extra_fields(prepared, where, key, value):
    srv, root, params, unlock, _clock = prepared
    material = _comment(prepared)
    action = material["action"]
    target = action if where == "action" else action["transition"]
    if where == "event":
        target = target["dialogue_event"]
    target[key] = value
    _save(root, params, material)
    token = unlock()
    before = _state(root)
    status, refused = _plan(srv, token, "wiki.proposal.prepare", params=params)
    assert status == 400 and refused["error_code"] == "admin_invalid_params", refused
    assert _state(root) == before


@pytest.mark.parametrize("failure", ["missing_policy", "other_coordinator", "unmapped_action", "wrong_page_id"])
def test_comment_requires_existing_route_and_exact_action_identity(prepared, failure):
    srv, root, params, unlock, _clock = prepared
    policy = None if failure == "missing_policy" else POLICY
    if failure == "unmapped_action":
        policy = POLICY.replace("[action-server-synthetic]", "[another-synthetic-action]")
    material = _comment(prepared, policy=policy)
    if failure == "other_coordinator":
        material["action"]["transition"]["dialogue_event"]["coordinator"] = "other"
    if failure == "wrong_page_id":
        material["action"]["page_id"] = "another-synthetic-action"
    _save(root, params, material)
    token = unlock()
    before = _state(root)
    status, refused = _plan(srv, token, "wiki.proposal.prepare", params=params)
    assert status == 400 and refused["error_code"] == "admin_invalid_params", refused
    assert _state(root) == before


@pytest.mark.parametrize("changed", ["action", "material", "coordination_policy"])
def test_comment_planned_inputs_cannot_change_before_actual_writer(prepared, changed):
    srv, root, params, unlock, _clock = prepared
    material = _comment(prepared)
    policy = root / "wiki.coordination.yaml"
    if changed == "coordination_policy":
        # Keep Git status identical across the second mutation; byte pinning
        # must protect the same routing input used by preview and execution.
        policy.write_text(policy.read_text() + "\n")
    token = unlock()
    status, plan = _plan(srv, token, "wiki.proposal.prepare", params=params)
    assert status == 200, plan
    git_status = _git(root, "status", "--porcelain")
    if changed == "action":
        path = root / material["action"]["page_ref"]
        path.write_text(path.read_text() + "Concurrent synthetic note.\n")
    elif changed == "material":
        material["action"]["transition"]["dialogue_event"]["text"] = "A different comment."
        (root / params["material_path"]).write_text(json.dumps(material))
    else:
        policy.write_text(policy.read_text().replace("Research", "Reassigned research"))
        assert _git(root, "status", "--porcelain") == git_status
    before = _state(root)
    status, refused = _execute_plan(srv, token, plan)
    assert status != 200 and not refused["ok"], refused
    assert _state(root) == before


def test_comment_revocation_after_plan_produces_zero_domain_effects(prepared):
    srv, root, params, unlock, _clock = prepared
    _comment(prepared)
    token = unlock()
    status, plan = _plan(srv, token, "wiki.proposal.prepare", params=params)
    assert status == 200, plan
    before = _state(root)
    status, locked = srv.post("/api/admin/session/lock", {}, headers={ADMIN_SESSION_HEADER: token})
    assert status == 200 and locked["state"] == "locked"
    status, refused = _execute_plan(srv, token, plan)
    assert status == 403 and refused["error_code"] == "admin_session_invalid", refused
    assert _state(root) == before


def test_same_dialogue_event_cannot_be_reapplied_with_fresh_cas(prepared):
    srv, root, params, unlock, _clock = prepared
    material = _comment(prepared)
    token = unlock()
    status, plan = _plan(srv, token, "wiki.proposal.prepare", params=params)
    assert status == 200, plan
    status, result = _execute_plan(srv, token, plan)
    assert status == 200 and result["ok"], result
    material["base_head"] = _git(root, "rev-parse", "HEAD")
    material["action"]["expected_sha256"] = _sha((root / material["action"]["page_ref"]).read_bytes())
    material["action"]["transition"]["recorded_at"] = "2026-10-25T05:00:01Z"
    _save(root, params, material)
    before = _state(root)
    status, refused = _plan(srv, token, "wiki.proposal.prepare", params=params)
    assert status == 400 and refused["error_code"] == "admin_invalid_params", refused
    assert _state(root) == before


@pytest.mark.parametrize('target', ['policy', 'action'])
def test_comment_late_mutation_cannot_replace_planned_authority_or_revision(prepared, monkeypatch, target):
    from wiki_core import coordination
    srv, root, params, unlock, _clock = prepared
    material = _comment(prepared)
    token = unlock()
    status, plan = _plan(srv, token, 'wiki.proposal.prepare', params=params)
    assert status == 200, plan
    head = _git(root, 'rev-parse', 'HEAD')
    action = root / material['action']['page_ref']
    original_text = action.read_text()
    original_route = coordination.validate_dialogue_route
    mutated = []
    def change_after_route(actual_root, ref, event):
        original_route(actual_root, ref, event)
        if actual_root.resolve() == root.resolve():
            assert not mutated
            mutated.append(True)
            if target == 'policy':
                policy = root / 'wiki.coordination.yaml'
                policy.write_text(policy.read_text().replace('Research', 'Different authority'))
            else:
                action.write_text(original_text + '\nConcurrent authored conclusion.\n')
    monkeypatch.setattr(coordination, 'validate_dialogue_route', change_after_route)
    status, refused = _execute_plan(srv, token, plan)
    assert status != 200 and not refused['ok'], refused
    assert mutated and _git(root, 'rev-parse', 'HEAD') == head
    assert action.read_text() == (original_text if target == 'policy'
                                else original_text + '\nConcurrent authored conclusion.\n')
    assert 'received-comment-0001' not in action.read_text()


def test_blocked_comment_does_not_unblock_or_replace_next_step(prepared):
    from wiki_core.action_transition import transition_action_page
    srv, root, params, unlock, _clock = prepared
    material = _comment(prepared)
    action = root / material['action']['page_ref']
    transition_action_page(root, action, 'blocked', recorded_at='2026-10-25T04:00:00Z',
        blocker_reason='Separate documentary review is pending.', blocked_by=[],
        next_action='Integrator reviews the retained documents.')
    _git(root, 'add', material['action']['page_ref'])
    _git(root, 'commit', '-m', 'Synthetic blocked action before receipt')
    material['base_head'] = _git(root, 'rev-parse', 'HEAD')
    material['action']['expected_sha256'] = _sha(action.read_bytes())
    material['action']['transition']['next_state'] = 'blocked'
    _save(root, params, material)
    before, before_body = parse_frontmatter(action)
    token = unlock()
    status, plan = _plan(srv, token, 'wiki.proposal.prepare', params=params)
    assert status == 200, plan
    status, result = _execute_plan(srv, token, plan)
    assert status == 200 and result['ok'], result
    after, body = parse_frontmatter(action)
    assert body == before_body
    assert {k: v for k, v in after.items() if k not in {'action_dialogue', 'action_state_history'}} == {
        k: v for k, v in before.items() if k not in {'action_dialogue', 'action_state_history'}}
