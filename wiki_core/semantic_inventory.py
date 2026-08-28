"""Independent semantic parity gate for events and authored relations.

The expected inventory is compiled directly from structured YAML frontmatter.
It never derives expectations from ``graph.json`` itself.  Snapshot read models
are then treated as observations and compared by opaque counts and hashes so a
private downstream can publish the result without publishing page identities.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from wiki_core.config import WikiConfig
from wiki_core.events import (
    IngestionEventIdentity,
    resolve_ingestion_event_identity,
)
from wiki_core.frontmatter import list_values, parse_frontmatter
from wiki_core.paths import WikiPaths

SEMANTIC_INVENTORY_SCHEMA_VERSION = "wiki_semantic_inventory.v1"
REQUIRED_SNAPSHOT_FILES = (
    "manifest.json",
    "ingestion.json",
    "temporal_graph.json",
    "graph.json",
)

# This independent map intentionally repeats the authored-field contract rather
# than importing the graph compiler's relation vocabulary. A drift in compiler
# type/direction/basis must therefore become observable here.
RELATION_DIRECTIONS = {
    "moc_parent": "directed",
    "collection_member": "directed",
    "source_ref": "directed",
    "related_page": "directed",
    "markdown_link": "directed",
    "source_emission": "directed",
    "dependency": "directed",
    "ownership": "directed",
    "participation": "directed",
    "evidence_supports": "directed",
    "impact": "directed",
    "proposal_transition": "directed",
    "temporal_sequence": "directed",
}
PROVENANCE_BEARING_TYPES = frozenset(
    {
        "source_ref",
        "markdown_link",
        "source_emission",
        "evidence_supports",
        "impact",
        "proposal_transition",
    }
)
DIRECT_COLLECTION_BASES = frozenset(
    {"member.collection_refs", "collection.members"}
)

# source, target, type, direction, basis, provenance.page_id,
# provenance.path, provenance.field
RelationKey = tuple[str, str, str, str, str, str, str, str]


class SemanticInventoryError(RuntimeError):
    """Operational error with a code safe to render at a public boundary."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class AuthoredPage:
    path: str
    page_id: str
    page_type: str
    values: dict[str, Any]


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _opaque(*parts: Any) -> str:
    return hashlib.sha256(
        "\0".join(str(part) for part in parts).encode("utf-8")
    ).hexdigest()


def _set_summary(values: Iterable[str]) -> dict[str, Any]:
    normalized = sorted(set(values))
    return {"count": len(normalized), "sha256": _sha256(normalized)}


def _counter_summary(values: Counter[RelationKey]) -> dict[str, Any]:
    normalized = [
        [*key, count]
        for key, count in sorted(values.items())
        if count > 0
    ]
    return {
        "count": sum(count for count in values.values() if count > 0),
        "unique_count": len(normalized),
        "sha256": _sha256(normalized),
    }


def _opaque_summary(values: Iterable[str]) -> dict[str, Any]:
    normalized = sorted(values)
    return {"count": len(normalized), "sha256": _sha256(normalized)}


def _comparison(expected: set[str], observed: set[str]) -> dict[str, Any]:
    missing = expected - observed
    extra = observed - expected
    return {
        "status": "pass" if not missing and not extra else "fail",
        "missing": _set_summary(missing),
        "extra": _set_summary(extra),
    }


def _relation_comparison(
    expected: Counter[RelationKey], observed: Counter[RelationKey]
) -> tuple[dict[str, Any], int]:
    missing = expected - observed
    extra = observed - expected
    missing_summary = _counter_summary(missing)
    extra_summary = _counter_summary(extra)
    error_count = int(missing_summary["count"]) + int(extra_summary["count"])
    return (
        {
            "status": "pass" if error_count == 0 else "fail",
            "missing": missing_summary,
            "extra": extra_summary,
        },
        error_count,
    )


