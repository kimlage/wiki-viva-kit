from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker

from wiki_core.config import WikiConfig
from wiki_core.action_transition import transition_action_page
from wiki_core.temporal import parse_temporal_event
from wiki_core.web.schemas import SNAPSHOT_FILES
from wiki_core.web.snapshot import _write_snapshot_artifacts, build_snapshot
from wiki_core.web.temporal import (
    _events_fingerprint,
    build_temporal_events,
    build_temporal_graph_payload,
    paginate_temporal_events,
    temporal_graph_errors,
)
from wiki_core.web.timeline import build_timeline_payload

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/temporal"


def _fixture(name: str) -> dict[str, object]:
    return parse_temporal_event(
        json.loads((FIXTURES / name).read_text(encoding="utf-8")),
        public_boundary=True,
    )


def _models() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    pages = {
        "pages": [
            {
                "id": "page-note",
                "path": "memories/example/note.md",
                "page_type": "context_note",
                "context": "example",
                "visibility": "public",
                "updated_at": "2026-07-01",
                "source_refs": ["source-public"],
                "relation_refs": {"evidence_refs": ["receipt-public"]},
                "temporal": {"dates": {}, "precision": {}, "action_state_history": []},
            },
            {
                "id": "source-public",
                "path": "memories/sources/public.md",
                "page_type": "source",
                "context": "example",
                "visibility": "public",
                "updated_at": "2026-06-01",
                "source_refs": [],
                "relation_refs": {"evidence_refs": []},
                "temporal": {"dates": {}, "precision": {}, "action_state_history": []},
            },
            {
                "id": "event-public",
                "path": "memories/system/ingestion/events/public.md",
                "page_type": "ingestion_event",
                "context": "example",
                "visibility": "public",
                "updated_at": "2026-06-10",
                "source_refs": ["source-public"],
                "relation_refs": {"evidence_refs": []},
                "temporal": {
                    "dates": {
                        "captured_at": "2026-05",
                        "verified_at": "2026-06-11",
                    },
                    "precision": {"captured_at": "month"},
                    "action_state_history": [],
                },
            },
            {
                "id": "decision-public",
                "path": "memories/decisions/public.md",
                "page_type": "decision",
                "context": "example",
                "visibility": "public",
                "updated_at": "2026-06-12",
                "source_refs": ["source-public"],
                "relation_refs": {"evidence_refs": []},
                "temporal": {
                    "dates": {"decided_at": "2025"},
                    "precision": {"decided_at": "year"},
                    "action_state_history": [],
                },
            },
            {
                "id": "action-public",
                "path": "memories/actions/public.md",
                "page_type": "action",
                "context": "example",
                "visibility": "public",
                "updated_at": "2026-06-15",
                "source_refs": ["source-public"],
                "relation_refs": {"evidence_refs": ["receipt-public"]},
                "work": {
                    "state": "done",
                    "created_at": "2026-06-01",
                    "due_at": "2026-06-14",
                    "completed_at": "2026-06-13",
                    "completion_receipt": "commit:abc123",
                    "cancellation_receipt": "",
                },
                "temporal": {
                    "dates": {
                        "created_at": "2026-06-01",
                        "due_at": "2026-06-14",
                        "completed_at": "2026-06-13",
                    },
                    "precision": {},
                    "action_state_history": [
                        {
                            "receipt_id": "sha256:" + "a" * 64,
                            "prior_receipt_id": "",
                            "previous_state": "open",
                            "next_state": "done",
                            "recorded_at": "2026-06-13T14:00:00Z",
                        }
                    ],
                },
            },
        ]
    }
    source_lifecycle = {
        "sources": [
            {
                "source_id": "source-public",
                "lifecycle_state": "ingested",
                "adoption_state": "accepted",
                "last_ingested_at": "2026-06-10",
                "last_sync_success_at": "2026-06-11T10:00:00Z",
                "last_run_at": "2026-06-11T10:00:00Z",
                "last_attempt_at": "2026-06-11T10:00:00Z",
                "last_attempt_state": "ok",
                "pipeline_stage_timestamps": {
                    "manifested": "2026-06-08",
                    "complete": "2026-06-12",
                },
                "reviewed_no_change_receipt": "sha256:" + "b" * 64,
            }
        ]
    }
    activity = {
        "events": [
            {
                "id": "snapshot-generated",
                "kind": "snapshot",
                "timestamp": "2026-07-11T12:00:00Z",
                "context": "system",
                "status": "draft",
                "commit": "",
            },
            {
                "id": "git-abc123",
                "kind": "git_commit",
                "timestamp": "2026-07-10T12:00:00Z",
                "context": "git",
                "status": "committed",
                "commit": "abc123def456",
            },
            {
                "id": "legacy-future",
                "kind": "future_legacy_kind",
                "timestamp": "2026-07-09T12:00:00Z",
                "context": "system",
                "status": "observed",
                "commit": "",
            },
        ]
    }
    return pages, source_lifecycle, activity


