from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from wiki_core.source_lifecycle import (
    SOURCE_ADOPTION_STATES,
    SOURCE_ADOPTION_TRANSITIONS,
    SOURCE_FRESHNESS_STATES,
    SOURCE_LAST_ATTEMPT_STATES,
    SOURCE_LIFECYCLE_STATES,
    SOURCE_LIFECYCLE_TRANSITIONS,
    SOURCE_PIPELINE_STAGES,
    SOURCE_PIPELINE_TRANSITIONS,
    declared_source_lifecycle_field,
    normalize_source_last_attempt_state,
    resolve_source_lifecycle,
    source_lifecycle_diagnostics,
    source_lifecycle_transition_diagnostics,
    source_lifecycle_value,
)


@pytest.mark.parametrize("state", SOURCE_LAST_ATTEMPT_STATES)
def test_canonical_last_attempt_states_are_preserved(state: str) -> None:
    assert normalize_source_last_attempt_state(state) == state
    assert (
        source_lifecycle_diagnostics(
            {"source_lifecycle": {"last_attempt_state": state}}
        )
        == ()
    )


@pytest.mark.parametrize("stage", SOURCE_PIPELINE_STAGES)
def test_canonical_pipeline_stages_are_accepted(stage: str) -> None:
    assert (
        source_lifecycle_diagnostics({"source_lifecycle": {"pipeline_stage": stage}})
        == ()
    )


@pytest.mark.parametrize(
    ("key", "states"),
    (
        ("state", SOURCE_LIFECYCLE_STATES),
        ("freshness_state", SOURCE_FRESHNESS_STATES),
        ("adoption_state", SOURCE_ADOPTION_STATES),
    ),
)
def test_complete_nested_enum_matrix_is_accepted(
    key: str, states: tuple[str, ...]
) -> None:
    for state in states:
        values = {"source_lifecycle": {key: state}}
        error_codes = {
            item.code
            for item in source_lifecycle_diagnostics(values)
            if item.severity == "error" and item.code.startswith("invalid_source_")
        }
        assert error_codes == set()


@pytest.mark.parametrize(
    ("legacy", "canonical"),
    (("partial", "failed"), ("running", "ok"), ("queued", "ok")),
)
def test_legacy_last_attempt_states_normalize_compatibly(
    legacy: str, canonical: str
) -> None:
    assert normalize_source_last_attempt_state(legacy) == canonical


def test_unknown_last_attempt_state_is_never_hidden_by_a_default() -> None:
    assert normalize_source_last_attempt_state("retrying") == "retrying"


def test_contradictory_flattened_and_nested_values_fail_closed() -> None:
    values = {
        "source_last_attempt_state": "ok",
        "source_lifecycle": {
            "last_attempt_state": "retrying",
            "pipeline_stage": "indexed",
        },
    }

    assert source_lifecycle_value(values, "last_attempt_state") == "ok"
    assert declared_source_lifecycle_field(values, "last_attempt_state") == (
        "source_last_attempt_state",
        "ok",
    )
    assert source_lifecycle_value(values, "pipeline_stage") == "indexed"
    diagnostics = source_lifecycle_diagnostics(values)
    assert [item.code for item in diagnostics] == [
        "conflicting_source_last_attempt_state"
    ]
    assert "flattened and nested values must match" in diagnostics[0].message


def test_equivalent_legacy_and_canonical_declarations_are_not_a_conflict() -> None:
    diagnostics = source_lifecycle_diagnostics(
        {
            "source_last_attempt_state": "partial",
            "source_lifecycle": {"last_attempt_state": "failed"},
        }
    )

    assert not any(item.code.startswith("conflicting_") for item in diagnostics)
    assert [item.code for item in diagnostics] == [
        "legacy_source_last_attempt_state"
    ]


def test_nested_lifecycle_diagnostics_are_actionable() -> None:
    diagnostics = source_lifecycle_diagnostics(
        {
            "source_lifecycle": {
                "last_attempt_state": "retrying",
                "pipeline_stage": "em_progresso",
            }
        }
    )

    assert [diagnostic.severity for diagnostic in diagnostics] == ["error", "error"]
    assert diagnostics[0].field == "source_lifecycle.last_attempt_state"
    assert diagnostics[0].value == "retrying"
    assert diagnostics[0].allowed == SOURCE_LAST_ATTEMPT_STATES
    assert "allowed: failed, needs_auth, never, ok" in diagnostics[0].message
    assert diagnostics[1].field == "source_lifecycle.pipeline_stage"
    assert diagnostics[1].value == "em_progresso"
    assert diagnostics[1].allowed == SOURCE_PIPELINE_STAGES


