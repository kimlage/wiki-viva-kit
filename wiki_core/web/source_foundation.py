"""Source foundation topology builder — `wiki_web_source_foundation.v1`.

Compiles ALREADY-BUILT local read models (pages payload, graph payload, the
`build_sources_payload()` output, the source lifecycle projection and the
compiled ingestion-event records) into one deterministic, layout-ready,
public-safe topology: source/channel stations, stream ports, pipeline lanes,
emission edges, target projections and typed gap diagnostics, sealed by a
`topology_sha256` over canonical JSON.

Contract (plan §8.2–§8.10, §9):

- pure function: NO network, NO file reads/writes, NO clock — every input is a
  local structure and `generated_at`/`revision` come from the caller;
- role classification (§9.3): `source_config`, `source_registry` and
  `input_stage` are governance plates, `input_channel` is a grouping bus —
  none of them is ever treated as an emitting source;
- relation vocabulary (§9.4): only `source_ref`, `source_emission`,
  `evidence_supports`, `impact` and `proposal_transition` build the
  provenance chain; orientation relations (`moc_parent`, `markdown_link`,
  `temporal_sequence`, `collection_member`) are ignored silently; anything
  else touching a source is reported as `relation_outside_source_vocabulary`;
- legacy ingestion events resolve through the canonical
  :func:`wiki_core.events.resolve_ingestion_event_identity` — an event may
  carry a legacy `page_type` (e.g. `source_catalog`) and the SINGULAR
  `source_ref` field, which is never confused with the PLURAL `source_refs`
  a config uses to declare which sources it governs;
- many-to-many provenance is preserved (§9.7): a target supported by N
  sources keeps N emissions — never collapsed to one;
- fail-closed secrets (§9.9): a secret-bearing recipe keeps the station by
  canonical ID only; platform/locator/filters/manual never enter the payload
  and the diagnostic reuses the canonical `source_recipe_secret_detected`;
- deterministic IDs (§9.6) with prefixes that can never collide with page IDs
  (a collision raises instead of shipping an ambiguous topology).
"""

from __future__ import annotations

import hashlib
import json
import posixpath
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from wiki_core.events import resolve_ingestion_event_identity
from wiki_core.frontmatter import list_values
from wiki_core.source_lifecycle import SOURCE_LAST_ATTEMPT_ALIASES
from wiki_core.source_recipe import SOURCE_RECIPE_SAFETY_ERROR_CODE

SOURCE_FOUNDATION_SCHEMA_VERSION = "wiki_web_source_foundation.v1"

# §9.3 — governance page types are control surfaces, never emitting sources.
GOVERNANCE_PAGE_TYPES = frozenset({"source_config", "source_registry", "input_stage"})

# §9.4 — relations that build the provenance chain.
PROVENANCE_RELATION_TYPES = frozenset(
    {"source_ref", "source_emission", "evidence_supports", "impact", "proposal_transition"}
)
# §9.4 — orientation-only relations: usable for placement, never as proof of
# origin. They are ignored silently instead of flagged.
ORIENTATION_RELATION_TYPES = frozenset(
    {"moc_parent", "markdown_link", "temporal_sequence", "collection_member"}
)

DIAGNOSTIC_SEVERITIES: dict[str, str] = {
    "source_recipe_missing": "warning",
    "source_recipe_invalid": "error",
    # One secret vocabulary only: the canonical recipe-validator code (§9.9).
    SOURCE_RECIPE_SAFETY_ERROR_CODE: "error",
    "source_lifecycle_missing": "warning",
    "source_never_synced": "info",
    "source_sync_failed": "error",
    "source_blocked": "error",
    "stream_never_observed": "warning",
    "stream_past_cadence": "warning",
    "stream_target_missing": "warning",
    "target_without_emission": "info",
    "emission_without_source": "error",
    "emission_without_target": "warning",
    "event_without_closure": "warning",
    "multiple_sources_supported": "info",
    "relation_outside_source_vocabulary": "info",
    "unresolved_canonical_page": "warning",
}


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _contained_rel(rel: Any) -> str:
    """Normalize a repo-relative posix path; '' when it escapes the repo.

    The builder never touches the filesystem, but authored refs still travel
    into the payload — an absolute path or a ``../`` escape must not."""
    text = str(rel or "").strip()
    if not text:
        return ""
    if text.startswith(("/", "\\")) or ":" in text.split("/", 1)[0]:
        return ""
    normalized = posixpath.normpath(text.replace("\\", "/"))
    if normalized == ".." or normalized.startswith("../") or normalized.startswith("/"):
        return ""
    return normalized