def test_adapters_emit_page_source_ingestion_action_decision_and_receipt_events() -> None:
    pages, sources, activity = _models()
    events, diagnostics = build_temporal_events(
        pages, sources, activity, public_boundary=True
    )
    kinds = {event["kind"] for event in events}

    assert diagnostics == []
    assert {
        "page_updated",
        "source_ingested",
        "source_refreshed",
        "source_pipeline_advanced",
        "ingestion_recorded",
        "decision_made",
        "action_created",
        "action_due",
        "action_completed",
        "action_state_changed",
        "receipt_recorded",
        "snapshot_recorded",
        "git_commit_recorded",
        "activity_recorded",
    } <= kinds
    ingestion = next(event for event in events if event["kind"] == "ingestion_recorded")
    assert ingestion["occurred_at"] == "2026-05"
    assert ingestion["precision"]["occurred_at"] == "month"
    decision = next(event for event in events if event["kind"] == "decision_made")
    assert decision["occurred_at"] == "2025"
    assert decision["precision"]["occurred_at"] == "year"
    legacy = next(
        event
        for event in events
        if event["origin"].get("legacy_kind") == "future_legacy_kind"
    )
    assert legacy["kind"] == "activity_recorded"


def test_legacy_typed_event_in_canonical_event_directory_is_visually_reachable() -> None:
    def page(page_id: str, page_type: str, path: str) -> dict[str, object]:
        return {
            "id": page_id,
            "path": path,
            "page_type": page_type,
            "context": "system",
            "visibility": "private_self",
            "updated_at": "2026-07-11",
            "source_refs": ["source-public"],
            "relation_refs": {"evidence_refs": []},
            "temporal": {
                "dates": {"captured_at": "2026-07-10"},
                "precision": {},
                "action_state_history": [],
            },
        }

    pages = {
        "pages": [
            page(
                "event-canonical",
                "ingestion_event",
                "memories/system/ingestion/events/canonical.md",
            ),
            page(
                "event-legacy",
                "source_catalog",
                "memories/system/ingestion/events/legacy.md",
            ),
            page(
                "catalog-outside",
                "source_catalog",
                "memories/sources/catalog.md",
            ),
        ]
    }

    events, diagnostics = build_temporal_events(
        pages, {"sources": []}, {"events": []}
    )
    ingestion = [event for event in events if event["kind"] == "ingestion_recorded"]

    assert diagnostics == []
    assert {
        tuple(event["subject_refs"])
        for event in ingestion
    } == {("page:event-canonical",), ("page:event-legacy",)}
    legacy = next(
        event
        for event in ingestion
        if event["subject_refs"] == ["page:event-legacy"]
    )
    assert legacy["origin"] == {
        "adapter": "ingestion_event_compat.v1",
        "legacy_kind": "source_catalog",
    }


def test_cancelled_action_without_receipt_never_fabricates_none_receipt() -> None:
    pages = {
        "pages": [
            {
                "id": "action-cancelled",
                "page_type": "action",
                "context": "system",
                "visibility": "public",
                "updated_at": "2026-07-11",
                "source_refs": [],
                "relation_refs": {"evidence_refs": []},
                "work": {
                    "state": "cancelled",
                    "cancellation_receipt": None,
                    "completion_receipt": None,
                },
                "temporal": {
                    "dates": {"completed_at": "2026-07-11"},
                    "precision": {},
                    "action_state_history": [],
                },
            }
        ]
    }

    events, diagnostics = build_temporal_events(
        pages, {"sources": []}, {"events": []}, public_boundary=True
    )

    assert "action_cancelled" in {event["kind"] for event in events}
    assert "receipt_recorded" not in {event["kind"] for event in events}
    assert "None" not in json.dumps(events)
    assert any(
        "terminal_action_missing_receipt" in row["error_codes"]
        for row in diagnostics
    )


def test_legacy_completed_state_is_not_silently_treated_as_canonical_done() -> None:
    pages = {
        "pages": [
            {
                "id": "action-legacy-completed",
                "page_type": "action",
                "context": "system",
                "visibility": "public",
                "updated_at": "2026-07-11",
                "source_refs": [],
                "relation_refs": {"evidence_refs": []},
                "work": {
                    "state": "completed",
                    "completion_receipt": "commit:legacy",
                },
                "temporal": {
                    "dates": {"completed_at": "2026-07-11"},
                    "precision": {},
                    "action_state_history": [],
                },
            }
        ]
    }

    events, diagnostics = build_temporal_events(
        pages, {"sources": []}, {"events": []}, public_boundary=True
    )

    assert not {"action_completed", "action_cancelled"} & {
        event["kind"] for event in events
    }
    codes = {code for row in diagnostics for code in row["error_codes"]}
    assert {
        "invalid_canonical_action_state",
        "completed_at_requires_canonical_terminal_state",
    } <= codes