def test_explicit_legacy_value_is_a_non_blocking_authoring_warning() -> None:
    diagnostics = source_lifecycle_diagnostics({"source_last_attempt_state": "partial"})

    assert len(diagnostics) == 1
    assert diagnostics[0].severity == "warning"
    assert diagnostics[0].field == "source_last_attempt_state"
    assert diagnostics[0].normalized_to == "failed"
    assert "normalizes to `failed`" in diagnostics[0].message


def _canonical_source_lifecycle(**updates: object) -> dict[str, object]:
    lifecycle: dict[str, object] = {
        "state": "ready",
        "freshness_state": "never_synced",
        "last_attempt_state": "never",
        "pipeline_stage": "configured",
        "adoption_state": "pending",
    }
    lifecycle.update(updates)
    return {"source_lifecycle": lifecycle}


@pytest.mark.parametrize(
    "values",
    (
        _canonical_source_lifecycle(state="configured"),
        _canonical_source_lifecycle(state="ready"),
        _canonical_source_lifecycle(
            state="syncing",
            freshness_state="fresh",
            last_attempt_state="ok",
            pipeline_stage="indexed",
        ),
        _canonical_source_lifecycle(
            state="proposed",
            freshness_state="fresh",
            last_attempt_state="ok",
            pipeline_stage="proposal_ready",
        ),
        _canonical_source_lifecycle(
            state="consolidated",
            freshness_state="fresh",
            last_attempt_state="ok",
            pipeline_stage="gate_pending",
            emitted_page_ids=["page-one"],
        ),
        _canonical_source_lifecycle(
            state="ingested",
            freshness_state="fresh",
            last_attempt_state="ok",
            pipeline_stage="complete",
            adoption_state="accepted",
            accepted_ref="sha256:accepted",
            emitted_page_ids=["page-one"],
        ),
        _canonical_source_lifecycle(
            state="ingested",
            freshness_state="fresh",
            last_attempt_state="ok",
            pipeline_stage="complete",
            adoption_state="reviewed_no_change",
            accepted_ref="sha256:no-change",
            reviewed_no_change_receipt="receipt:no-change",
        ),
        {
            **_canonical_source_lifecycle(
                state="blocked",
                freshness_state="stale",
                last_attempt_state="failed",
                pipeline_stage="manifested",
            ),
            "source_blocked_reason": "Synthetic parser failed safely.",
        },
    ),
)
def test_valid_fixture_state_matrix(values: dict[str, object]) -> None:
    assert resolve_source_lifecycle(values).valid is True


@pytest.mark.parametrize(
    ("updates", "expected_codes"),
    (
        (
            {
                "state": "ingested",
                "adoption_state": "accepted",
                "emitted_page_ids": ["page-one"],
            },
            {"accepted_source_missing_ref"},
        ),
        (
            {
                "state": "ingested",
                "adoption_state": "accepted",
                "accepted_ref": "sha256:accepted",
            },
            {"accepted_source_missing_closure"},
        ),
        (
            {
                "state": "ingested",
                "adoption_state": "reviewed_no_change",
                "accepted_ref": "sha256:no-change",
            },
            {"reviewed_no_change_missing_receipt"},
        ),
        (
            {"state": "blocked", "last_attempt_state": "ok"},
            {"blocked_source_missing_reason", "blocked_source_attempt_mismatch"},
        ),
        (
            {
                "state": "blocked",
                "last_attempt_state": "failed",
                "adoption_state": "",
                "blocked_reason": "Synthetic failure.",
            },
            {"blocked_source_adoption_mismatch"},
        ),
        (
            {
                "state": "",
                "adoption_state": "accepted",
                "accepted_ref": "sha256:accepted",
                "emitted_page_ids": ["page-one"],
            },
            {"accepted_source_lifecycle_mismatch"},
        ),
    ),
)
def test_acceptance_and_blocker_dependencies_fail_closed(
    updates: dict[str, object], expected_codes: set[str]
) -> None:
    diagnostics = source_lifecycle_diagnostics(
        _canonical_source_lifecycle(**updates)
    )
    codes = {item.code for item in diagnostics}
    assert expected_codes <= codes


