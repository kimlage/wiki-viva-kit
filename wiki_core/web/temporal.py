"""Semantic temporal graph adapters and deterministic pagination."""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import re
from collections import Counter
from typing import Any, Iterable, Mapping, Sequence

from wiki_core.action_state import (
    CANONICAL_ACTION_STATES,
    TERMINAL_ACTION_STATES,
    valid_action_transition,
)
from wiki_core.temporal import (
    TEMPORAL_DATE_FIELDS,
    TEMPORAL_EVENT_SCHEMA_VERSION,
    TEMPORAL_GRAPH_SCHEMA_VERSION,
    TemporalEventError,
    event_anchor,
    parse_temporal_event,
)

DEFAULT_TEMPORAL_PAGE_SIZE = 160
MAX_TEMPORAL_PAGE_SIZE = 500
_MICROSECONDS_PER_SECOND = 1_000_000
_SECONDS_PER_DAY = 24 * 60 * 60
_SAFE_REF_RE = re.compile(
    r"[a-z][a-z0-9_-]{0,31}:[A-Za-z0-9][A-Za-z0-9._/:-]{0,255}"
)
_SAFE_REF_KIND_RE = re.compile(r"[a-z][a-z0-9_-]{0,31}")
_SAFE_SEGMENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,255}")
_OPAQUE_DIAGNOSTIC_REF_RE = re.compile(
    r"[a-z][a-z0-9_-]{0,31}:opaque-[0-9a-f]{24}"
)
_ACTION_RECEIPT_ID_RE = re.compile(r"sha256:[0-9a-f]{64}")


class _TrustedOpaqueIdentifier(str):
    """Internal provenance marker for identities generated from SHA-256."""


def _typed_ref(kind: str, value: Any) -> str:
    trusted_input = isinstance(value, _TrustedOpaqueIdentifier)
    raw = str(value or "").strip()
    if _SAFE_REF_RE.fullmatch(raw):
        return _TrustedOpaqueIdentifier(raw) if trusted_input else raw
    if _SAFE_SEGMENT_RE.fullmatch(raw):
        typed = f"{kind}:{raw}"
        return _TrustedOpaqueIdentifier(typed) if trusted_input else typed
    # A malformed, personal or free-form legacy ref is not echoed into a public
    # read model.  Its stable digest preserves identity for repair diagnostics.
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return _TrustedOpaqueIdentifier(f"{kind}:opaque-{digest}")


def _event_id(kind: str, *identity: Any) -> str:
    seed = json.dumps(identity, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
    safe_kind = re.sub(r"[^a-z0-9_]+", "_", kind.replace("-", "_"))[:80]
    return _TrustedOpaqueIdentifier(f"evt_{safe_kind}_{digest}")


def _hashed_identity(prefix: str, value: str) -> _TrustedOpaqueIdentifier:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]
    return _TrustedOpaqueIdentifier(f"{prefix}{digest}")


def _trusted_opaque_identifiers(raw: Mapping[str, Any]) -> frozenset[str]:
    """Collect only identities carrying the internal generator provenance marker."""

    trusted: set[str] = set()
    event_id = raw.get("event_id")
    if isinstance(event_id, _TrustedOpaqueIdentifier):
        trusted.add(str(event_id))
    for field in (
        "subject_refs",
        "context_refs",
        "source_refs",
        "evidence_refs",
        "caused_by",
        "supersedes",
    ):
        for value in raw.get(field) or ():
            if isinstance(value, _TrustedOpaqueIdentifier):
                trusted.add(str(value))
    actor = raw.get("actor")
    if isinstance(actor, Mapping):
        actor_ref = actor.get("ref")
        if isinstance(actor_ref, _TrustedOpaqueIdentifier):
            trusted.add(str(actor_ref))
    return frozenset(trusted)


def _visibility(page: Mapping[str, Any]) -> str:
    raw = str(page.get("visibility") or "").strip().lower()
    return "public" if raw in {"public", "public_candidate"} else "private"


def _context_refs(page: Mapping[str, Any]) -> list[str]:
    return [_typed_ref("context", page.get("context") or "system")]


def _source_refs(page: Mapping[str, Any]) -> list[str]:
    return [_typed_ref("source", ref) for ref in page.get("source_refs") or []]


def _evidence_refs(page: Mapping[str, Any]) -> list[str]:
    refs = dict(page.get("relation_refs") or {}).get("evidence_refs") or []
    return [_typed_ref("page", ref) for ref in refs]


def _raw_event(
    *,
    kind: str,
    lane: str | None = None,
    identity: Sequence[Any],
    subject_refs: Sequence[str],
    context_refs: Sequence[str],
    visibility: str,
    adapter: str,
    source_refs: Sequence[str] = (),
    evidence_refs: Sequence[str] = (),
    caused_by: Sequence[str] = (),
    supersedes: Sequence[str] = (),
    before: Mapping[str, Any] | None = None,
    after: Mapping[str, Any] | None = None,
    confidence: str = "confirmed",
    actor: Mapping[str, str] | None = None,
    legacy_kind: str | None = None,
    event_id: str | None = None,
    **dates: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": TEMPORAL_EVENT_SCHEMA_VERSION,
        "event_id": event_id or _event_id(kind, *identity),
        "kind": kind,
        "subject_refs": list(subject_refs),
        "context_refs": list(context_refs),
        "precision": {},
        "actor": dict(actor) if actor is not None else None,
        "source_refs": list(source_refs),
        "evidence_refs": list(evidence_refs),
        "caused_by": list(caused_by),
        "supersedes": list(supersedes),
        "before": dict(before or {}),
        "after": dict(after or {}),
        "confidence": confidence,
        "visibility": visibility,
        "origin": {"adapter": adapter},
    }
    if legacy_kind:
        payload["origin"]["legacy_kind"] = legacy_kind
    if lane is not None:
        payload["lane"] = lane
    for field in TEMPORAL_DATE_FIELDS:
        value = dates.get(field)
        if value not in (None, ""):
            payload[field] = str(value)
    declared_precision = dates.get("precision")
    if isinstance(declared_precision, Mapping):
        payload["precision"] = {
            str(key): str(value)
            for key, value in declared_precision.items()
            if str(key) in TEMPORAL_DATE_FIELDS and value not in (None, "")
        }
    return payload