def test_rejected_middle_action_transition_never_creates_dangling_cause() -> None:
    pages = {
        "pages": [
            {
                "id": "action-causal-gap",
                "page_type": "action",
                "context": "system",
                "visibility": "public",
                "updated_at": "2026-07-11",
                "source_refs": [],
                "relation_refs": {"evidence_refs": []},
                "work": {"state": "in_progress"},
                "temporal": {
                    "dates": {},
                    "precision": {},
                    "action_state_history": [
                        {
                            "receipt_id": "sha256:" + "1" * 64,
                            "prior_receipt_id": "",
                            "receipt_kind": "transition",
                            "previous_state": "open",
                            "next_state": "in_progress",
                            "recorded_at": "2026-07-11T10:00:00Z",
                        },
                        {
                            "receipt_id": "sha256:" + "2" * 64,
                            "prior_receipt_id": "sha256:" + "1" * 64,
                            "receipt_kind": "transition",
                            "previous_state": "in_progress",
                            "next_state": "blocked",
                            "recorded_at": "invalid-date",
                        },
                        {
                            "receipt_id": "sha256:" + "3" * 64,
                            "prior_receipt_id": "sha256:" + "2" * 64,
                            "receipt_kind": "transition",
                            "previous_state": "blocked",
                            "next_state": "open",
                            "recorded_at": "2026-07-11T12:00:00Z",
                        },
                    ],
                },
            }
        ]
    }

    payload = build_temporal_graph_payload(
        pages,
        {"sources": []},
        {"events": []},
        repo_id="action-causal-gap",
        generated_at="2026-07-11T13:00:00Z",
        public_boundary=True,
        limit=None,
    )
    transition_events = [
        event
        for event in payload["events"]
        if event["kind"] == "action_state_changed"
    ]
    receipt_events = [
        event for event in payload["events"] if event["kind"] == "receipt_recorded"
    ]
    codes = {
        code
        for diagnostic in payload["diagnostics"]
        for code in diagnostic["error_codes"]
    }

    assert [event["after"]["state"] for event in transition_events] == [
        "in_progress"
    ]
    assert len(receipt_events) == 1
    assert {
        "recorded_at_invalid_temporal_value",
        "transition_receipt_chain_discontinuous",
    } <= codes
    assert temporal_graph_errors(payload) == []


def test_invalid_terminal_reopen_history_emits_diagnostic_not_false_event() -> None:
    pages = {
        "pages": [
            {
                "id": "action-impossible-reopen",
                "page_type": "action",
                "context": "system",
                "visibility": "public",
                "updated_at": "2026-07-11",
                "source_refs": [],
                "relation_refs": {"evidence_refs": []},
                "work": {"state": "open"},
                "temporal": {
                    "dates": {},
                    "precision": {},
                    "action_state_history": [
                        {
                            "receipt_id": "sha256:" + "4" * 64,
                            "prior_receipt_id": "",
                            "receipt_kind": "transition",
                            "previous_state": "done",
                            "next_state": "open",
                            "recorded_at": "2026-07-11T10:00:00Z",
                        }
                    ],
                },
            }
        ]
    }

    events, diagnostics = build_temporal_events(
        pages, {"sources": []}, {"events": []}, public_boundary=True
    )

    action_history = [
        event
        for event in events
        if event["kind"] in {"action_state_changed", "receipt_recorded"}
    ]
    assert action_history == []
    assert any(
        "transition_receipt_has_invalid_transition" in row["error_codes"]
        for row in diagnostics
    )


@pytest.mark.parametrize("receipt_id", ["", "receipt-arbitrary"])
def test_untrusted_action_receipt_id_never_emits_confirmed_history(
    receipt_id: str,
) -> None:
    pages = {
        "pages": [
            {
                "id": "action-untrusted-receipt",
                "page_type": "action",
                "context": "system",
                "visibility": "public",
                "updated_at": "2026-07-11",
                "source_refs": [],
                "relation_refs": {"evidence_refs": []},
                "work": {"state": "in_progress"},
                "temporal": {
                    "dates": {},
                    "precision": {},
                    "action_state_history": [
                        {
                            "receipt_id": receipt_id,
                            "prior_receipt_id": "",
                            "receipt_kind": "transition",
                            "previous_state": "open",
                            "next_state": "in_progress",
                            "recorded_at": "2026-07-11T10:00:00Z",
                        }
                    ],
                },
            }
        ]
    }

    events, diagnostics = build_temporal_events(
        pages, {"sources": []}, {"events": []}, public_boundary=True
    )

    assert not {
        "action_state_changed",
        "action_state_canonicalized",
        "action_contract_updated",
        "receipt_recorded",
    } & {event["kind"] for event in events}
    assert any(
        "transition_receipt_id_invalid" in row["error_codes"]
        for row in diagnostics
    )


