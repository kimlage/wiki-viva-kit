"""Canonical source lifecycle resolution, validation and transition policy.

Source pages author the canonical nested ``source_lifecycle`` mapping.  Early
v8 pages may still expose flattened ``source_<field>`` values, but compatibility
must never turn ambiguity into a healthy-looking source: equal declarations are
accepted, contradictory declarations are diagnosed and snapshot publication
remains fail closed.

This module is deliberately read-only.  It defines the transition tables and
audits changes, but it does not provide a lifecycle writer yet.  Consequently a
change to an existing source's lifecycle/adoption/attempt state is refused with
a safe ``*_receipt_required`` diagnostic even when the edge is legal.  That is
the honest boundary until an atomic writer can append and verify chained source
attempt receipts.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from wiki_core.detectors import scan_text
from wiki_core.frontmatter import parse_frontmatter


SOURCE_LIFECYCLE_STATES: tuple[str, ...] = (
    "blocked",
    "configured",
    "consolidated",
    "ingested",
    "proposed",
    "ready",
    "syncing",
)

SOURCE_FRESHNESS_STATES: tuple[str, ...] = (
    "fresh",
    "never_synced",
    "stale",
)

SOURCE_LAST_ATTEMPT_STATES: tuple[str, ...] = (
    "failed",
    "needs_auth",
    "never",
    "ok",
    "parser_error",
    "secret_blocked",
)

SOURCE_PIPELINE_STAGES: tuple[str, ...] = (
    "complete",
    "configured",
    "deep_read",
    "extracted",
    "gate_pending",
    "indexed",
    "integrating",
    "manifested",
    "proposal_ready",
)

_SOURCE_PIPELINE_SEQUENCE: tuple[str, ...] = (
    "configured",
    "manifested",
    "extracted",
    "indexed",
    "deep_read",
    "proposal_ready",
    "integrating",
    "gate_pending",
    "complete",
)

SOURCE_ADOPTION_STATES: tuple[str, ...] = (
    "accepted",
    "pending",
    "reviewed_no_change",
)

# Explicit source lifecycle edges copied from the v8 lifecycle contract.  A
# missing edge is invalid; callers must not infer permissive transitions.
SOURCE_LIFECYCLE_TRANSITIONS: dict[str, frozenset[str]] = {
    "configured": frozenset({"ready", "blocked"}),
    "ready": frozenset({"syncing", "blocked"}),
    "syncing": frozenset({"proposed", "blocked", "ready"}),
    "proposed": frozenset({"consolidated", "blocked", "ready"}),
    "consolidated": frozenset({"ingested", "proposed", "blocked"}),
    "ingested": frozenset({"ready", "syncing", "blocked"}),
    "blocked": frozenset({"configured", "ready", "syncing"}),
}

# Adoption is an approval record, not transient pipeline progress.  Accepted
# states cannot be reset or changed into each other by editing Markdown.
SOURCE_ADOPTION_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"accepted", "reviewed_no_change"}),
    "accepted": frozenset(),
    "reviewed_no_change": frozenset(),
}

# Attempt stages move one proven step at a time. Integration and gate review
# may retry their immediately preceding stage, while a completed attempt may
# begin a new configured cycle. A blocked lifecycle keeps its current stage;
# unblock/retry does not invent a backward pipeline jump.
SOURCE_PIPELINE_TRANSITIONS: dict[str, frozenset[str]] = {
    "configured": frozenset({"manifested"}),
    "manifested": frozenset({"extracted"}),
    "extracted": frozenset({"indexed"}),
    "indexed": frozenset({"deep_read"}),
    "deep_read": frozenset({"proposal_ready"}),
    "proposal_ready": frozenset({"integrating"}),
    "integrating": frozenset({"proposal_ready", "gate_pending"}),
    "gate_pending": frozenset({"integrating", "complete"}),
    "complete": frozenset({"configured"}),
}

SOURCE_FAILURE_ATTEMPT_STATES = frozenset(
    {"failed", "needs_auth", "parser_error", "secret_blocked"}
)

# ``sync.last_status`` predates the v8 last-attempt projection.  These values
# remain readable and normalize to the canonical snapshot vocabulary.
SOURCE_LAST_ATTEMPT_ALIASES: dict[str, str] = {
    "partial": "failed",
    "queued": "ok",
    "running": "ok",
}

SOURCE_SYNC_STATES = frozenset(
    (*SOURCE_LAST_ATTEMPT_STATES, *SOURCE_LAST_ATTEMPT_ALIASES)
)

_ENUM_FIELDS: dict[str, tuple[str, ...]] = {
    "lifecycle_state": SOURCE_LIFECYCLE_STATES,
    "freshness_state": SOURCE_FRESHNESS_STATES,
    "last_attempt_state": SOURCE_LAST_ATTEMPT_STATES,
    "pipeline_stage": SOURCE_PIPELINE_STAGES,
    "adoption_state": SOURCE_ADOPTION_STATES,
}

# Logical field -> canonical nested spelling. ``state`` is intentionally the
# nested lifecycle spelling used by the source template.
_NESTED_FIELDS: dict[str, str] = {
    "lifecycle_state": "state",
}

_LIST_FIELDS = frozenset(
    {
        "emitted_page_ids",
        "emitted_action_ids",
        "proposal_ids",
        "secret_safe_log_refs",
    }
)

_CANONICAL_NESTED_FIELDS = frozenset(
    {
        "state",
        "freshness_state",
        "last_attempt_state",
        "pipeline_stage",
        "pipeline_stage_timestamps",
        "adoption_state",
        "last_sync_success_at",
        "last_ingested_at",
        "last_attempt_at",
        "blocked_reason",
        "emitted_page_ids",
        "emitted_action_ids",
        "proposal_ids",
        "raw_artifact_count",
        "secret_safe_log_refs",
        "reviewed_no_change_receipt",
        "accepted_ref",
    }
)


@dataclass(frozen=True)
class SourceLifecycleDiagnostic:
    """One deterministic, log-safe authoring diagnostic."""

    severity: Literal["error", "warning"]
    field: str
    value: str = ""
    allowed: tuple[str, ...] = ()
    normalized_to: str = ""
    code: str = "invalid_source_lifecycle"
    detail: str = ""

    @property
    def message(self) -> str:
        if self.detail:
            return self.detail
        value = _display_value(self.value)
        if self.severity == "warning":
            return (
                f"legacy `{self.field}` value `{value}` normalizes to "
                f"`{self.normalized_to}`; prefer the canonical value"
            )
        return (
            f"invalid `{self.field}` value `{value}`; allowed: "
            f"{', '.join(self.allowed)}"
        )


@dataclass(frozen=True)
class SourceLifecycleResolution:
    """Resolved compatibility view plus every fail-closed diagnostic."""

    values: Mapping[str, Any]
    fields: Mapping[str, str]
    diagnostics: tuple[SourceLifecycleDiagnostic, ...]

    @property
    def valid(self) -> bool:
        return not any(item.severity == "error" for item in self.diagnostics)


@dataclass(frozen=True)
class SourceLifecycleTransitionDiagnostic:
    """One safe finding for a source page changed relative to the Git base."""

    code: str
    message: str


def _display_value(value: str, limit: int = 80) -> str:
    """Return a bounded diagnostic value, redacting secret/PII first."""

    findings = [
        finding
        for finding in scan_text(value)
        if finding.category in {"secret", "pii"}
    ]
    if findings:
        categories = ",".join(sorted({finding.category for finding in findings}))
        return f"<redacted:{categories}>"
    rendered = " ".join(value.splitlines()).replace("`", "'")
    if len(rendered) <= limit:
        return rendered
    return rendered[: limit - 3] + "..."


def _is_declared(value: Any) -> bool:
    return value not in (None, "", [])


def _normalized_for_comparison(key: str, value: Any) -> Any:
    if key == "last_attempt_state":
        return normalize_source_last_attempt_state(value)
    return value


def _field_declarations(
    values: Mapping[str, Any], key: str
) -> tuple[tuple[str, Any], ...]:
    """Collect every supported authored spelling for one logical field."""

    declarations: list[tuple[str, Any]] = []
    direct_field = f"source_{key}"
    direct = values.get(direct_field)
    if _is_declared(direct) or (
        direct_field in values and key in _LIST_FIELDS and direct == []
    ):
        declarations.append((direct_field, direct))

    # ``lifecycle_state`` without the source prefix predates the flattened v8
    # spelling and remains readable. It receives the same conflict treatment.
    if key == "lifecycle_state":
        legacy = values.get("lifecycle_state")
        if _is_declared(legacy):
            declarations.append(("lifecycle_state", legacy))

    nested = values.get("source_lifecycle")
    if isinstance(nested, Mapping):
        nested_key = _NESTED_FIELDS.get(key, key)
        nested_value = nested.get(nested_key)
        if _is_declared(nested_value) or (
            nested_key in nested
            and (key in _LIST_FIELDS or key == "pipeline_stage_timestamps")
            and nested_value in ([], {})
        ):
            declarations.append((f"source_lifecycle.{nested_key}", nested_value))
        # Detect an accidental nested ``lifecycle_state`` alongside canonical
        # ``state`` rather than silently ignoring it.
        if key == "lifecycle_state":
            alias_value = nested.get("lifecycle_state")
            if _is_declared(alias_value):
                declarations.append(
                    ("source_lifecycle.lifecycle_state", alias_value)
                )
    return tuple(declarations)


def _safe_raw(value: Any) -> str:
    return _display_value("" if value is None else str(value))


def resolve_source_lifecycle(
    values: Mapping[str, Any],
) -> SourceLifecycleResolution:
    """Resolve and validate one source page's complete lifecycle declaration.

    Compatibility precedence remains flattened-first for a *valid* read model,
    but every disagreement is an error.  No caller may mistake precedence for
    permission to publish contradictory declarations.
    """

    diagnostics: list[SourceLifecycleDiagnostic] = []
    resolved: dict[str, Any] = {}
    fields: dict[str, str] = {}
    nested = values.get("source_lifecycle")
    if _is_declared(nested) and not isinstance(nested, Mapping):
        diagnostics.append(
            SourceLifecycleDiagnostic(
                severity="error",
                field="source_lifecycle",
                code="invalid_source_lifecycle_mapping",
                detail="invalid `source_lifecycle` value; a mapping is required",
            )
        )
    if isinstance(nested, Mapping):
        for unknown_key in sorted(
            set(str(key) for key in nested) - _CANONICAL_NESTED_FIELDS
        ):
            diagnostics.append(
                SourceLifecycleDiagnostic(
                    severity="error",
                    field="source_lifecycle",
                    code="unknown_source_lifecycle_field",
                    detail=(
                        "unknown `source_lifecycle` field "
                        f"`{_display_value(unknown_key)}`"
                    ),
                )
            )

    # Resolve every field consumed by the source read model, not just enums.
    keys = (
        "lifecycle_state",
        "freshness_state",
        "last_attempt_state",
        "pipeline_stage",
        "pipeline_stage_timestamps",
        "adoption_state",
        "last_sync_success_at",
        "last_ingested_at",
        "last_attempt_at",
        "emitted_page_ids",
        "emitted_action_ids",
        "proposal_ids",
        "raw_artifact_count",
        "secret_safe_log_refs",
        "reviewed_no_change_receipt",
        "accepted_ref",
        "blocked_reason",
    )
    for key in keys:
        declarations = _field_declarations(values, key)
        if not declarations:
            continue
        field, value = declarations[0]
        resolved[key] = value
        fields[key] = field
        comparison_values = {
            str(_normalized_for_comparison(key, candidate))
            for _candidate_field, candidate in declarations
        }
        if len(comparison_values) > 1:
            diagnostics.append(
                SourceLifecycleDiagnostic(
                    severity="error",
                    field=key,
                    code=f"conflicting_source_{key}",
                    detail=(
                        f"conflicting declarations for `{key}`; flattened and "
                        "nested values must match"
                    ),
                )
            )

    for key, allowed in _ENUM_FIELDS.items():
        if key not in resolved:
            continue
        field = fields[key]
        raw = str(resolved[key])
        normalized = (
            SOURCE_LAST_ATTEMPT_ALIASES.get(raw)
            if key == "last_attempt_state"
            else None
        )
        if normalized is not None:
            diagnostics.append(
                SourceLifecycleDiagnostic(
                    severity="warning",
                    field=field,
                    value=_safe_raw(raw),
                    allowed=allowed,
                    normalized_to=normalized,
                    code="legacy_source_last_attempt_state",
                )
            )
            resolved[key] = normalized
        elif raw not in allowed:
            diagnostics.append(
                SourceLifecycleDiagnostic(
                    severity="error",
                    field=field,
                    value=_safe_raw(raw),
                    allowed=allowed,
                    code=f"invalid_source_{key}",
                )
            )

    for key in _LIST_FIELDS:
        if key not in resolved:
            continue
        value = resolved[key]
        if not isinstance(value, list) or any(
            not isinstance(item, str) or not item.strip() for item in value
        ):
            diagnostics.append(
                _dependency_error(
                    key,
                    f"`{key}` must be a list of non-empty strings",
                    f"invalid_source_{key}",
                )
            )
        elif len(value) != len(set(value)):
            diagnostics.append(
                _dependency_error(
                    key,
                    f"`{key}` must not contain duplicate entries",
                    f"duplicate_source_{key}",
                )
            )

    timestamps = resolved.get("pipeline_stage_timestamps")
    if timestamps is not None and (
        not isinstance(timestamps, Mapping)
        or any(
            str(stage) not in SOURCE_PIPELINE_STAGES
            or not isinstance(timestamp, str)
            or not timestamp.strip()
            for stage, timestamp in (
                timestamps.items() if isinstance(timestamps, Mapping) else ()
            )
        )
    ):
        diagnostics.append(
            _dependency_error(
                "pipeline_stage_timestamps",
                "`pipeline_stage_timestamps` must map canonical stages to non-empty strings",
                "invalid_source_pipeline_stage_timestamps",
            )
        )

    raw_artifact_count = resolved.get("raw_artifact_count")
    if raw_artifact_count is not None and (
        isinstance(raw_artifact_count, bool)
        or not isinstance(raw_artifact_count, int)
        or raw_artifact_count < 0
    ):
        diagnostics.append(
            _dependency_error(
                "raw_artifact_count",
                "`raw_artifact_count` must be a non-negative integer",
                "invalid_source_raw_artifact_count",
            )
        )

    for key in (
        "accepted_ref",
        "reviewed_no_change_receipt",
        "blocked_reason",
        "last_sync_success_at",
        "last_ingested_at",
        "last_attempt_at",
    ):
        if key in resolved and not isinstance(resolved[key], str):
            diagnostics.append(
                _dependency_error(
                    key,
                    f"`{key}` must be a string",
                    f"invalid_source_{key}",
                )
            )

    lifecycle = str(resolved.get("lifecycle_state") or "")
    freshness = str(resolved.get("freshness_state") or "")
    attempt = str(resolved.get("last_attempt_state") or "")
    adoption = str(resolved.get("adoption_state") or "")
    accepted_ref_value = resolved.get("accepted_ref")
    accepted_ref = (
        accepted_ref_value.strip() if isinstance(accepted_ref_value, str) else ""
    )
    emitted_pages = resolved.get("emitted_page_ids")
    has_emitted_pages = bool(
        isinstance(emitted_pages, list)
        and emitted_pages
        and all(isinstance(item, str) and item.strip() for item in emitted_pages)
    )
    no_change_value = resolved.get("reviewed_no_change_receipt")
    no_change_receipt = (
        no_change_value.strip() if isinstance(no_change_value, str) else ""
    )
    blocked_value = (
        resolved.get("blocked_reason")
        or values.get("source_blocked_reason")
        or values.get("blocked_reason")
        or ""
    )
    blocked_reason = blocked_value.strip() if isinstance(blocked_value, str) else ""

    if adoption == "accepted":
        if not accepted_ref:
            diagnostics.append(
                _dependency_error(
                    "adoption_state",
                    "accepted adoption requires `accepted_ref`",
                    "accepted_source_missing_ref",
                )
            )
        if not has_emitted_pages:
            diagnostics.append(
                _dependency_error(
                    "adoption_state",
                    "accepted adoption requires at least one `emitted_page_ids` closure",
                    "accepted_source_missing_closure",
                )
            )
    elif adoption == "reviewed_no_change":
        if not accepted_ref:
            diagnostics.append(
                _dependency_error(
                    "adoption_state",
                    "reviewed-no-change adoption requires `accepted_ref`",
                    "reviewed_no_change_missing_ref",
                )
            )
        if not no_change_receipt:
            diagnostics.append(
                _dependency_error(
                    "adoption_state",
                    "reviewed-no-change adoption requires `reviewed_no_change_receipt`",
                    "reviewed_no_change_missing_receipt",
                )
            )

    if lifecycle == "ingested" and adoption not in {
        "accepted",
        "reviewed_no_change",
    }:
        diagnostics.append(
            _dependency_error(
                "lifecycle_state",
                "ingested lifecycle requires accepted or reviewed-no-change adoption",
                "ingested_source_missing_adoption",
            )
        )
    if adoption in {"accepted", "reviewed_no_change"} and lifecycle != "ingested":
        diagnostics.append(
            _dependency_error(
                "adoption_state",
                "accepted adoption requires `lifecycle_state=ingested`",
                "accepted_source_lifecycle_mismatch",
            )
        )

    if lifecycle == "blocked":
        if not blocked_reason:
            diagnostics.append(
                _dependency_error(
                    "lifecycle_state",
                    "blocked lifecycle requires a secret-safe blocker reason",
                    "blocked_source_missing_reason",
                )
            )
        if attempt not in SOURCE_FAILURE_ATTEMPT_STATES:
            diagnostics.append(
                _dependency_error(
                    "last_attempt_state",
                    "blocked lifecycle requires a failed attempt state",
                    "blocked_source_attempt_mismatch",
                )
            )
        if adoption != "pending":
            diagnostics.append(
                _dependency_error(
                    "adoption_state",
                    "blocked lifecycle requires pending adoption",
                    "blocked_source_adoption_mismatch",
                )
            )
    elif lifecycle and (blocked_reason or attempt in SOURCE_FAILURE_ATTEMPT_STATES):
        diagnostics.append(
            _dependency_error(
                "lifecycle_state",
                "a blocker reason or failed attempt requires `lifecycle_state=blocked`",
                "source_blocker_state_mismatch",
            )
        )

    if freshness == "never_synced" and str(
        resolved.get("last_sync_success_at") or ""
    ).strip():
        diagnostics.append(
            _dependency_error(
                "freshness_state",
                "never-synced freshness cannot declare `last_sync_success_at`",
                "never_synced_has_success_timestamp",
            )
        )

    return SourceLifecycleResolution(
        values=resolved,
        fields=fields,
        diagnostics=tuple(diagnostics),
    )


def _dependency_error(
    field: str, detail: str, code: str
) -> SourceLifecycleDiagnostic:
    return SourceLifecycleDiagnostic(
        severity="error",
        field=field,
        code=code,
        detail=detail,
    )


def source_lifecycle_value(
    values: Mapping[str, Any], key: str, fallback: Any = ""
) -> Any:
    """Return one value from the shared resolver compatibility view."""

    resolved = resolve_source_lifecycle(values).values
    logical_key = "lifecycle_state" if key == "state" else key
    return resolved.get(logical_key, fallback)


def declared_source_lifecycle_field(
    values: Mapping[str, Any], key: str
) -> tuple[str, str] | None:
    """Return the effective authored field path and safe string value, if any."""

    logical_key = "lifecycle_state" if key == "state" else key
    resolution = resolve_source_lifecycle(values)
    if logical_key not in resolution.values:
        return None
    return (
        resolution.fields[logical_key],
        _safe_raw(resolution.values[logical_key]),
    )


def normalize_source_last_attempt_state(value: Any) -> str:
    """Normalize known legacy states while preserving unknown values verbatim."""

    raw = "" if value is None else str(value)
    return SOURCE_LAST_ATTEMPT_ALIASES.get(raw, raw)


def source_lifecycle_diagnostics(
    values: Mapping[str, Any],
) -> tuple[SourceLifecycleDiagnostic, ...]:
    """Validate the complete authored lifecycle through the shared resolver."""

    return resolve_source_lifecycle(values).diagnostics


def valid_source_lifecycle_transition(previous: str, next_state: str) -> bool:
    """Return whether an operational lifecycle edge is explicitly allowed."""

    return next_state in SOURCE_LIFECYCLE_TRANSITIONS.get(previous, frozenset())


def valid_source_adoption_transition(previous: str, next_state: str) -> bool:
    """Return whether an adoption edge is explicitly allowed."""

    return next_state in SOURCE_ADOPTION_TRANSITIONS.get(previous, frozenset())


def valid_source_pipeline_transition(previous: str, next_stage: str) -> bool:
    """Return whether an attempt pipeline edge is explicitly allowed."""

    return next_stage in SOURCE_PIPELINE_TRANSITIONS.get(previous, frozenset())


def _pipeline_transition_code(previous: str, next_stage: str) -> str:
    if not next_stage:
        return "illegal_source_pipeline_reset"
    try:
        previous_index = _SOURCE_PIPELINE_SEQUENCE.index(previous)
        next_index = _SOURCE_PIPELINE_SEQUENCE.index(next_stage)
    except ValueError:
        return "illegal_source_pipeline_transition"
    if next_index < previous_index:
        return "illegal_source_pipeline_reset"
    return "illegal_source_pipeline_transition"


def source_lifecycle_transition_diagnostics(
    previous_text: str, current_text: str
) -> tuple[SourceLifecycleTransitionDiagnostic, ...]:
    """Fail closed on lifecycle edits until a chained writer is available.

    The diagnostic surface never includes authored values, reasons, refs or
    document text.  Invalid edges receive a specific error; legal state changes
    still require the future append-only writer/receipt verifier.
    """

    previous, _previous_body = parse_frontmatter(previous_text)
    current, _current_body = parse_frontmatter(current_text)
    if str(previous.get("page_type") or "") != "source" or str(
        current.get("page_type") or ""
    ) != "source":
        return ()
    before = resolve_source_lifecycle(previous)
    after = resolve_source_lifecycle(current)
    diagnostics: list[SourceLifecycleTransitionDiagnostic] = []

    previous_lifecycle = str(before.values.get("lifecycle_state") or "")
    next_lifecycle = str(after.values.get("lifecycle_state") or "")
    if previous_lifecycle and previous_lifecycle != next_lifecycle:
        if (
            not next_lifecycle
            or not valid_source_lifecycle_transition(previous_lifecycle, next_lifecycle)
        ):
            diagnostics.append(
                SourceLifecycleTransitionDiagnostic(
                    code="illegal_source_lifecycle_transition",
                    message=(
                        "source lifecycle changed through an edge that is not "
                        "allowed by SOURCE_LIFECYCLE_TRANSITIONS"
                    ),
                )
            )
        else:
            diagnostics.append(
                SourceLifecycleTransitionDiagnostic(
                    code="source_lifecycle_transition_receipt_required",
                    message=(
                        "source lifecycle changed without the pending central "
                        "writer and append-only transition receipt"
                    ),
                )
            )

    previous_adoption = str(before.values.get("adoption_state") or "")
    next_adoption = str(after.values.get("adoption_state") or "")
    if previous_adoption and previous_adoption != next_adoption:
        if (
            not next_adoption
            or not valid_source_adoption_transition(previous_adoption, next_adoption)
        ):
            diagnostics.append(
                SourceLifecycleTransitionDiagnostic(
                    code="illegal_source_adoption_transition",
                    message=(
                        "source adoption changed through a reset or edge that is "
                        "not allowed by SOURCE_ADOPTION_TRANSITIONS"
                    ),
                )
            )
        else:
            diagnostics.append(
                SourceLifecycleTransitionDiagnostic(
                    code="source_adoption_transition_receipt_required",
                    message=(
                        "source adoption changed without the pending central "
                        "writer and append-only acceptance receipt"
                    ),
                )
            )

    previous_attempt = str(before.values.get("last_attempt_state") or "")
    next_attempt = str(after.values.get("last_attempt_state") or "")
    previous_pipeline = str(before.values.get("pipeline_stage") or "")
    next_pipeline = str(after.values.get("pipeline_stage") or "")
    if previous_pipeline and previous_pipeline != next_pipeline:
        if valid_source_pipeline_transition(previous_pipeline, next_pipeline):
            diagnostics.append(
                SourceLifecycleTransitionDiagnostic(
                    code="source_pipeline_transition_receipt_required",
                    message=(
                        "source pipeline changed without the pending append-only "
                        "attempt transition receipt"
                    ),
                )
            )
        else:
            code = _pipeline_transition_code(previous_pipeline, next_pipeline)
            diagnostics.append(
                SourceLifecycleTransitionDiagnostic(
                    code=code,
                    message=(
                        "source pipeline changed through an edge that is not "
                        "allowed by SOURCE_PIPELINE_TRANSITIONS"
                    ),
                )
            )
    if previous_attempt and previous_attempt != next_attempt:
        diagnostics.append(
            SourceLifecycleTransitionDiagnostic(
                code="source_attempt_receipt_required",
                message=(
                    "source last-attempt state changed without the pending "
                    "append-only attempt receipt"
                ),
            )
        )
    return tuple(diagnostics)


__all__ = [
    "SOURCE_ADOPTION_STATES",
    "SOURCE_ADOPTION_TRANSITIONS",
    "SOURCE_FAILURE_ATTEMPT_STATES",
    "SOURCE_FRESHNESS_STATES",
    "SOURCE_LAST_ATTEMPT_ALIASES",
    "SOURCE_LAST_ATTEMPT_STATES",
    "SOURCE_LIFECYCLE_STATES",
    "SOURCE_LIFECYCLE_TRANSITIONS",
    "SOURCE_PIPELINE_STAGES",
    "SOURCE_PIPELINE_TRANSITIONS",
    "SOURCE_SYNC_STATES",
    "SourceLifecycleDiagnostic",
    "SourceLifecycleResolution",
    "SourceLifecycleTransitionDiagnostic",
    "declared_source_lifecycle_field",
    "normalize_source_last_attempt_state",
    "resolve_source_lifecycle",
    "source_lifecycle_diagnostics",
    "source_lifecycle_transition_diagnostics",
    "source_lifecycle_value",
    "valid_source_adoption_transition",
    "valid_source_lifecycle_transition",
    "valid_source_pipeline_transition",
]