def test_invalid_lifecycle_state_is_rejected() -> None:
    diagnostics = source_lifecycle_diagnostics(
        _canonical_source_lifecycle(state="published")
    )

    assert [item.code for item in diagnostics] == [
        "invalid_source_lifecycle_state"
    ]
    assert "`published`" in diagnostics[0].message


def test_secret_shaped_invalid_value_is_never_echoed() -> None:
    secret = "sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz123456"
    diagnostics = source_lifecycle_diagnostics(
        _canonical_source_lifecycle(state=secret)
    )
    rendered = "\n".join(item.message for item in diagnostics)

    assert secret not in rendered
    assert "<redacted:secret>" in rendered


def test_unknown_nested_key_and_malformed_closure_list_are_rejected() -> None:
    values = _canonical_source_lifecycle(
        state="ingested",
        adoption_state="accepted",
        accepted_ref="sha256:accepted",
        emitted_page_ids=["page-one", 2, ""],
        mystery_state="quietly_published",
    )
    codes = {item.code for item in source_lifecycle_diagnostics(values)}

    assert "unknown_source_lifecycle_field" in codes
    assert "invalid_source_emitted_page_ids" in codes
    assert "accepted_source_missing_closure" in codes


def test_reviewed_no_change_receipt_must_be_a_non_empty_string() -> None:
    values = _canonical_source_lifecycle(
        state="ingested",
        adoption_state="reviewed_no_change",
        accepted_ref="sha256:no-change",
        reviewed_no_change_receipt=["not", "a", "receipt"],
    )
    codes = {item.code for item in source_lifecycle_diagnostics(values)}

    assert "invalid_source_reviewed_no_change_receipt" in codes
    assert "reviewed_no_change_missing_receipt" in codes


def _source_document(page_id: str, **updates: object) -> str:
    lifecycle = _canonical_source_lifecycle(**updates)["source_lifecycle"]
    lines = [
        "---",
        f"page_id: {page_id}",
        "page_type: source",
        "source_lifecycle:",
    ]
    assert isinstance(lifecycle, dict)
    for key, value in lifecycle.items():
        if isinstance(value, list):
            lines.append(f"  {key}:")
            lines.extend(f"    - {item}" for item in value)
        else:
            lines.append(f"  {key}: {value}")
    lines.extend(["---", "", "# Source", ""])
    return "\n".join(lines)


def test_transition_tables_are_explicit_and_adoption_is_not_resettable() -> None:
    assert SOURCE_LIFECYCLE_TRANSITIONS["ready"] == frozenset(
        {"syncing", "blocked"}
    )
    assert SOURCE_ADOPTION_TRANSITIONS["accepted"] == frozenset()
    assert SOURCE_ADOPTION_TRANSITIONS["reviewed_no_change"] == frozenset()
    assert SOURCE_PIPELINE_TRANSITIONS["configured"] == frozenset({"manifested"})
    assert SOURCE_PIPELINE_TRANSITIONS["gate_pending"] == frozenset(
        {"integrating", "complete"}
    )
    assert SOURCE_PIPELINE_TRANSITIONS["complete"] == frozenset({"configured"})


def test_illegal_lifecycle_transition_and_adoption_reset_are_diagnosed() -> None:
    illegal_edge = source_lifecycle_transition_diagnostics(
        _source_document("source-one"),
        _source_document(
            "source-one",
            state="ingested",
            freshness_state="fresh",
            last_attempt_state="never",
            pipeline_stage="complete",
            adoption_state="accepted",
            accepted_ref="sha256:accepted",
            emitted_page_ids=["page-one"],
        ),
    )
    assert "illegal_source_lifecycle_transition" in {
        item.code for item in illegal_edge
    }

    accepted = _source_document(
        "source-one",
        state="ingested",
        freshness_state="fresh",
        last_attempt_state="ok",
        pipeline_stage="complete",
        adoption_state="accepted",
        accepted_ref="sha256:accepted",
        emitted_page_ids=["page-one"],
    )
    reset = _source_document(
        "source-one",
        state="ingested",
        freshness_state="fresh",
        last_attempt_state="ok",
        pipeline_stage="complete",
        adoption_state="pending",
    )
    diagnostics = source_lifecycle_transition_diagnostics(accepted, reset)
    assert "illegal_source_adoption_transition" in {
        item.code for item in diagnostics
    }