def test_state_preserving_receipts_use_truthful_kinds_and_reject_unknown_kind() -> None:
    first_receipt = "sha256:" + "1" * 64
    second_receipt = "sha256:" + "2" * 64
    pages = {
        "pages": [
            {
                "id": "action-state-preserving",
                "page_type": "action",
                "context": "system",
                "visibility": "public",
                "updated_at": "2026-07-11",
                "source_refs": [],
                "relation_refs": {"evidence_refs": []},
                "work": {"state": "open"},
                "temporal": {
                    "dates": {},
                    "precision": {},
                    "action_state_history": [
                        {
                            "receipt_id": first_receipt,
                            "prior_receipt_id": "",
                            "receipt_kind": "legacy_canonicalization",
                            "previous_state": "open",
                            "next_state": "open",
                            "recorded_at": "2026-07-11T10:00:00Z",
                        },
                        {
                            "receipt_id": second_receipt,
                            "prior_receipt_id": first_receipt,
                            "receipt_kind": "contract_update",
                            "previous_state": "open",
                            "next_state": "open",
                            "recorded_at": "2026-07-11T11:00:00Z",
                        },
                        {
                            "receipt_id": "sha256:" + "3" * 64,
                            "prior_receipt_id": second_receipt,
                            "receipt_kind": "unknown_same_state_kind",
                            "previous_state": "open",
                            "next_state": "open",
                            "recorded_at": "2026-07-11T12:00:00Z",
                        },
                    ],
                },
            }
        ]
    }

    payload = build_temporal_graph_payload(
        pages,
        {"sources": []},
        {"events": []},
        repo_id="action-state-preserving",
        generated_at="2026-07-11T13:00:00Z",
        public_boundary=True,
        limit=None,
    )
    kinds = [
        event["kind"]
        for event in payload["events"]
        if event["kind"].startswith("action_")
    ]

    assert "action_state_changed" not in kinds
    assert set(kinds) == {
        "action_state_canonicalized",
        "action_contract_updated",
    }
    assert sum(
        event["kind"] == "receipt_recorded" for event in payload["events"]
    ) == 2
    assert any(
        "transition_receipt_state_preserving_kind_invalid"
        in row["error_codes"]
        for row in payload["diagnostics"]
    )
    assert temporal_graph_errors(payload) == []


def test_action_history_state_chain_and_current_state_must_reconcile() -> None:
    pages = {
        "pages": [
            {
                "id": "action-state-discontinuity",
                "page_type": "action",
                "context": "system",
                "visibility": "public",
                "updated_at": "2026-07-11",
                "source_refs": [],
                "relation_refs": {"evidence_refs": []},
                "work": {"state": "blocked"},
                "temporal": {
                    "dates": {},
                    "precision": {},
                    "action_state_history": [
                        {
                            "receipt_id": "sha256:" + "1" * 64,
                            "prior_receipt_id": "",
                            "receipt_kind": "transition",
                            "previous_state": "open",
                            "next_state": "in_progress",
                            "recorded_at": "2026-07-11T10:00:00Z",
                        },
                        {
                            "receipt_id": "sha256:" + "2" * 64,
                            "prior_receipt_id": "sha256:" + "1" * 64,
                            "receipt_kind": "transition",
                            "previous_state": "open",
                            "next_state": "done",
                            "recorded_at": "2026-07-11T11:00:00Z",
                        },
                    ],
                },
            }
        ]
    }

    events, diagnostics = build_temporal_events(
        pages, {"sources": []}, {"events": []}, public_boundary=True
    )
    transitions = [
        event for event in events if event["kind"] == "action_state_changed"
    ]
    codes = {code for row in diagnostics for code in row["error_codes"]}

    assert [event["after"]["state"] for event in transitions] == ["in_progress"]
    assert {
        "transition_history_state_discontinuous",
        "transition_history_final_state_mismatch",
    } <= codes


def test_rejected_middle_source_stage_keeps_last_emitted_causal_pointer() -> None:
    pages = {
        "pages": [
            {
                "id": "source-causal-gap",
                "page_type": "source",
                "context": "system",
                "visibility": "public",
                "updated_at": "2026-07-11",
                "source_refs": [],
                "relation_refs": {"evidence_refs": []},
                "temporal": {
                    "dates": {},
                    "precision": {},
                    "action_state_history": [],
                },
            }
        ]
    }
    sources = {
        "sources": [
            {
                "source_id": "source-causal-gap",
                "lifecycle_state": "configured",
                "pipeline_stage_timestamps": {
                    "manifested": "2026-07-11T10:00:00Z",
                    "rejected": "2026-07-11T11:00:00+25:00",
                    "complete": "2026-07-11T12:00:00Z",
                },
            }
        ]
    }

    payload = build_temporal_graph_payload(
        pages,
        sources,
        {"events": []},
        repo_id="source-causal-gap",
        generated_at="2026-07-11T13:00:00Z",
        public_boundary=True,
        limit=None,
    )
    stages = {
        event["after"]["pipeline_stage"]: event
        for event in payload["events"]
        if event["kind"] == "source_pipeline_advanced"
    }

    assert set(stages) == {"manifested", "complete"}
    assert stages["manifested"]["caused_by"] == []
    assert stages["complete"]["caused_by"] == [
        f"event:{stages['manifested']['event_id']}"
    ]
    assert any(
        "recorded_at_invalid_temporal_value" in row["error_codes"]
        for row in payload["diagnostics"]
    )
    assert temporal_graph_errors(payload) == []