def load_snapshot_payloads(snapshot_dir: Path) -> dict[str, dict[str, Any]]:
    """Load only the read models needed by this read-only gate."""

    try:
        base = snapshot_dir.expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise SemanticInventoryError("snapshot_directory_unavailable") from exc
    if not base.is_dir():
        raise SemanticInventoryError("snapshot_directory_unavailable")

    payloads: dict[str, dict[str, Any]] = {}
    for name in REQUIRED_SNAPSHOT_FILES:
        try:
            payload = json.loads((base / name).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SemanticInventoryError("snapshot_payload_unavailable") from exc
        if not isinstance(payload, dict):
            raise SemanticInventoryError("snapshot_payload_invalid")
        payloads[name] = payload
    return payloads


def _authored_pages(root: Path, config: WikiConfig) -> list[AuthoredPage]:
    memory_root = root / str(config.paths["memory_root"])
    if not memory_root.is_dir():
        return []
    pages: list[AuthoredPage] = []
    for path in sorted(memory_root.rglob("*.md")):
        values, _body = parse_frontmatter(path)
        rel = path.relative_to(root).as_posix()
        page_id = str(values.get("page_id") or rel).strip()
        pages.append(
            AuthoredPage(
                path=rel,
                page_id=page_id,
                page_type=str(values.get("page_type") or "").strip(),
                values=dict(values),
            )
        )
    return pages


def _page_indexes(
    pages: Sequence[AuthoredPage],
) -> tuple[dict[str, AuthoredPage], dict[str, str], list[str]]:
    by_id_all: dict[str, list[AuthoredPage]] = defaultdict(list)
    by_path: dict[str, str] = {}
    for page in pages:
        by_id_all[page.page_id].append(page)
        by_path[page.path] = page.page_id
    duplicates = [
        _opaque("duplicate_page_id", page_id)
        for page_id, records in sorted(by_id_all.items())
        if len(records) > 1
    ]
    by_id = {
        page_id: records[0]
        for page_id, records in by_id_all.items()
        if len(records) == 1
    }
    return by_id, by_path, duplicates


def _resolve_ref(
    raw: Any,
    by_id: Mapping[str, AuthoredPage],
    by_path: Mapping[str, str],
) -> str | None:
    ref = str(raw or "").strip()
    if not ref:
        return None
    if ref in by_id:
        return ref
    return by_path.get(ref)


def _unique_values(*values: Any) -> list[str]:
    return list(dict.fromkeys(item for value in values for item in list_values(value)))


def _event_inventory(
    pages: Sequence[AuthoredPage],
    by_path: Mapping[str, str],
    payloads: Mapping[str, Mapping[str, Any]],
    root: Path,
    config: WikiConfig,
    duplicate_page_ids: Sequence[str],
) -> tuple[dict[str, Any], dict[str, IngestionEventIdentity], int]:
    paths = WikiPaths(root, config)
    try:
        event_prefix = paths.ingest_events_dir.relative_to(root).as_posix().rstrip("/")
    except ValueError as exc:
        raise SemanticInventoryError("events_directory_outside_repository") from exc

    authored: dict[str, IngestionEventIdentity] = {}
    authored_closed: set[str] = set()
    identity_by_path: dict[str, IngestionEventIdentity] = {}
    event_duplicate_ids: list[str] = []
    for page in pages:
        in_events_directory = page.path.startswith(event_prefix + "/")
        values = {**page.values, "page_id": page.page_id}
        identity = resolve_ingestion_event_identity(
            Path(page.path), values, in_events_directory=in_events_directory
        )
        if not in_events_directory or not identity.recognized:
            continue
        if page.page_id in authored:
            event_duplicate_ids.append(_opaque("duplicate_event_id", page.page_id))
            continue
        authored[page.page_id] = identity
        identity_by_path[page.path] = identity
        if list_values(page.values.get("consolidated_into")):
            authored_closed.add(page.page_id)

    authored_ids = set(authored)
    closure_ids: set[str] = set()
    closure_closed_ids: set[str] = set()
    closure_unresolved: list[str] = []
    closure_identity_mismatch: list[str] = []
    for row in (payloads.get("ingestion.json") or {}).get("events") or []:
        if not isinstance(row, Mapping):
            closure_unresolved.append(_opaque("closure_row_not_object"))
            continue
        path = str(row.get("path") or "").strip()
        page_id = by_path.get(path)
        identity = identity_by_path.get(path)
        if not page_id or identity is None:
            closure_unresolved.append(_opaque("closure_unknown_path", path))
            continue
        closure_ids.add(page_id)
        if row.get("closed") is True:
            closure_closed_ids.add(page_id)
        if str(row.get("event_id") or "").strip() != identity.event_id:
            closure_identity_mismatch.append(
                _opaque("closure_event_identity_mismatch", path)
            )

    temporal_ids: set[str] = set()
    temporal_unresolved: list[str] = []
    for event in (payloads.get("temporal_graph.json") or {}).get("events") or []:
        if not isinstance(event, Mapping) or event.get("kind") != "ingestion_recorded":
            continue
        page_subjects = [
            str(ref).removeprefix("page:")
            for ref in event.get("subject_refs") or []
            if str(ref).startswith("page:")
        ]
        if len(page_subjects) != 1:
            temporal_unresolved.append(
                _opaque("temporal_ingestion_subject_cardinality", event.get("event_id"))
            )
            continue
        temporal_ids.add(page_subjects[0])

    graph_ids = {
        str(edge.get("target") or "")
        for edge in (payloads.get("graph.json") or {}).get("edges") or []
        if isinstance(edge, Mapping)
        and edge.get("type") == "source_emission"
        and str(edge.get("target") or "")
    }

    comparisons = {
        "closure": _comparison(authored_ids, closure_ids),
        "closure_closed": _comparison(authored_closed, closure_closed_ids),
        "temporal": _comparison(authored_ids, temporal_ids),
        "graph": _comparison(authored_ids, graph_ids),
    }
    unresolved = [
        *duplicate_page_ids,
        *event_duplicate_ids,
        *closure_unresolved,
        *temporal_unresolved,
        *closure_identity_mismatch,
    ]
    comparison_errors = sum(
        int(comparison[side]["count"])
        for comparison in comparisons.values()
        for side in ("missing", "extra")
    )
    error_count = comparison_errors + len(unresolved)
    report = {
        "status": "pass" if error_count == 0 else "fail",
        "authored": _set_summary(authored_ids),
        "authored_closed": _set_summary(authored_closed),
        "canonical_count": sum(
            identity.compatibility == "canonical" for identity in authored.values()
        ),
        "legacy_count": sum(identity.is_legacy for identity in authored.values()),
        "surfaces": {
            "closure": _set_summary(closure_ids),
            "closure_closed": _set_summary(closure_closed_ids),
            "temporal": _set_summary(temporal_ids),
            "graph": _set_summary(graph_ids),
        },
        "comparisons": comparisons,
        "unresolved": _opaque_summary(unresolved),
        "identity_mismatches": _opaque_summary(closure_identity_mismatch),
    }
    return report, authored, error_count


def _relation_key(
    source: str,
    target: str,
    relation_type: str,
    direction: str,
    basis: str,
    provenance_page_id: str,
    provenance_path: str,
    provenance_field: str,
) -> RelationKey:
    return (
        source,
        target,
        relation_type,
        direction,
        basis,
        provenance_page_id,
        provenance_path,
        provenance_field,
    )


def _expected_relations(
    pages: Sequence[AuthoredPage],
    by_id: Mapping[str, AuthoredPage],
    by_path: Mapping[str, str],
    authored_events: Mapping[str, IngestionEventIdentity],
) -> tuple[Counter[RelationKey], list[str]]:
    expected: Counter[RelationKey] = Counter()
    unresolved: list[str] = []

    def add(
        page: AuthoredPage,
        raw_ref: Any,
        relation_type: str,
        field: str,
        *,
        reverse: bool = False,
        basis: str = "frontmatter",
        provenance_page_id: str | None = None,
        provenance_path: str | None = None,
        provenance_field: str | None = None,
        direction: str | None = None,
    ) -> None:
        target = _resolve_ref(raw_ref, by_id, by_path)
        if target is None:
            unresolved.append(_opaque("unresolved_relation", page.path, field, raw_ref))
            return
        source_id, target_id = (target, page.page_id) if reverse else (page.page_id, target)
        relation_direction = direction or RELATION_DIRECTIONS.get(relation_type)
        if relation_direction is None:
            unresolved.append(
                _opaque("unknown_relation_type", page.path, field, relation_type)
            )
            return
        key = _relation_key(
            source_id,
            target_id,
            relation_type,
            relation_direction,
            basis,
            page.page_id if provenance_page_id is None else provenance_page_id,
            page.path if provenance_path is None else provenance_path,
            field if provenance_field is None else provenance_field,
        )
        # The runtime graph de-duplicates identical semantic edges. Preserve a
        # multiset across distinct meanings while normalizing repeated text in
        # the same frontmatter field to one expected edge.
        expected[key] = 1

    for page in pages:
        values = page.values
        for ref in _unique_values(values.get("moc_parent")):
            add(page, ref, "moc_parent", "moc_parent")

        source_refs = _unique_values(
            values.get("source_refs"), values.get("source_ref")
        )
        for ref in source_refs:
            add(page, ref, "source_ref", "source_refs")
            if page.page_id in authored_events:
                add(page, ref, "source_emission", "source_refs", reverse=True)

        for ref in _unique_values(values.get("related_pages")):
            add(page, ref, "related_page", "related_pages")
        for ref in _unique_values(values.get("proposal_ids")):
            add(page, ref, "proposal_transition", "proposal_ids")
        for ref in _unique_values(values.get("consolidated_into")):
            add(page, ref, "impact", "consolidated_into")
        for ref in _unique_values(values.get("participants")):
            add(page, ref, "participation", "participants", reverse=True)
        for ref in _unique_values(
            values.get("previous_refs"), values.get("previous_ref")
        ):
            add(page, ref, "temporal_sequence", "previous_refs", reverse=True)

        if page.page_type == "action":
            for ref in _unique_values(values.get("blocked_by")):
                add(page, ref, "dependency", "blocked_by", reverse=True)
            for ref in _unique_values(values.get("owner_ref")):
                add(page, ref, "ownership", "owner_ref", reverse=True)
            for ref in _unique_values(
                values.get("evidence_refs"),
                values.get("evidence_for"),
                values.get("evidence_against"),
            ):
                add(page, ref, "evidence_supports", "evidence_refs", reverse=True)

        for ref in _unique_values(
            values.get("collection_refs"), values.get("collection_ref")
        ):
            add(
                page,
                ref,
                "collection_member",
                "collection_refs",
                basis="member.collection_refs",
            )

        collection = values.get("collection")
        if isinstance(collection, Mapping):
            for ref in _unique_values(collection.get("members")):
                target = _resolve_ref(ref, by_id, by_path)
                if target is None:
                    unresolved.append(
                        _opaque("unresolved_relation", page.path, "collection", ref)
                    )
                    continue
                key = _relation_key(
                    target,
                    page.page_id,
                    "collection_member",
                    "directed",
                    "collection.members",
                    page.page_id,
                    page.path,
                    "collection",
                )
                expected[key] = 1

        relation_cases = values.get("relation_cases")
        if isinstance(relation_cases, list):
            for index, raw_case in enumerate(relation_cases):
                if not isinstance(raw_case, Mapping):
                    unresolved.append(
                        _opaque("invalid_relation_case", page.path, index)
                    )
                    continue
                relation_type = str(raw_case.get("type") or "")
                target = _resolve_ref(raw_case.get("target"), by_id, by_path)
                direction = str(raw_case.get("direction") or "") or RELATION_DIRECTIONS.get(
                    relation_type, ""
                )
                provenance = raw_case.get("provenance")
                provenance_map = provenance if isinstance(provenance, Mapping) else {}
                if (
                    target is None
                    or not direction
                    or relation_type not in RELATION_DIRECTIONS
                    or (
                        relation_type in PROVENANCE_BEARING_TYPES
                        and not provenance_map
                    )
                ):
                    unresolved.append(
                        _opaque("invalid_relation_case", page.path, index)
                    )
                    continue
                key = _relation_key(
                    page.page_id,
                    target,
                    relation_type,
                    direction,
                    str(raw_case.get("basis") or "explicit_fixture"),
                    str(provenance_map.get("page_id") or page.page_id),
                    str(provenance_map.get("path") or page.path),
                    str(
                        provenance_map.get("field")
                        or f"relation_cases[{index}]"
                    ),
                )
                expected[key] = 1

    return expected, unresolved


def _actual_relations(graph: Mapping[str, Any]) -> Counter[RelationKey]:
    actual: Counter[RelationKey] = Counter()
    for edge in graph.get("edges") or []:
        if not isinstance(edge, Mapping):
            continue
        relation_type = str(edge.get("type") or "")
        basis = str(edge.get("basis") or "")
        if relation_type == "markdown_link" and basis == "markdown_body":
            continue
        if relation_type == "collection_member" and basis not in DIRECT_COLLECTION_BASES:
            continue
        provenance = edge.get("provenance")
        provenance_map = provenance if isinstance(provenance, Mapping) else {}
        key = _relation_key(
            str(edge.get("source") or ""),
            str(edge.get("target") or ""),
            relation_type,
            str(edge.get("direction") or ""),
            basis,
            str(provenance_map.get("page_id") or ""),
            str(provenance_map.get("path") or ""),
            str(provenance_map.get("field") or ""),
        )
        actual[key] += 1
    return actual


def build_semantic_inventory(
    root: Path,
    config: WikiConfig,
    payloads: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a sanitized semantic parity report without writing artifacts."""

    root = root.resolve()
    if payloads is None:
        # Lazy import keeps this independent compiler out of the snapshot
        # module's import graph while still allowing a read-only live check.
        from wiki_core.web.snapshot import build_snapshot

        payloads = build_snapshot(root, config)

    missing_payloads = [
        name
        for name in ("ingestion.json", "temporal_graph.json", "graph.json")
        if not isinstance(payloads.get(name), Mapping)
    ]
    if missing_payloads:
        raise SemanticInventoryError("required_snapshot_payload_missing")

    pages = _authored_pages(root, config)
    by_id, by_path, duplicate_page_ids = _page_indexes(pages)
    event_report, authored_events, event_errors = _event_inventory(
        pages,
        by_path,
        payloads,
        root,
        config,
        duplicate_page_ids,
    )
    expected_relations, unresolved_relations = _expected_relations(
        pages, by_id, by_path, authored_events
    )
    actual_relations = _actual_relations(payloads["graph.json"])
    relation_comparison, relation_diff_errors = _relation_comparison(
        expected_relations, actual_relations
    )
    relation_errors = relation_diff_errors + len(unresolved_relations)
    relation_report = {
        "status": "pass" if relation_errors == 0 else "fail",
        "expected": _counter_summary(expected_relations),
        "actual": _counter_summary(actual_relations),
        "comparison": relation_comparison,
        "unresolved": _opaque_summary(unresolved_relations),
        "scope": {
            "markdown_body_links": "excluded",
            "derived_collection_member_types": "excluded",
            "direct_frontmatter_references": "included",
        },
    }

    error_count = event_errors + relation_errors
    return {
        "schema_version": SEMANTIC_INVENTORY_SCHEMA_VERSION,
        "repository": {"id_sha256": _sha256(str(config.repo_id))},
        "status": "pass" if error_count == 0 else "fail",
        "summary": {
            "error_count": error_count,
            "event_error_count": event_errors,
            "relation_error_count": relation_errors,
        },
        "events": event_report,
        "relations": relation_report,
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    """Render the sanitized report without identifiers, titles or paths."""

    events = report.get("events") or {}
    relations = report.get("relations") or {}
    lines = [
        "# Wiki semantic inventory",
        "",
        f"- Schema: `{report.get('schema_version') or ''}`",
        f"- Status: **{str(report.get('status') or 'fail').upper()}**",
        f"- Errors: {int((report.get('summary') or {}).get('error_count') or 0)}",
        "",
        "## Event surfaces",
        "",
        "| Surface | Count | SHA-256 |",
        "| --- | ---: | --- |",
    ]
    surfaces = {
        "authored": events.get("authored") or {},
        "authored_closed": events.get("authored_closed") or {},
        **dict(events.get("surfaces") or {}),
    }
    for name, summary in surfaces.items():
        lines.append(
            f"| {name} | {int(summary.get('count') or 0)} | "
            f"`{str(summary.get('sha256') or '')}` |"
        )
    lines.extend(
        [
            "",
            "## Relations",
            "",
            "| Inventory | Count | Unique | SHA-256 |",
            "| --- | ---: | ---: | --- |",
        ]
    )
    for name in ("expected", "actual"):
        summary = relations.get(name) or {}
        lines.append(
            f"| {name} | {int(summary.get('count') or 0)} | "
            f"{int(summary.get('unique_count') or 0)} | "
            f"`{str(summary.get('sha256') or '')}` |"
        )
    comparison = relations.get("comparison") or {}
    lines.extend(
        [
            "",
            f"- Missing relations: {int((comparison.get('missing') or {}).get('count') or 0)}",
            f"- Extra relations: {int((comparison.get('extra') or {}).get('count') or 0)}",
            f"- Unresolved authored references: {int((relations.get('unresolved') or {}).get('count') or 0)}",
            "",
        ]
    )
    return "\n".join(lines)


__all__ = [
    "SEMANTIC_INVENTORY_SCHEMA_VERSION",
    "SemanticInventoryError",
    "build_semantic_inventory",
    "load_snapshot_payloads",
    "render_markdown",
]
