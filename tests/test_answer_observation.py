"""Actual HTTP producer and local CLI fixture; no model/live runtime claim."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
import yaml

from wiki_core.action_transition import transition_action_page, _parse_document, _render_document
from wiki_core.config import load_config
from wiki_core.answer_observation import observe_canonical_answer
from test_web_server import _repo, _Server, _server_action


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.delenv("WIKI_COCKPIT_CORS_ORIGINS", raising=False)
    srv = _Server(tmp_path, _repo(tmp_path))
    try:
        yield srv
    finally:
        srv.close()


def setup(app, *, mode="accept", timeout=10):
    root = app.server.root
    p = _server_action(root)
    # The fixture is an actual local CLI consumer with a fictional task. It
    # validates the on-disk producer facts, deduplicates and unblocks the same
    # task/run without starting a model. The Hermes consumer has separate E2E.
    script = root / "fixture_observer.py"
    script.write_text('''import argparse,json,pathlib,hashlib,time,sys
p=argparse.ArgumentParser();p.add_argument('--event-file');a=p.parse_args()
e=json.loads(pathlib.Path(a.event_file).read_text());root=pathlib.Path.cwd()
assert e['event']['actor']=='operator' and e['event']['kind']=='answer'
# A separate process can take the writer's page lock during the callback.
assert e['event']['text']=='The retained synthetic source.'
state=json.loads((root/'fixture_task.json').read_text())
assert state['task_id']=='same-native-task' and state['run_id']=='same-native-run'
assert e['event']['reply_to']==state['question']
if e['source']['kind']=='wiki_cockpit_action_transition':
 assert e['receipt']['changed'] is True and e['receipt']['idempotent'] is False
 assert hashlib.sha256((root/e['receipt']['page_ref']).read_bytes()).hexdigest()==e['receipt']['after_sha256']
else:
 assert set(e['receipt'])=={'receipt_id'}
 assert e['source']['coverage']=='canonical_event_and_transition_lineage'
(root/'fixture_envelope.json').write_text(json.dumps(e))
mode=(root/'fixture_mode.txt').read_text()
new=e['event']['event_id'] not in state['seen']
if new:
 state['seen'].append(e['event']['event_id'])
 if mode not in {'held','refused'}:state['blocked']=False
(root/'fixture_task.json').write_text(json.dumps(state))
if mode=='timeout':time.sleep(2)
if mode=='deep':
 print('['*12000+'0'+']'*12000);sys.exit(0)
status='refused' if mode=='refused' else 'held' if mode=='held' else 'resumed' if new else 'observed'
print(json.dumps({'ok':True,'status':status,'unblocked':status=='resumed','model_started':False,
 'event_id':e['event']['event_id'],'task_ref':e['task_ref'] if mode!='wrong' else {'repo_id':'wrong'}}))
''')
    source = script.read_text()
    marker = "assert e['event']['actor']=='operator' and e['event']['kind']=='answer'"
    lock_probe = ("\nsys.path.insert(0, " + repr(str(Path(__file__).resolve().parents[1])) + ")"
        + "\nfrom wiki_core.action_transition import _action_file_lock"
        + "\nwith _action_file_lock(root, 'memories/actions/action-server-synthetic.md'): pass")
    script.write_text(source.replace(marker, marker + lock_probe))
    (root / "fixture_mode.txt").write_text(mode)
    state = {"task_id": "same-native-task", "run_id": "same-native-run", "question": "question-fixture-one", "blocked": True, "seen": [], "model_starts": 0}
    (root / "fixture_task.json").write_text(json.dumps(state))
    policy = {"schema_version": "wiki_coordination.v1", "profiles": {"research": {
        "label": "Research", "scope": "Synthetic fixture only", "action_ids": ["action-server-synthetic"],
        "answer_observer": {"argv": [sys.executable, str(script)], "timeout_seconds": timeout}}}}
    (root / "wiki.coordination.yaml").write_text(yaml.safe_dump(policy))
    # Activating a command requires intentional startup with that policy.
    # Restart only this isolated test server after authoring its fixture.
    app.close()
    activated = _Server(root, load_config(root))
    app.__dict__.update(activated.__dict__)
    transition_action_page(root, p, "open", dialogue_event={"event_id": "question-fixture-one", "kind": "question",
        "text": "Which source?", "coordinator": "research"}, dialogue_actor="coordinator:research")
    request = {"page_ref": p.relative_to(root).as_posix(), "next_state": "open",
        "expected_sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "dialogue_event": {
        "event_id": "answer-fixture-one", "kind": "answer", "coordinator": "research",
        "reply_to": "question-fixture-one", "text": "  The retained synthetic source.  "}}
    return root, p, request, policy


def test_http_answer_calls_real_cli_once_after_commit_and_unblocks_fixture(app, monkeypatch):
    root, p, request, _ = setup(app)
    import wiki_core.web.server as server
    monkeypatch.setattr(server, "build_snapshot", lambda *a, **k: pytest.fail("observer rebuilt a global snapshot"))
    status, result = app.post("/api/actions/transition", request, attempt_key="same-answer-attempt")
    assert status == 200, result
    delivery = result["answer_observation"]
    assert delivery["status"] == "delivered" and delivery["answer_committed"]
    state = json.loads((root / "fixture_task.json").read_text())
    assert not state["blocked"] and state["seen"] == ["answer-fixture-one"]
    assert state["task_id"] == "same-native-task" and state["run_id"] == "same-native-run" and state["model_starts"] == 0
    envelope = json.loads((root / "fixture_envelope.json").read_text())
    assert envelope["event"]["text"] == "The retained synthetic source."
    assert envelope["receipt"] == {k: v for k, v in result.items() if k not in {"answer_observation", "attempt_key", "replayed"}}
    assert "nonce" not in json.dumps(envelope) and "authenticated" not in json.dumps(envelope)
    repeated = app.post("/api/actions/transition", request, attempt_key="same-answer-attempt")
    assert repeated[0] == status and repeated[1]["replayed"] is True
    assert {k: v for k, v in repeated[1].items() if k != "replayed"} == {k: v for k, v in result.items() if k != "replayed"}
    assert len(_parse_document(p.read_text())[0]["action_dialogue"]) == 2


def test_reconciliation_uses_canonical_event_and_only_retained_receipt_id(app):
    root, p, request, _ = setup(app)
    status, result = app.post("/api/actions/transition", request)
    assert status == 200
    # A later legitimate suffix must neither erase the answer nor force a
    # forged original afterSHA/HTTP receipt during reconciliation.
    transition_action_page(root, p, "open", priority="high")
    out = observe_canonical_answer(root, request["page_ref"], "answer-fixture-one",
        {"receipt_id": result["receipt_id"]}, reconciliation=True,
        active_policy_sha256=app.server.answer_observer_policy_sha256)
    assert out["status"] == "delivered", out
    envelope = json.loads((root / "fixture_envelope.json").read_text())
    assert envelope["source"] == {"kind": "wiki_canonical_answer_reconciliation", "coverage": "canonical_event_and_transition_lineage"}
    assert envelope["receipt"] == {"receipt_id": result["receipt_id"]}
    assert json.loads((root / "fixture_task.json").read_text())["seen"] == ["answer-fixture-one"]


@pytest.mark.parametrize("mode,expected", [("timeout", "unknown"), ("wrong", "unknown"), ("held", "delivered")])
def test_unknown_or_refused_delivery_does_not_repeat_or_erase_answer(app, mode, expected):
    root, p, request, _ = setup(app, mode=mode, timeout=1)
    status, result = app.post("/api/actions/transition", request)
    assert status == 200 and result["changed"]
    assert result["answer_observation"]["status"] == expected
    if mode == "held":
        assert result["answer_observation"]["consumer_status"] == "held" and not result["answer_observation"]["unblocked"]
        assert json.loads((root / "fixture_task.json").read_text())["blocked"]
    fm, _ = _parse_document(p.read_text())
    assert len(fm["action_dialogue"]) == 2 and fm["action_dialogue"][-1]["actor"] == "operator"
    # Retrying the answer itself is still a CAS conflict, not another effect.
    assert app.post("/api/actions/transition", request)[0] == 409


def test_observer_is_opt_in_and_bad_config_preserves_the_canonical_answer(app):
    root, p, request, policy = setup(app)
    policy["profiles"]["research"].pop("answer_observer")
    (root / "wiki.coordination.yaml").write_text(yaml.safe_dump(policy))
    status, result = app.post("/api/actions/transition", request)
    assert status == 200 and result["answer_observation"]["status"] == "not_configured"
    assert not (root / "fixture_envelope.json").exists()
    policy["profiles"]["research"]["answer_observer"] = {"argv": ["invalid"], "timeout_seconds": 0}
    (root / "wiki.coordination.yaml").write_text(yaml.safe_dump(policy))
    result = observe_canonical_answer(root, request["page_ref"], "answer-fixture-one", {"receipt_id": result["receipt_id"]}, reconciliation=True,
        active_policy_sha256=app.server.answer_observer_policy_sha256)
    assert result["status"] == "refused" and result["answer_committed"]


def test_wrong_operator_nonce_never_notifies_consumer(app):
    root, p, request, _ = setup(app)
    before = p.read_bytes()
    assert app.post("/api/actions/transition", request, nonce="wrong")[0] == 403
    assert p.read_bytes() == before and not (root / "fixture_envelope.json").exists()


@pytest.mark.parametrize("field,later", [("answer", False), ("answer", True), ("question", True)])
def test_reconciliation_refuses_changed_original_payload_even_after_new_receipt(app, field, later):
    root, p, request, _ = setup(app)
    status, result = app.post("/api/actions/transition", request)
    assert status == 200
    (root / "fixture_envelope.json").unlink()
    fm, body = _parse_document(p.read_text())
    fm["action_dialogue"][1 if field == "answer" else 0]["text"] = "Altered synthetic text."
    p.write_text(_render_document(fm, body))
    if later:
        # Even a subsequent valid receipt over the altered state must not
        # authenticate the original answer/prefix against the old receipt.
        transition_action_page(root, p, "open", priority="high")
    out = observe_canonical_answer(root, request["page_ref"], "answer-fixture-one",
        {"receipt_id": result["receipt_id"]}, reconciliation=True,
        active_policy_sha256=app.server.answer_observer_policy_sha256)
    assert out["status"] == "refused", out
    assert out["error"] == ("answer_payload_binding_mismatch" if later else "current_support_binding_mismatch")
    assert not (root / "fixture_envelope.json").exists()


def test_reconciliation_keeps_honest_bound_when_original_support_was_overwritten(app):
    root, p, request, _ = setup(app)
    request["priority"] = "high"
    status, result = app.post("/api/actions/transition", request)
    assert status == 200
    transition_action_page(root, p, "open", priority="low")
    out = observe_canonical_answer(root, request["page_ref"], "answer-fixture-one",
        {"receipt_id": result["receipt_id"]}, reconciliation=True,
        active_policy_sha256=app.server.answer_observer_policy_sha256)
    assert out["status"] == "refused" and out["error"] == "original_answer_support_not_retained"


@pytest.mark.parametrize("mode", ["deep", "exception"])
def test_post_commit_consumer_failure_preserves_http_receipt_and_replay(app, monkeypatch, mode):
    root, p, request, _ = setup(app, mode=mode)
    if mode == "exception":
        import wiki_core.answer_observation as module
        def fail(*args, **kwargs):
            raise RuntimeError("synthetic unexpected failure")
        monkeypatch.setattr(module, "observe_canonical_answer", fail)
    status, result = app.post("/api/actions/transition", request, attempt_key="post-commit-fixture")
    assert status == 200 and result["changed"] and result["receipt_id"]
    assert result["answer_observation"]["status"] == "unknown"
    assert result["answer_observation"]["answer_committed"] is True
    assert hashlib.sha256(p.read_bytes()).hexdigest() == result["after_sha256"]
    repeated_status, repeated = app.post("/api/actions/transition", request, attempt_key="post-commit-fixture")
    assert repeated_status == 200 and repeated["receipt_id"] == result["receipt_id"] and repeated["replayed"]
    assert len(_parse_document(p.read_text())[0]["action_dialogue"]) == 2


def test_known_commit_survives_handled_post_commit_capture_failure(app, monkeypatch):
    root,p,request,_=setup(app)
    import wiki_core.answer_observation as module
    def fail(*args,**kwargs):raise module.AnswerObservationError("coordinator_route_changed")
    monkeypatch.setattr(module,"_capture",fail)
    status,result=app.post("/api/actions/transition",request)
    assert status==200 and result["changed"]
    assert result["answer_observation"]["answer_committed"] is True
    assert result["answer_observation"]["status"]=="refused"
    assert hashlib.sha256(p.read_bytes()).hexdigest()==result["after_sha256"]


def test_consumer_explicit_refusal_never_becomes_delivered_even_with_ok_true(app):
    root,_,request,_=setup(app,mode="refused")
    status,result=app.post("/api/actions/transition",request)
    assert status==200 and result["answer_observation"]["answer_committed"]
    assert result["answer_observation"]["status"]=="refused"
    assert result["answer_observation"]["consumer_status"]=="refused"
    assert result["answer_observation"]["unblocked"] is False
    assert json.loads((root/"fixture_task.json").read_text())["blocked"]