def test_temporal_graph_cursor_pages_reconcile_counts_ranges_and_stale_cursor() -> None:
    events = [_fixture("imprecise-event.json"), _fixture("conflicting-event.json")]
    # Add stable distinct copies to exercise more than one page.
    expanded = []
    for index in range(5):
        event = dict(events[index % 2])
        event["event_id"] = f"evt_pagination_{index}"
        expanded.append(event)

    first = paginate_temporal_events(
        expanded,
        repo_id="temporal-fixture",
        generated_at="2026-07-11T12:00:00Z",
        limit=2,
    )
    second = paginate_temporal_events(
        expanded,
        repo_id="temporal-fixture",
        generated_at="2026-07-11T12:00:00Z",
        limit=2,
        cursor=first["next_cursor"],
    )
    third = paginate_temporal_events(
        expanded,
        repo_id="temporal-fixture",
        generated_at="2026-07-11T12:00:00Z",
        limit=2,
        cursor=second["next_cursor"],
    )

    assert first["event_count"] == first["total_count"] == 5
    assert first["returned_count"] == len(first["events"]) == 2
    assert first["range"]["event_count"] == 5
    assert first["summary"]["event_count"] == 5
    assert first["truncated"] is True and first["page"]["remaining_count"] == 3
    assert second["page"]["offset"] == 2
    assert third["returned_count"] == 1
    assert third["truncated"] is False and third["next_cursor"] is None
    assert temporal_graph_errors(first) == []

    changed = [*expanded, {**expanded[0], "event_id": "evt_pagination_changed"}]
    with pytest.raises(ValueError, match="stale or invalid temporal cursor"):
        paginate_temporal_events(
            changed,
            repo_id="temporal-fixture",
            generated_at="2026-07-11T12:00:00Z",
            limit=2,
            cursor=first["next_cursor"],
        )


def test_causal_references_resolve_against_full_result_before_pagination() -> None:
    first = _fixture("imprecise-event.json")
    second = _fixture("conflicting-event.json")
    first["caused_by"] = [f"event:{second['event_id']}"]
    second["supersedes"] = [f"event:{first['event_id']}"]
    events = [first, second]

    partial = paginate_temporal_events(
        events,
        repo_id="temporal-causal-pagination",
        generated_at="2026-07-11T12:00:00Z",
        limit=1,
    )

    # The first page legitimately points beyond its returned slice. Its full
    # canonical input was validated before pagination, so page-local validation
    # must not misclassify that reference as dangling.
    assert partial["returned_count"] == 1
    assert partial["truncated"] is True
    assert temporal_graph_errors(partial) == []

    for field in ("caused_by", "supersedes"):
        invalid = json.loads(json.dumps(events))
        invalid[0][field] = ["event:missing-event"]
        with pytest.raises(ValueError, match=rf"{field} target is unresolved"):
            paginate_temporal_events(
                invalid,
                repo_id="temporal-causal-pagination",
                generated_at="2026-07-11T12:00:00Z",
                limit=1,
            )

    complete = paginate_temporal_events(
        events,
        repo_id="temporal-causal-static",
        generated_at="2026-07-11T12:00:00Z",
        limit=None,
    )
    complete["events"][0]["caused_by"] = ["event:missing-event"]
    assert (
        "temporal graph caused_by target is unresolved"
        in temporal_graph_errors(complete)
    )


def test_far_future_same_millisecond_keeps_exact_order_across_cursor_pages() -> None:
    pages = {
        "pages": [
            {
                "id": "older",
                "page_type": "context_note",
                "context": "system",
                "visibility": "public",
                "updated_at": "9998-12-31T23:59:59.123455Z",
                "source_refs": [],
                "relation_refs": {"evidence_refs": []},
                "temporal": {
                    "dates": {},
                    "precision": {},
                    "action_state_history": [],
                },
            },
            {
                "id": "newer",
                "page_type": "context_note",
                "context": "system",
                "visibility": "public",
                "updated_at": "9998-12-31T23:59:59.123456Z",
                "source_refs": [],
                "relation_refs": {"evidence_refs": []},
                "temporal": {
                    "dates": {},
                    "precision": {},
                    "action_state_history": [],
                },
            },
        ]
    }

    events, diagnostics = build_temporal_events(
        pages, {"sources": []}, {"events": []}, public_boundary=True
    )
    first = paginate_temporal_events(
        events,
        repo_id="temporal-far-future",
        generated_at="2026-07-11T12:00:00Z",
        limit=1,
    )
    second = paginate_temporal_events(
        events,
        repo_id="temporal-far-future",
        generated_at="2026-07-11T12:00:00Z",
        limit=1,
        cursor=first["next_cursor"],
    )

    assert diagnostics == []
    assert [event["recorded_at"] for event in events] == [
        "9998-12-31T23:59:59.123456Z",
        "9998-12-31T23:59:59.123455Z",
    ]
    assert first["events"][0]["recorded_at"].endswith(".123456Z")
    assert first["truncated"] is True
    assert second["events"][0]["recorded_at"].endswith(".123455Z")
    assert second["next_cursor"] is None


