"""Modular template blocks — the compiler.

A **template** is the complete contract of an information module: how content
below it is interpreted (lenses), what the interface offers (surfaces), how the
place looks (identity), what structure is born with it (subpages). A **block**
is the modular unit of those contributions.

This module owns the block VOCABULARY (fixed, versioned — a new surface/provider
/landmark needs code here, never just YAML), the VALIDATION, and the STACK
RESOLUTION that produces, per anchor, the resolved block stack + interface +
identity + derived outputs (quadrant assignments, relations, missions). It reads
the template registry (:mod:`wiki_core.templates_registry`), the pages and the
link graph; it writes nothing. Deterministic and pure-ish (only reads files).

Blocks come from three rings of DEFINITION — the kit registry (`wiki.templates
.yaml` `blocks:`), a per-wiki local override (`wiki.templates.local.yaml`), and
wiki pages of `page_type: template_block` (frontmatter `block:`). Blocks apply to
a scope through four rings of RESOLUTION — kit defaults → the anchor's own
template → the chain of ancestor anchors → the anchor's own frontmatter — with
the nearest ring winning config, the most restrictive privacy always winning,
and every resolved block carrying its `origin`.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wiki_core.action_state import (
    legacy_action_state_from_body,
    resolve_action_state,
)
from wiki_core.config import WikiConfig, load_config
from wiki_core.collections import (
    collection_cycle_diagnostics,
    collection_spec,
    collection_reference_diagnostics,
    collection_membership_basis,
    member_collection_refs,
    validate_collection_declaration,
)
from wiki_core.facets import FACET_QUADRANTS, FACETS, facet_of, home_quadrant
from wiki_core.freshness import freshness_state, is_stale_exempt
from wiki_core.frontmatter import list_values, parse_frontmatter
from wiki_core.graph.page_graph import PageGraph, build_page_graph
from wiki_core.quadrants import DEFAULT_QUADRANT_MAP, quadrant_contract
from wiki_core.templates_registry import TemplateRegistry, load_template_registry

BLOCKS_SCHEMA_VERSION = "wiki_web_blocks.v1"
BLOCK_STACKS_SCHEMA_VERSION = "wiki_web_block_stacks.v1"
VISUAL_GRAMMAR_SCHEMA_VERSION = "wiki.visual_grammar.v1"

# --- The FIXED vocabulary (source of truth in code) -------------------------
BLOCK_KINDS = frozenset({"interpretation", "interface", "gate", "skill"})
SCOPE_MODES = frozenset({"self", "children", "descendants", "context", "linked"})
NESTED_MODES = frozenset({"summarize", "project_all", "hide_nested"})
SURFACES = frozenset({"views", "missions", "create", "intake", "score", "panels"})
MISSION_PROVIDERS = frozenset(
    {
        "stale",
        "gates_failing",
        "approvals_pending",
        "template_conformity",
        "source_cursor_overdue",
        "source_closure",
        "quadrant_absence",
        "relation_cadence_overdue",
        "date_upcoming",
        "commitment_open",
        "meeting_followup",
    }
)
INTAKE_FORMS = frozenset(
    {
        "copy_file",
        "paste_text",
        "source_sync",
        "recipe_export_checklist",
        "promote_reference",
        "meeting_note",
        "interaction_note",
    }
)
SCORE_LOOPS = frozenset(
    {
        "mission_health",
        "source_closure",
        "evidence_integrity",
        "context_vitality",
        "template_conformity",
        "skill_completion",
    }
)
SCENE_LAYOUTS = frozenset({"quadrants", "radar", "atlas", "districts", "trails", "focus"})
SCENE_OVERLAYS = frozenset({"privacy_ring", "approval_halo", "stream_particles", "weather_signal"})
IDENTITY_LANDMARKS = frozenset(
    {"observatory", "beacon", "crystal_spire", "plaza", "forge", "shelf", "engine"}
)
IDENTITY_MOTIFS = frozenset({"rings", "grid", "ledger", "shelves", "orbits", "streams", "none"})
IDENTITY_AMBIENTS = frozenset({"none", "motes", "drift"})
VISUAL_PRIMITIVES = frozenset(
    {
        "region_card",
        "region_work_card",
        "attention_rail",
        "type_shelf",
        "source_badge",
        "action_lane",
        "risk_notch",
        "review_halo",
        "hidden_histogram",
        "core_debt_meter",
        "empty_region_affordance",
        "bridge_count",
        "center_badge",
        "scope_chip",
        "legend_key",
    }
)
VISUAL_PRIMITIVE_SLOTS = frozenset(
    {
        "region.card",
        "region.rail",
        "region.shelf",
        "region.marker",
        "region.empty",
        "cluster.tooltip",
        "fallback.card",
        "reader.badge",
        "dock.action",
        "legend.entry",
    }
)
VISUAL_PRIMITIVE_PACKS = frozenset({"region_operations", "evidence_first", "review_first", "quiet_structure"})
VISUAL_PRIMITIVE_PURPOSES = {
    "region_card": "summarize region size and purpose",
    "region_work_card": "show composition, attention and next actions",
    "attention_rail": "filter attention inside the active region",
    "type_shelf": "show why a region is dense by page family",
    "source_badge": "mark raw, synced and consolidated evidence",
    "action_lane": "separate work items from context",
    "risk_notch": "show risk without flooding the region",
    "review_halo": "show pending proposal or approval review",
    "hidden_histogram": "describe hidden work behind render limits",
    "core_debt_meter": "flag classification debt in the core ring",
    "empty_region_affordance": "explain required absences and valid creation paths",
    "bridge_count": "explain cross-region dependencies",
    "center_badge": "show the active anchor center",
    "scope_chip": "show the active center, region or filter scope",
    "legend_key": "explain the resolved visual grammar",
}
DEFAULT_VISUAL_PACKS: dict[str, dict[str, Any]] = {
    "region_operations": {
        "slots": {
            "region.card": "region_card",
            "region.rail": "attention_rail",
            "region.shelf": "type_shelf",
            "region.marker": "action_lane",
            "region.empty": "empty_region_affordance",
            "cluster.tooltip": "hidden_histogram",
            "fallback.card": "region_work_card",
            "legend.entry": "legend_key",
        }
    },
    "evidence_first": {
        "extends": "region_operations",
        "slots": {
            "reader.badge": "source_badge",
            "dock.action": "action_lane",
        },
    },
    "review_first": {
        "extends": "region_operations",
        "slots": {
            "region.marker": "review_halo",
            "dock.action": "review_halo",
        },
    },
    "quiet_structure": {
        "extends": "region_operations",
        "slots": {
            "region.card": "center_badge",
            "region.rail": "core_debt_meter",
            "region.marker": "scope_chip",
        },
    },
}

# Quadrant IDs in canonical order, derived from the facet contract
# (wiki_core.facets encodes the honest 1:1 facet <-> quadrant mapping; one lens
# per quadrant). NOT the same object as quadrants.QUADRANTS, which holds the
# full QuadrantDefinition records.
_FACET_QUADRANT = {facet: FACET_QUADRANTS[facet][0] for facet in FACETS}
_QUADRANT_FACET = {quadrant: facet for facet, quadrant in _FACET_QUADRANT.items()}
QUADRANT_IDS: tuple[str, ...] = tuple(_FACET_QUADRANT[facet] for facet in FACETS)

# The interior of each quadrant — sub-lenses. Refinement of reading/display/
# extraction WITHIN the region; the four spatial regions and the 1:1 AQAL
# contract do NOT change. Order matters: PERCEPTION comes first in q1.
SUB_LENSES: dict[str, tuple[str, ...]] = {
    "q1": ("percepcao", "intencao", "identidade"),
    "q2": ("comportamento", "producao", "evidencias", "capacidades"),
    "q3": ("pessoas", "rede", "encontros", "cultura"),
    "q4": ("ferramentas", "processos", "fontes", "automacoes", "governanca"),
}

# Default sub-lens a page falls under WITHIN its home quadrant, keyed by page_type.
# Center/area pages have no sub-lens unless the page or registry classifies them.
SUBLENS_DEFAULT_BY_TYPE: dict[str, str] = {
    # q1 interior
    "claim": "percepcao",
    "insight": "percepcao",
    "journal_entry": "percepcao",
    "perspective": "percepcao",
    "decision": "intencao",
    "initiative": "intencao",
    "project": "intencao",
    "responsibility": "identidade",
    # q2 interior
    "action": "comportamento",
    "artifact": "producao",
    "evidence": "evidencias",
    "source": "evidencias",
    "source_catalog": "evidencias",
    "source_registry": "evidencias",
    "system_log": "evidencias",
    "ingestion_event": "evidencias",
    "dashboard": "evidencias",
    "root_index": "evidencias",
    "ontology_index": "evidencias",
    # q3 interior
    "person": "pessoas",
    "role": "pessoas",
    "meeting": "encontros",
    "holon": "cultura",
    "relationship_map": "rede",
    # q4 interior
    "operational_rule": "governanca",
    "context_hub": "governanca",
    "tool": "ferramentas",
    "process": "processos",
    "source_config": "fontes",
    "input_channel": "fontes",
    "input_stage": "fontes",
    "template_block": "governanca",
    "skill": "automacoes",
}

ROOT_ENTITY_TYPE_PARENT_PROJECTION: dict[str, tuple[str, str]] = {
    "person": ("relacoes", "pessoas"),
    "team": ("relacoes", "cultura"),
    "company": ("sistemas", "governanca"),
    "community": ("relacoes", "cultura"),
    "project": ("intencao", "intencao"),
    "product": ("pratica", "producao"),
}

ANCHOR_TYPE_PARENT_PROJECTION: dict[str, tuple[str, str]] = {
    "holon": ("relacoes", "cultura"),
    "project": ("intencao", "intencao"),
    "source": ("pratica", "evidencias"),
    "template_block": ("sistemas", "governanca"),
}

SUBJECT_ROLE_FACET: dict[str, str] = {
    "perception": "intencao",
    "percepcao": "intencao",
    "interior_intent": "intencao",
    "intent": "intencao",
    "intention": "intencao",
    "intencao": "intencao",
    "objetivo": "intencao",
    "objective": "intencao",
    "goal": "intencao",
    "decision": "intencao",
    "practice": "pratica",
    "pratica": "pratica",
    "observable_action": "pratica",
    "behavior": "pratica",
    "comportamento": "pratica",
    "production": "pratica",
    "producao": "pratica",
    "artifact_output": "pratica",
    "evidence": "pratica",
    "relation": "relacoes",
    "relationship": "relacoes",
    "relations": "relacoes",
    "relacao": "relacoes",
    "relacoes": "relacoes",
    "people": "relacoes",
    "pessoas": "relacoes",
    "network": "relacoes",
    "rede": "relacoes",
    "role_culture": "relacoes",
    "meeting_shared_meaning": "relacoes",
    "system": "sistemas",
    "system_process": "sistemas",
    "systems": "sistemas",
    "sistema": "sistemas",
    "sistemas": "sistemas",
    "process": "sistemas",
    "processo": "sistemas",
    "governance": "sistemas",
    "governanca": "sistemas",
    "source_input": "sistemas",
    "tool_governance": "sistemas",
}


@dataclass
class BlockWorld:
    """Everything the compiler reads, loaded once. Deterministic."""

    root: Path
    config: WikiConfig
    registry: TemplateRegistry
    blocks: dict[str, dict[str, Any]]  # block_id -> definition
    block_origin: dict[str, str]  # block_id -> "registry" | f"page:{page_id}"
    pages: list[dict[str, Any]]
    by_id: dict[str, dict[str, Any]]
    by_path: dict[str, dict[str, Any]]
    children: dict[str, list[str]]  # parent key (path or id) -> [child page_id]
    graph: PageGraph
    today: dt.date


# --- Loading ----------------------------------------------------------------


def _page_records(root: Path, config: WikiConfig, today: dt.date) -> list[dict[str, Any]]:
    memory_root = root / config.paths["memory_root"]
    records: list[dict[str, Any]] = []
    if not memory_root.exists():
        return records
    for path in sorted(p for p in memory_root.rglob("*.md") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        values, body = parse_frontmatter(path)
        page_id = str(values.get("page_id") or rel).strip()
        records.append(
            {
                "id": page_id,
                "path": rel,
                "title": str(values.get("title") or page_id),
                "page_type": str(values.get("page_type") or ""),
                "context": str(values.get("context") or config.default_context),
                "visibility": str(values.get("visibility") or config.default_visibility),
                "moc_parent": str(values.get("moc_parent") or ""),
                "updated_at": str(values.get("updated_at") or ""),
                "values": values,
                # Internal-only input for the legacy action adapter. Derived
                # payloads select explicit fields and never publish this body.
                "body": body,
            }
        )
    return records


def load_block_world(
    root: Path,
    config: WikiConfig | None = None,
    *,
    pages: list[dict[str, Any]] | None = None,
    graph: PageGraph | None = None,
    today: dt.date | None = None,
) -> BlockWorld:
    config = config or load_config(root)
    today = today or dt.date.today()
    registry = load_template_registry(root, config)
    records = pages if pages is not None else _page_records(root, config, today)

    blocks: dict[str, dict[str, Any]] = {}
    origin: dict[str, str] = {}
    # Ring: kit + local registry blocks (already merged by load_template_registry).
    for block_id, definition in registry.raw_blocks.items():
        blocks[block_id] = dict(definition)
        origin[block_id] = "registry"
    # Ring: pages that DEFINE a block (page > registry on id clash).
    for page in records:
        if page["page_type"] != "template_block":
            continue
        definition = page["values"].get("block")
        if not isinstance(definition, dict):
            continue
        block_id = str(definition.get("block_id") or "").strip()
        if not block_id:
            continue
        blocks[block_id] = dict(definition)
        origin[block_id] = f"page:{page['id']}"

    by_id = {page["id"]: page for page in records}
    by_path = {page["path"]: page for page in records}
    children: dict[str, list[str]] = {}
    for page in records:
        parent = page["moc_parent"].strip()
        if parent:
            children.setdefault(parent, []).append(page["id"])
    graph = graph if graph is not None else build_page_graph(root, config)
    return BlockWorld(
        root=root,
        config=config,
        registry=registry,
        blocks=blocks,
        block_origin=origin,
        pages=records,
        by_id=by_id,
        by_path=by_path,
        children=children,
        graph=graph,
        today=today,
    )


# --- Anchor & scope helpers -------------------------------------------------


def is_anchor_type(world: BlockWorld, page_type: str) -> bool:
    return bool(world.registry.resolve(page_type).can_anchor_blocks)


def _resolve_parent(world: BlockWorld, page: dict[str, Any]) -> dict[str, Any] | None:
    key = page["moc_parent"].strip()
    if not key:
        return None
    return world.by_path.get(key) or world.by_id.get(key)


def anchor_chain(world: BlockWorld, page: dict[str, Any]) -> list[dict[str, Any]]:
    """Ancestor pages via moc_parent, ROOT-FIRST (farthest → nearest). Cycle-safe."""
    chain: list[dict[str, Any]] = []
    seen: set[str] = {page["id"]}
    current = _resolve_parent(world, page)
    while current and current["id"] not in seen:
        seen.add(current["id"])
        chain.append(current)
        current = _resolve_parent(world, current)
    chain.reverse()  # root-first
    return chain


def _is_descendant(world: BlockWorld, anchor: dict[str, Any], target: dict[str, Any]) -> bool:
    if anchor["id"] == target["id"]:
        return True
    seen: set[str] = {target["id"]}
    current = _resolve_parent(world, target)
    while current and current["id"] not in seen:
        if current["id"] == anchor["id"]:
            return True
        seen.add(current["id"])
        current = _resolve_parent(world, current)
    return False


_PROJECT_MEMBER_PROJECTION: dict[str, tuple[str, str]] = {
    "claims": ("intencao", "percepcao"),
    "decisions": ("intencao", "intencao"),
    "actions": ("pratica", "comportamento"),
    "evidence_refs": ("pratica", "evidencias"),
    "roles": ("relacoes", "pessoas"),
    "responsibilities": ("relacoes", "cultura"),
    "related_holons": ("relacoes", "cultura"),
    "source_refs": ("sistemas", "fontes"),
}


def _project_member_role(anchor: dict[str, Any], target: dict[str, Any]) -> tuple[str, str, str] | None:
    if anchor["page_type"] != "project":
        return None
    for field, (facet, sub_lens) in _PROJECT_MEMBER_PROJECTION.items():
        if any(_page_ref_matches(ref, target) for ref in list_values(anchor["values"].get(field))):
            return field, facet, sub_lens
    return None


def _scope_reaches(
    world: BlockWorld, scope: str, anchor: dict[str, Any], target: dict[str, Any]
) -> bool:
    if anchor["id"] == target["id"]:
        return True
    if scope == "self":
        return False
    if scope == "linked" and collection_membership_basis(
        anchor,
        target,
        default=world.registry.resolve(anchor["page_type"]).collection,
    ):
        return True
    if _page_ref_matches(target["values"].get("subject_ref") or target["values"].get("subject"), anchor):
        return True
    if (
        anchor["page_type"] == "source"
        and not _is_descendant(world, target, anchor)
        and any(
            _page_ref_matches(ref, anchor)
            for ref in [
                *list_values(target["values"].get("source_ref")),
                *list_values(target["values"].get("source_refs")),
            ]
        )
    ):
        return True
    if (
        anchor["page_type"] == "holon"
        and not _is_descendant(world, target, anchor)
        and any(
            _page_ref_matches(ref, anchor)
            for ref in list_values(target["values"].get("related_holons"))
        )
    ):
        return True
    if not _is_descendant(world, target, anchor) and _project_member_role(anchor, target):
        return True
    # ``linked`` is an explicit relation scope. It must not silently degrade to
    # the descendants fallback below; doing so would re-flatten collection
    # indexes into their canonical hierarchy.
    if scope == "linked":
        return False
    if scope == "children":
        return target["moc_parent"] in {anchor["path"], anchor["id"]}
    if scope == "context":
        return target["context"] == anchor["context"] and bool(anchor["context"])
    # descendants (default)
    return _is_descendant(world, anchor, target)


def scope_pages(world: BlockWorld, anchor: dict[str, Any], scope: str) -> list[dict[str, Any]]:
    """Pages the block governs BELOW the anchor (excluding the anchor itself)."""
    out = [
        page
        for page in world.pages
        if page["id"] != anchor["id"] and _scope_reaches(world, scope, anchor, page)
    ]
    return out


# --- Stack resolution -------------------------------------------------------


def _block_instances(entries: Any) -> list[dict[str, Any]]:
    """Normalize a `blocks:` list (from a template or a page frontmatter)."""
    out: list[dict[str, Any]] = []
    if not isinstance(entries, list):
        return out
    for entry in entries:
        if isinstance(entry, str):
            out.append({"id": entry})
        elif isinstance(entry, dict) and entry.get("id"):
            out.append(dict(entry))
    return out


def _collection_scope_instance_errors(label: str, instance: dict[str, Any]) -> list[str]:
    if "collection_scope" in instance and not isinstance(
        instance.get("collection_scope"), bool
    ):
        return [f"{label}: collection_scope must be boolean"]
    return []


def _package_instances(world: BlockWorld, entries: Any) -> list[dict[str, Any]]:
    """Expand a `packages:` list into block instances (attachment sugar: a
    package is a named group; its blocks apply in order at the same ring)."""
    out: list[dict[str, Any]] = []
    if not isinstance(entries, list):
        return out
    for entry in entries:
        name = entry if isinstance(entry, str) else str((entry or {}).get("id") or "")
        package = world.registry.raw_packages.get(name)
        if not package:
            continue
        for inst in _block_instances(package.get("blocks")):
            out.append(inst)
    return out


def _default_scope(world: BlockWorld, block_id: str) -> str:
    definition = world.blocks.get(block_id) or {}
    scope = (definition.get("scope") or {}).get("default_mode")
    return str(scope) if scope in SCOPE_MODES else "descendants"


def _apply(stack: list[dict[str, Any]], instance: dict[str, Any], *, origin: str, world: BlockWorld) -> None:
    block_id = str(instance["id"])
    scope = str(instance.get("scope") or _default_scope(world, block_id))
    config = dict(instance.get("config") or {})
    definition = world.blocks.get(block_id) or {}
    kind = str(definition.get("kind") or "")
    collection_scope = (
        bool(instance.get("collection_scope"))
        if "collection_scope" in instance
        else bool(definition.get("collection_scope", False))
    )
    for existing in stack:
        if existing["id"] == block_id:
            # Nearer ring wins: override config key-by-key, adopt nearer scope/origin.
            existing["config"].update(config)
            existing["scope"] = scope
            existing["origin"] = origin
            existing["collection_scope"] = collection_scope
            return
    stack.append(
        {
            "id": block_id,
            "origin": origin,
            "scope": scope,
            "kind": kind,
            "config": config,
            "known": block_id in world.blocks,
            "collection_scope": collection_scope,
        }
    )


def _has_collection_contract(world: BlockWorld, anchor: dict[str, Any]) -> bool:
    default = world.registry.resolve(anchor["page_type"]).collection
    spec = collection_spec(anchor, default)
    if spec["member_types"] or spec["members"]:
        return True
    return any(
        page["id"] != anchor["id"]
        and any(
            ref in {anchor["id"], anchor["path"]}
            for ref in member_collection_refs(page)
        )
        for page in world.pages
    )


def _activate_collection_scopes(
    world: BlockWorld, page: dict[str, Any], stack: list[dict[str, Any]]
) -> None:
    """Switch collection-aware type blocks only when membership is declared.

    Legacy ontology indexes often own real moc descendants. They must keep that
    behavior until the page or one of its members explicitly declares a
    collection relation. The resolved stack records the basis either way.
    """

    active = _has_collection_contract(world, page)
    for entry in stack:
        if not entry.get("collection_scope"):
            continue
        entry["declared_scope"] = str(entry.get("scope") or "descendants")
        entry["scope"] = "linked" if active else entry["declared_scope"]
        entry["scope_basis"] = (
            "collection_contract" if active else "canonical_hierarchy"
        )


def resolve_stack(world: BlockWorld, page: dict[str, Any]) -> list[dict[str, Any]]:
    """The ordered block stack governing `page`, nearest ring winning config.

    Order applied (each overrides the previous): kit defaults → ancestor anchors
    root-first (their template + frontmatter blocks whose scope reaches here) →
    this page's own template blocks → this page's own frontmatter blocks.
    """
    stack: list[dict[str, Any]] = []
    # Ring 0: kit defaults (top-level `default_blocks:` in the registry, if any).
    for inst in _block_instances(getattr(world.registry, "vocabulary", {}).get("default_blocks")):
        _apply(stack, inst, origin="kit", world=world)
    # Ring 1: ancestor anchors, root-first (template blocks + frontmatter blocks
    # + frontmatter packages, expanded).
    for ancestor in anchor_chain(world, page):
        spec = world.registry.resolve(ancestor["page_type"])
        instances = (
            _block_instances(list(spec.blocks))
            + _block_instances(ancestor["values"].get("blocks"))
            + _package_instances(world, ancestor["values"].get("packages"))
        )
        for inst in instances:
            if _scope_reaches(world, str(inst.get("scope") or _default_scope(world, str(inst["id"]))), ancestor, page):
                _apply(stack, inst, origin=f"anchor:{ancestor['id']}", world=world)
    # Ring 2: this page's own template blocks.
    own_spec = world.registry.resolve(page["page_type"])
    for inst in _block_instances(list(own_spec.blocks)):
        _apply(stack, inst, origin=f"template:{page['page_type']}", world=world)
    # Ring 3: this page's own frontmatter blocks + packages (nearest).
    for inst in _block_instances(page["values"].get("blocks")) + _package_instances(
        world, page["values"].get("packages")
    ):
        _apply(stack, inst, origin="page", world=world)
    _activate_collection_scopes(world, page, stack)
    return stack


def _stack_block(stack: list[dict[str, Any]], family_id_prefix: str) -> dict[str, Any] | None:
    for entry in stack:
        if entry["id"].startswith(family_id_prefix):
            return entry
    return None


# --- Quadrant assignments ---------------------------------------------------


def _home_quadrant_overrides(world: BlockWorld) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for page_type in world.registry.raw_types:
        home = world.registry.resolve(page_type).home_quadrant
        if home:
            # Accept either a facet name (intencao..) or a quadrant id (q1..).
            facet = home if home in FACETS else _QUADRANT_FACET.get(home, "")
            if facet:
                overrides[page_type] = facet
    return overrides


def _facet_from_quadrant_or_facet(value: Any) -> str | None:
    raw = str(value or "").strip()
    if raw in FACETS:
        return raw
    return _QUADRANT_FACET.get(raw)


def _page_ref_matches(value: Any, page: dict[str, Any]) -> bool:
    refs = list_values(value)
    return bool({page["id"], page["path"]}.intersection(refs))


def _resolve_page_ref(world: BlockWorld, value: Any) -> dict[str, Any] | None:
    for ref in list_values(value):
        page = world.by_id.get(ref) or world.by_path.get(ref)
        if page:
            return page
    return None


def _projection_from_raw(
    raw: Any,
    *,
    page: dict[str, Any],
    center: dict[str, Any],
    basis: str,
    subject_center: str = "",
    through_center: str = "",
) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    facet = _facet_from_quadrant_or_facet(raw.get("facet") or raw.get("quadrant"))
    if not facet:
        return None
    quadrant = _FACET_QUADRANT[facet]
    explicit_lens = str(raw.get("sub_lens") or raw.get("lens") or "").strip()
    lens = explicit_lens if explicit_lens in SUB_LENSES[quadrant] else _sub_lens_for(page, quadrant)
    return {
        "center": center["id"],
        "page": page["id"],
        "quadrant": quadrant,
        "facet": facet,
        "sub_lens": lens,
        "basis": basis,
        "subject_center": subject_center,
        "through_center": through_center,
        "local_quadrant_under_subject": "",
        "local_facet_under_subject": "",
        "local_sub_lens_under_subject": "",
        "reason": str(raw.get("reason") or ""),
    }


def _projection_override(
    world: BlockWorld,
    center: dict[str, Any],
    page: dict[str, Any],
) -> dict[str, Any] | None:
    values = page["values"]
    raw = values.get("projection_overrides") or values.get("quadrant_projections")
    candidate: Any = None
    if isinstance(raw, dict):
        candidate = raw.get(center["id"]) or raw.get(center["path"]) or raw.get("*")
    elif isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            target = item.get("center") or item.get("anchor") or item.get("root")
            if _page_ref_matches(target, center) or str(target or "").strip() == "*":
                candidate = item
                break
    projection = _projection_from_raw(candidate, page=page, center=center, basis="projection_override")
    if projection:
        projection["subject_center"] = str((candidate or {}).get("subject_center") or "")
        projection["through_center"] = str((candidate or {}).get("through_center") or "")
    return projection


def _subject_role_projection(
    center: dict[str, Any],
    page: dict[str, Any],
) -> dict[str, Any] | None:
    values = page["values"]
    subject_ref = values.get("subject_ref") or values.get("subject")
    if subject_ref and not _page_ref_matches(subject_ref, center):
        return None
    role = str(values.get("subject_role") or values.get("projection_role") or "").strip()
    facet = SUBJECT_ROLE_FACET.get(role)
    if not facet:
        return None
    return _projection_from_raw(
        {"facet": facet, "sub_lens": values.get("sub_lens"), "reason": f"subject_role:{role}"},
        page=page,
        center=center,
        basis="subject_role",
        subject_center=center["id"],
    )


def _subject_nested_center_projection(
    world: BlockWorld,
    center: dict[str, Any],
    page: dict[str, Any],
) -> dict[str, Any] | None:
    """Project a cross-folder page through its declared subject center.

    A claim may live in ``memories/claims`` while describing a company or
    product root. The physical ``moc_parent`` chain should not make that claim
    global-Q1 for the person's root. Its declared subject becomes the local
    center; ancestor centers see it through that subject center's parent role.
    """
    values = page["values"]
    subject_page = _resolve_page_ref(world, values.get("subject_ref") or values.get("subject"))
    if not subject_page or subject_page["id"] == center["id"]:
        return None
    subject_anchor = _nearest_anchor_including_self(world, subject_page)
    if not subject_anchor or subject_anchor["id"] == center["id"]:
        return None
    nested_center = _first_nested_anchor_under_center(world, center, subject_anchor)
    if not nested_center:
        return None
    parent_projection = _parent_projection(center, nested_center)
    if not parent_projection:
        return None

    role = str(values.get("subject_role") or values.get("projection_role") or "").strip()
    facet = SUBJECT_ROLE_FACET.get(role)
    local = (
        _projection_from_raw(
            {"facet": facet, "sub_lens": values.get("sub_lens"), "reason": f"subject_role:{role}"},
            page=page,
            center=subject_anchor,
            basis="subject_role",
            subject_center=subject_anchor["id"],
        )
        if facet
        else None
    )
    projected = dict(parent_projection)
    projected["page"] = page["id"]
    projected["basis"] = "subject_nested_center_projection"
    projected["local_quadrant_under_subject"] = str((local or {}).get("quadrant") or "")
    projected["local_facet_under_subject"] = str((local or {}).get("facet") or "")
    projected["local_sub_lens_under_subject"] = str((local or {}).get("sub_lens") or "")
    if local and local.get("reason"):
        projected["reason"] = str(local["reason"])
    return projected


def _page_quadrants(world: BlockWorld, page: dict[str, Any], overrides: dict[str, str]) -> list[str]:
    """The quadrant(s) a page lives in, as facet ids. Multi-quadrant allowed."""
    values = page["values"]
    observed = [v for v in list_values(values.get("observed_quadrants")) if v]
    if observed:
        return [_QUADRANT_FACET.get(v, v) for v in observed if _QUADRANT_FACET.get(v, v) in FACETS]
    declared = _facet_from_quadrant_or_facet(values.get("quadrant"))
    if declared:
        return [declared]
    home = str(values.get("home_quadrant") or "").strip()
    if home:
        facet = home if home in FACETS else _QUADRANT_FACET.get(home, "")
        if facet:
            return [facet]
    if page["page_type"] == "root_entity" and page["moc_parent"].strip():
        # Compatibility for direct classification of the nested root page
        # itself. Descendants now use parent-relative projection below.
        entity_type = str(values.get("root_entity_type") or "").strip()
        facet = (ROOT_ENTITY_TYPE_PARENT_PROJECTION.get(entity_type) or ("", ""))[0]
        if facet:
            return [facet]
    facet = home_quadrant(page["page_type"], overrides)
    if facet:
        return [facet]
    return []


def _sub_lens_for(page: dict[str, Any], quadrant: str) -> str:
    explicit = str(page["values"].get("sub_lens") or "").strip()
    options = SUB_LENSES[quadrant]
    if explicit in options:
        return explicit
    if page["page_type"] == "root_entity":
        entity_type = str(page["values"].get("root_entity_type") or "").strip()
        if entity_type in {"person", "team", "company", "community"} and "pessoas" in options:
            return "pessoas"
    default = SUBLENS_DEFAULT_BY_TYPE.get(page["page_type"])
    if default in options:
        return default
    # skill pages: human = capacidades (q2), agent = automacoes (q4)
    if page["page_type"] == "skill":
        kind = str(page["values"].get("skill_type") or "")
        if kind == "human" and "capacidades" in options:
            return "capacidades"
        if kind == "agent" and "automacoes" in options:
            return "automacoes"
    return options[0]


def _nearest_anchor_including_self(world: BlockWorld, page: dict[str, Any]) -> dict[str, Any] | None:
    if is_anchor_type(world, page["page_type"]):
        return page
    for ancestor in reversed(anchor_chain(world, page)):
        if is_anchor_type(world, ancestor["page_type"]):
            return ancestor
    return None


def _first_nested_anchor_under_center(
    world: BlockWorld,
    center: dict[str, Any],
    page: dict[str, Any],
) -> dict[str, Any] | None:
    chain = anchor_chain(world, page)
    if is_anchor_type(world, page["page_type"]):
        chain.append(page)
    anchor_chain_ids = [
        ancestor["id"] for ancestor in chain if is_anchor_type(world, ancestor["page_type"])
    ]
    if center["id"] not in anchor_chain_ids:
        return None
    center_index = anchor_chain_ids.index(center["id"])
    if center_index >= len(anchor_chain_ids) - 1:
        return None
    next_anchor_id = anchor_chain_ids[center_index + 1]
    return world.by_id.get(next_anchor_id)


def _nearest_parent_anchor(world: BlockWorld, page: dict[str, Any]) -> dict[str, Any] | None:
    for ancestor in reversed(anchor_chain(world, page)):
        if is_anchor_type(world, ancestor["page_type"]):
            return ancestor
    return None


def _parent_projection(
    center: dict[str, Any],
    nested_center: dict[str, Any],
) -> dict[str, Any] | None:
    explicit = _projection_from_raw(
        nested_center["values"].get("parent_projection"),
        page=nested_center,
        center=center,
        basis="parent_projection",
        subject_center=nested_center["id"],
        through_center=nested_center["id"],
    )
    if explicit:
        return explicit
    values = nested_center["values"]
    if nested_center["page_type"] == "root_entity":
        entity_type = str(values.get("root_entity_type") or "").strip()
        default = ROOT_ENTITY_TYPE_PARENT_PROJECTION.get(entity_type)
        if default:
            facet, lens = default
            return _projection_from_raw(
                {
                    "facet": facet,
                    "sub_lens": lens,
                    "reason": f"root_entity_type:{entity_type}",
                },
                page=nested_center,
                center=center,
                basis="parent_projection_default",
                subject_center=nested_center["id"],
                through_center=nested_center["id"],
            )
    default = ANCHOR_TYPE_PARENT_PROJECTION.get(nested_center["page_type"])
    if default:
        facet, lens = default
        return _projection_from_raw(
            {
                "facet": facet,
                "sub_lens": lens,
                "reason": f"anchor_type:{nested_center['page_type']}",
            },
            page=nested_center,
            center=center,
            basis="parent_projection_default",
            subject_center=nested_center["id"],
            through_center=nested_center["id"],
        )
    return None


def _direct_page_projections(
    world: BlockWorld,
    center: dict[str, Any],
    page: dict[str, Any],
    overrides: dict[str, str],
) -> list[dict[str, Any]]:
    explicit = _subject_role_projection(center, page)
    if explicit:
        return [explicit]
    project_role = _project_member_role(center, page)
    if project_role:
        field, facet, sub_lens = project_role
        projected = _projection_from_raw(
            {"facet": facet, "sub_lens": sub_lens, "reason": f"project_field:{field}"},
            page=page,
            center=center,
            basis="project_reference",
            subject_center=center["id"],
        )
        if projected:
            return [projected]
    facets = _page_quadrants(world, page, overrides)
    if not facets:
        edge_facet = _edge_facet(world, page, center)
        facets = [edge_facet] if edge_facet else []
    projections: list[dict[str, Any]] = []
    for facet in facets:
        quadrant = _FACET_QUADRANT.get(facet)
        if not quadrant:
            continue
        projections.append(
            {
                "center": center["id"],
                "page": page["id"],
                "quadrant": quadrant,
                "facet": facet,
                "sub_lens": _sub_lens_for(page, quadrant),
                "basis": "page_semantics",
                "subject_center": center["id"],
                "through_center": "",
                "local_quadrant_under_subject": quadrant,
                "local_facet_under_subject": facet,
                "local_sub_lens_under_subject": _sub_lens_for(page, quadrant),
                "reason": "",
            }
        )
    return projections


def project_quadrants(
    world: BlockWorld,
    center: dict[str, Any],
    page: dict[str, Any],
    overrides: dict[str, str],
) -> list[dict[str, Any]]:
    """Project `page` into quadrants relative to `center`.

    Quadrants are not intrinsic page coordinates. They are a reading of a page
    from an active center. If a page lives under another anchor, the ancestor
    center sees the whole nested center through that center's parent projection,
    while the nested center still classifies its own children locally.
    """
    explicit = _projection_override(world, center, page)
    if explicit:
        return [explicit]

    subject_projection = _subject_nested_center_projection(world, center, page)
    if subject_projection:
        return [subject_projection]

    nested_center = _first_nested_anchor_under_center(world, center, page)
    if nested_center:
        parent_projection = _parent_projection(center, nested_center)
        if parent_projection:
            local = _direct_page_projections(world, nested_center, page, overrides)
            local_first = local[0] if local else None
            projected = dict(parent_projection)
            projected["page"] = page["id"]
            projected["basis"] = (
                "nested_center_self_projection"
                if nested_center["id"] == page["id"]
                else "nested_center_projection"
            )
            projected["local_quadrant_under_subject"] = str((local_first or {}).get("quadrant") or "")
            projected["local_facet_under_subject"] = str((local_first or {}).get("facet") or "")
            projected["local_sub_lens_under_subject"] = str((local_first or {}).get("sub_lens") or "")
            return [projected]

    return _direct_page_projections(world, center, page, overrides)


def _nested_mode(quad_entry: dict[str, Any]) -> str:
    config = dict(quad_entry.get("config") or {})
    mode = str(config.get("nested_mode") or "").strip()
    return mode if mode in NESTED_MODES else "summarize"


def _include_nested_member(
    world: BlockWorld,
    center: dict[str, Any],
    page: dict[str, Any],
    mode: str,
) -> bool:
    if mode == "project_all":
        return True
    nested_center = _first_nested_anchor_under_center(world, center, page)
    if not nested_center:
        return True
    if mode == "hide_nested":
        return False
    # summarize: the parent map shows the nested center as one projected node;
    # the nested center's own descendants appear after entering that center.
    return page["id"] == nested_center["id"]


def quadrant_assignments(
    world: BlockWorld, anchor: dict[str, Any], quad_entry: dict[str, Any]
) -> dict[str, Any]:
    overrides = _home_quadrant_overrides(world)
    scope = str(quad_entry.get("scope") or "descendants")
    mode = _nested_mode(quad_entry)
    members = scope_pages(world, anchor, scope)
    by_quadrant: dict[str, list[str]] = {"q1": [], "q2": [], "q3": [], "q4": [], "q0_core": []}
    sub_lens: dict[str, dict[str, list[str]]] = {q: {} for q in QUADRANT_IDS}
    projections: dict[str, list[dict[str, Any]]] = {}
    for page in members:
        if not _include_nested_member(world, anchor, page, mode):
            continue
        page_projections = project_quadrants(world, anchor, page, overrides)
        if not page_projections:
            by_quadrant["q0_core"].append(page["id"])
            continue
        projections[page["id"]] = page_projections
        for projection in page_projections:
            quad = projection.get("quadrant")
            if quad not in QUADRANT_IDS:
                continue
            by_quadrant[quad].append(page["id"])
            lens = str(projection.get("sub_lens") or _sub_lens_for(page, quad))
            sub_lens[quad].setdefault(lens, []).append(page["id"])
    config = dict(quad_entry.get("config") or {})
    required = [str(q) for q in (config.get("required_quadrants") or list(QUADRANT_IDS))]
    empty = [q for q in required if not by_quadrant.get(q)]
    return {
        "center": anchor["id"],
        "scope": scope,
        "nested_mode": mode,
        "by_quadrant": {k: sorted(set(v)) for k, v in by_quadrant.items()},
        "sub_lens": {q: {k: sorted(set(v)) for k, v in sub_lens[q].items()} for q in QUADRANT_IDS},
        "projections": {
            page_id: sorted(entries, key=lambda item: (item.get("quadrant", ""), item.get("basis", "")))
            for page_id, entries in sorted(projections.items())
        },
        "required_quadrants": required,
        "empty_quadrants": empty,
    }


def _edge_facet(world: BlockWorld, page: dict[str, Any], anchor: dict[str, Any]) -> str | None:
    """The facet implied by how `page` links to `anchor` (source_ref etc.)."""
    source_refs = [
        *list_values(page["values"].get("source_ref")),
        *list_values(page["values"].get("source_refs")),
    ]
    if any(_page_ref_matches(ref, anchor) for ref in source_refs):
        return facet_of(page["page_type"], "source_ref")
    return facet_of(page["page_type"], None)


# --- Relations (the Q3 rede sub-lens, operationalized) ----------------------

_INTERACTION_TYPES = frozenset({"meeting", "journal_entry", "ingestion_event"})


def _parse_date(value: str) -> dt.date | None:
    value = str(value).strip()
    for fmt in ("%Y-%m-%d", "%m-%d"):
        try:
            parsed = dt.datetime.strptime(value, fmt).date()
            if fmt == "%m-%d":
                return parsed.replace(year=dt.date.today().year)
            return parsed
        except ValueError:
            continue
    return None


def _last_interaction(world: BlockWorld, person: dict[str, Any]) -> str:
    """Most recent updated_at among pages that link the person (meeting/journal/
    event). Derived from the graph — interaction is not a new store."""
    node = world.graph.nodes.get(person["path"])
    latest = person["updated_at"]
    if node is not None:
        for rel in node.inbound_links:
            linker = world.by_path.get(rel)
            if linker and linker["page_type"] in _INTERACTION_TYPES:
                if linker["updated_at"] > latest:
                    latest = linker["updated_at"]
    return latest


def relations_derived(world: BlockWorld, anchor: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    scope = str(entry.get("scope") or "descendants")
    people = [
        p
        for p in scope_pages(world, anchor, scope)
        if p["page_type"] == "person"
        or (p["page_type"] == "root_entity" and str(p["values"].get("root_entity_type") or "") == "person")
    ]
    due: list[dict[str, Any]] = []
    upcoming: list[dict[str, Any]] = []
    commitments: list[dict[str, Any]] = []
    for person in people:
        values = person["values"]
        relationship = values.get("relationship") if isinstance(values.get("relationship"), dict) else {}
        cadence = relationship.get("contact_cadence_days")
        last = _last_interaction(world, person)
        last_date = _parse_date(last)
        next_due_days: int | None = None
        if cadence and last_date:
            try:
                next_due = last_date + dt.timedelta(days=int(cadence))
                next_due_days = (next_due - world.today).days
            except (TypeError, ValueError):
                next_due_days = None
        if next_due_days is not None and next_due_days < 0:
            due.append(
                {
                    "person": person["id"],
                    "title": person["title"],
                    "relationship_kind": str(relationship.get("kind") or ""),
                    "last_interaction": last,
                    "overdue_days": -next_due_days,
                }
            )
        for date_entry in values.get("dates") or []:
            if not isinstance(date_entry, dict):
                continue
            date = _parse_date(str(date_entry.get("date") or ""))
            if date is None:
                continue
            days_until = (date - world.today).days
            if 0 <= days_until <= 30:
                upcoming.append(
                    {
                        "person": person["id"],
                        "title": person["title"],
                        "kind": str(date_entry.get("kind") or ""),
                        "in_days": days_until,
                    }
                )
        for commitment in values.get("commitments") or []:
            if not isinstance(commitment, dict):
                continue
            due_date = _parse_date(str(commitment.get("due") or ""))
            days_left = (due_date - world.today).days if due_date else None
            if days_left is not None and days_left <= 7:
                commitments.append(
                    {
                        "person": person["id"],
                        "title": person["title"],
                        "ref": str(commitment.get("ref") or ""),
                        "days_left": days_left,
                    }
                )
    return {
        "due": sorted(due, key=lambda item: -item["overdue_days"]),
        "upcoming_dates": sorted(upcoming, key=lambda item: item["in_days"]),
        "open_commitments": sorted(commitments, key=lambda item: item["days_left"]),
    }


# --- Subpages ---------------------------------------------------------------


def missing_subpages(world: BlockWorld, anchor: dict[str, Any]) -> list[dict[str, Any]]:
    spec = world.registry.resolve(anchor["page_type"])
    missing: list[dict[str, Any]] = []
    for sub in spec.subpages:
        if not sub.get("required"):
            continue
        rel = str(sub.get("rel") or "")
        # Present if the anchor declares the rel in frontmatter, OR a child of the
        # declared page_type exists below it.
        declared = str(anchor["values"].get(rel) or "").strip()
        has_child = any(
            child["page_type"] == sub.get("page_type")
            for child_id in world.children.get(anchor["path"], []) + world.children.get(anchor["id"], [])
            for child in [world.by_id.get(child_id)]
            if child
        )
        if not declared and not has_child:
            missing.append({"rel": rel, "page_type": str(sub.get("page_type") or ""), "slug": str(sub.get("slug") or "")})
    return missing


# --- Interface & identity ---------------------------------------------------


def _block_config(entry: dict[str, Any] | None) -> dict[str, Any]:
    return dict((entry or {}).get("config") or {})


def _merge_visual_pack(pack_id: str, packs: dict[str, dict[str, Any]], seen: set[str] | None = None) -> dict[str, Any]:
    seen = seen or set()
    if pack_id in seen:
        return {"slots": {}}
    seen.add(pack_id)
    pack = packs.get(pack_id) or {}
    base_id = str(pack.get("extends") or "").strip()
    merged = _merge_visual_pack(base_id, packs, seen) if base_id else {"slots": {}}
    slots = dict(merged.get("slots") or {})
    slots.update({str(k): str(v) for k, v in dict(pack.get("slots") or {}).items()})
    result = dict(pack)
    result["slots"] = slots
    if base_id:
        result["extends"] = base_id
    return result


def _configured_visual_packs(*configs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    packs = {key: dict(value) for key, value in DEFAULT_VISUAL_PACKS.items()}
    for cfg in configs:
        raw = cfg.get("packs")
        if not isinstance(raw, dict):
            continue
        for pack_id, definition in raw.items():
            if isinstance(definition, dict):
                base = dict(packs.get(str(pack_id), {}))
                base.update(definition)
                packs[str(pack_id)] = base
    return {pack_id: _merge_visual_pack(pack_id, packs) for pack_id in sorted(packs)}


def resolve_visual_grammar(world: BlockWorld, anchor: dict[str, Any], stack: list[dict[str, Any]]) -> dict[str, Any]:
    quad = _stack_block(stack, "wiki.block.quadrants")
    regions_entry = _stack_block(stack, "wiki.block.ui_regions")
    grammar_entry = _stack_block(stack, "wiki.block.visual_grammar")
    if quad is None and regions_entry is None and grammar_entry is None:
        return {}
    regions_cfg = _block_config(regions_entry)
    grammar_cfg = _block_config(grammar_entry)
    default_pack = str(
        regions_cfg.get("visual_pack")
        or grammar_cfg.get("default_pack")
        or grammar_cfg.get("visual_pack")
        or "region_operations"
    )
    if default_pack not in VISUAL_PRIMITIVE_PACKS:
        default_pack = "region_operations"
    packs = _configured_visual_packs(grammar_cfg, regions_cfg)
    allowed = [str(item) for item in regions_cfg.get("allowed_packs") or grammar_cfg.get("allowed_packs") or sorted(VISUAL_PRIMITIVE_PACKS)]
    allowed = [item for item in allowed if item in VISUAL_PRIMITIVE_PACKS]
    if default_pack not in allowed:
        allowed.insert(0, default_pack)
    resolved_packs = {pack_id: packs[pack_id] for pack_id in sorted(packs) if pack_id in allowed}
    return {
        "schema_version": VISUAL_GRAMMAR_SCHEMA_VERSION,
        "default_pack": default_pack,
        "allowed_packs": allowed,
        "packs": resolved_packs,
        "primitive_purpose": {key: VISUAL_PRIMITIVE_PURPOSES[key] for key in sorted(VISUAL_PRIMITIVES)},
    }


def resolve_interface(world: BlockWorld, anchor: dict[str, Any], stack: list[dict[str, Any]]) -> dict[str, Any]:
    quad = _stack_block(stack, "wiki.block.quadrants")
    relations = _stack_block(stack, "wiki.block.relations")
    has_quadrants = quad is not None
    regions_entry = _stack_block(stack, "wiki.block.ui_regions")
    visual_grammar = resolve_visual_grammar(world, anchor, stack)

    # views: the home view comes from the stack — quadrants ONLY when the
    # quadrants block is attached; a bare root reads as a radar. The DEFAULT
    # offer is deliberately small (home + atlas + focus): radar/districts/
    # trails exist in the vocabulary but a wiki opts INTO them via config —
    # a view that has no purpose yet has no button.
    views_entry = _stack_block(stack, "wiki.block.ui_views")
    views_cfg = _block_config(views_entry)
    default_view = str(views_cfg.get("default") or ("quadrants" if has_quadrants else "radar"))
    default_available = [default_view, "atlas", "focus"]
    available = [str(v) for v in (views_cfg.get("available") or default_available)]
    if not has_quadrants:
        available = [v for v in available if v != "quadrants"]
        if default_view == "quadrants":
            default_view = "radar"
    if default_view not in available:
        available.insert(0, default_view)

    # missions: the surface exists only when ui_missions is in the stack (the
    # gamification package). Providers = explicit config, else the block's
    # declared defaults, plus whatever interpretation blocks contribute.
    missions_entry = _stack_block(stack, "wiki.block.ui_missions")
    missions_cfg = _block_config(missions_entry)
    missions_active = missions_entry is not None
    default_providers: list[str] = []
    if missions_entry is not None:
        definition = world.blocks.get(missions_entry["id"]) or {}
        default_providers = list((definition.get("defaults") or {}).get("providers") or [])
    providers = list(missions_cfg.get("providers") or default_providers)
    if missions_active:
        for entry in stack:
            definition = world.blocks.get(entry["id"]) or {}
            for prov in (definition.get("contributes") or {}).get("missions_providers") or []:
                if prov not in providers:
                    providers.append(prov)
    else:
        providers = []
    providers = [p for p in providers if p in MISSION_PROVIDERS]

    # create
    create_entry = _stack_block(stack, "wiki.block.ui_create")
    create_cfg = _block_config(create_entry)
    arrangement = str(create_cfg.get("arrangement") or ("by_quadrant" if has_quadrants else "by_family"))
    if arrangement == "by_quadrant" and not has_quadrants:
        arrangement = "by_family"
    obligations = missing_subpages(world, anchor)

    # intake: config forms + contributed forms
    intake_entry = _stack_block(stack, "wiki.block.ui_intake")
    intake_cfg = _block_config(intake_entry)
    forms = list(intake_cfg.get("forms") or [])
    for entry in stack:
        definition = world.blocks.get(entry["id"]) or {}
        for form in (definition.get("contributes") or {}).get("intake_forms") or []:
            if form not in forms:
                forms.append(form)
    forms = [f for f in forms if f in INTAKE_FORMS]

    # score
    score_entry = _stack_block(stack, "wiki.block.gamification")
    score_cfg = _block_config(score_entry)
    loops = [loop for loop in (score_cfg.get("loops") or []) if loop in SCORE_LOOPS]

    return {
        "views": {"available": available, "default": default_view},
        "missions": {
            "active": missions_active,
            "providers": providers,
            "weather_contrib": bool(missions_cfg.get("weather_contrib", True)) and missions_active,
            "quiet": bool(missions_cfg.get("quiet", False)),
        },
        "create": {
            "catalog": [str(t) for t in (create_cfg.get("catalog") or [])],
            "arrangement": arrangement,
            "obligations_first": bool(create_cfg.get("obligations_first", True)),
            "obligations": obligations,
            "disabled_reason": str(create_cfg.get("disabled_reason") or ""),
        },
        "intake": {"forms": forms},
        "score": {"loops": loops, "no_leaderboard": True},
        "regions": {
            "active": regions_entry is not None or has_quadrants,
            "visual_pack": visual_grammar.get("default_pack") or "region_operations",
        },
        "has_quadrants": has_quadrants,
        "has_relations": relations is not None,
    }


def resolve_identity(world: BlockWorld, anchor: dict[str, Any]) -> dict[str, Any]:
    spec = world.registry.resolve(anchor["page_type"])
    identity = dict(spec.identity)
    # A page may declare its own identity (an area's landmark), which wins over
    # the type default — this is how one root_entity type shows as an observatory
    # while a team holon shows as a plaza, without a new page type per flavor.
    page_identity = anchor["values"].get("identity")
    if isinstance(page_identity, dict):
        identity = {**identity, **page_identity}
    horizon = str(identity.get("horizon_label") or "title")
    horizon_text = anchor["context"] if horizon == "context" else anchor["title"]
    return {
        "landmark": str(identity.get("landmark") or ""),
        "motif": str(identity.get("motif") or "none"),
        "ambient": str(identity.get("ambient") or "none"),
        "horizon_label": horizon,
        "horizon_text": horizon_text,
        "context": anchor["context"],
    }


# --- Derived outputs & per-anchor record ------------------------------------


PAGE_TYPE_FAMILIES = {
    "root_index": "root",
    "root_entity": "root",
    "context_hub": "hub",
    "ontology_index": "hub",
    "source_catalog": "hub",
    "relationship_map": "hub",
    "source": "source",
    "source_config": "source",
    "source_registry": "source",
    "input_channel": "source",
    "input_stage": "source",
    "decision": "decision",
    "claim": "decision",
    "action": "action",
    "process": "action",
    "operational_rule": "rule",
    "dashboard": "rule",
    "system_log": "rule",
    "methodology_plan": "rule",
    "template_block": "rule",
    "ingestion_event": "event",
    "journal_entry": "event",
    "meeting": "event",
    "proposal": "event",
    "person": "person",
    "role": "person",
    "responsibility": "person",
}
RAW_PAGE_TYPES = {"source", "source_config", "source_registry", "input_channel", "input_stage", "ingestion_event"}


def _page_family(page: dict[str, Any]) -> str:
    return PAGE_TYPE_FAMILIES.get(page["page_type"], "content")


def _page_freshness(page: dict[str, Any], world: BlockWorld) -> str:
    values = page["values"]
    return freshness_state(
        values.get("updated_at") or values.get("date"),
        values.get("stale_after_days"),
        world.today,
        stale_exempt=is_stale_exempt(values.get("stale_exempt")),
    )


def _page_is_proposal(page: dict[str, Any]) -> bool:
    status = str(page["values"].get("status") or "").lower()
    return page["page_type"] == "proposal" or status in {"proposal", "draft", "proposed", "pending_review"}


def _page_has_risk(page: dict[str, Any]) -> bool:
    return bool(list_values(page["values"].get("risk_flags")) or list_values(page["values"].get("risks")))


def _page_is_open_action(page: dict[str, Any]) -> bool:
    if page["page_type"] != "action":
        return False
    return not resolve_action_state(
        page["values"],
        legacy_state=legacy_action_state_from_body(str(page.get("body") or "")),
    ).terminal


REGION_PREVIEW_LIMIT = 40


def _summary_for_pages(world: BlockWorld, pages: list[dict[str, Any]]) -> dict[str, int]:
    total = len(pages)
    shown = min(total, REGION_PREVIEW_LIMIT)
    stale = sum(1 for page in pages if _page_freshness(page, world) == "stale")
    raw = sum(1 for page in pages if page["page_type"] in RAW_PAGE_TYPES)
    source_backed = sum(1 for page in pages if list_values(page["values"].get("source_refs")))
    unsourced = sum(
        1
        for page in pages
        if page["page_type"] in {"claim", "decision", "methodology_plan"} and not list_values(page["values"].get("source_refs"))
    )
    return {
        "total": total,
        "shown": shown,
        "hidden": total - shown,
        "stale": stale,
        "proposal": sum(1 for page in pages if _page_is_proposal(page)),
        "risk": sum(1 for page in pages if _page_has_risk(page)),
        "raw": raw,
        "unsourced": unsourced,
        "open_actions": sum(1 for page in pages if _page_is_open_action(page)),
        "source_backed": source_backed,
    }


def _type_mix(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[tuple[str, str], int] = {}
    for page in pages:
        key = (page["page_type"], _page_family(page))
        counts[key] = counts.get(key, 0) + 1
    return [
        {"page_type": page_type, "family": family, "count": count}
        for (page_type, family), count in sorted(counts.items(), key=lambda item: (-item[1], item[0][1], item[0][0]))
    ]


def _attention_hints(summary: dict[str, int]) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    for kind, key in (
        ("risk", "risk"),
        ("proposal", "proposal"),
        ("stale", "stale"),
        ("unsourced", "unsourced"),
        ("raw", "raw"),
        ("hidden", "hidden"),
    ):
        count = int(summary.get(key) or 0)
        if count > 0:
            hints.append({"kind": kind, "count": count})
    return hints


def _action_hints(summary: dict[str, int]) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    if summary["open_actions"] > 0:
        hints.append({"kind": "review", "label_key": "region.action.review", "count": summary["open_actions"]})
    if summary["stale"] > 0:
        hints.append({"kind": "refresh", "label_key": "region.action.refresh", "count": summary["stale"]})
    if summary["unsourced"] > 0:
        hints.append({"kind": "add_evidence", "label_key": "region.action.addEvidence", "count": summary["unsourced"]})
    if summary["raw"] > 0:
        hints.append({"kind": "inspect_sources", "label_key": "region.action.inspectSources", "count": summary["raw"]})
    return hints


def _visual_config_errors(label: str, config: Any) -> list[str]:
    if not isinstance(config, dict):
        return []
    errors: list[str] = []
    for key in ("visual_pack", "default_pack"):
        value = config.get(key)
        if value is not None and str(value) not in VISUAL_PRIMITIVE_PACKS:
            errors.append(f"{label}: unknown visual pack `{value}` (use {sorted(VISUAL_PRIMITIVE_PACKS)})")
    for pack_id in config.get("allowed_packs") or []:
        if str(pack_id) not in VISUAL_PRIMITIVE_PACKS:
            errors.append(f"{label}: unknown allowed visual pack `{pack_id}`")
    raw_packs = config.get("packs")
    if isinstance(raw_packs, dict):
        for pack_id, pack in raw_packs.items():
            if str(pack_id) not in VISUAL_PRIMITIVE_PACKS:
                errors.append(f"{label}: unknown visual pack `{pack_id}`")
            if not isinstance(pack, dict):
                continue
            extends = pack.get("extends")
            if extends is not None and str(extends) not in VISUAL_PRIMITIVE_PACKS:
                errors.append(f"{label}: visual pack `{pack_id}` extends unknown pack `{extends}`")
            for slot, primitive in dict(pack.get("slots") or {}).items():
                if str(slot) not in VISUAL_PRIMITIVE_SLOTS:
                    errors.append(f"{label}: unknown visual primitive slot `{slot}`")
                if str(primitive) not in VISUAL_PRIMITIVES:
                    errors.append(f"{label}: unknown visual primitive `{primitive}`")
    return errors


def region_groups_derived(
    world: BlockWorld,
    anchor: dict[str, Any],
    assignments: dict[str, Any],
    visual_grammar: dict[str, Any],
) -> dict[str, Any]:
    default_pack = str(visual_grammar.get("default_pack") or "region_operations")
    quadrant_labels = {"q1": "intencao", "q2": "pratica", "q3": "relacoes", "q4": "sistemas"}
    groups: list[dict[str, Any]] = []
    by_quadrant = assignments.get("by_quadrant") or {}
    for quadrant in ("q1", "q2", "q3", "q4"):
        ids = [page_id for page_id in by_quadrant.get(quadrant, []) if page_id != anchor["id"]]
        pages = [world.by_id[page_id] for page_id in ids if page_id in world.by_id]
        summary = _summary_for_pages(world, pages)
        label = quadrant_labels[quadrant]
        pack = "evidence_first" if summary["raw"] or summary["unsourced"] else "review_first" if summary["proposal"] else default_pack
        groups.append(
            {
                "id": f"quadrant:{label}",
                "kind": "quadrant",
                "label_key": label,
                "purpose": "act" if summary["open_actions"] else "verify" if summary["stale"] or summary["unsourced"] else "navigate",
                "visual_role": "quadrant",
                "member_ids": ids,
                "summary": summary,
                "type_mix": _type_mix(pages),
                "attention_hints": _attention_hints(summary),
                "action_hints": _action_hints(summary),
                "visual": {
                    "grammar_id": visual_grammar.get("schema_version") or VISUAL_GRAMMAR_SCHEMA_VERSION,
                    "pack_id": pack if pack in VISUAL_PRIMITIVE_PACKS else default_pack,
                    "slots": dict((visual_grammar.get("packs") or {}).get(pack, {}).get("slots") or {}),
                    "emphasis": [
                        label
                        for label, active in (
                            ("attention", bool(summary["stale"] or summary["risk"] or summary["proposal"] or summary["unsourced"])),
                            ("healthy", not bool(summary["stale"] or summary["risk"] or summary["proposal"] or summary["unsourced"])),
                        )
                        if active
                    ],
                },
            }
        )
    core_ids = [page_id for page_id in by_quadrant.get("q0_core", []) if page_id != anchor["id"]]
    if core_ids:
        pages = [world.by_id[page_id] for page_id in core_ids if page_id in world.by_id]
        summary = _summary_for_pages(world, pages)
        groups.append(
            {
                "id": "core:q0",
                "kind": "core",
                "label_key": "core",
                "purpose": "understand",
                "visual_role": "core",
                "member_ids": core_ids,
                "summary": summary,
                "type_mix": _type_mix(pages),
                "attention_hints": _attention_hints(summary),
                "action_hints": [{"kind": "open_blocks", "label_key": "region.action.openBlocks", "count": summary["total"]}],
                "visual": {
                    "grammar_id": visual_grammar.get("schema_version") or VISUAL_GRAMMAR_SCHEMA_VERSION,
                    "pack_id": "quiet_structure",
                    "slots": dict((visual_grammar.get("packs") or {}).get("quiet_structure", {}).get("slots") or {}),
                    "emphasis": ["attention"] if summary["total"] > 0 else ["muted"],
                },
            }
        )
    return {"schema_version": "wiki.region_groups.v1", "anchor": anchor["id"], "groups": groups}


def derived_outputs(world: BlockWorld, anchor: dict[str, Any], stack: list[dict[str, Any]]) -> dict[str, Any]:
    derived: dict[str, Any] = {"missions": [], "warnings": []}
    quad = _stack_block(stack, "wiki.block.quadrants")
    visual_grammar = resolve_visual_grammar(world, anchor, stack)
    if quad is not None:
        assignments = quadrant_assignments(world, anchor, quad)
        derived["quadrant_assignments"] = assignments["by_quadrant"]
        derived["quadrant_projections"] = assignments["projections"]
        derived["quadrant_sub_lens"] = assignments["sub_lens"]
        derived["quadrant_nested_mode"] = assignments["nested_mode"]
        derived["empty_quadrants"] = assignments["empty_quadrants"]
        derived["region_groups"] = region_groups_derived(world, anchor, assignments, visual_grammar)
        for quadrant in assignments["empty_quadrants"]:
            derived["missions"].append(
                {
                    "provider": "quadrant_absence",
                    "quadrant": quadrant,
                    "anchor": anchor["id"],
                }
            )
    relations = _stack_block(stack, "wiki.block.relations")
    if relations is not None:
        rel = relations_derived(world, anchor, relations)
        derived["relations"] = rel
        for item in rel["due"]:
            derived["missions"].append(
                {"provider": "relation_cadence_overdue", "person": item["person"], "anchor": anchor["id"]}
            )
        for item in rel["upcoming_dates"]:
            derived["missions"].append(
                {"provider": "date_upcoming", "person": item["person"], "anchor": anchor["id"]}
            )
        for item in rel["open_commitments"]:
            derived["missions"].append(
                {"provider": "commitment_open", "person": item["person"], "anchor": anchor["id"]}
            )
    missing = missing_subpages(world, anchor)
    if missing:
        derived["missing_subpages"] = missing
        for sub in missing:
            derived["missions"].append(
                {"provider": "template_conformity", "rel": sub["rel"], "anchor": anchor["id"]}
            )
    return derived


def anchor_record(world: BlockWorld, anchor: dict[str, Any]) -> dict[str, Any]:
    stack = resolve_stack(world, anchor)
    return {
        "stack": stack,
        "interface": resolve_interface(world, anchor, stack),
        "identity": resolve_identity(world, anchor),
        "visual_grammar": resolve_visual_grammar(world, anchor, stack),
        "derived": derived_outputs(world, anchor, stack),
    }


def build_anchor_tree(world: BlockWorld) -> dict[str, Any]:
    records: dict[str, dict[str, Any]] = {}
    for page in world.pages:
        if not is_anchor_type(world, page["page_type"]):
            continue
        parent = _nearest_parent_anchor(world, page)
        records[page["id"]] = {
            "id": page["id"],
            "path": page["path"],
            "title": page["title"],
            "page_type": page["page_type"],
            "parent": parent["id"] if parent else "",
            "children": [],
        }
    for record in records.values():
        parent_id = record["parent"]
        if parent_id and parent_id in records:
            records[parent_id]["children"].append(record["id"])
    for record in records.values():
        record["children"] = sorted(set(record["children"]))
    return {
        "roots": sorted(record["id"] for record in records.values() if not record["parent"]),
        "nodes": dict(sorted(records.items())),
    }


# --- Validation -------------------------------------------------------------


def validate_blocks(world: BlockWorld) -> list[str]:
    """WARN-first: an unknown surface/provider/landmark is an authoring mistake,
    not data corruption. Returns human-readable strings for the audit gate."""
    errors: list[str] = []
    collection_defaults = {
        page_type: dict(world.registry.resolve(page_type).collection)
        for page_type in world.registry.raw_types
        if world.registry.resolve(page_type).collection
    }
    for diagnostic in collection_reference_diagnostics(
        world.pages, defaults_by_type=collection_defaults
    ):
        errors.append(
            f"page `{diagnostic['page_id']}`: {diagnostic['field']} references "
            f"missing page `{diagnostic['ref']}`"
        )
    for diagnostic in collection_cycle_diagnostics(
        world.pages,
        defaults_by_type=collection_defaults,
        allows_cycles=False,
    ):
        edge_details = "; ".join(
            f"{edge['member']} -> {edge['collection']} via {edge['basis']} "
            f"declared by {edge['declaration_page']} ({edge['origin']})"
            for edge in diagnostic["cycle_edges"]
        )
        errors.append(
            "collection cycle is forbidden: "
            f"{diagnostic['cycle_path_text']}; remove or narrow one declared "
            f"membership edge: {edge_details}"
        )
    for page in world.pages:
        for problem in validate_collection_declaration(page):
            errors.append(f"page `{page['id']}`: {problem}")
        declared_collection = page["values"].get("collection")
        if isinstance(declared_collection, dict):
            if not is_anchor_type(world, page["page_type"]):
                errors.append(
                    f"page `{page['id']}`: collection requires a block-anchor page type"
                )
            for member_type in declared_collection.get("member_types") or []:
                if str(member_type) not in world.registry.raw_types:
                    errors.append(
                        f"page `{page['id']}`: collection references unknown member type `{member_type}`"
                    )
            known_contexts = set(world.config.contexts)
            for context in declared_collection.get("contexts") or []:
                if str(context) != "*" and str(context) not in known_contexts:
                    errors.append(
                        f"page `{page['id']}`: collection references unknown context `{context}`"
                    )
            merged_collection = collection_spec(
                page, world.registry.resolve(page["page_type"]).collection
            )
            inbound_collection_refs = any(
                candidate["id"] != page["id"]
                and any(
                    ref in {page["id"], page["path"]}
                    for ref in member_collection_refs(candidate)
                )
                for candidate in world.pages
            )
            if not (
                merged_collection["member_types"]
                or merged_collection["members"]
                or inbound_collection_refs
            ):
                errors.append(
                    f"page `{page['id']}`: collection has no member selector or inbound collection_refs"
                )
        for ref in member_collection_refs(page):
            target = world.by_id.get(ref) or world.by_path.get(ref)
            if target is not None and not is_anchor_type(world, target["page_type"]):
                errors.append(
                    f"page `{page['id']}`: collection_refs target `{ref}` is not a block anchor"
                )
    for block_id, definition in sorted(world.blocks.items()):
        kind = str(definition.get("kind") or "")
        if kind not in BLOCK_KINDS:
            errors.append(f"block `{block_id}`: unknown kind `{kind}` (use {sorted(BLOCK_KINDS)})")
        scope = (definition.get("scope") or {}).get("default_mode")
        if scope is not None and scope not in SCOPE_MODES:
            errors.append(f"block `{block_id}`: unknown scope mode `{scope}`")
        errors.extend(
            _collection_scope_instance_errors(f"block `{block_id}`", definition)
        )
        for anchor_type in definition.get("anchors") or []:
            if anchor_type not in world.registry.raw_types:
                errors.append(f"block `{block_id}`: anchors unknown page type `{anchor_type}`")
        if kind == "interface":
            surface = str(definition.get("surface") or "")
            if surface not in SURFACES:
                errors.append(f"block `{block_id}`: unknown surface `{surface}` (use {sorted(SURFACES)})")
            if surface == "score":
                nl = (definition.get("config_schema") or {}).get("no_leaderboard")
                if isinstance(nl, dict) and nl.get("const") is not True:
                    errors.append(f"block `{block_id}`: no_leaderboard must be const true")
        profile = definition.get("scene_profile") or {}
        layout = profile.get("layout")
        if layout not in (None, "null") and layout not in SCENE_LAYOUTS:
            errors.append(f"block `{block_id}`: unknown scene layout `{layout}`")
        for overlay in profile.get("overlays") or []:
            if overlay not in SCENE_OVERLAYS:
                errors.append(f"block `{block_id}`: unknown overlay `{overlay}`")
        errors.extend(_visual_config_errors(f"block `{block_id}`", definition.get("config")))
    # Identity vocabulary on types.
    for page_type in world.registry.raw_types:
        spec = world.registry.resolve(page_type)
        identity = spec.identity
        if identity:
            if identity.get("landmark") and identity["landmark"] not in IDENTITY_LANDMARKS:
                errors.append(f"type `{page_type}`: unknown identity landmark `{identity['landmark']}`")
            if identity.get("motif") and identity["motif"] not in IDENTITY_MOTIFS:
                errors.append(f"type `{page_type}`: unknown identity motif `{identity['motif']}`")
            if identity.get("ambient") and identity["ambient"] not in IDENTITY_AMBIENTS:
                errors.append(f"type `{page_type}`: unknown identity ambient `{identity['ambient']}`")
        for inst in _block_instances(list(spec.blocks)):
            if inst["id"] not in world.blocks:
                errors.append(
                    f"type `{page_type}`: references unknown block `{inst['id']}`"
                )
            errors.extend(
                _collection_scope_instance_errors(
                    f"type `{page_type}` block `{inst['id']}`", inst
                )
            )
    # Packages: every block a package groups must exist.
    for name, package in sorted(world.registry.raw_packages.items()):
        for inst in _block_instances(package.get("blocks")):
            if inst["id"] not in world.blocks:
                errors.append(f"package `{name}`: groups unknown block `{inst['id']}`")
    # Pages that attach blocks/packages: must be anchor types, must reference
    # known blocks/packages.
    for page in world.pages:
        instances = _block_instances(page["values"].get("blocks"))
        raw_packages = page["values"].get("packages")
        package_names = [
            entry if isinstance(entry, str) else str((entry or {}).get("id") or "")
            for entry in (raw_packages if isinstance(raw_packages, list) else [])
        ]
        if not instances and not package_names:
            continue
        if not is_anchor_type(world, page["page_type"]):
            errors.append(
                f"page `{page['id']}`: page_type `{page['page_type']}` cannot anchor blocks "
                f"(needs can_anchor_blocks: true)"
            )
        for inst in instances:
            if inst["id"] not in world.blocks:
                errors.append(f"page `{page['id']}`: references unknown block `{inst['id']}`")
            errors.extend(
                _collection_scope_instance_errors(
                    f"page `{page['id']}` block `{inst['id']}`", inst
                )
            )
            errors.extend(_visual_config_errors(f"page `{page['id']}` block `{inst['id']}`", inst.get("config")))
        for name in package_names:
            if name and name not in world.registry.raw_packages:
                errors.append(f"page `{page['id']}`: references unknown package `{name}`")
    return errors


# --- LLM package & interview spec (used by F4 / F6) -------------------------


def block_context_package(world: BlockWorld, anchor: dict[str, Any]) -> dict[str, Any]:
    """The stack + resolved lenses handed to the deep-read agent. Read-only."""
    stack = resolve_stack(world, anchor)
    contract = quadrant_contract(world.config.language)
    lens_entries: list[dict[str, Any]] = []
    quad = _stack_block(stack, "wiki.block.quadrants")
    if quad is not None:
        definition = world.blocks.get(quad["id"]) or {}
        perspectives = definition.get("perspectives") or {q: DEFAULT_QUADRANT_MAP.get(q, []) for q in QUADRANT_IDS}
        labels = dict((quad.get("config") or {}).get("labels") or {})
        contract_quadrants = contract.get("quadrants", {})
        lenses: dict[str, Any] = {}
        for quadrant in QUADRANT_IDS:
            info = contract_quadrants.get(quadrant, {}) if isinstance(contract_quadrants, dict) else {}
            lenses[quadrant] = {
                "label": labels.get(quadrant) or info.get("label") or quadrant,
                "operational_test": info.get("operational_test") or "",
                "perspective": perspectives.get(quadrant),
                "sub_lenses": list(SUB_LENSES[quadrant]),
            }
        lens_entries.append(
            {"id": quad["id"], "origin": quad["origin"], "lenses": lenses, "boundary_rule": contract.get("boundary_rule", "")}
        )
    write_policy = "proposal_branch_only"
    gate = _stack_block(stack, "wiki.block.git_human_gate")
    obligations = [
        {"target_page": world.config.paths.get("operation_page", "memories/operations.md"), "obligation": "update_or_no_change_reason"}
    ]
    return {
        "schema_version": "wiki_block_stack.v1",
        "center": anchor["id"],
        "stack": [
            {"id": entry["id"], "origin": entry["origin"], "scope": entry["scope"], "kind": entry["kind"]}
            for entry in stack
        ],
        "lenses": lens_entries,
        "write_policy": write_policy if gate is not None else write_policy,
        "target_obligations": obligations,
    }


def interview_spec(world: BlockWorld, page_type: str) -> dict[str, Any]:
    """Derive the questions to fill a page of `page_type` — one source, rendered
    as form / wizard / interview. From pinned fields + block config schemas."""
    spec = world.registry.resolve(page_type)
    questions: list[dict[str, Any]] = []
    seen: set[str] = set()
    if not str(spec.body_template):
        pass
    for facet in FACETS:
        for field_name in spec.facets.get(facet, ()):  # type: ignore[union-attr]
            if field_name in seen:
                continue
            seen.add(field_name)
            questions.append({"field": field_name, "kind": "text", "facet": facet, "optional": True})
    for field_name in spec.pinned_fields:
        if field_name in seen:
            continue
        seen.add(field_name)
        questions.append({"field": field_name, "kind": "text", "optional": False})
    for inst in _block_instances(list(spec.blocks)):
        definition = world.blocks.get(str(inst["id"])) or {}
        schema = definition.get("config_schema") or {}
        for key, kind in schema.items():
            if key in seen:
                continue
            seen.add(key)
            questions.append({"field": key, "kind": "choice" if isinstance(kind, str) and kind.startswith("enum") else "text", "optional": True})
    return {"schema_version": "wiki_interview_spec.v1", "page_type": page_type, "questions": questions}


# --- Snapshot payloads ------------------------------------------------------


def build_blocks_payload(world: BlockWorld) -> dict[str, Any]:
    blocks: dict[str, Any] = {}
    for block_id, definition in sorted(world.blocks.items()):
        record = dict(definition)
        record["origin"] = world.block_origin.get(block_id, "registry")
        blocks[block_id] = record
    return {
        "schema_version": BLOCKS_SCHEMA_VERSION,
        "vocabulary": {
            "block_kinds": sorted(BLOCK_KINDS),
            "scope_modes": sorted(SCOPE_MODES),
            "nested_modes": sorted(NESTED_MODES),
            "surfaces": sorted(SURFACES),
            "mission_providers": sorted(MISSION_PROVIDERS),
            "intake_forms": sorted(INTAKE_FORMS),
            "score_loops": sorted(SCORE_LOOPS),
            "scene_layouts": sorted(SCENE_LAYOUTS),
            "scene_overlays": sorted(SCENE_OVERLAYS),
            "identity_landmarks": sorted(IDENTITY_LANDMARKS),
            "identity_motifs": sorted(IDENTITY_MOTIFS),
            "identity_ambients": sorted(IDENTITY_AMBIENTS),
            "visual_primitives": sorted(VISUAL_PRIMITIVES),
            "visual_primitive_slots": sorted(VISUAL_PRIMITIVE_SLOTS),
            "visual_primitive_packs": sorted(VISUAL_PRIMITIVE_PACKS),
            "sub_lenses": {q: list(SUB_LENSES[q]) for q in QUADRANT_IDS},
        },
        "blocks": blocks,
        "packages": {
            name: {
                "title": str(package.get("title") or name),
                "summary": str(package.get("summary") or ""),
                "blocks": [inst["id"] for inst in _block_instances(package.get("blocks"))],
            }
            for name, package in sorted(world.registry.raw_packages.items())
        },
        "warnings": validate_blocks(world),
    }


def build_block_stacks_payload(world: BlockWorld) -> dict[str, Any]:
    anchors: dict[str, Any] = {}
    for page in world.pages:
        if not is_anchor_type(world, page["page_type"]):
            continue
        anchors[page["id"]] = anchor_record(world, page)
    return {
        "schema_version": BLOCK_STACKS_SCHEMA_VERSION,
        "anchor_tree": build_anchor_tree(world),
        "anchors": dict(sorted(anchors.items())),
    }


def blocks_payloads(
    root: Path,
    config: WikiConfig | None = None,
    *,
    pages: list[dict[str, Any]] | None = None,
    graph: PageGraph | None = None,
    today: dt.date | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Convenience: (blocks.json, block_stacks.json) for the snapshot."""
    world = load_block_world(root, config, pages=pages, graph=graph, today=today)
    return build_blocks_payload(world), build_block_stacks_payload(world)
