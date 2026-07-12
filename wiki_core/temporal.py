"""Canonical semantic-time contract for Wiki Viva.

``timeline.json`` remains the repository activity compatibility surface.  This
module defines the stricter event carried by ``temporal_graph.json``: each date
keeps its real precision, conflicting intervals stay visible, and public events
are scanned before they can cross the snapshot boundary.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass
from typing import Any, Collection, Mapping, Sequence

from wiki_core.detectors import scan_text

TEMPORAL_EVENT_SCHEMA_VERSION = "wiki_temporal_event.v1"
TEMPORAL_GRAPH_SCHEMA_VERSION = "wiki_temporal_graph.v1"
ACTIVITY_TIMELINE_CONTRACT_VERSION = "activity_timeline.v1"
ACTIVITY_TIMELINE_LEGACY_SCHEMA_VERSION = "wiki_web_timeline.v1"

TEMPORAL_DATE_FIELDS = (
    "occurred_at",
    "recorded_at",
    "valid_from",
    "valid_to",
    "created_at",
    "due_at",
    "completed_at",
    "verified_at",
    "ingested_at",
    "superseded_at",
)
TEMPORAL_PRECISIONS = frozenset({"year", "month", "day", "instant"})
TEMPORAL_CONFIDENCE = frozenset(
    {"confirmed", "inferred", "uncertain", "conflicting"}
)
TEMPORAL_VISIBILITY = frozenset({"public", "private"})
TEMPORAL_ACTOR_KINDS = frozenset({"human", "agent", "system", "unknown"})
TEMPORAL_LANE_IDS = frozenset(
    {"source", "action", "decision", "receipt", "page", "system", "other"}
)

# Core owns a bounded vocabulary.  Packs may later contribute namespaced kinds
# through the pack registry; accepting arbitrary prose here would make filters,
# adapters and privacy diagnostics drift before that registry exists.
TEMPORAL_EVENT_KINDS = frozenset(
    {
        "activity_recorded",
        "snapshot_recorded",
        "git_commit_recorded",
        "page_updated",
        "source_configured",
        "source_ingested",
        "source_refreshed",
        "source_refresh_due",
        "source_pipeline_advanced",
        "ingestion_recorded",
        "action_created",
        "action_due",
        "action_completed",
        "action_cancelled",
        "action_state_changed",
        "action_state_canonicalized",
        "action_contract_updated",
        "decision_recorded",
        "decision_made",
        "receipt_recorded",
    }
)

_EVENT_ID_RE = re.compile(r"[a-z][a-z0-9._-]{2,159}")
_KIND_RE = re.compile(r"[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*){0,5}")
_REF_RE = re.compile(
    r"[a-z][a-z0-9_-]{0,31}:[A-Za-z0-9][A-Za-z0-9._/:-]{0,255}"
)
_YEAR_RE = re.compile(r"\d{4}")
_MONTH_RE = re.compile(r"\d{4}-\d{2}")
_DAY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_PUBLIC_STATE_KEY_RE = re.compile(r"[a-z][a-z0-9_]{0,63}")
_PUBLIC_STATE_VALUE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}")
_GENERATED_EVENT_ID_RE = re.compile(
    r"(?P<semantic>evt_[a-z][a-z0-9_]{2,79}_)(?P<digest>[0-9a-f]{24})"
)
_GENERATED_OPAQUE_REF_RE = re.compile(
    r"(?P<prefix>[a-z][a-z0-9_-]{0,31}:)opaque-(?P<digest>[0-9a-f]{24})"
)
_GENERATED_EVENT_REF_RE = re.compile(
    r"(?P<prefix>[a-z][a-z0-9_-]{0,31}:)"
    r"(?P<semantic>evt_[a-z][a-z0-9_]{2,79}_)(?P<digest>[0-9a-f]{24})"
)


def _public_ref_projection(
    value: str,
    *,
    trusted_opaque_identifiers: Collection[str] = (),
) -> str:
    """Mask only a provenance-marked core digest, retaining authored semantics."""

    if value not in trusted_opaque_identifiers:
        return value

    opaque_match = _GENERATED_OPAQUE_REF_RE.fullmatch(value)
    if opaque_match is not None:
        return f"{opaque_match.group('prefix')}<opaque-digest>"
    event_match = _GENERATED_EVENT_REF_RE.fullmatch(value)
    if event_match is not None:
        return (
            f"{event_match.group('prefix')}"
            f"{event_match.group('semantic')}<opaque-digest>"
        )
    return value


@dataclass(frozen=True)
class TemporalValue:
    """One validated timestamp together with its honest interval bounds."""

    value: str
    precision: str
    lower: dt.datetime
    upper: dt.datetime


class TemporalEventError(ValueError):
    """Safe validation refusal; messages name fields/codes, never raw values."""

    def __init__(self, errors: Sequence[str]) -> None:
        self.errors = tuple(dict.fromkeys(str(error) for error in errors if error))
        super().__init__("; ".join(self.errors) or "invalid temporal event")


def _utc_start(date: dt.date) -> dt.datetime:
    return dt.datetime.combine(date, dt.time.min, tzinfo=dt.timezone.utc)


def parse_temporal_value(
    raw: Any, *, declared_precision: str | None = None
) -> TemporalValue:
    """Parse year/month/day/offset-instant without fabricating precision."""

    if not isinstance(raw, str) or not raw.strip():
        raise TemporalEventError(("temporal_value_required",))
    value = raw.strip()
    precision = str(declared_precision or "").strip()
    inferred = ""
    lower: dt.datetime
    upper: dt.datetime
    try:
        if _YEAR_RE.fullmatch(value):
            inferred = "year"
            year = int(value)
            lower = _utc_start(dt.date(year, 1, 1))
            upper = _utc_start(dt.date(year + 1, 1, 1)) - dt.timedelta(
                microseconds=1
            )
        elif _MONTH_RE.fullmatch(value):
            inferred = "month"
            year, month = (int(part) for part in value.split("-"))
            lower = _utc_start(dt.date(year, month, 1))
            if month == 12:
                next_month = dt.date(year + 1, 1, 1)
            else:
                next_month = dt.date(year, month + 1, 1)
            upper = _utc_start(next_month) - dt.timedelta(microseconds=1)
        elif _DAY_RE.fullmatch(value):
            inferred = "day"
            day = dt.date.fromisoformat(value)
            lower = _utc_start(day)
            upper = lower + dt.timedelta(days=1) - dt.timedelta(microseconds=1)
        else:
            inferred = "instant"
            fractional = re.search(
                r"T\d{2}:\d{2}:\d{2}[.,](\d+)(?:Z|[+-]\d{2}:\d{2})$",
                value,
            )
            if fractional is not None and len(fractional.group(1)) > 6:
                # datetime.fromisoformat silently truncates nanoseconds. The v1
                # contract stores microseconds, so refuse precision it cannot
                # preserve instead of collapsing distinct authored instants.
                raise TemporalEventError(
                    ("temporal_fraction_precision_unsupported",)
                )
            # Offset is mandatory.  A naive clock time would silently pretend a
            # timezone and change ordering across downstream installations.
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("timezone missing")
            normalized = parsed.astimezone(dt.timezone.utc)
            # Keep the full precision Python can represent.  Dropping the
            # microsecond component collapses distinct instants (for example
            # ``.1`` and ``.9``) into the same event and cursor ordering key.
            timespec = "microseconds" if normalized.microsecond else "seconds"
            value = normalized.isoformat(timespec=timespec).replace("+00:00", "Z")
            lower = upper = normalized
    except TemporalEventError:
        raise
    except (OverflowError, ValueError) as exc:
        raise TemporalEventError(("invalid_temporal_value",)) from exc

    if precision and precision not in TEMPORAL_PRECISIONS:
        raise TemporalEventError(("invalid_temporal_precision",))
    if precision and precision != inferred:
        raise TemporalEventError(("temporal_precision_mismatch",))
    return TemporalValue(value=value, precision=inferred, lower=lower, upper=upper)


def _refs(value: Any, *, field: str, errors: list[str]) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        errors.append(f"{field}_must_be_list")
        return []
    if len(value) > 128:
        errors.append(f"{field}_too_many")
        return []
    output: list[str] = []
    for item in value:
        if not isinstance(item, str) or not _REF_RE.fullmatch(item):
            errors.append(f"{field}_invalid_ref")
            continue
        if item not in output:
            output.append(item)
    return output


def _json_mapping(value: Any, *, field: str, errors: list[str]) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        errors.append(f"{field}_must_be_object")
        return {}
    output = {str(key): item for key, item in value.items()}
    if not _json_interoperable(output):
        errors.append(f"{field}_non_interoperable_json")
        return {}
    try:
        encoded = json.dumps(
            output,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
        )
    except (TypeError, ValueError):
        errors.append(f"{field}_must_be_json")
        return {}
    if len(encoded.encode("utf-8")) > 16_384:
        errors.append(f"{field}_too_large")
        return {}
    return output


def _json_interoperable(value: Any, *, depth: int = 0) -> bool:
    """JSON profile that round-trips identically through Python and JS."""

    if depth > 16:
        return False
    if value is None or isinstance(value, (bool, str)):
        return True
    if isinstance(value, int):
        return -(2**53 - 1) <= value <= 2**53 - 1
    # JSON has no portable distinction between 1.0 and 1, and JS also loses
    # negative zero/large integer precision. Decimal quantities belong in
    # explicit strings until the temporal schema defines a decimal type.
    if isinstance(value, float):
        return False
    if isinstance(value, list):
        return all(_json_interoperable(item, depth=depth + 1) for item in value)
    if isinstance(value, Mapping):
        return all(
            isinstance(key, str)
            and _json_interoperable(item, depth=depth + 1)
            for key, item in value.items()
        )
    return False


def _conflicts(points: Mapping[str, TemporalValue]) -> list[str]:
    conflicts: list[str] = []

    def definitely_before(left: str, right: str) -> bool:
        return (
            left in points
            and right in points
            and points[left].upper < points[right].lower
        )

    if definitely_before("valid_to", "valid_from"):
        conflicts.append("valid_to_before_valid_from")
    if definitely_before("due_at", "created_at"):
        conflicts.append("due_at_before_created_at")
    if definitely_before("completed_at", "created_at"):
        conflicts.append("completed_at_before_created_at")
    if definitely_before("superseded_at", "valid_from"):
        conflicts.append("superseded_at_before_valid_from")
    return conflicts


def _public_state_map_safe(value: Mapping[str, Any]) -> bool:
    """Public before/after state is code, never a free-form narrative dump."""

    for key, item in value.items():
        if not _PUBLIC_STATE_KEY_RE.fullmatch(str(key)):
            return False
        if item is None or isinstance(item, (bool, int)):
            continue
        if isinstance(item, str) and _PUBLIC_STATE_VALUE_RE.fullmatch(item):
            continue
        return False
    return True


_ANCHOR_ORDER = (
    "occurred_at",
    "completed_at",
    "recorded_at",
    "created_at",
    "due_at",
    "verified_at",
    "ingested_at",
    "valid_from",
    "superseded_at",
    "valid_to",
)


def event_anchor(event: Mapping[str, Any]) -> TemporalValue | None:
    precision = event.get("precision") if isinstance(event.get("precision"), dict) else {}
    for field in _ANCHOR_ORDER:
        value = event.get(field)
        if not value:
            continue
        try:
            return parse_temporal_value(
                value,
                declared_precision=str(precision.get(field) or "") or None,
            )
        except TemporalEventError:
            return None
    return None


_EVENT_FIELDS = frozenset(
    {
        "schema_version",
        "event_id",
        "kind",
        "lane",
        "subject_refs",
        "context_refs",
        *TEMPORAL_DATE_FIELDS,
        "precision",
        "actor",
        "source_refs",
        "evidence_refs",
        "caused_by",
        "supersedes",
        "before",
        "after",
        "confidence",
        "visibility",
        "origin",
        "temporal_conflicts",
        "anchor",
    }
)


def parse_temporal_event(
    raw: Mapping[str, Any],
    *,
    public_boundary: bool = False,
    allowed_kinds: Collection[str] = (),
    _trusted_opaque_identifiers: Collection[str] = (),
) -> dict[str, Any]:
    """Validate and normalize one ``wiki_temporal_event.v1`` mapping.

    Conflicting but well-formed dates remain publishable and carry explicit
    conflict codes.  Invalid dates/refs fail; access secrets fail at every
    visibility, while PII/entity findings fail only for public events or an
    explicit public export boundary. ``_trusted_opaque_identifiers`` is an
    internal adapter channel populated only from generator provenance markers;
    authored callers must leave it empty so generated-looking text is scanned.
    """

    if not isinstance(raw, Mapping):
        raise TemporalEventError(("event_must_be_object",))
    errors: list[str] = []
    unknown = sorted(str(key) for key in raw if str(key) not in _EVENT_FIELDS)
    if unknown:
        errors.append("unknown_event_fields")
    if raw.get("schema_version") != TEMPORAL_EVENT_SCHEMA_VERSION:
        errors.append("invalid_schema_version")
    event_id_raw = raw.get("event_id")
    if not isinstance(event_id_raw, str) or not _EVENT_ID_RE.fullmatch(event_id_raw):
        errors.append("invalid_event_id")
        event_id = "invalid-event"
    else:
        event_id = str(event_id_raw)
    kind = raw.get("kind")
    if (
        not isinstance(kind, str)
        or len(kind) > 80
        or not _KIND_RE.fullmatch(kind)
    ):
        errors.append("invalid_event_kind")
        kind = "activity_recorded"
    elif kind not in TEMPORAL_EVENT_KINDS and kind not in set(allowed_kinds):
        errors.append("unknown_event_kind")

    lane_raw = raw.get("lane")
    lane: str | None = None
    if lane_raw is not None:
        lane = str(lane_raw)
        if lane not in TEMPORAL_LANE_IDS:
            errors.append("invalid_temporal_lane")

    subject_refs = _refs(raw.get("subject_refs"), field="subject_refs", errors=errors)
    context_refs = _refs(raw.get("context_refs"), field="context_refs", errors=errors)
    if not subject_refs:
        errors.append("subject_refs_required")
    if not context_refs:
        errors.append("context_refs_required")

    declared_precision = raw.get("precision")
    if declared_precision is None:
        declared_precision = {}
    if not isinstance(declared_precision, Mapping):
        errors.append("precision_must_be_object")
        declared_precision = {}
    unknown_precision = sorted(
        str(key) for key in declared_precision if str(key) not in TEMPORAL_DATE_FIELDS
    )
    if unknown_precision:
        errors.append("unknown_precision_fields")

    points: dict[str, TemporalValue] = {}
    for field in TEMPORAL_DATE_FIELDS:
        value = raw.get(field)
        if value in (None, ""):
            continue
        try:
            points[field] = parse_temporal_value(
                value,
                declared_precision=(
                    str(declared_precision.get(field) or "") or None
                ),
            )
        except TemporalEventError as exc:
            errors.extend(f"{field}_{code}" for code in exc.errors)

    actor_raw = raw.get("actor")
    actor: dict[str, str] | None = None
    if actor_raw is not None:
        if not isinstance(actor_raw, Mapping):
            errors.append("actor_must_be_object_or_null")
        else:
            actor_kind = str(actor_raw.get("kind") or "")
            actor_ref = str(actor_raw.get("ref") or "")
            if set(actor_raw) != {"kind", "ref"}:
                errors.append("invalid_actor_fields")
            if actor_kind not in TEMPORAL_ACTOR_KINDS:
                errors.append("invalid_actor_kind")
            if not _REF_RE.fullmatch(actor_ref):
                errors.append("invalid_actor_ref")
            actor = {"kind": actor_kind, "ref": actor_ref}

    confidence = str(raw.get("confidence") or "")
    if confidence not in TEMPORAL_CONFIDENCE:
        errors.append("invalid_confidence")
    visibility = str(raw.get("visibility") or "")
    if visibility not in TEMPORAL_VISIBILITY:
        errors.append("invalid_visibility")

    before = _json_mapping(raw.get("before"), field="before", errors=errors)
    after = _json_mapping(raw.get("after"), field="after", errors=errors)
    origin = _json_mapping(raw.get("origin"), field="origin", errors=errors)
    if set(origin) - {"adapter", "legacy_kind"}:
        errors.append("invalid_origin_fields")
    if not isinstance(origin.get("adapter"), str) or not origin.get("adapter"):
        errors.append("origin_adapter_required")
    elif len(str(origin.get("adapter"))) > 120:
        errors.append("origin_adapter_too_long")
    if origin.get("legacy_kind") is not None:
        if not isinstance(origin.get("legacy_kind"), str) or not origin.get(
            "legacy_kind"
        ):
            errors.append("origin_legacy_kind_must_be_string")
        elif len(str(origin.get("legacy_kind"))) > 120:
            errors.append("origin_legacy_kind_too_long")

    source_refs = _refs(raw.get("source_refs"), field="source_refs", errors=errors)
    evidence_refs = _refs(
        raw.get("evidence_refs"), field="evidence_refs", errors=errors
    )
    caused_by = _refs(raw.get("caused_by"), field="caused_by", errors=errors)
    supersedes = _refs(raw.get("supersedes"), field="supersedes", errors=errors)

    if errors:
        raise TemporalEventError(errors)

    conflicts = _conflicts(points)
    if conflicts:
        confidence = "conflicting"
    anchor_field = next((field for field in _ANCHOR_ORDER if field in points), None)
    anchor = (
        {
            "field": anchor_field,
            "value": points[anchor_field].value,
            "precision": points[anchor_field].precision,
        }
        if anchor_field
        else None
    )
    event: dict[str, Any] = {
        "schema_version": TEMPORAL_EVENT_SCHEMA_VERSION,
        "event_id": event_id,
        "kind": kind,
        "subject_refs": subject_refs,
        "context_refs": context_refs,
    }
    if lane is not None:
        event["lane"] = lane
    for field in TEMPORAL_DATE_FIELDS:
        event[field] = points[field].value if field in points else None
    event.update(
        {
            "precision": {
                field: points[field].precision
                for field in TEMPORAL_DATE_FIELDS
                if field in points
            },
            "actor": actor,
            "source_refs": source_refs,
            "evidence_refs": evidence_refs,
            "caused_by": caused_by,
            "supersedes": supersedes,
            "before": before,
            "after": after,
            "confidence": confidence,
            "visibility": visibility,
            "origin": origin,
            "temporal_conflicts": conflicts,
            "anchor": anchor,
        }
    )

    serialized = json.dumps(
        event,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
    )
    # Secrets are scanned on the complete event, including machine identifiers.
    # PII/entity scanners intentionally see a field-aware projection: a random
    # 24-hex event/ref digest can satisfy Luhn by chance, but it carries no
    # human data. Only exact core-generated forms are masked; arbitrary IDs,
    # paths, state values, actor refs and every other authored string remain in
    # the public scan.
    blocked = {
        finding.category
        for finding in scan_text(serialized)
        if finding.category == "secret"
    }
    if public_boundary or visibility == "public":
        trusted_opaque_identifiers = frozenset(
            str(value) for value in _trusted_opaque_identifiers
        )
        projected = dict(event)
        generated_event_id = _GENERATED_EVENT_ID_RE.fullmatch(str(event_id))
        if (
            generated_event_id is not None
            and event_id in trusted_opaque_identifiers
        ):
            # The kind-like prefix is authored/semantic and must remain visible
            # to the PII scanner. Only the random digest is machine-opaque.
            projected["event_id"] = (
                f"{generated_event_id.group('semantic')}<opaque-digest>"
            )

        for field in (
            "subject_refs",
            "context_refs",
            "source_refs",
            "evidence_refs",
            "caused_by",
            "supersedes",
        ):
            projected[field] = [
                _public_ref_projection(
                    value,
                    trusted_opaque_identifiers=trusted_opaque_identifiers,
                )
                for value in event[field]
            ]
        if actor is not None:
            projected["actor"] = {
                **actor,
                "ref": _public_ref_projection(
                    actor["ref"],
                    trusted_opaque_identifiers=trusted_opaque_identifiers,
                ),
            }
        public_serialized = json.dumps(
            projected,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
        )
        blocked.update(
            finding.category
            for finding in scan_text(public_serialized)
            if finding.category in {"pii", "entity"}
        )
    blocked = sorted(blocked)
    if blocked:
        raise TemporalEventError(
            tuple(f"publication_blocked_{category}" for category in blocked)
        )
    if (public_boundary or visibility == "public") and not all(
        _public_state_map_safe(value) for value in (before, after)
    ):
        raise TemporalEventError(("publication_blocked_freeform_state",))
    return event


__all__ = [
    "ACTIVITY_TIMELINE_CONTRACT_VERSION",
    "ACTIVITY_TIMELINE_LEGACY_SCHEMA_VERSION",
    "TEMPORAL_ACTOR_KINDS",
    "TEMPORAL_CONFIDENCE",
    "TEMPORAL_DATE_FIELDS",
    "TEMPORAL_EVENT_KINDS",
    "TEMPORAL_EVENT_SCHEMA_VERSION",
    "TEMPORAL_GRAPH_SCHEMA_VERSION",
    "TEMPORAL_PRECISIONS",
    "TEMPORAL_VISIBILITY",
    "TemporalEventError",
    "TemporalValue",
    "event_anchor",
    "parse_temporal_event",
    "parse_temporal_value",
]
