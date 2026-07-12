from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from wiki_core.temporal import (
    TEMPORAL_EVENT_SCHEMA_VERSION,
    TemporalEventError,
    _public_ref_projection,
    parse_temporal_event,
    parse_temporal_value,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/temporal"


def _fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _event(**overrides: object) -> dict[str, object]:
    event: dict[str, object] = {
        "schema_version": TEMPORAL_EVENT_SCHEMA_VERSION,
        "event_id": "evt_parser_fixture",
        "kind": "page_updated",
        "subject_refs": ["page:public-fixture"],
        "context_refs": ["context:system"],
        "recorded_at": "2026-07-11",
        "precision": {},
        "actor": None,
        "source_refs": [],
        "evidence_refs": [],
        "caused_by": [],
        "supersedes": [],
        "before": {},
        "after": {},
        "confidence": "confirmed",
        "visibility": "private",
        "origin": {"adapter": "test.v1"},
    }
    event.update(overrides)
    return event


@pytest.mark.parametrize(
    ("raw", "precision", "canonical"),
    [
        ("2024", "year", "2024"),
        ("2024-03", "month", "2024-03"),
        ("2024-03-02", "day", "2024-03-02"),
        ("2024-03-02T10:30:00-03:00", "instant", "2024-03-02T13:30:00Z"),
    ],
)
def test_temporal_value_preserves_real_precision(
    raw: str, precision: str, canonical: str
) -> None:
    point = parse_temporal_value(raw)

    assert point.precision == precision
    assert point.value == canonical
    assert point.lower <= point.upper


def test_temporal_value_rejects_naive_instants_and_precision_mismatch() -> None:
    with pytest.raises(TemporalEventError, match="invalid_temporal_value"):
        parse_temporal_value("2026-07-11T12:00:00")
    with pytest.raises(TemporalEventError, match="temporal_precision_mismatch"):
        parse_temporal_value("2026-07", declared_precision="day")


def test_temporal_value_preserves_distinct_fractional_instants_in_canonical_utc() -> None:
    early = parse_temporal_value("2026-07-11T12:00:00.1-03:00")
    late = parse_temporal_value("2026-07-11T12:00:00.9-03:00")

    assert early.value == "2026-07-11T15:00:00.100000Z"
    assert late.value == "2026-07-11T15:00:00.900000Z"
    assert early.lower == early.upper
    assert late.lower == late.upper
    assert early.lower.microsecond == 100_000
    assert late.lower.microsecond == 900_000
    assert early.lower < late.lower


@pytest.mark.parametrize(
    "instant",
    [
        "2026-01-01T00:00:00.1234561Z",
        "2026-01-01T00:00:00.1234569+00:00",
    ],
)
def test_temporal_value_rejects_fractional_precision_it_cannot_preserve(
    instant: str,
) -> None:
    with pytest.raises(
        TemporalEventError,
        match="temporal_fraction_precision_unsupported",
    ):
        parse_temporal_value(instant)


@pytest.mark.parametrize("field", ["before", "after"])
@pytest.mark.parametrize("visibility", ["private", "public"])
@pytest.mark.parametrize("nonfinite", [float("nan"), float("inf"), float("-inf")])
def test_event_parser_rejects_nonfinite_state_in_every_visibility(
    field: str,
    visibility: str,
    nonfinite: float,
) -> None:
    with pytest.raises(TemporalEventError) as exc:
        parse_temporal_event(
            _event(**{field: {"score": nonfinite}}, visibility=visibility)
        )

    assert f"{field}_non_interoperable_json" in exc.value.errors


@pytest.mark.parametrize(
    "value",
    [
        1.0,
        -0.0,
        2**53,
        {"nested": [1, {"value": 1.25}]},
    ],
)
def test_event_parser_rejects_json_numbers_that_do_not_round_trip_in_js(
    value: object,
) -> None:
    with pytest.raises(TemporalEventError) as exc:
        parse_temporal_event(_event(after={"metric": value}))

    assert "after_non_interoperable_json" in exc.value.errors


def test_event_parser_accepts_js_safe_integers_in_nested_state() -> None:
    parsed = parse_temporal_event(
        _event(after={"metric": 2**53 - 1, "nested": [True, None, "1.25"]})
    )

    assert parsed["after"]["metric"] == 2**53 - 1


def test_imprecise_public_fixture_remains_imprecise_and_schema_valid() -> None:
    raw = _fixture("imprecise-event.json")
    parsed = parse_temporal_event(raw, public_boundary=True)

    assert parsed == raw
    assert parsed["occurred_at"] == "2024"
    assert parsed["precision"] == {
        "occurred_at": "year",
        "recorded_at": "instant",
        "valid_from": "month",
    }
    assert parsed["anchor"] == {
        "field": "occurred_at",
        "value": "2024",
        "precision": "year",
    }
    assert parsed["temporal_conflicts"] == []

    schema = json.loads(
        (
            ROOT
            / "docs/references/schemas/wiki-temporal-event-v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    errors = list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
            parsed
        )
    )
    assert errors == []


def test_conflicting_fixture_is_preserved_and_marked_without_fabrication() -> None:
    raw = _fixture("conflicting-event.json")
    parsed = parse_temporal_event(raw, public_boundary=True)

    assert parsed == raw
    assert parsed["confidence"] == "conflicting"
    assert parsed["temporal_conflicts"] == ["due_at_before_created_at"]


def test_overlapping_imprecise_intervals_do_not_create_a_false_conflict() -> None:
    parsed = parse_temporal_event(
        _event(
            valid_from="2024-12",
            valid_to="2024",
            recorded_at=None,
        )
    )

    assert parsed["temporal_conflicts"] == []
    assert parsed["precision"] == {"valid_from": "month", "valid_to": "year"}


def test_event_parser_blocks_secrets_everywhere_and_pii_at_public_boundary() -> None:
    secret = "sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz123456"
    with pytest.raises(TemporalEventError, match="publication_blocked_secret"):
        parse_temporal_event(_event(before={"state": secret}))

    cpf = "529.982.247-25"
    private = parse_temporal_event(_event(before={"reference": cpf}))
    assert private["before"]["reference"] == cpf
    with pytest.raises(TemporalEventError, match="publication_blocked_pii"):
        parse_temporal_event(
            _event(before={"reference": cpf}, visibility="public")
        )
    with pytest.raises(
        TemporalEventError, match="publication_blocked_freeform_state"
    ):
        parse_temporal_event(
            _event(after={"note": "free form public narrative"}, visibility="public")
        )


def test_public_scan_masks_only_exact_core_generated_digests() -> None:
    event_id = "evt_page_updated_01459737043164285dafbc4f"
    parsed = parse_temporal_event(
        _event(
            event_id=event_id,
            visibility="public",
            caused_by=[f"event:{event_id}"],
            evidence_refs=["page:opaque-01459737043164285dafbc4f"],
        ),
        _trusted_opaque_identifiers={
            event_id,
            f"event:{event_id}",
            "page:opaque-01459737043164285dafbc4f",
        },
    )
    assert parsed["event_id"] == event_id
    assert parsed["caused_by"] == [f"event:{event_id}"]
    assert parsed["evidence_refs"] == ["page:opaque-01459737043164285dafbc4f"]

    # A merely similar authored identifier is not a typed generated digest and
    # must keep crossing the normal public-data detector.
    with pytest.raises(TemporalEventError, match="publication_blocked_pii"):
        parse_temporal_event(
            _event(
                event_id="evt_authored_01459737043164285dafbc4f_extra",
                visibility="public",
            )
        )

    assert _public_ref_projection(
        "page:opaque-01459737043164285dafbc4f",
        trusted_opaque_identifiers={"page:opaque-01459737043164285dafbc4f"},
    ) == "page:<opaque-digest>"
    assert _public_ref_projection(
        "event:evt_page_updated_01459737043164285dafbc4f",
        trusted_opaque_identifiers={
            "event:evt_page_updated_01459737043164285dafbc4f"
        },
    ) == "event:evt_page_updated_<opaque-digest>"
    for authored_ref in (
        "page:opaque-01459737043164285dafbc4f_extra",
        "page:prefix-opaque-01459737043164285dafbc4f",
        "event:x_evt_page_updated_01459737043164285dafbc4f",
        "event:evt_page_updated_01459737043164285dafbc4f_extra",
    ):
        assert _public_ref_projection(authored_ref) == authored_ref

    for authored_ref in (
        "event:x_evt_page_updated_01459737043164285dafbc4f",
        "event:evt_page_updated_01459737043164285dafbc4f_extra",
    ):
        with pytest.raises(TemporalEventError, match="publication_blocked_pii"):
            parse_temporal_event(
                _event(
                    event_id="evt_public_scan_near_match",
                    visibility="public",
                    evidence_refs=[authored_ref],
                )
            )


@pytest.mark.parametrize(
    "event_id",
    [
        "evt_cpf52998224725_aaaaaaaaaaaaaaaaaaaaaaaa",
        "evt_card_4111111111111111_bbbbbbbbbbbbbbbbbbbbbbbb",
    ],
)
def test_public_scan_retains_pii_in_generated_event_semantic_prefix(
    event_id: str,
) -> None:
    with pytest.raises(TemporalEventError, match="publication_blocked_pii"):
        parse_temporal_event(_event(event_id=event_id, visibility="public"))


@pytest.mark.parametrize(
    "event_id",
    [
        "evt_activity_52998224725aaaaaaaaaaaaa",
        "evt_activity_4242424242424242bbbbbbbb",
    ],
)
def test_public_scan_does_not_trust_authored_generated_looking_digest(
    event_id: str,
) -> None:
    with pytest.raises(TemporalEventError, match="publication_blocked_pii"):
        parse_temporal_event(_event(event_id=event_id, visibility="public"))


@pytest.mark.parametrize(
    "field",
    [
        "subject_refs",
        "context_refs",
        "source_refs",
        "evidence_refs",
        "caused_by",
        "supersedes",
        "actor",
    ],
)
@pytest.mark.parametrize(
    "event_id",
    [
        "evt_cpf52998224725_bbbbbbbbbbbbbbbbbbbbbbbb",
        "evt_activity_52998224725aaaaaaaaaaaaa",
    ],
)
def test_public_scan_retains_pii_in_untrusted_generated_looking_event_ref(
    field: str,
    event_id: str,
) -> None:
    event_ref = f"event:{event_id}"
    override: object = (
        {"kind": "human", "ref": event_ref}
        if field == "actor"
        else [event_ref]
    )
    with pytest.raises(TemporalEventError, match="publication_blocked_pii"):
        parse_temporal_event(
            _event(**{field: override}, visibility="public")
        )


def test_event_parser_rejects_unknown_kinds_bad_refs_and_unknown_fields() -> None:
    with pytest.raises(TemporalEventError) as exc:
        parse_temporal_event(
            _event(
                kind="translated_custom_kind",
                subject_refs=["free form person"],
                invented=True,
            )
        )

    assert {
        "unknown_event_fields",
        "unknown_event_kind",
        "subject_refs_invalid_ref",
        "subject_refs_required",
    } <= set(exc.value.errors)
