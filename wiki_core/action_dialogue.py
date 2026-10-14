"""Append-only questions, answers and directions on a canonical action.

Actor identity is supplied by the trusted local adapter, not by event text.
Events record communication; they neither admit execution nor grant access.
"""
from __future__ import annotations

import re
from typing import Any

EVENT_ID = re.compile(r"^[a-zA-Z0-9_-]{8,80}$")
KINDS = {"direction", "question", "confirmation_request", "answer", "comment"}
QUESTIONS = {"question", "confirmation_request"}


def append_event(history: Any, event: Any, *, actor: str, at: str,
                 before_sha256: str, terminal: bool) -> list[dict[str, Any]]:
    # Import lazily to share the mutation boundary's safe errors and scanner.
    from wiki_core.action_transition import ActionTransitionError, _assert_no_secrets
    if history is None:
        history = []
    if not isinstance(history, list) or any(not isinstance(e, dict) for e in history):
        raise ActionTransitionError("invalid_action_dialogue")
    if len(history) >= 500:
        raise ActionTransitionError("action_dialogue_capacity")
    if not isinstance(event, dict) or set(event) - {"event_id", "kind", "text", "reply_to", "coordinator"}:
        raise ActionTransitionError("invalid_dialogue_event")
    eid, kind, text = event.get("event_id"), event.get("kind"), event.get("text")
    coordinator, reply = event.get("coordinator"), event.get("reply_to", "")
    if (not isinstance(eid, str) or not EVENT_ID.fullmatch(eid)
        or not isinstance(kind, str) or kind not in KINDS
        or not isinstance(text, str) or not text.strip() or len(text) > 2000
        or not isinstance(coordinator, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", coordinator)
        or not isinstance(reply, str)
        or actor not in {"operator", "coordinator:" + coordinator}):
        raise ActionTransitionError("invalid_dialogue_event")
    if terminal:
        raise ActionTransitionError("terminal_action_dialogue")
    if any(e.get("event_id") == eid for e in history):
        raise ActionTransitionError("duplicate_dialogue_event")
    if kind == "direction" and actor != "operator":
        raise ActionTransitionError("operator_direction_required")
    if kind == "answer":
        question = next((e for e in history if e.get("event_id") == reply), None)
        if not question or question.get("kind") not in QUESTIONS or question.get("coordinator") != coordinator:
            raise ActionTransitionError("unknown_dialogue_question")
        if actor == question.get("actor"):
            raise ActionTransitionError("dialogue_self_answer")
        if any(e.get("kind") == "answer" and e.get("reply_to") == reply for e in history):
            raise ActionTransitionError("dialogue_question_already_answered")
    elif reply:
        raise ActionTransitionError("unexpected_dialogue_reply")
    _assert_no_secrets(text)
    return [*history, {"event_id": eid, "kind": kind, "text": text.strip(),
        "coordinator": coordinator, "actor": actor, "reply_to": reply,
        "at": at, "before_sha256": before_sha256}]


def dialogue_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    answered = {e.get("reply_to") for e in events if e.get("kind") == "answer"}
    pending = [e["event_id"] for e in events if e.get("kind") in QUESTIONS and e.get("event_id") not in answered]
    return {"pending_question_ids": pending, "runtime_connected": False,
            "execution_ready": False, "events": events}
