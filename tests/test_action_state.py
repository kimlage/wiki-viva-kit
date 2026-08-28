from wiki_core.action_state import (
    ACTION_STATE_TRANSITIONS,
    action_is_terminal,
    legacy_action_state_from_body,
    resolve_action_state,
    valid_action_transition,
)


def test_canonical_action_state_wins_over_contradictory_editorial_fields() -> None:
    resolution = resolve_action_state(
        {"action_state": "open", "state": "done", "status": "completed"},
        legacy_state="cancelled",
    )

    assert resolution.state == "open"
    assert resolution.source == "action_state"
    assert resolution.compatibility is False
    assert resolution.warnings == ()
    assert action_is_terminal(
        {"action_state": "open", "status": "done"}, legacy_state="completed"
    ) is False


def test_invalid_canonical_state_never_falls_back_to_legacy_copy() -> None:
    resolution = resolve_action_state(
        {"action_state": "finished", "status": "done"}, legacy_state="completed"
    )

    assert resolution.state == "unknown"
    assert resolution.valid is False
    assert resolution.warnings == ("invalid_action_state",)


def test_legacy_adapter_is_explicit_and_keeps_unknown_editorial_copy_open() -> None:
    closed = resolve_action_state({}, legacy_state="concluida_em_2026-06-12")
    recurring = resolve_action_state({"status": "recurring"})

    assert closed.state == "done"
    assert closed.terminal is True
    assert closed.compatibility is True
    assert recurring.state == "open"
    assert recurring.warnings == (
        "legacy_action_state",
        "unknown_legacy_action_state",
    )


def test_legacy_body_parser_is_bilingual_and_strips_inline_detail() -> None:
    assert legacy_action_state_from_body("# A\n\nState: `completed`.\n") == "completed"
    assert (
        legacy_action_state_from_body("Estado: bloqueada — aguardando revisao.\n")
        == "bloqueada"
    )


def test_transition_table_is_closed_for_terminal_states() -> None:
    assert valid_action_transition("open", "in_progress") is True
    assert valid_action_transition("blocked", "open") is True
    assert valid_action_transition("done", "open") is False
    assert valid_action_transition("cancelled", "in_progress") is False
    assert ACTION_STATE_TRANSITIONS["done"] == frozenset()
