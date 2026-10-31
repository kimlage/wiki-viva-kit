import hashlib

import pytest

from wiki_core.action_transition import transition_action_page, ActionTransitionError, action_transition_diagnostics
from wiki_core.action_dialogue import dialogue_summary
from wiki_core.frontmatter import parse_frontmatter
from test_action_transition import _write_action


def event(eid="question-0001", kind="question", text="Which source confirms the date?", **extra):
    return dict(event_id=eid, kind=kind, text=text, coordinator="research", **extra)


def write(root, path, item, actor="operator", **extra):
    return transition_action_page(root, path, "open", dialogue_event=item, dialogue_actor=actor,
        expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), **extra)


def test_question_answer_preserve_lifecycle_and_are_auditable(tmp_path):
    path = _write_action(tmp_path)
    before = path.read_text()
    write(tmp_path, path, event(), "coordinator:research")
    middle = path.read_text()
    assert action_transition_diagnostics(before, middle) == ()
    write(tmp_path, path, event("answer-0001", "answer", "Use the signed source.", reply_to="question-0001"))
    after = path.read_text()
    fm, _ = parse_frontmatter(after)
    assert fm["action_state"] == "open"
    assert len(fm["action_dialogue"]) == 2
    assert dialogue_summary(fm["action_dialogue"])["pending_question_ids"] == []
    assert action_transition_diagnostics(before, after) == ()
    assert action_transition_diagnostics(middle, after) == ()
    assert not dialogue_summary(fm["action_dialogue"])["execution_ready"]


def test_direction_and_next_step_are_one_atomic_receipted_write(tmp_path):
    path = _write_action(tmp_path)
    before = path.read_text()
    with pytest.raises(ActionTransitionError, match="direction_next_action_mismatch"):
        write(tmp_path, path, event(kind="direction", text="Review source"))
    assert path.read_text() == before
    write(tmp_path, path, event(kind="direction", text="Review source"), next_action="Review source")
    fm, _ = parse_frontmatter(path.read_text())
    assert fm["next_action"] == "Review source"
    assert fm["action_state_history"][-1]["support_fields"] == ["action_dialogue", "next_action"]
    assert action_transition_diagnostics(before, path.read_text()) == ()


@pytest.mark.parametrize("extra,code", [
    ({"kind":"answer", "reply_to":"missing-question"}, "unknown_dialogue_question"),
    ({"actor":"operator"}, "invalid_dialogue_event"),
    ({"text":""}, "invalid_dialogue_event"),
    ({"kind":"comment", "reply_to":"question-0001"}, "unexpected_dialogue_reply"),
    ({"text":"x"*2001}, "invalid_dialogue_event"),
])
def test_invalid_event_is_not_written(tmp_path, extra, code):
    path = _write_action(tmp_path); before = path.read_bytes()
    item = event(); item.update(extra)
    with pytest.raises(ActionTransitionError, match=code):
        write(tmp_path, path, item)
    assert path.read_bytes() == before


def test_concurrent_duplicate_self_and_repeated_answers_refused(tmp_path):
    path = _write_action(tmp_path); old_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    write(tmp_path, path, event(), "coordinator:research")
    with pytest.raises(ActionTransitionError, match="stale_action_revision"):
        transition_action_page(tmp_path, path, "open", dialogue_event=event(), expected_sha256=old_sha)
    with pytest.raises(ActionTransitionError, match="duplicate_dialogue_event"):
        write(tmp_path, path, event(), "coordinator:research")
    answer = event("answer-0001", "answer", "Confirmed date", reply_to="question-0001")
    with pytest.raises(ActionTransitionError, match="dialogue_self_answer"):
        write(tmp_path, path, answer, "coordinator:research")
    write(tmp_path, path, answer)
    with pytest.raises(ActionTransitionError, match="dialogue_question_already_answered"):
        write(tmp_path, path, {**answer, "event_id":"answer-0002"})