def test_removing_an_existing_lifecycle_state_is_an_illegal_edge() -> None:
    previous = _source_document("source-one")
    current = previous.replace("  state: ready\n", "")

    diagnostics = source_lifecycle_transition_diagnostics(previous, current)

    assert [item.code for item in diagnostics] == [
        "illegal_source_lifecycle_transition"
    ]


def test_legal_existing_source_change_still_requires_future_writer_receipts() -> None:
    diagnostics = source_lifecycle_transition_diagnostics(
        _source_document("source-one"),
        _source_document(
            "source-one",
            state="syncing",
            freshness_state="fresh",
            last_attempt_state="ok",
            pipeline_stage="manifested",
        ),
    )
    assert {item.code for item in diagnostics} == {
        "source_lifecycle_transition_receipt_required",
        "source_pipeline_transition_receipt_required",
        "source_attempt_receipt_required",
    }


def test_pipeline_forward_retry_and_reset_edges_fail_closed_distinctly() -> None:
    forward = source_lifecycle_transition_diagnostics(
        _source_document("source-one", pipeline_stage="configured"),
        _source_document("source-one", pipeline_stage="manifested"),
    )
    assert [item.code for item in forward] == [
        "source_pipeline_transition_receipt_required"
    ]

    review_retry = source_lifecycle_transition_diagnostics(
        _source_document("source-one", pipeline_stage="gate_pending"),
        _source_document("source-one", pipeline_stage="integrating"),
    )
    assert [item.code for item in review_retry] == [
        "source_pipeline_transition_receipt_required"
    ]

    reset = source_lifecycle_transition_diagnostics(
        _source_document("source-one", pipeline_stage="indexed"),
        _source_document("source-one", pipeline_stage="extracted"),
    )
    assert [item.code for item in reset] == [
        "illegal_source_pipeline_reset"
    ]

    skipped_forward_stage = source_lifecycle_transition_diagnostics(
        _source_document("source-one", pipeline_stage="configured"),
        _source_document("source-one", pipeline_stage="indexed"),
    )
    assert [item.code for item in skipped_forward_stage] == [
        "illegal_source_pipeline_transition"
    ]


def test_first_canonical_adoption_has_no_prior_transition_edge() -> None:
    previous = "---\npage_id: source-one\npage_type: source\n---\n\n# Source\n"
    current = _source_document(
        "source-one",
        state="ingested",
        freshness_state="fresh",
        last_attempt_state="ok",
        pipeline_stage="complete",
        adoption_state="accepted",
        accepted_ref="sha256:accepted",
        emitted_page_ids=["page-one"],
    )

    assert source_lifecycle_transition_diagnostics(previous, current) == ()


def test_published_json_schema_matches_acceptance_dependencies() -> None:
    schema_path = (
        Path(__file__).parents[1]
        / "docs/references/schemas/wiki-source-lifecycle-v2.schema.json"
    )
    validator = Draft202012Validator(
        json.loads(schema_path.read_text(encoding="utf-8"))
    )
    valid = _canonical_source_lifecycle(
        state="ingested",
        freshness_state="fresh",
        last_attempt_state="ok",
        pipeline_stage="complete",
        adoption_state="accepted",
        accepted_ref="sha256:accepted",
        emitted_page_ids=["page-one"],
    )["source_lifecycle"]
    invalid = _canonical_source_lifecycle(
        state="ingested",
        adoption_state="accepted",
        emitted_page_ids=["page-one"],
    )["source_lifecycle"]
    ready_accepted = _canonical_source_lifecycle(
        state="ready",
        adoption_state="accepted",
        accepted_ref="sha256:accepted",
        emitted_page_ids=["page-one"],
    )["source_lifecycle"]
    unknown_timestamp = _canonical_source_lifecycle(
        pipeline_stage_timestamps={"quietly_published": "2026-07-11T10:00:00Z"}
    )["source_lifecycle"]

    assert list(validator.iter_errors(valid)) == []
    assert any(
        error.validator == "required" for error in validator.iter_errors(invalid)
    )
    assert any(
        error.validator == "const"
        for error in validator.iter_errors(ready_accepted)
    )
    assert any(
        error.validator == "enum"
        for error in validator.iter_errors(unknown_timestamp)
    )