def test_activity_timeline_compatibility_keeps_kinds_without_silent_cap(
    tmp_path: Path,
) -> None:
    pages = {
        "pages": [
            {
                "id": f"page-{index}",
                "path": f"memories/example/{index}.md",
                "title": f"Page {index}",
                "page_type": "context_note",
                "context": "example",
                "updated_at": "2026-07-01",
                "freshness_state": "fresh",
            }
            for index in range(200)
        ]
    }
    timeline = build_timeline_payload(
        tmp_path,
        WikiConfig(repo_id="timeline-fixture", default_context="system"),
        pages,
        {"updated_at": "", "title": "Operations"},
        {"proposal": {"human_gate_state": "draft"}},
        generated_at="2026-07-11T12:00:00Z",
    )

    assert timeline["schema_version"] == "wiki_web_timeline.v1"
    assert timeline["contract_version"] == "activity_timeline.v1"
    assert timeline["compatibility"] == {
        "legacy_schema_version": "wiki_web_timeline.v1",
        "legacy_event_kinds_preserved": True,
        "replacement_payload": "temporal_graph.json",
    }
    assert timeline["event_count"] == timeline["returned_count"] == 201
    assert len(timeline["events"]) == 201
    assert timeline["truncated"] is False
    assert timeline["next_cursor"] is None
    assert {event["kind"] for event in timeline["events"]} == {
        "snapshot",
        "page_updated",
    }


def test_snapshot_manifest_integrates_temporal_graph_and_pins_all_versions(
    tmp_path: Path,
) -> None:
    memories = tmp_path / "memories"
    memories.mkdir()
    (memories / "index.md").write_text(
        """---
page_id: root
page_type: root_index
title: Public temporal root
context: system
visibility: public
updated_at: 2026-07-11
stale_after_days: 30
---

# Public temporal root

Synthetic public fixture.
""",
        encoding="utf-8",
    )
    snapshot = build_snapshot(
        tmp_path,
        WikiConfig(repo_id="temporal-snapshot"),
        generated_at="2026-07-11T12:00:00Z",
    )

    assert "temporal_graph.json" in SNAPSHOT_FILES
    assert tuple(snapshot) == SNAPSHOT_FILES
    assert snapshot["manifest.json"]["capabilities"].count("temporal_graph") == 1
    expected_versions = {
        "activity_timeline": "activity_timeline.v1",
        "temporal_event": "wiki_temporal_event.v1",
        "temporal_graph": "wiki_temporal_graph.v1",
    }
    assert {
        key: snapshot["manifest.json"]["versions"][key]
        for key in expected_versions
    } == expected_versions
    assert snapshot["manifest.json"]["contract_errors"] == []
    temporal = snapshot["temporal_graph.json"]
    assert temporal["event_count"] == temporal["returned_count"]
    assert temporal["truncated"] is False


def test_canonical_action_writer_flows_through_snapshot_into_temporal_events(
    tmp_path: Path,
) -> None:
    memories = tmp_path / "memories"
    actions = memories / "actions"
    actions.mkdir(parents=True)
    (memories / "index.md").write_text(
        """---
page_id: root
page_type: root_index
title: Public action root
context: system
visibility: public
updated_at: 2026-07-11
stale_after_days: 30
---

# Public action root
""",
        encoding="utf-8",
    )
    action = actions / "action-synthetic-transition.md"
    action.write_text(
        """---
page_id: action-synthetic-transition
page_type: action
title: Synthetic transition
context: system
visibility: public
updated_at: 2026-07-10
stale_after_days: 30
moc_parent: memories/index.md
action_state: open
status: pending
owner_kind: unassigned
next_action: Review the synthetic transition.
created_at: 2026-07-10
priority: normal
attention_basis: Synthetic temporal integration.
source_refs: []
---

# Synthetic transition
""",
        encoding="utf-8",
    )
    transition_action_page(
        tmp_path,
        action.relative_to(tmp_path),
        "in_progress",
        reason="Synthetic integration proof.",
        expected_sha256=hashlib.sha256(action.read_bytes()).hexdigest(),
        recorded_at="2026-07-11T14:30:00Z",
    )

    snapshot = build_snapshot(
        tmp_path,
        WikiConfig(repo_id="action-transition-temporal"),
        generated_at="2026-07-11T15:00:00Z",
    )
    action_page = next(
        page
        for page in snapshot["pages.json"]["pages"]
        if page["id"] == "action-synthetic-transition"
    )
    assert action_page["temporal"]["action_state_history"] == [
        {
            "receipt_id": action_page["temporal"]["action_state_history"][0][
                "receipt_id"
            ],
            "prior_receipt_id": "",
            "receipt_kind": "transition",
            "previous_state": "open",
            "next_state": "in_progress",
            "recorded_at": "2026-07-11T14:30:00Z",
        }
    ]
    temporal = snapshot["temporal_graph.json"]
    transition_events = [
        event
        for event in temporal["events"]
        if event["kind"] in {"action_state_changed", "receipt_recorded"}
        and "page:action-synthetic-transition" in event["subject_refs"]
    ]
    assert {event["kind"] for event in transition_events} == {
        "action_state_changed",
        "receipt_recorded",
    }
    assert not any(
        "transition_receipt_has_noncanonical_state" in diagnostic["error_codes"]
        for diagnostic in temporal["diagnostics"]
    )