def _safe_ref(ref: Any) -> str:
    """A ref that may travel in diagnostics: ids pass through, path-like refs
    are containment-checked — an escaping path is dropped ('' filters out)."""
    text = str(ref or "").strip()
    if not text:
        return ""
    if "/" in text or "\\" in text or text.startswith("."):
        return _contained_rel(text)
    return text


def _sha(text: str, length: int) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def _emission_id(
    source_id: str,
    stream_id: str | None,
    event_page_id: str | None,
    target_page_id: str | None,
    relation_type: str,
) -> str:
    basis = "|".join(
        [source_id, stream_id or "", event_page_id or "", target_page_id or "", relation_type]
    )
    return f"emission:{_sha(basis, 20)}"


class _Diagnostics:
    """Aggregates gaps per (code, subject) so a day-1 consumer with hundreds of
    unconfigured sources yields a linear, severity-honest diagnostic list."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], dict[str, Any]] = {}

    def add(self, code: str, subject_ref: str, related_refs: Sequence[str] = ()) -> None:
        severity = DIAGNOSTIC_SEVERITIES.get(code)
        if severity is None:  # pragma: no cover — internal vocabulary guard
            raise ValueError(f"unknown diagnostic code `{code}`")
        key = (code, subject_ref)
        record = self._records.get(key)
        if record is None:
            record = {
                "code": code,
                "severity": severity,
                "subject_ref": subject_ref,
                "related": set(),
                "count": 0,
            }
            self._records[key] = record
        record["count"] += 1
        record["related"].update(
            safe for ref in related_refs if (safe := _safe_ref(ref))
        )

    def codes_for(self, subject_refs: set[str]) -> list[str]:
        return sorted(
            {code for (code, subject) in self._records if subject in subject_refs}
        )

    def to_payload(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for (code, subject), record in sorted(self._records.items()):
            related = sorted(record["related"])
            out.append(
                {
                    # §9.6 — deterministic, page-ID-safe gap identity.
                    "gap_id": f"gap:{code}:{_sha(subject + '|' + ','.join(related), 16)}",
                    "code": code,
                    "severity": record["severity"],
                    "subject_ref": subject,
                    "related_refs": related,
                    "message_key": f"source_foundation.diagnostics.{code}",
                    "count": record["count"],
                }
            )
        return out


def _resolver(pages: Sequence[Mapping[str, Any]]):
    """id/path → canonical page id resolver over the pages payload."""
    by_id: dict[str, str] = {}
    by_path: dict[str, str] = {}
    for page in pages:
        page_id = str(page.get("id") or "")
        path = _contained_rel(page.get("path"))
        if page_id:
            by_id[page_id] = page_id
        if path and page_id:
            by_path[path] = page_id

    def resolve(ref: Any) -> str | None:
        text = str(ref or "").strip()
        if not text:
            return None
        if text in by_id:
            return text
        return by_path.get(_contained_rel(text))

    return resolve


def _stream_freshness(stream: Mapping[str, Any]) -> str:
    if not stream.get("selected", True):
        return "disabled"
    if stream.get("cursor_age_days") is None:
        return "never"
    if stream.get("breached"):
        return "stale"
    return "fresh"


_CODE_LIKE = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_.-")


def _skip_reason_code(value: Any) -> str:
    """Only code-like skip reasons travel; free text stays inside the private
    boundary and is represented by a fixed marker code."""
    text = str(value or "").strip()
    if not text:
        return ""
    if set(text) <= _CODE_LIKE:
        return text
    return "skip_reason_present"


def _event_closure_state(values: Mapping[str, Any]) -> str:
    closure = values.get("impact_closure") if isinstance(values.get("impact_closure"), dict) else {}
    consolidated = list_values(values.get("consolidated_into"))
    no_change = list_values(closure.get("no_change"))
    gate_state = str(values.get("gate_state") or values.get("status") or "").strip().lower()
    if consolidated or gate_state in {"accepted", "approved", "merged"}:
        return "accepted"
    if no_change or str(values.get("reviewed_no_change_receipt") or "").strip():
        return "reviewed_no_change"
    if gate_state == "blocked":
        return "blocked"
    if gate_state in {"", "open", "pending", "proposed", "draft"}:
        return "pending"
    return "unknown"


def build_source_foundation_payload(
    *,
    repo_id: str,
    revision: str,
    generated_at: str,
    pages_payload: Mapping[str, Any],
    graph_payload: Mapping[str, Any],
    source_entities_payload: Mapping[str, Any],
    source_lifecycle_payload: Mapping[str, Any],
    ingestion_events: Sequence[Mapping[str, Any]] = (),
    events_dir: str = "",
    mode: Literal["public", "private"] = "public",
) -> dict[str, Any]:
    """Compile the source-foundation topology from already-built read models.

    ``ingestion_events`` carries the compiled event records as
    ``{"path": <repo-relative path>, "values": <parsed frontmatter>}`` — raw
    frontmatter is required so the legacy SINGULAR ``source_ref`` field and
    gate/closure fields survive (the pages payload merges refs and drops the
    gate). ``events_dir`` is the repo-relative canonical events directory used
    by the identity resolver for legacy-typed events.

    ``mode`` is accepted per §9.2; the topology is sanitized by construction
    (locators, filter values, manuals, auth pointers and secrets never enter
    it), so both modes currently emit identical bytes. A future private mode
    may only ever ADD detail inside the private boundary — never remove
    fail-closed behavior.
    """
    if mode not in ("public", "private"):
        raise ValueError(f"unknown sanitization mode `{mode}`")

    pages: list[Mapping[str, Any]] = list(pages_payload.get("pages") or [])
    resolve = _resolver(pages)
    pages_by_id: dict[str, Mapping[str, Any]] = {
        str(page.get("id") or ""): page for page in pages if page.get("id")
    }
    known_page_ids = set(pages_by_id)
    events_dir_rel = _contained_rel(events_dir)

    sources: list[Mapping[str, Any]] = list(source_entities_payload.get("sources") or [])
    lifecycle_by_id: dict[str, Mapping[str, Any]] = {
        str(record.get("source_id") or ""): record
        for record in source_lifecycle_payload.get("sources") or []
    }
    diagnostics = _Diagnostics()

    # ---- Stations: one per real source, one per real input channel (§9.3).
    source_ids: list[str] = []
    station_meta: dict[str, dict[str, Any]] = {}
    for source in sources:
        source_id = str(source.get("source_id") or "")
        if not source_id:
            continue
        page = pages_by_id.get(source_id, {})
        if page and str(page.get("page_type") or "") in GOVERNANCE_PAGE_TYPES:
            # A governance page can never register as an emitting station.
            continue
        source_ids.append(source_id)
        recipe_errors = [str(code) for code in source.get("recipe_errors") or []]
        if SOURCE_RECIPE_SAFETY_ERROR_CODE in recipe_errors:
            recipe_state = "secret_blocked"
        elif source.get("recipe_ok"):
            recipe_state = "valid"
        elif recipe_errors:
            recipe_state = "invalid"
        else:
            recipe_state = "missing"
        lifecycle = lifecycle_by_id.get(source_id)
        station_meta[source_id] = {
            "source": source,
            "recipe_state": recipe_state,
            "lifecycle": lifecycle,
        }
        if recipe_state == "missing":
            diagnostics.add("source_recipe_missing", source_id)
        elif recipe_state == "invalid":
            diagnostics.add("source_recipe_invalid", source_id, recipe_errors)
        elif recipe_state == "secret_blocked":
            # Code only — never the offending value nor which field held it.
            diagnostics.add(SOURCE_RECIPE_SAFETY_ERROR_CODE, source_id)
        if lifecycle is None:
            diagnostics.add("source_lifecycle_missing", source_id)
        sync_state = str((source.get("sync") or {}).get("last_status") or "never")
        normalized_sync = SOURCE_LAST_ATTEMPT_ALIASES.get(sync_state, sync_state)
        if normalized_sync == "never":
            diagnostics.add("source_never_synced", source_id)
        elif normalized_sync in {"failed", "needs_auth", "parser_error", "secret_blocked"}:
            diagnostics.add("source_sync_failed", source_id)
        if lifecycle is not None and str(lifecycle.get("lifecycle_state") or "") == "blocked":
            diagnostics.add("source_blocked", source_id)

    source_id_set = set(source_ids)

    # ---- Channels group sources through a REAL relation (channel source_refs).
    channel_pages = sorted(
        (
            page
            for page in pages
            if str(page.get("page_type") or "") == "input_channel" and page.get("id")
        ),
        key=lambda page: str(page.get("id")),
    )
    channel_of_source: dict[str, str] = {}
    channel_members: dict[str, list[str]] = {}
    for channel in channel_pages:
        channel_id = str(channel.get("id"))
        members: list[str] = []
        for ref in channel.get("source_refs") or []:
            member = resolve(ref)
            if member in source_id_set and member not in channel_of_source:
                channel_of_source[member] = channel_id
                members.append(member)
        channel_members[channel_id] = members

    # ---- Stream ports and pipeline lanes.
    streams_out: list[dict[str, Any]] = []
    pipelines_out: list[dict[str, Any]] = []
    stream_ids_by_source: dict[str, list[str]] = {}
    pipeline_ids_by_source: dict[str, list[str]] = {}
    declared_targets_by_stream: dict[str, list[str]] = {}
    stream_by_declared_target: dict[tuple[str, str], list[str]] = {}
    for source_id in source_ids:
        meta = station_meta[source_id]
        source = meta["source"]
        for stream in source.get("streams") or []:
            recipe_stream_id = str(stream.get("id") or "")
            if not recipe_stream_id:
                continue
            stream_id = f"stream:{source_id}:{recipe_stream_id}"
            declared_ids: list[str] = []
            for target_ref in stream.get("target_pages") or []:
                target_id = resolve(target_ref)
                if target_id is None:
                    diagnostics.add("stream_target_missing", stream_id, [str(target_ref)])
                    continue
                if target_id not in declared_ids:
                    declared_ids.append(target_id)
                stream_by_declared_target.setdefault((source_id, target_id), []).append(
                    stream_id
                )
            declared_targets_by_stream[stream_id] = declared_ids
            freshness = _stream_freshness(stream)
            if freshness == "never":
                diagnostics.add("stream_never_observed", stream_id)
            elif freshness == "stale":
                diagnostics.add("stream_past_cadence", stream_id)
            filters = stream.get("filters") if isinstance(stream.get("filters"), dict) else {}
            streams_out.append(
                {
                    "stream_id": stream_id,
                    "source_id": source_id,
                    "recipe_stream_id": recipe_stream_id,
                    "label": str(stream.get("label") or recipe_stream_id),
                    "selected": bool(stream.get("selected", True)),
                    "privacy": str(stream.get("privacy") or ""),
                    "cadence_days": int(stream.get("cadence_days") or 0),
                    "cursor_age_days": stream.get("cursor_age_days")
                    if isinstance(stream.get("cursor_age_days"), int)
                    else None,
                    "freshness_state": freshness,
                    "breached": bool(stream.get("breached")),
                    "target_page_ids": sorted(declared_ids),
                    # Keys only (§8.4): filter VALUES stay inside the private
                    # boundary of the detailed read model.
                    "filter_keys": sorted(str(key) for key in filters),
                    "skip_reason_code": _skip_reason_code(stream.get("skip_reason")),
                }
            )
            stream_ids_by_source.setdefault(source_id, []).append(stream_id)
        lifecycle = meta["lifecycle"] or {}
        current_stage = str(lifecycle.get("pipeline_stage") or "")
        stage_timestamps = (
            lifecycle.get("pipeline_stage_timestamps")
            if isinstance(lifecycle.get("pipeline_stage_timestamps"), dict)
            else {}
        )
        seen_kinds: set[str] = set()
        for pipeline in source.get("pipelines") or []:
            kind = str(pipeline.get("kind") or "")
            if not kind or kind in seen_kinds:
                continue
            seen_kinds.add(kind)
            pipeline_id = f"pipeline:{source_id}:{kind}"
            pipelines_out.append(
                {
                    "pipeline_id": pipeline_id,
                    "source_id": source_id,
                    "kind": kind,
                    "cadence_days": int(pipeline.get("cadence_days") or 0),
                    "stream_ids": sorted(stream_ids_by_source.get(source_id, [])),
                    "current_stage": current_stage,
                    "last_transition_at": str(stage_timestamps.get(current_stage) or ""),
                }
            )
            pipeline_ids_by_source.setdefault(source_id, []).append(pipeline_id)

    def _stream_for_target(source_id: str, target_id: str | None) -> str | None:
        """Attribute an emission to a stream only when exactly one stream of
        the source declares that target — ambiguity stays honest (None)."""
        if target_id is None:
            return None
        declared = stream_by_declared_target.get((source_id, target_id)) or []
        unique = sorted(set(declared))
        return unique[0] if len(unique) == 1 else None

    # ---- Event chain (events input; canonical + legacy identity).
    emissions_by_id: dict[str, dict[str, Any]] = {}

    def _add_emission(
        *,
        source_id: str,
        event_page_id: str | None,
        target_page_id: str | None,
        relation_type: str,
        observed_at: str | None,
        closure_state: str,
        proposal_page_ids: Sequence[str] = (),
        evidence_refs: Sequence[str] = (),
        provenance_basis: str,
    ) -> dict[str, Any]:
        stream_id = _stream_for_target(source_id, target_page_id)
        emission_id = _emission_id(
            source_id, stream_id, event_page_id, target_page_id, relation_type
        )
        record = {
            "emission_id": emission_id,
            "source_id": source_id,
            "stream_id": stream_id,
            "event_page_id": event_page_id,
            "proposal_page_ids": sorted(
                {safe for ref in proposal_page_ids if (safe := _safe_ref(ref))}
            ),
            "target_page_id": target_page_id,
            "relation_type": relation_type,
            "observed_at": observed_at or None,
            "closure_state": closure_state,
            "evidence_refs": sorted(
                {safe for ref in evidence_refs if (safe := _safe_ref(ref))}
            ),
            "provenance_basis": provenance_basis,
        }
        return emissions_by_id.setdefault(emission_id, record)

    event_page_ids_in_input: set[str] = set()
    recognized_event_ids: set[str] = set()
    sorted_events = sorted(
        (dict(record) for record in ingestion_events),
        key=lambda record: (str(record.get("path") or ""),),
    )
    for record in sorted_events:
        rel = _contained_rel(record.get("path"))
        values = record.get("values")
        if not isinstance(values, Mapping):
            continue
        authored_type = str(values.get("page_type") or "")
        if authored_type in GOVERNANCE_PAGE_TYPES or authored_type == "input_channel":
            # A config's PLURAL `source_refs` declares governance, not emission.
            continue
        in_events_directory = bool(
            events_dir_rel
            and rel
            and (rel == events_dir_rel or rel.startswith(events_dir_rel + "/"))
        )
        identity = resolve_ingestion_event_identity(
            Path(rel or str(record.get("path") or "")),
            values,
            in_events_directory=in_events_directory,
        )
        if not identity.recognized:
            continue
        event_page_id = resolve(identity.page_id) or identity.page_id or identity.event_id
        if not event_page_id:
            continue
        event_page_ids_in_input.add(event_page_id)
        recognized_event_ids.add(event_page_id)
        closure_state = _event_closure_state(values)
        if closure_state == "pending":
            diagnostics.add("event_without_closure", event_page_id)
        # SINGULAR legacy `source_ref` and canonical PLURAL `source_refs` are
        # both event→source references here; the resolver made this an event,
        # so neither is ever read as a config declaration.
        raw_source_refs = [
            *list_values(values.get("source_refs")),
            *list_values(values.get("source_ref")),
        ]
        if identity.source_id:
            raw_source_refs.append(identity.source_id)
        event_sources: list[str] = []
        for ref in raw_source_refs:
            # A source station may exist without a page record in hand-built
            # payloads, so the station set itself is also an accepted anchor.
            resolved = resolve(ref) or (ref if ref in source_id_set else None)
            if resolved is None:
                diagnostics.add("unresolved_canonical_page", event_page_id, [str(ref)])
                continue
            if resolved in source_id_set and resolved not in event_sources:
                event_sources.append(resolved)
        target_ids: list[str] = []
        for ref in list_values(values.get("consolidated_into")):
            resolved = resolve(ref)
            if resolved is None:
                diagnostics.add("unresolved_canonical_page", event_page_id, [str(ref)])
                continue
            if resolved not in target_ids:
                target_ids.append(resolved)
        proposal_ids = list_values(values.get("proposal_ids"))
        evidence_refs = list_values(values.get("evidence_refs"))
        observed_at = str(values.get("updated_at") or "") or None
        provenance_basis = (
            "ingestion_event_legacy" if identity.is_legacy else "ingestion_event"
        )
        if not event_sources:
            diagnostics.add("emission_without_source", event_page_id, target_ids)
            continue
        for event_source in event_sources:
            if not target_ids:
                emission = _add_emission(
                    source_id=event_source,
                    event_page_id=event_page_id,
                    target_page_id=None,
                    relation_type="source_emission",
                    observed_at=observed_at,
                    closure_state=closure_state,
                    proposal_page_ids=proposal_ids,
                    evidence_refs=evidence_refs,
                    provenance_basis=provenance_basis,
                )
                if closure_state in {"accepted", "unknown"}:
                    diagnostics.add(
                        "emission_without_target", emission["emission_id"], [event_page_id]
                    )
                continue
            for target_id in target_ids:
                _add_emission(
                    source_id=event_source,
                    event_page_id=event_page_id,
                    target_page_id=target_id,
                    relation_type="source_emission",
                    observed_at=observed_at,
                    closure_state=closure_state,
                    proposal_page_ids=proposal_ids,
                    evidence_refs=evidence_refs,
                    provenance_basis=provenance_basis,
                )

    # Event pages already indexed in the pages payload (canonical or legacy)
    # are provenance pages, never knowledge targets.
    for page in pages:
        page_id = str(page.get("id") or "")
        if not page_id or page_id in recognized_event_ids:
            continue
        rel = _contained_rel(page.get("path"))
        in_events_directory = bool(
            events_dir_rel
            and rel
            and (rel == events_dir_rel or rel.startswith(events_dir_rel + "/"))
        )
        identity = resolve_ingestion_event_identity(
            Path(rel or page_id),
            {
                "page_id": page_id,
                "page_type": page.get("page_type"),
                "event_id": page.get("event_id"),
                "source_id": page.get("source_id"),
            },
            in_events_directory=in_events_directory,
        )
        if identity.recognized:
            recognized_event_ids.add(page_id)

    # ---- Graph provenance edges (§9.4 vocabulary).
    graph_edges = sorted(
        (dict(edge) for edge in graph_payload.get("edges") or []),
        key=lambda edge: (
            str(edge.get("source") or ""),
            str(edge.get("target") or ""),
            str(edge.get("type") or ""),
        ),
    )
    for edge in graph_edges:
        edge_type = str(edge.get("type") or "")
        edge_source = str(edge.get("source") or "")
        edge_target = str(edge.get("target") or "")
        observed_at = str(edge.get("observed_at") or "") or None
        basis = str(edge.get("basis") or "frontmatter")
        touches_source = edge_source in source_id_set or edge_target in source_id_set
        if edge_type in ORIENTATION_RELATION_TYPES:
            continue
        if edge_type not in PROVENANCE_RELATION_TYPES:
            if touches_source:
                subject = edge_source if edge_source in source_id_set else edge_target
                other = edge_target if subject == edge_source else edge_source
                diagnostics.add(
                    "relation_outside_source_vocabulary", subject, [other, edge_type]
                )
            continue
        if edge_type == "source_ref" and edge_target in source_id_set:
            referencing = pages_by_id.get(edge_source, {})
            referencing_type = str(referencing.get("page_type") or "")
            if (
                referencing_type in GOVERNANCE_PAGE_TYPES
                or referencing_type == "input_channel"
                or edge_source in source_id_set
                or edge_source in recognized_event_ids
            ):
                # Governance declarations, channel grouping and event pages are
                # not knowledge targets.
                continue
            _add_emission(
                source_id=edge_target,
                event_page_id=None,
                target_page_id=edge_source,
                relation_type="source_ref",
                observed_at=observed_at,
                # A canonical page carrying the reference IS integrated content.
                closure_state="accepted",
                provenance_basis=basis,
            )
        elif edge_type == "evidence_supports" and edge_source in source_id_set:
            if edge_target in source_id_set or edge_target in recognized_event_ids:
                continue
            _add_emission(
                source_id=edge_source,
                event_page_id=None,
                target_page_id=edge_target,
                relation_type="evidence_supports",
                observed_at=observed_at,
                closure_state="accepted",
                provenance_basis=basis,
            )
        elif edge_type == "source_emission" and edge_source in source_id_set:
            if edge_target in event_page_ids_in_input:
                continue  # already compiled with full closure from the event.
            _add_emission(
                source_id=edge_source,
                event_page_id=edge_target,
                target_page_id=None,
                relation_type="source_emission",
                observed_at=observed_at,
                closure_state="unknown",
                provenance_basis="graph_edge",
            )

    emissions_out = sorted(
        emissions_by_id.values(),
        key=lambda record: (
            record["source_id"],
            record["target_page_id"] or "",
            record["event_page_id"] or "",
            record["relation_type"],
            record["emission_id"],
        ),
    )

    # ---- Target projections (§8.7): many-to-many preserved, never collapsed.
    target_meta: dict[str, dict[str, Any]] = {}

    def _target(page_id: str) -> dict[str, Any]:
        return target_meta.setdefault(
            page_id,
            {
                "source_ids": set(),
                "event_page_ids": set(),
                "emission_count": 0,
                "accepted_count": 0,
                "pending_count": 0,
                "declared_by": set(),
            },
        )

    for emission in emissions_out:
        target_id = emission["target_page_id"]
        if target_id is None:
            continue
        meta = _target(target_id)
        meta["source_ids"].add(emission["source_id"])
        if emission["event_page_id"]:
            meta["event_page_ids"].add(emission["event_page_id"])
        meta["emission_count"] += 1
        if emission["closure_state"] in {"accepted", "reviewed_no_change"}:
            meta["accepted_count"] += 1
        elif emission["closure_state"] == "pending":
            meta["pending_count"] += 1
    for stream_id, declared_ids in declared_targets_by_stream.items():
        for target_id in declared_ids:
            _target(target_id)["declared_by"].add(stream_id)

    targets_out: list[dict[str, Any]] = []
    for page_id in sorted(target_meta):
        meta = target_meta[page_id]
        emission_count = meta["emission_count"]
        if emission_count == 0:
            closure_state = "declared_only"
            diagnostics.add(
                "target_without_emission", page_id, sorted(meta["declared_by"])
            )
        elif meta["accepted_count"] == emission_count:
            closure_state = "accepted"
        elif meta["pending_count"] > 0:
            closure_state = "pending"
        else:
            closure_state = "mixed"
        source_ids_for_target = sorted(meta["source_ids"])
        if len(source_ids_for_target) >= 2:
            diagnostics.add("multiple_sources_supported", page_id, source_ids_for_target)
        targets_out.append(
            {
                "page_id": page_id,
                "source_ids": source_ids_for_target,
                "event_page_ids": sorted(meta["event_page_ids"]),
                "emission_count": emission_count,
                "accepted_count": meta["accepted_count"],
                "pending_count": meta["pending_count"],
                "closure_state": closure_state,
                "target_declared_by_stream_ids": sorted(meta["declared_by"]),
            }
        )

    # ---- Stations payload (after diagnostics so codes can be attached).
    emission_ids_by_source: dict[str, list[str]] = {}
    emission_targets_by_source: dict[str, set[str]] = {}
    for emission in emissions_out:
        emission_ids_by_source.setdefault(emission["source_id"], []).append(
            emission["emission_id"]
        )
        if emission["target_page_id"]:
            emission_targets_by_source.setdefault(emission["source_id"], set()).add(
                emission["target_page_id"]
            )

    stations_out: list[dict[str, Any]] = []
    for source_id in source_ids:
        meta = station_meta[source_id]
        source = meta["source"]
        lifecycle = meta["lifecycle"] or {}
        recipe_state = meta["recipe_state"]
        page = pages_by_id.get(source_id, {})
        stream_ids = sorted(stream_ids_by_source.get(source_id, []))
        target_page_ids = set(emission_targets_by_source.get(source_id, set()))
        for stream_id in stream_ids:
            target_page_ids.update(declared_targets_by_stream.get(stream_id, []))
        subject_refs = {source_id, *stream_ids, *emission_ids_by_source.get(source_id, [])}
        config_page_id = resolve(source.get("config_ref"))
        stations_out.append(
            {
                "station_id": f"station:{source_id}",
                "kind": "source",
                "canonical_page_id": source_id,
                "path": _contained_rel(source.get("path") or page.get("path")),
                "title": str(source.get("title") or source_id),
                "context": str(source.get("context") or page.get("context") or ""),
                # sources.py already blanks platform on a secret recipe; keep
                # the station fail-closed even against a hand-built payload.
                "platform": ""
                if recipe_state == "secret_blocked"
                else str(source.get("platform") or ""),
                "owner_ref": str(source.get("owner") or ""),
                "config_page_id": config_page_id,
                "channel_station_id": (
                    f"channel:{channel_of_source[source_id]}"
                    if source_id in channel_of_source
                    else None
                ),
                "recipe_state": recipe_state,
                "sync_state": str((source.get("sync") or {}).get("last_status") or "never"),
                "lifecycle_state": str(lifecycle.get("lifecycle_state") or ""),
                "adoption_state": str(lifecycle.get("adoption_state") or ""),
                "pipeline_stage": str(lifecycle.get("pipeline_stage") or ""),
                "pending_stream_count": int(source.get("pending_streams") or 0),
                "next_due_days": source.get("next_due_days")
                if isinstance(source.get("next_due_days"), int)
                else None,
                "stream_ids": stream_ids,
                "pipeline_ids": sorted(pipeline_ids_by_source.get(source_id, [])),
                "emission_ids": sorted(emission_ids_by_source.get(source_id, [])),
                "target_page_ids": sorted(target_page_ids),
                "diagnostic_codes": diagnostics.codes_for(subject_refs),
            }
        )
    for channel in channel_pages:
        channel_id = str(channel.get("id"))
        members = channel_members.get(channel_id, [])
        stations_out.append(
            {
                "station_id": f"channel:{channel_id}",
                "kind": "input_channel",
                "canonical_page_id": channel_id,
                "path": _contained_rel(channel.get("path")),
                "title": str(channel.get("title") or channel_id),
                "context": str(channel.get("context") or ""),
                "platform": "",
                "owner_ref": "",
                "config_page_id": None,
                "channel_station_id": None,
                "recipe_state": "missing",
                "sync_state": "",
                "lifecycle_state": "",
                "adoption_state": "",
                "pipeline_stage": "",
                "pending_stream_count": sum(
                    int(station_meta[member]["source"].get("pending_streams") or 0)
                    for member in members
                ),
                "next_due_days": None,
                "stream_ids": [],
                "pipeline_ids": [],
                "emission_ids": [],
                "target_page_ids": [],
                "diagnostic_codes": diagnostics.codes_for({channel_id}),
            }
        )
    stations_out.sort(key=lambda station: station["station_id"])

    diagnostics_out = diagnostics.to_payload()

    # §9.6 — derived IDs must never collide with page IDs (nor become a
    # reducer centerId). Fail loudly instead of shipping ambiguity.
    derived_ids = {
        *(station["station_id"] for station in stations_out),
        *(stream["stream_id"] for stream in streams_out),
        *(pipeline["pipeline_id"] for pipeline in pipelines_out),
        *(emission["emission_id"] for emission in emissions_out),
        *(diagnostic["gap_id"] for diagnostic in diagnostics_out),
    }
    collisions = sorted(derived_ids & known_page_ids)
    if collisions:
        raise ValueError(
            "derived source-foundation IDs collide with page IDs: "
            + ", ".join(collisions)
        )

    streams_out.sort(key=lambda stream: stream["stream_id"])
    pipelines_out.sort(key=lambda pipeline: pipeline["pipeline_id"])

    summary = {
        "sources": len(source_ids),
        "channels": len(channel_pages),
        "streams": len(streams_out),
        "pipelines": len(pipelines_out),
        "emissions": len(emissions_out),
        "targets": len(targets_out),
        "gaps": sum(diagnostic["count"] for diagnostic in diagnostics_out),
        "blocked_sources": sum(
            1 for station in stations_out if station["lifecycle_state"] == "blocked"
        ),
        "pending_streams": sum(
            station["pending_stream_count"]
            for station in stations_out
            if station["kind"] == "source"
        ),
    }

    topology = {
        "stations": stations_out,
        "streams": streams_out,
        "pipelines": pipelines_out,
        "emissions": emissions_out,
        "targets": targets_out,
        "diagnostics": diagnostics_out,
        "summary": summary,
    }
    topology_sha256 = hashlib.sha256(_canonical_json(topology)).hexdigest()

    return {
        "schema_version": SOURCE_FOUNDATION_SCHEMA_VERSION,
        "repo_id": str(repo_id),
        "revision": str(revision),
        "generated_at": str(generated_at),
        "topology_sha256": topology_sha256,
        "summary": summary,
        "stations": stations_out,
        "streams": streams_out,
        "pipelines": pipelines_out,
        "emissions": emissions_out,
        "targets": targets_out,
        "diagnostics": diagnostics_out,
    }


_TOPOLOGY_KEYS = ("stations", "streams", "pipelines", "emissions", "targets", "diagnostics")


def source_foundation_payload_errors(payload: Any) -> list[str]:
    """Contract errors for an already-built (or parsed-back) payload.

    §8.10 item 3: a snapshot that advertises `source_foundation_v1` must carry
    a valid, sealed topology — a missing, torn or error-marked payload is an
    honest contract error, never a silently empty foundation. The hash check
    recomputes `topology_sha256` over the same canonical JSON the builder
    sealed, so a payload edited after build cannot keep its seal.
    """

    if not isinstance(payload, Mapping):
        return ["source foundation payload must be an object"]
    errors: list[str] = []
    if payload.get("schema_version") != SOURCE_FOUNDATION_SCHEMA_VERSION:
        errors.append("source foundation schema version mismatch")
    if payload.get("error") or payload.get("error_code"):
        # An explicit degraded payload can never validate as a topology.
        errors.append("source foundation payload carries an error marker")
        return errors
    topology: dict[str, Any] = {}
    for key in _TOPOLOGY_KEYS:
        value = payload.get(key)
        if not isinstance(value, list):
            errors.append(f"source foundation {key} must be a list")
        topology[key] = value
    summary = payload.get("summary")
    if not isinstance(summary, Mapping):
        errors.append("source foundation summary must be an object")
    topology["summary"] = dict(summary) if isinstance(summary, Mapping) else summary
    if errors:
        return errors
    expected = hashlib.sha256(_canonical_json(topology)).hexdigest()
    if payload.get("topology_sha256") != expected:
        errors.append("source foundation topology hash mismatch")
    return errors