def test_multiple_questions_only_answered_one_is_cleared(tmp_path):
    path = _write_action(tmp_path)
    write(tmp_path, path, event(), "coordinator:research")
    write(tmp_path, path, event("question-0002", "confirmation_request"), "coordinator:research")
    write(tmp_path, path, event("answer-0001", "answer", "Confirmed", reply_to="question-0001"))
    fm, _ = parse_frontmatter(path.read_text())
    assert dialogue_summary(fm["action_dialogue"])["pending_question_ids"] == ["question-0002"]


def test_answer_does_not_unblock_waiting_action(tmp_path):
    path = _write_action(tmp_path, action_state="waiting_human")
    transition_action_page(tmp_path, path, "waiting_human", dialogue_event=event(), dialogue_actor="coordinator:research")
    transition_action_page(tmp_path, path, "waiting_human", dialogue_event=event("answer-0001", "answer", "Use source", reply_to="question-0001"))
    assert parse_frontmatter(path.read_text())[0]["action_state"] == "waiting_human"


def test_terminal_and_secrets_refused(tmp_path):
    path = _write_action(tmp_path)
    with pytest.raises(ActionTransitionError, match="secret_blocked"):
        write(tmp_path, path, event(text="api_key: sk-proj-" + "a"*64))
    transition_action_page(tmp_path, path, "done", completion_receipt="Synthetic result.")
    with pytest.raises(ActionTransitionError, match="terminal_action_dialogue"):
        transition_action_page(tmp_path, path, "done", dialogue_event=event())


def test_dialogue_rewrite_detected(tmp_path):
    path = _write_action(tmp_path)
    write(tmp_path, path, event())
    before = path.read_text()
    after = before.replace("Which source confirms the date?", "Different history")
    assert action_transition_diagnostics(before, after)[0].code == "action_dialogue_rewritten"


def test_v3_receipt_then_v4_dialogue_is_writable_and_auditable(tmp_path, monkeypatch):
    import wiki_core.action_transition as module
    from wiki_core.page_types import load_page_type_registry, validate_shape
    from pathlib import Path
    path = _write_action(tmp_path, extra={"source_refs": ["source-synthetic"]})
    original = path.read_text()
    with monkeypatch.context() as patch:
        patch.setattr(module, "_CALENDAR_RECEIPT_VERSION", "wiki_action_transition_receipt.v3")
        patch.setattr(module, "_local_calendar_offset_minutes", lambda _: 0)
        patch.setattr(module, "_SUPPORT_FIELDS", module._SUPPORT_FIELDS_V3)
        transition_action_page(tmp_path, path, "open", priority="high")
    fm, body = module._parse_document(path.read_text())
    entry = fm["action_state_history"][-1]
    entry.pop("calendar_utc_offset_minutes")
    entry["receipt_id"] = module._receipt_id(entry)
    path.write_text(module._render_document(fm, body))
    v3 = path.read_text()
    assert parse_frontmatter(v3)[0]["action_state_history"][-1]["schema_version"].endswith(".v3")
    write(tmp_path, path, event(), "coordinator:research")
    assert action_transition_diagnostics(original, path.read_text()) == ()
    assert action_transition_diagnostics(v3, path.read_text()) == ()
    fm, _ = parse_frontmatter(path.read_text())
    shape = load_page_type_registry(Path(__file__).resolve().parents[1]).page_types["action"]
    # This fixture uses numeric stale_after_days; the flat shape parser expects text.
    fm["stale_after_days"] = str(fm["stale_after_days"])
    assert validate_shape(tmp_path, str(path.relative_to(tmp_path)), fm, path.read_text(), shape) == []

@pytest.mark.parametrize('history', [False, {}, ['broken'], [{'kind': 'question'}]])
def test_invalid_stored_dialogue_is_rejected_by_shape_and_append(tmp_path, history):
    from wiki_core.page_types import validate_shape
    from wiki_core.action_dialogue import append_event
    assert any('invalid_action_dialogue' in e for e in validate_shape(tmp_path, 'synthetic.md', {'page_type': 'action', 'action_dialogue': history}, '', {}))
    with pytest.raises(ActionTransitionError, match='invalid_action_dialogue'):
        append_event(history, event(), actor='operator', at='2026-10-14T00:00:00Z', before_sha256='a'*64, terminal=False)