def test_static_temporal_graph_is_complete_and_schema_valid() -> None:
    pages, sources, activity = _models()
    payload = build_temporal_graph_payload(
        pages,
        sources,
        activity,
        repo_id="temporal-fixture",
        generated_at="2026-07-11T12:00:00Z",
        public_boundary=True,
        limit=None,
    )

    assert payload["event_count"] == payload["total_count"]
    assert payload["returned_count"] == payload["total_count"]
    assert payload["truncated"] is False
    assert payload["next_cursor"] is None
    assert payload["page"]["remaining_count"] == 0
    assert payload["range"]["basis"] == "full_result"
    assert payload["returned_range"]["basis"] == "returned_page"
    assert temporal_graph_errors(payload) == []

    event_schema = json.loads(
        (
            ROOT
            / "docs/references/schemas/wiki-temporal-event-v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    graph_schema = json.loads(
        (
            ROOT
            / "docs/references/schemas/wiki-temporal-graph-v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    standalone_event_schema = {
        key: value
        for key, value in event_schema.items()
        if key not in {"$schema", "$id", "title"}
    }

    def embedded_refs(value: object) -> object:
        if isinstance(value, list):
            return [embedded_refs(item) for item in value]
        if isinstance(value, dict):
            return {
                key: (
                    item.replace(
                        "#/$defs/", "#/$defs/temporal_event/$defs/", 1
                    )
                    if key == "$ref"
                    and isinstance(item, str)
                    and item.startswith("#/$defs/")
                    else embedded_refs(item)
                )
                for key, item in value.items()
            }
        return value

    assert graph_schema["properties"]["events"]["items"] == {
        "$ref": "#/$defs/temporal_event"
    }
    assert graph_schema["$defs"]["temporal_event"] == embedded_refs(
        standalone_event_schema
    )
    errors = list(
        Draft202012Validator(
            graph_schema,
            format_checker=FormatChecker(),
        ).iter_errors(payload)
    )
    assert errors == []


def test_showcase_namespaced_pack_event_validates_against_offline_graph_schema() -> None:
    profiles = yaml.safe_load(
        (ROOT / "packs/study-research/temporal/profiles.yaml").read_text(
            encoding="utf-8"
        )
    )
    adapter_id = "study-research.learning-captured"
    adapter = {"adapter_id": adapter_id, **profiles["adapters"][adapter_id]}
    pages = {
        "pages": [
            {
                "id": "study-source-showcase",
                "path": "memories/study/source-showcase.md",
                "page_type": adapter["page_type"],
                "context": "study",
                "visibility": "public",
                "source_refs": [],
                "relation_refs": {"evidence_refs": []},
                "temporal": {
                    "dates": {},
                    "adapter_fields": {"captured_at": "2024-05"},
                    "precision": {"captured_at": "month"},
                    "action_state_history": [],
                },
            }
        ]
    }
    payload = build_temporal_graph_payload(
        pages,
        {"sources": []},
        {"events": []},
        repo_id="pack-showcase",
        generated_at="2026-07-11T12:00:00Z",
        public_boundary=True,
        limit=None,
        pack_temporal_adapters=[adapter],
    )

    assert [event["kind"] for event in payload["events"]] == [adapter_id]
    assert payload["events"][0]["lane"] == "source"
    graph_schema = json.loads(
        (ROOT / "docs/references/schemas/wiki-temporal-graph-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    standalone_schema = json.loads(
        (ROOT / "docs/references/schemas/wiki-temporal-event-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(
        standalone_schema,
        format_checker=FormatChecker(),
    ).validate(payload["events"][0])
    # No registry/resolver is provided: the graph contract must stay fully
    # self-contained for offline consumers.
    Draft202012Validator(
        graph_schema,
        format_checker=FormatChecker(),
    ).validate(payload)


def test_adapter_diagnostic_is_code_only_and_does_not_echo_invalid_value() -> None:
    pages, sources, activity = _models()
    invalid = "not a real date with private prose"
    pages["pages"][0]["updated_at"] = invalid  # type: ignore[index]
    events, diagnostics = build_temporal_events(
        pages, sources, activity, public_boundary=True
    )

    assert events
    assert any(row["adapter"] == "page.v1" for row in diagnostics)
    serialized = json.dumps(diagnostics)
    assert invalid not in serialized
    assert all(
        set(row) == {"code", "adapter", "subject_ref", "error_codes"}
        for row in diagnostics
    )


def test_private_secret_rejection_diagnostic_keeps_only_kind_and_opaque_digest() -> None:
    secret = "sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz123456"
    raw_subject = f"page:{secret}"
    pages = {
        "pages": [
            {
                "id": secret,
                "page_type": "context_note",
                "context": "system",
                "visibility": "private",
                "updated_at": "2026-07-11",
                "source_refs": [],
                "relation_refs": {"evidence_refs": []},
                "temporal": {
                    "dates": {},
                    "precision": {},
                    "action_state_history": [],
                },
            }
        ]
    }

    events, diagnostics = build_temporal_events(
        pages,
        {"sources": []},
        {"events": []},
        public_boundary=False,
    )

    assert events == []
    assert diagnostics == [
        {
            "code": "temporal_adapter_rejected",
            "adapter": "page.v1",
            "subject_ref": (
                "page:opaque-"
                + hashlib.sha256(raw_subject.encode("utf-8")).hexdigest()[:24]
            ),
            "error_codes": ["publication_blocked_secret"],
        }
    ]
    assert secret not in json.dumps(diagnostics, allow_nan=False)


@pytest.mark.parametrize(
    "authored_id",
    [
        "opaque-52998224725deadbeefcafe0",
        "opaque-4242424242424242bbbbbbbb",
    ],
)
@pytest.mark.parametrize("visibility", ["public", "private"])
def test_generated_looking_authored_subject_is_always_rehashed_in_diagnostics(
    authored_id: str,
    visibility: str,
) -> None:
    raw_subject = f"page:{authored_id}"
    pages = {
        "pages": [
            {
                "id": authored_id,
                "page_type": "context_note",
                "context": "system",
                "visibility": visibility,
                # Force a structural diagnostic in both visibility modes.  The
                # assertion below is about diagnostic subject projection, not
                # whether a particular digit sequence happens to match a PII
                # detector boundary.
                "updated_at": "invalid-date",
                "source_refs": [],
                "relation_refs": {"evidence_refs": []},
                "temporal": {
                    "dates": {},
                    "precision": {},
                    "action_state_history": [],
                },
            }
        ]
    }

    _events, diagnostics = build_temporal_events(
        pages,
        {"sources": []},
        {"events": []},
        public_boundary=visibility == "public",
    )

    expected = (
        "page:opaque-"
        + hashlib.sha256(raw_subject.encode("utf-8")).hexdigest()[:24]
    )
    diagnostic = next(
        row for row in diagnostics if row["adapter"] == "page.v1"
    )
    assert diagnostic["subject_ref"] == expected
    assert diagnostic["subject_ref"] != raw_subject
    assert authored_id not in json.dumps(diagnostics, allow_nan=False)


def test_public_snapshot_pii_rejection_never_echoes_the_authored_subject(
    tmp_path: Path,
) -> None:
    memories = tmp_path / "memories"
    memories.mkdir()
    (memories / "index.md").write_text(
        """---
page_id: root
page_type: root_index
title: Public root
context: system
visibility: public
updated_at: 2026-07-11
stale_after_days: 30
---

# Public root
""",
        encoding="utf-8",
    )
    pii = "529.982.247-25"
    (memories / "unsafe-subject.md").write_text(
        f"""---
page_id: {pii}
page_type: context_note
title: Synthetic public boundary fixture
context: system
visibility: public
updated_at: 2026-07-11
stale_after_days: 30
---

# Synthetic public boundary fixture
""",
        encoding="utf-8",
    )

    snapshot = build_snapshot(
        tmp_path,
        WikiConfig(repo_id="temporal-public-boundary"),
        generated_at="2026-07-11T12:00:00Z",
    )
    temporal = snapshot["temporal_graph.json"]
    raw_subject = f"page:{pii}"
    expected_subject = (
        "page:opaque-"
        + hashlib.sha256(raw_subject.encode("utf-8")).hexdigest()[:24]
    )

    diagnostic = next(
        row
        for row in temporal["diagnostics"]
        if "publication_blocked_pii" in row["error_codes"]
    )
    assert diagnostic["subject_ref"] == expected_subject
    assert pii not in json.dumps(temporal, allow_nan=False)
    assert snapshot["manifest.json"]["contract_errors"] == []


def test_snapshot_writer_rejects_nonfinite_json_before_creating_artifact(
    tmp_path: Path,
) -> None:
    target = tmp_path / "snapshot"

    with pytest.raises(ValueError, match="Out of range float values"):
        _write_snapshot_artifacts(
            target,
            {"temporal_graph.json": {"before": {"score": float("nan")}}},
        )

    assert not (target / "temporal_graph.json").exists()


def test_temporal_event_fingerprint_round_trips_identically_through_node() -> None:
    event = _fixture("imprecise-event.json")
    event["after"] = {
        "metric": 2**53 - 1,
        "nested": [True, None, "1.25"],
    }
    events = [event]
    expected = _events_fingerprint(events)
    module = (
        ROOT / "apps/wiki-cockpit/scripts/release-matrix-lib.mjs"
    ).as_uri()
    script = (
        f'import {{ sha256CanonicalJson }} from "{module}";'
        'let raw="";for await (const chunk of process.stdin) raw+=chunk;'
        "console.log(sha256CanonicalJson(JSON.parse(raw)));"
    )
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        input=json.dumps(events, ensure_ascii=False, allow_nan=False),
        text=True,
        capture_output=True,
        check=True,
        cwd=ROOT / "apps/wiki-cockpit",
    )

    assert completed.stdout.strip() == expected


def test_temporal_graph_validator_detects_count_range_and_cursor_tampering() -> None:
    payload = paginate_temporal_events(
        [_fixture("imprecise-event.json"), _fixture("conflicting-event.json")],
        repo_id="temporal-fixture",
        generated_at="2026-07-11T12:00:00Z",
        limit=1,
    )
    payload["event_count"] = 9
    payload["returned_count"] = 4
    payload["range"]["event_count"] = 7
    payload["next_cursor"] = None

    errors = temporal_graph_errors(payload)
    assert "temporal graph event_count and total_count disagree" in errors
    assert "temporal graph returned_count disagrees with events" in errors
    assert "temporal graph range does not cover full result" in errors
    assert "temporal graph next_cursor disagrees with truncated" in errors
