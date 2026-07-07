"""Facets — the natural-language presentation of the canonical AQAL quadrant
contract (:mod:`wiki_core.quadrants`) for the page-centered "Focus" view.

The cockpit shows one page or anchor at the center surrounded by FOUR named
lenses, in plain language, with NO jargon at the surface — one lens per
quadrant, so the four quadrants are each honestly present:

    intencao  (q1, interior-individual)  — identity and intent: why it exists,
                what it means, what it prioritizes and how it is perceived.
    pratica   (q2, exterior-individual)  — outputs and evidence: observable
                behavior, actions, artifacts, direct outputs and metrics.
    relacoes  (q3, interior-collective)  — culture and relations: shared
                meaning, lived roles, rituals, norms and relationship context.
    sistemas  (q4, exterior-collective)  — systems and governance: channels,
                tools, pipelines, workflows, rules and process infrastructure.

This is a FAITHFUL 1:1 mapping onto the four quadrants (unlike the earlier draft
that split q1 into two lenses and merged the two exterior quadrants — which hid
q4/systems). It is the single source of the mapping: pure and deterministic; the
quadrant IDs (q1..q4) stay internal. The maps below are semantic defaults and
fallbacks. The authoritative quadrant placement for block-driven views is the
anchor-relative projection emitted by ``wiki_core.template_blocks``.
"""

from __future__ import annotations

# Canonical facet order = quadrant order q1..q4 (drives the Focus sector order).
FACETS: tuple[str, ...] = ("intencao", "pratica", "relacoes", "sistemas")

# Facet -> the quadrant it presents. One lens per quadrant, 1:1.
FACET_QUADRANTS: dict[str, tuple[str, ...]] = {
    "intencao": ("q1",),
    "pratica": ("q2",),
    "relacoes": ("q3",),
    "sistemas": ("q4",),
}

# Default local lens a page falls under when no anchor-relative projection gives
# a stronger answer, keyed by page_type. Per-type registry overrides win over
# this table. Structural/index types map to None (they are navigation, not a
# lens).
DEFAULT_PAGE_TYPE_FACET: dict[str, str | None] = {
    # Identity and intent (q1, interior-individual): intent AND perception both live here.
    "decision": "intencao",
    "responsibility": "intencao",
    "project": "intencao",
    "initiative": "intencao",
    "insight": "intencao",
    "journal_entry": "intencao",
    "claim": "intencao",
    "perspective": "intencao",
    # Outputs and evidence (q2, exterior-individual): observable traces, outputs, artifacts and evidence.
    "action": "pratica",
    "artifact": "pratica",
    "evidence": "pratica",
    "source": "pratica",
    "source_catalog": "pratica",
    "source_registry": "pratica",
    "system_log": "pratica",
    "ingestion_event": "pratica",
    "dashboard": "pratica",
    "root_index": "pratica",
    "ontology_index": "pratica",
    # Culture and relations (q3, interior-collective): culture, lived roles and people-in-context.
    "person": "relacoes",
    "role": "relacoes",  # a role is a relationship/expectation
    "meeting": "relacoes",
    "holon": "relacoes",
    "relationship_map": "relacoes",
    # Systems and governance (q4, exterior-collective): coordination, governance and process infrastructure.
    "operational_rule": "sistemas",
    "context_hub": "sistemas",
    "process": "sistemas",
    "source_config": "sistemas",
    "input_channel": "sistemas",
    "input_stage": "sistemas",
    "skill": "sistemas",
    "tool": "sistemas",
    "template_block": "sistemas",
    # The active root stays at the center of the quadrant map.
    "root_entity": None,
}

# Secondary signal: the typed relation edge, when the neighbor's page_type is
# unknown/ambiguous. moc_parent/markdown_link are structural (None).
DEFAULT_EDGE_FACET: dict[str, str | None] = {
    "moc_parent": None,
    "markdown_link": None,
    "source_ref": "pratica",  # points at source evidence (q2 trace)
    "pr_impact": "sistemas",  # governance/pipeline (q4)
    "ingestion_chain": "sistemas",  # a pipeline (q4)
    "decision": "intencao",
    "claim": "intencao",  # a claim is interior perception (q1)
    "action": "pratica",
}


def facet_of(
    neighbor_page_type: str | None,
    edge_type: str | None = None,
    overrides: dict[str, str] | None = None,
) -> str | None:
    """Which facet a neighbor page belongs to, seen from the center.

    Precedence: per-type override (from the template registry) → page_type
    default → edge_type default → None (active-root/unknown, shown outside the lenses).
    """
    if overrides and neighbor_page_type and neighbor_page_type in overrides:
        candidate = overrides[neighbor_page_type]
        return candidate if candidate in FACET_QUADRANTS else None
    if neighbor_page_type in DEFAULT_PAGE_TYPE_FACET:
        return DEFAULT_PAGE_TYPE_FACET[neighbor_page_type]
    if edge_type in DEFAULT_EDGE_FACET:
        return DEFAULT_EDGE_FACET[edge_type]
    return None


def home_quadrant(
    page_type: str | None,
    overrides: dict[str, str] | None = None,
) -> str | None:
    """The quadrant a page LIVES IN, keyed by its OWN page_type (not a neighbor
    edge — that is the difference from :func:`facet_of`). Drives the Quadrants
    perspective's spatial home.

    Precedence: per-type registry override → page_type default → None. The active
    root and unknown types are None; common catalog/log/source pages should have
    explicit defaults so q0_core stays a center, not an unclassified page bucket.
    """
    if overrides and page_type and page_type in overrides:
        candidate = overrides[page_type]
        return candidate if candidate in FACET_QUADRANTS else None
    return DEFAULT_PAGE_TYPE_FACET.get(page_type)