def _diagnostic_subject_ref(value: Any) -> str:
    """Keep only a bounded subject kind plus an opaque stable identity.

    Adapter diagnostics are part of the snapshot even when the rejected event
    itself cannot cross the privacy boundary.  Copying its authored subject
    would therefore turn the error path into a PII/secret exfiltration path.
    """

    trusted_generated = isinstance(value, _TrustedOpaqueIdentifier)
    raw = str(value or "")
    kind, separator, _subject = raw.partition(":")
    if not separator or not _SAFE_REF_KIND_RE.fullmatch(kind):
        kind = "system"
    if trusted_generated and _OPAQUE_DIAGNOSTIC_REF_RE.fullmatch(raw):
        return raw
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return f"{kind}:opaque-{digest}"


def _diagnostic(
    *,
    adapter: str,
    subject_ref: str,
    errors: Iterable[str],
    code: str = "temporal_adapter_rejected",
) -> dict[str, Any]:
    return {
        "code": code,
        "adapter": adapter,
        "subject_ref": _diagnostic_subject_ref(subject_ref),
        "error_codes": sorted(set(str(error) for error in errors)),
    }


def _append_event(
    events: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
    raw: Mapping[str, Any],
    *,
    public_boundary: bool,
    allowed_kinds: Sequence[str] = (),
) -> bool:
    try:
        event = parse_temporal_event(
            raw,
            public_boundary=public_boundary,
            allowed_kinds=allowed_kinds,
            _trusted_opaque_identifiers=_trusted_opaque_identifiers(raw),
        )
    except TemporalEventError as exc:
        subject_refs = raw.get("subject_refs")
        subject_ref = (
            str(subject_refs[0])
            if isinstance(subject_refs, list) and subject_refs
            else "system:unknown"
        )
        origin = raw.get("origin") if isinstance(raw.get("origin"), Mapping) else {}
        diagnostics.append(
            _diagnostic(
                adapter=str(origin.get("adapter") or "unknown"),
                subject_ref=subject_ref,
                errors=exc.errors,
            )
        )
        return False
    events.append(event)
    return True


def _page_temporal_dates(page: Mapping[str, Any]) -> dict[str, Any]:
    raw = page.get("temporal")
    temporal = dict(raw) if isinstance(raw, Mapping) else {}
    dates = temporal.get("dates")
    output = dict(dates) if isinstance(dates, Mapping) else {}
    if page.get("updated_at") and not output.get("recorded_at"):
        output["recorded_at"] = str(page.get("updated_at"))
    precision = temporal.get("precision")
    if isinstance(precision, Mapping):
        output["precision"] = dict(precision)
    return output


def _adapt_pages(
    pages_payload: Mapping[str, Any],
    *,
    public_boundary: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for page in pages_payload.get("pages") or []:
        if not isinstance(page, Mapping):
            continue
        page_id = str(page.get("id") or page.get("path") or "")
        subject = _typed_ref("page", page_id)
        contexts = _context_refs(page)
        visibility = _visibility(page)
        source_refs = _source_refs(page)
        evidence_refs = _evidence_refs(page)
        dates = _page_temporal_dates(page)
        updated = dates.get("recorded_at")
        if updated:
            _append_event(
                events,
                diagnostics,
                _raw_event(
                    kind="page_updated",
                    identity=(page_id, updated),
                    subject_refs=(subject,),
                    context_refs=contexts,
                    visibility=visibility,
                    adapter="page.v1",
                    source_refs=source_refs,
                    evidence_refs=evidence_refs,
                    after={"page_type": str(page.get("page_type") or "unknown")},
                    recorded_at=updated,
                    valid_from=dates.get("valid_from"),
                    valid_to=dates.get("valid_to"),
                    verified_at=dates.get("verified_at"),
                    superseded_at=dates.get("superseded_at"),
                    precision=dates.get("precision"),
                ),
                public_boundary=public_boundary,
            )

        page_type = str(page.get("page_type") or "")
        if page_type == "ingestion_event":
            occurred = dates.get("occurred_at") or dates.get("captured_at")
            _append_event(
                events,
                diagnostics,
                _raw_event(
                    kind="ingestion_recorded",
                    identity=(page_id, occurred, updated),
                    subject_refs=(subject,),
                    context_refs=contexts,
                    visibility=visibility,
                    adapter="ingestion_event.v1",
                    source_refs=source_refs,
                    evidence_refs=evidence_refs,
                    occurred_at=occurred,
                    recorded_at=dates.get("recorded_at"),
                    verified_at=dates.get("verified_at"),
                    ingested_at=dates.get("ingested_at"),
                    precision=dates.get("precision"),
                ),
                public_boundary=public_boundary,
            )

        if page_type == "decision":
            decided = dates.get("occurred_at") or dates.get("decided_at")
            decision_kind = "decision_made" if decided else "decision_recorded"
            _append_event(
                events,
                diagnostics,
                _raw_event(
                    kind=decision_kind,
                    identity=(page_id, decided, updated),
                    subject_refs=(subject,),
                    context_refs=contexts,
                    visibility=visibility,
                    adapter="decision.v1",
                    source_refs=source_refs,
                    evidence_refs=evidence_refs,
                    occurred_at=decided,
                    recorded_at=dates.get("recorded_at"),
                    valid_from=dates.get("valid_from"),
                    valid_to=dates.get("valid_to"),
                    verified_at=dates.get("verified_at"),
                    superseded_at=dates.get("superseded_at"),
                    precision=dates.get("precision"),
                ),
                public_boundary=public_boundary,
            )

        if page_type != "action":
            continue
        work = dict(page.get("work") or {})
        action_dates = {**dates}
        # ``work.created_at`` has a legacy UI fallback to updated_at. Temporal
        # history consumes only explicit frontmatter dates projected through
        # page.temporal, so that compatibility fallback never invents creation.
        state_raw = str(work.get("state") or "")
        if state_raw in CANONICAL_ACTION_STATES:
            state = state_raw
        else:
            state = "unknown"
            diagnostics.append(
                _diagnostic(
                    adapter="action.v1",
                    subject_ref=subject,
                    errors=("invalid_canonical_action_state",),
                )
            )
        common = {
            "subject_refs": (subject,),
            "context_refs": contexts,
            "visibility": visibility,
            "source_refs": source_refs,
            "evidence_refs": evidence_refs,
        }
        for kind, field in (
            ("action_created", "created_at"),
            ("action_due", "due_at"),
        ):
            if not action_dates.get(field):
                continue
            _append_event(
                events,
                diagnostics,
                _raw_event(
                    kind=kind,
                    identity=(page_id, field, action_dates[field]),
                    adapter="action.v1",
                    after={"state": state},
                    precision=action_dates.get("precision"),
                    **common,
                    **{field: action_dates[field]},
                ),
                public_boundary=public_boundary,
            )
        if action_dates.get("completed_at") and state in TERMINAL_ACTION_STATES:
            terminal_kind = "action_cancelled" if state == "cancelled" else "action_completed"
            _append_event(
                events,
                diagnostics,
                _raw_event(
                    kind=terminal_kind,
                    identity=(page_id, state, action_dates["completed_at"]),
                    adapter="action.v1",
                    after={"state": state},
                    completed_at=action_dates["completed_at"],
                    precision=action_dates.get("precision"),
                    **common,
                ),
                public_boundary=public_boundary,
            )
            selected_receipt = (
                work.get("cancellation_receipt")
                if state == "cancelled"
                else work.get("completion_receipt")
            )
            receipt_ref = str(selected_receipt or "")
            if receipt_ref:
                receipt_subject = _typed_ref(
                    "receipt",
                    _hashed_identity("receipt-", receipt_ref),
                )
                _append_event(
                    events,
                    diagnostics,
                    _raw_event(
                        kind="receipt_recorded",
                        identity=(page_id, receipt_ref, action_dates["completed_at"]),
                        subject_refs=(receipt_subject, subject),
                        context_refs=contexts,
                        visibility=visibility,
                        adapter="action_receipt.v1",
                        evidence_refs=(*evidence_refs, _typed_ref("receipt", receipt_ref)),
                        recorded_at=action_dates["completed_at"],
                        precision=action_dates.get("precision"),
                    ),
                    public_boundary=public_boundary,
                )
            else:
                diagnostics.append(
                    _diagnostic(
                        adapter="action_receipt.v1",
                        subject_ref=subject,
                        errors=("terminal_action_missing_receipt",),
                    )
                )
        elif action_dates.get("completed_at"):
            diagnostics.append(
                _diagnostic(
                    adapter="action.v1",
                    subject_ref=subject,
                    errors=("completed_at_requires_canonical_terminal_state",),
                )
            )

        temporal = page.get("temporal") if isinstance(page.get("temporal"), Mapping) else {}
        history = temporal.get("action_state_history") or []
        prior_event_ref = ""
        prior_receipt_id = ""
        prior_history_state = ""
        for index, row in enumerate(history):
            if not isinstance(row, Mapping):
                diagnostics.append(
                    _diagnostic(
                        adapter="action_transition_receipt.v1",
                        subject_ref=subject,
                        errors=("transition_history_row_must_be_object",),
                    )
                )
                continue
            recorded_at = str(row.get("recorded_at") or "")
            receipt_id = str(row.get("receipt_id") or "")
            row_prior_receipt_id = str(row.get("prior_receipt_id") or "")
            receipt_kind = str(row.get("receipt_kind") or "")
            previous_state = str(row.get("previous_state") or "")
            next_state = str(row.get("next_state") or "")
            if (
                previous_state not in CANONICAL_ACTION_STATES
                or next_state not in CANONICAL_ACTION_STATES
            ):
                diagnostics.append(
                    _diagnostic(
                        adapter="action_transition_receipt.v1",
                        subject_ref=subject,
                        errors=("transition_receipt_has_noncanonical_state",),
                    )
                )
                continue
            if not _ACTION_RECEIPT_ID_RE.fullmatch(receipt_id):
                diagnostics.append(
                    _diagnostic(
                        adapter="action_transition_receipt.v1",
                        subject_ref=subject,
                        errors=("transition_receipt_id_invalid",),
                    )
                )
                continue
            if row_prior_receipt_id != prior_receipt_id:
                diagnostics.append(
                    _diagnostic(
                        adapter="action_transition_receipt.v1",
                        subject_ref=subject,
                        errors=("transition_receipt_chain_discontinuous",),
                    )
                )
                continue
            if prior_history_state and previous_state != prior_history_state:
                diagnostics.append(
                    _diagnostic(
                        adapter="action_transition_receipt.v1",
                        subject_ref=subject,
                        errors=("transition_history_state_discontinuous",),
                    )
                )
                continue
            if not valid_action_transition(previous_state, next_state):
                diagnostics.append(
                    _diagnostic(
                        adapter="action_transition_receipt.v1",
                        subject_ref=subject,
                        errors=("transition_receipt_has_invalid_transition",),
                    )
                )
                continue
            if previous_state == next_state:
                event_kind = {
                    "legacy_canonicalization": "action_state_canonicalized",
                    "contract_update": "action_contract_updated",
                }.get(receipt_kind, "")
                if not event_kind:
                    diagnostics.append(
                        _diagnostic(
                            adapter="action_transition_receipt.v1",
                            subject_ref=subject,
                            errors=(
                                "transition_receipt_state_preserving_kind_invalid",
                            ),
                        )
                    )
                    continue
            else:
                if receipt_kind not in {"", "transition"}:
                    diagnostics.append(
                        _diagnostic(
                            adapter="action_transition_receipt.v1",
                            subject_ref=subject,
                            errors=("transition_receipt_kind_invalid",),
                        )
                    )
                    continue
                event_kind = "action_state_changed"
            transition_id = _event_id(
                event_kind, page_id, receipt_id or index, recorded_at
            )
            transition_emitted = _append_event(
                events,
                diagnostics,
                _raw_event(
                    kind=event_kind,
                    identity=(page_id, receipt_id or index, recorded_at),
                    event_id=transition_id,
                    adapter="action_transition_receipt.v1",
                    before={"state": previous_state},
                    after={"state": next_state},
                    caused_by=((prior_event_ref,) if prior_event_ref else ()),
                    recorded_at=recorded_at,
                    **common,
                ),
                public_boundary=public_boundary,
            )
            if transition_emitted and receipt_id:
                _append_event(
                    events,
                    diagnostics,
                    _raw_event(
                        kind="receipt_recorded",
                        identity=(page_id, receipt_id, recorded_at),
                        subject_refs=(
                            _typed_ref(
                                "receipt",
                                _hashed_identity("receipt-", receipt_id),
                            ),
                            subject,
                        ),
                        context_refs=contexts,
                        visibility=visibility,
                        adapter="action_transition_receipt.v1",
                        evidence_refs=(_typed_ref("receipt", receipt_id),),
                        caused_by=(_typed_ref("event", transition_id),),
                        recorded_at=recorded_at,
                    ),
                    public_boundary=public_boundary,
                )
            if transition_emitted:
                prior_event_ref = _typed_ref("event", transition_id)
                prior_receipt_id = receipt_id
                prior_history_state = next_state
        if (
            prior_history_state
            and state in CANONICAL_ACTION_STATES
            and prior_history_state != state
        ):
            diagnostics.append(
                _diagnostic(
                    adapter="action_transition_receipt.v1",
                    subject_ref=subject,
                    errors=("transition_history_final_state_mismatch",),
                )
            )
    return events, diagnostics


def _adapt_pack_temporal(
    pages_payload: Mapping[str, Any],
    adapters: Sequence[Mapping[str, Any]],
    *,
    public_boundary: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Compile validated field mappings; packs never supply executable code."""

    events: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    allowed_kinds = sorted(
        {str(adapter.get("event_kind") or "") for adapter in adapters}
    )
    pages = [page for page in pages_payload.get("pages") or [] if isinstance(page, Mapping)]
    for adapter in adapters:
        adapter_id = str(adapter["adapter_id"])
        page_type = str(adapter["page_type"])
        event_kind = str(adapter["event_kind"])
        for page in pages:
            if str(page.get("page_type") or "") != page_type:
                continue
            page_id = str(page.get("id") or page.get("path") or "")
            subject = _typed_ref("page", page_id)
            temporal = page.get("temporal")
            temporal = dict(temporal) if isinstance(temporal, Mapping) else {}
            canonical_dates = temporal.get("dates")
            canonical_dates = (
                dict(canonical_dates) if isinstance(canonical_dates, Mapping) else {}
            )
            adapter_fields = temporal.get("adapter_fields")
            adapter_fields = (
                dict(adapter_fields) if isinstance(adapter_fields, Mapping) else {}
            )
            precision_fields = temporal.get("precision")
            precision_fields = (
                dict(precision_fields) if isinstance(precision_fields, Mapping) else {}
            )

            def projected(source_field: str) -> Any:
                if source_field in adapter_fields:
                    return adapter_fields[source_field]
                return canonical_dates.get(source_field)

            dates: dict[str, Any] = {}
            precision: dict[str, str] = {}
            for target, source_field in adapter["time"].items():
                value = projected(str(source_field))
                if value in (None, ""):
                    continue
                dates[str(target)] = value
                declared = precision_fields.get(str(source_field))
                if declared not in (None, ""):
                    precision[str(target)] = str(declared)
            if any(field not in dates for field in adapter["required_times"]):
                continue

            def mapped_refs(provenance_kind: str, ref_kind: str) -> list[str]:
                output: list[str] = []
                for source_field in adapter["provenance"][provenance_kind][
                    "fields"
                ]:
                    value = adapter_fields.get(str(source_field))
                    values = value if isinstance(value, list) else [value]
                    for item in values:
                        if item in (None, ""):
                            continue
                        ref = _typed_ref(ref_kind, item)
                        if ref not in output:
                            output.append(ref)
                return output

            source_refs = mapped_refs("source_refs", "source")
            evidence_refs = mapped_refs("evidence_refs", "page")
            missing_provenance: list[str] = []
            if (
                adapter["provenance"]["source_refs"]["policy"] == "required"
                and not source_refs
            ):
                missing_provenance.append("pack_temporal_source_refs_required")
            if (
                adapter["provenance"]["evidence_refs"]["policy"] == "required"
                and not evidence_refs
            ):
                missing_provenance.append("pack_temporal_evidence_refs_required")
            if missing_provenance:
                diagnostics.append(
                    _diagnostic(
                        adapter=f"experience_pack.{adapter_id}.v1",
                        subject_ref=subject,
                        errors=missing_provenance,
                    )
                )
                continue

            state: dict[str, dict[str, Any]] = {"before": {}, "after": {}}
            for side in ("before", "after"):
                for state_key, source_field in adapter["state"][side].items():
                    value = projected(str(source_field))
                    if value not in (None, ""):
                        state[side][str(state_key)] = value
            _append_event(
                events,
                diagnostics,
                _raw_event(
                    kind=event_kind,
                    lane=str(adapter["lane"]),
                    identity=(
                        adapter_id,
                        page_id,
                        tuple(sorted((key, str(value)) for key, value in dates.items())),
                    ),
                    subject_refs=(subject,),
                    context_refs=_context_refs(page),
                    visibility=_visibility(page),
                    adapter=f"experience_pack.{adapter_id}.v1",
                    source_refs=source_refs,
                    evidence_refs=evidence_refs,
                    before=state["before"],
                    after=state["after"],
                    confidence=str(adapter["confidence"]),
                    precision=precision,
                    **dates,
                ),
                public_boundary=public_boundary,
                allowed_kinds=allowed_kinds,
            )
    return events, diagnostics


def _adapt_sources(
    source_lifecycle_payload: Mapping[str, Any],
    pages_payload: Mapping[str, Any],
    *,
    public_boundary: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    pages = {
        str(page.get("id") or ""): page
        for page in pages_payload.get("pages") or []
        if isinstance(page, Mapping)
    }
    for source in source_lifecycle_payload.get("sources") or []:
        if not isinstance(source, Mapping):
            continue
        source_id = str(source.get("source_id") or "")
        page = pages.get(source_id, {})
        subject = _typed_ref("source", source_id)
        contexts = _context_refs(page)
        visibility = _visibility(page)
        page_updated = str(page.get("updated_at") or "")
        state = str(source.get("lifecycle_state") or "")
        if state == "configured" and page_updated:
            _append_event(
                events,
                diagnostics,
                _raw_event(
                    kind="source_configured",
                    identity=(source_id, page_updated),
                    subject_refs=(subject,),
                    context_refs=contexts,
                    visibility=visibility,
                    adapter="source_lifecycle.v2",
                    after={"lifecycle_state": state},
                    recorded_at=page_updated,
                ),
                public_boundary=public_boundary,
            )
        last_ingested = str(source.get("last_ingested_at") or "")
        if last_ingested:
            _append_event(
                events,
                diagnostics,
                _raw_event(
                    kind="source_ingested",
                    identity=(source_id, last_ingested),
                    subject_refs=(subject,),
                    context_refs=contexts,
                    visibility=visibility,
                    adapter="source_lifecycle.v2",
                    after={
                        "lifecycle_state": state,
                        "adoption_state": str(source.get("adoption_state") or ""),
                    },
                    ingested_at=last_ingested,
                ),
                public_boundary=public_boundary,
            )
        last_run = str(
            source.get("last_sync_success_at") or source.get("last_run_at") or ""
        )
        if last_run:
            _append_event(
                events,
                diagnostics,
                _raw_event(
                    kind="source_refreshed",
                    identity=(source_id, last_run),
                    subject_refs=(subject,),
                    context_refs=contexts,
                    visibility=visibility,
                    adapter="source_lifecycle.v2",
                    after={
                        "last_attempt_state": str(
                            source.get("last_attempt_state") or "unknown"
                        )
                    },
                    recorded_at=last_run,
                ),
                public_boundary=public_boundary,
            )
        previous_stage_ref = ""
        timestamps = source.get("pipeline_stage_timestamps")
        if isinstance(timestamps, Mapping):
            for stage, value in sorted(timestamps.items(), key=lambda item: str(item[1])):
                when = str(value or "")
                if not when:
                    continue
                stage_event_id = _event_id(
                    "source_pipeline_advanced", source_id, stage, when
                )
                stage_emitted = _append_event(
                    events,
                    diagnostics,
                    _raw_event(
                        kind="source_pipeline_advanced",
                        identity=(source_id, stage, when),
                        event_id=stage_event_id,
                        subject_refs=(subject,),
                        context_refs=contexts,
                        visibility=visibility,
                        adapter="source_pipeline.v1",
                        caused_by=((previous_stage_ref,) if previous_stage_ref else ()),
                        after={"pipeline_stage": str(stage)},
                        recorded_at=when,
                    ),
                    public_boundary=public_boundary,
                )
                if stage_emitted:
                    previous_stage_ref = _typed_ref("event", stage_event_id)

        receipt_ref = str(source.get("reviewed_no_change_receipt") or "")
        receipt_at = str(
            source.get("last_attempt_at") or source.get("last_ingested_at") or ""
        )
        if receipt_ref and receipt_at:
            _append_event(
                events,
                diagnostics,
                _raw_event(
                    kind="receipt_recorded",
                    identity=(source_id, receipt_ref, receipt_at),
                    subject_refs=(
                        _typed_ref(
                            "receipt",
                            _hashed_identity("receipt-", receipt_ref),
                        ),
                        subject,
                    ),
                    context_refs=contexts,
                    visibility=visibility,
                    adapter="source_review_receipt.v1",
                    evidence_refs=(_typed_ref("receipt", receipt_ref),),
                    recorded_at=receipt_at,
                ),
                public_boundary=public_boundary,
            )
    return events, diagnostics


def _adapt_activity(
    activity_timeline: Mapping[str, Any],
    *,
    public_boundary: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for legacy in activity_timeline.get("events") or []:
        if not isinstance(legacy, Mapping):
            continue
        legacy_kind = str(legacy.get("kind") or "unknown")
        # Page and operation updates are adapted from pages.json with stronger
        # identity.  Keep only repository/system activity that has no page row.
        if legacy_kind in {"page_updated", "operations_updated"}:
            continue
        kind = {
            "snapshot": "snapshot_recorded",
            "git_commit": "git_commit_recorded",
        }.get(legacy_kind, "activity_recorded")
        commit = str(legacy.get("commit") or "")
        subject = (
            _typed_ref("commit", commit)
            if kind == "git_commit_recorded" and commit
            else _typed_ref("system", legacy.get("id") or legacy_kind)
        )
        timestamp = str(legacy.get("timestamp") or "")
        _append_event(
            events,
            diagnostics,
            _raw_event(
                kind=kind,
                identity=(legacy.get("id"), legacy_kind, timestamp),
                subject_refs=(subject,),
                context_refs=(
                    _typed_ref("context", legacy.get("context") or "system"),
                ),
                visibility="public" if public_boundary else "private",
                adapter="activity_timeline.v1",
                legacy_kind=legacy_kind,
                after={"status": str(legacy.get("status") or "unknown")},
                occurred_at=(timestamp if kind == "git_commit_recorded" else None),
                recorded_at=(timestamp if kind != "git_commit_recorded" else None),
            ),
            public_boundary=public_boundary,
        )
    return events, diagnostics


def build_temporal_events(
    pages_payload: Mapping[str, Any],
    source_lifecycle_payload: Mapping[str, Any],
    activity_timeline: Mapping[str, Any],
    *,
    public_boundary: bool = False,
    pack_temporal_adapters: Sequence[Mapping[str, Any]] = (),
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Adapt current read models into one stable event set."""

    events: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for adapter in (
        _adapt_pages(
            pages_payload,
            public_boundary=public_boundary,
        ),
        _adapt_pack_temporal(
            pages_payload,
            pack_temporal_adapters,
            public_boundary=public_boundary,
        ),
        _adapt_sources(
            source_lifecycle_payload,
            pages_payload,
            public_boundary=public_boundary,
        ),
        _adapt_activity(
            activity_timeline,
            public_boundary=public_boundary,
        ),
    ):
        events.extend(adapter[0])
        diagnostics.extend(adapter[1])

    by_id: dict[str, dict[str, Any]] = {}
    for event in events:
        event_id = str(event["event_id"])
        if event_id not in by_id:
            by_id[event_id] = event
            continue
        if by_id[event_id] != event:
            diagnostics.append(
                _diagnostic(
                    code="temporal_event_id_collision",
                    adapter=str(
                        (event.get("origin") or {}).get("adapter") or "unknown"
                    ),
                    subject_ref=str(
                        (event.get("subject_refs") or ["system:unknown"])[0]
                    ),
                    errors=("event_id_collision",),
                )
            )
    deduped = list(by_id.values())

    def sort_key(event: Mapping[str, Any]) -> tuple[int, int, str]:
        anchor = event_anchor(event)
        if anchor is None:
            return (1, 0, str(event.get("event_id") or ""))
        return (
            0,
            -_utc_microsecond_ordinal(anchor.lower),
            str(event.get("event_id") or ""),
        )

    deduped.sort(key=sort_key)
    diagnostics.sort(
        key=lambda row: (
            str(row.get("subject_ref") or ""),
            str(row.get("adapter") or ""),
            str(row.get("code") or ""),
        )
    )
    return deduped, diagnostics


def _utc_microsecond_ordinal(value: dt.datetime) -> int:
    """Return an exact, platform-independent UTC ordering key.

    ``datetime.timestamp()`` returns a float. Far from the Unix epoch, adjacent
    microseconds can therefore collapse to the same value and fall through to
    the event-id tiebreaker. An integer ordinal preserves every supported
    microsecond and also avoids platform-specific timestamp range limits.
    """

    utc = value.astimezone(dt.timezone.utc)
    seconds = (
        utc.toordinal() * _SECONDS_PER_DAY
        + utc.hour * 60 * 60
        + utc.minute * 60
        + utc.second
    )
    return seconds * _MICROSECONDS_PER_SECOND + utc.microsecond


def _events_fingerprint(events: Sequence[Mapping[str, Any]]) -> str:
    encoded = json.dumps(
        list(events),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _event_reference_errors(events: Sequence[Mapping[str, Any]]) -> list[str]:
    """Validate graph-local causal targets without exposing their raw values."""

    event_ids = {
        str(event.get("event_id") or "")
        for event in events
        if isinstance(event, Mapping) and event.get("event_id")
    }
    errors: list[str] = []
    for event in events:
        if not isinstance(event, Mapping):
            continue
        for field in ("caused_by", "supersedes"):
            references = event.get(field)
            if not isinstance(references, list):
                errors.append(f"temporal graph {field} references must be a list")
                continue
            for reference in references:
                if not isinstance(reference, str) or not reference.startswith("event:"):
                    errors.append(
                        f"temporal graph {field} target is not an event reference"
                    )
                    continue
                if reference.removeprefix("event:") not in event_ids:
                    errors.append(f"temporal graph {field} target is unresolved")
    return list(dict.fromkeys(errors))


def _encode_cursor(offset: int, fingerprint: str) -> str:
    raw = json.dumps(
        {"v": 1, "offset": offset, "fingerprint": fingerprint},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str, fingerprint: str) -> int:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid temporal cursor") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("v") != 1
        or payload.get("fingerprint") != fingerprint
        or not isinstance(payload.get("offset"), int)
        or isinstance(payload.get("offset"), bool)
        or payload["offset"] < 0
    ):
        raise ValueError("stale or invalid temporal cursor")
    return int(payload["offset"])


def _range(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    anchored = [
        (event_anchor(event), event)
        for event in events
        if event_anchor(event) is not None
    ]
    undated = len(events) - len(anchored)
    if not anchored:
        return {
            "from": None,
            "to": None,
            "from_precision": None,
            "to_precision": None,
            "event_count": len(events),
            "dated_count": 0,
            "undated_count": undated,
            "basis": "full_result",
        }
    earliest_point, earliest_event = min(anchored, key=lambda item: item[0].lower)  # type: ignore[union-attr]
    latest_point, latest_event = max(anchored, key=lambda item: item[0].upper)  # type: ignore[union-attr]
    earliest_anchor = earliest_event.get("anchor") or {}
    latest_anchor = latest_event.get("anchor") or {}
    return {
        "from": earliest_anchor.get("value"),
        "to": latest_anchor.get("value"),
        "from_precision": earliest_point.precision,  # type: ignore[union-attr]
        "to_precision": latest_point.precision,  # type: ignore[union-attr]
        "event_count": len(events),
        "dated_count": len(anchored),
        "undated_count": undated,
        "basis": "full_result",
    }


def paginate_temporal_events(
    events: Sequence[Mapping[str, Any]],
    *,
    repo_id: str,
    generated_at: str,
    diagnostics: Sequence[Mapping[str, Any]] = (),
    cursor: str | None = None,
    limit: int | None = DEFAULT_TEMPORAL_PAGE_SIZE,
) -> dict[str, Any]:
    """Return one cursor-bound page; ``limit=None`` emits a complete snapshot."""

    canonical_events = [dict(event) for event in events]
    reference_errors = _event_reference_errors(canonical_events)
    if reference_errors:
        raise ValueError("invalid temporal graph: " + "; ".join(reference_errors))
    fingerprint = _events_fingerprint(canonical_events)
    offset = _decode_cursor(cursor, fingerprint) if cursor else 0
    if offset > len(canonical_events):
        raise ValueError("temporal cursor offset exceeds event count")
    if limit is None:
        page_limit = max(len(canonical_events) - offset, 0)
    else:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError("temporal limit must be an integer")
        if limit < 1 or limit > MAX_TEMPORAL_PAGE_SIZE:
            raise ValueError(
                f"temporal limit must be between 1 and {MAX_TEMPORAL_PAGE_SIZE}"
            )
        page_limit = limit
    returned = canonical_events[offset : offset + page_limit]
    next_offset = offset + len(returned)
    has_more = next_offset < len(canonical_events)
    next_cursor = _encode_cursor(next_offset, fingerprint) if has_more else None
    by_kind = Counter(str(event.get("kind") or "unknown") for event in canonical_events)
    by_context = Counter(
        context
        for event in canonical_events
        for context in event.get("context_refs") or []
    )
    conflict_count = sum(
        1 for event in canonical_events if event.get("temporal_conflicts")
    )
    imprecise_count = sum(
        1
        for event in canonical_events
        if any(
            precision in {"year", "month"}
            for precision in (event.get("precision") or {}).values()
        )
    )
    full_range = _range(canonical_events)
    payload = {
        "schema_version": TEMPORAL_GRAPH_SCHEMA_VERSION,
        "event_schema_version": TEMPORAL_EVENT_SCHEMA_VERSION,
        "repo_id": repo_id,
        "revision": f"sha256:{fingerprint}",
        "generated_at": generated_at,
        # Both names are intentional during the v1 bridge: the product plan
        # example used total_count while downstream QA asks for event_count.
        "event_count": len(canonical_events),
        "total_count": len(canonical_events),
        "returned_count": len(returned),
        "truncated": has_more,
        "next_cursor": next_cursor,
        "page": {
            "offset": offset,
            "limit": page_limit,
            "remaining_count": max(len(canonical_events) - next_offset, 0),
            "fingerprint": fingerprint,
        },
        "range": full_range,
        "returned_range": {**_range(returned), "basis": "returned_page"},
        "summary": {
            "scope": "full_result",
            "event_count": len(canonical_events),
            "by_kind": dict(sorted(by_kind.items())),
            "by_context": dict(sorted(by_context.items())),
            "conflict_count": conflict_count,
            "imprecise_count": imprecise_count,
            "diagnostic_count": len(diagnostics),
        },
        "diagnostics": [dict(row) for row in diagnostics],
        "events": returned,
    }
    errors = temporal_graph_errors(payload)
    if errors:
        raise ValueError("invalid temporal graph: " + "; ".join(errors))
    return payload


def build_temporal_graph_payload(
    pages_payload: Mapping[str, Any],
    source_lifecycle_payload: Mapping[str, Any],
    activity_timeline: Mapping[str, Any],
    *,
    repo_id: str,
    generated_at: str,
    public_boundary: bool = False,
    cursor: str | None = None,
    limit: int | None = None,
    pack_temporal_adapters: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Build the snapshot read model (complete by default, never silently cut)."""

    events, diagnostics = build_temporal_events(
        pages_payload,
        source_lifecycle_payload,
        activity_timeline,
        public_boundary=public_boundary,
        pack_temporal_adapters=pack_temporal_adapters,
    )
    return paginate_temporal_events(
        events,
        repo_id=repo_id,
        generated_at=generated_at,
        diagnostics=diagnostics,
        cursor=cursor,
        limit=limit,
    )


def temporal_graph_errors(payload: Mapping[str, Any]) -> list[str]:
    """Cheap runtime invariants used by snapshot publication and tests."""

    errors: list[str] = []
    if payload.get("schema_version") != TEMPORAL_GRAPH_SCHEMA_VERSION:
        errors.append("temporal graph schema_version mismatch")
    events = payload.get("events")
    if not isinstance(events, list):
        errors.append("temporal graph events must be a list")
        events = []
    counts = (payload.get("event_count"), payload.get("total_count"))
    if not all(isinstance(value, int) and not isinstance(value, bool) for value in counts):
        errors.append("temporal graph total counts must be integers")
    elif counts[0] != counts[1]:
        errors.append("temporal graph event_count and total_count disagree")
    returned_count = payload.get("returned_count")
    if returned_count != len(events):
        errors.append("temporal graph returned_count disagrees with events")
    total = payload.get("total_count")
    if isinstance(total, int) and isinstance(returned_count, int):
        if returned_count < 0 or returned_count > total:
            errors.append("temporal graph returned_count is outside total_count")
    page = payload.get("page")
    if not isinstance(page, Mapping):
        errors.append("temporal graph page metadata missing")
        page = {}
    offset = page.get("offset")
    remaining = page.get("remaining_count")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        errors.append("temporal graph page offset is invalid")
    if not isinstance(remaining, int) or isinstance(remaining, bool) or remaining < 0:
        errors.append("temporal graph remaining_count is invalid")
    if (
        isinstance(total, int)
        and isinstance(returned_count, int)
        and isinstance(offset, int)
        and isinstance(remaining, int)
        and offset + returned_count + remaining != total
    ):
        errors.append("temporal graph page counts do not reconcile")
    truncated = payload.get("truncated")
    next_cursor = payload.get("next_cursor")
    if not isinstance(truncated, bool):
        errors.append("temporal graph truncated must be boolean")
    elif truncated != bool(remaining):
        errors.append("temporal graph truncated disagrees with remaining_count")
    if bool(next_cursor) != bool(truncated):
        errors.append("temporal graph next_cursor disagrees with truncated")
    full_range = payload.get("range")
    if not isinstance(full_range, Mapping):
        errors.append("temporal graph range missing")
    elif full_range.get("event_count") != total or full_range.get("basis") != "full_result":
        errors.append("temporal graph range does not cover full result")
    summary = payload.get("summary")
    if not isinstance(summary, Mapping):
        errors.append("temporal graph summary missing")
    elif summary.get("event_count") != total or summary.get("scope") != "full_result":
        errors.append("temporal graph summary does not cover full result")
    ids = [
        str(event.get("event_id") or "")
        for event in events
        if isinstance(event, Mapping)
    ]
    if len(ids) != len(events) or not all(ids):
        errors.append("temporal graph returned event has no id")
    if len(ids) != len(set(ids)):
        errors.append("temporal graph returned event ids are not unique")
    # A cursor page can legitimately reference an event outside the returned
    # slice. The constructor validates the complete canonical sequence before
    # slicing; standalone validation can resolve references only when this
    # payload itself carries the complete static result.
    complete_static_result = (
        isinstance(total, int)
        and isinstance(returned_count, int)
        and isinstance(offset, int)
        and isinstance(remaining, int)
        and offset == 0
        and remaining == 0
        and returned_count == total == len(events)
        and truncated is False
    )
    if complete_static_result:
        errors.extend(_event_reference_errors(events))
    return errors


__all__ = [
    "DEFAULT_TEMPORAL_PAGE_SIZE",
    "MAX_TEMPORAL_PAGE_SIZE",
    "build_temporal_events",
    "build_temporal_graph_payload",
    "paginate_temporal_events",
    "temporal_graph_errors",
]
