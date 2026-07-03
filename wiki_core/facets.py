"""Facets — the natural-language presentation of the canonical AQAL quadrant
contract (:mod:`wiki_core.quadrants`) for the page-centered "Focus" view.

The cockpit shows one page at the center surrounded by FOUR named lenses, in
plain language, with NO jargon at the surface — one lens per quadrant, so the
four quadrants are each honestly present:

    intencao  (q1, interior-individual)  — why it exists AND how it is
                perceived: identity, intent, priorities, decisions, insights,
                felt states. (Intent and perception are both interior — they
                share this lens.)
    pratica   (q2, exterior-individual)  — what the entity does and produces:
                actions, artifacts, evidence, observable output.
    relacoes  (q3, interior-collective)  — who and how together: people, roles,
                meetings, culture, shared meaning.
    sistemas  (q4, exterior-collective)  — the systems that coordinate it:
                sources, channels, pipelines, dashboards, processes, governance.

This is a FAITHFUL 1:1 mapping onto the four quadrants (unlike the earlier draft
that split q1 into two lenses and merged the two exterior quadrants — which hid
q4/systems). It is the single source of the mapping: pure and deterministic; the
quadrant IDs (q1..q4) stay internal.
"""

from __future__ import annotations

from wiki_core.quadrants import is_portuguese

FACET_SCHEMA_VERSION = "wiki_facets.v1"

# Canonical facet order = quadrant order q1..q4 (drives the Focus sector order).
FACETS: tuple[str, ...] = ("intencao", "pratica", "relacoes", "sistemas")

# Facet -> the quadrant it presents. One lens per quadrant, 1:1.
FACET_QUADRANTS: dict[str, tuple[str, ...]] = {
    "intencao": ("q1",),
    "pratica": ("q2",),
    "relacoes": ("q3",),
    "sistemas": ("q4",),
}

_FACET_LABELS_EN = {
    "intencao": "Intention",
    "pratica": "Practice",
    "relacoes": "Relations",
    "sistemas": "Systems",
}
_FACET_LABELS_PT = {
    "intencao": "Intenção",
    "pratica": "Prática",
    "relacoes": "Relações",
    "sistemas": "Sistemas",
}
_FACET_HINTS_EN = {
    "intencao": "Why it exists and how it is perceived: identity, intent, priorities, decisions, insights.",
    "pratica": "What is done and produced: actions, artifacts, evidence.",
    "relacoes": "Who and how together: people, roles, meetings, culture.",
    "sistemas": "The systems that coordinate it: sources, channels, pipelines, dashboards, governance.",
}
_FACET_HINTS_PT = {
    "intencao": "Por que existe e como é percebido: identidade, intenção, prioridades, decisões, percepções.",
    "pratica": "O que se faz e se produz: ações, artefatos, evidências.",
    "relacoes": "Quem e como juntos: pessoas, papéis, reuniões, cultura.",
    "sistemas": "Os sistemas que o coordenam: fontes, canais, pipelines, dashboards, governança.",
}

# Default lens a NEIGHBOR page falls under when read from the center, keyed by
# the neighbor's page_type. Per-type registry overrides win over this table.
# Structural/index types map to None (they are navigation, not a lens).
DEFAULT_PAGE_TYPE_FACET: dict[str, str | None] = {
    # Intention (q1, interior-individual): intent AND perception both live here.
    "decision": "intencao",
    "operational_rule": "intencao",  # a rule you set for yourself = declared intent/constraint
    "responsibility": "intencao",
    "project": "intencao",
    "initiative": "intencao",
    "insight": "intencao",
    "journal_entry": "intencao",
    "claim": "intencao",
    "perspective": "intencao",
    # Practice (q2, exterior-individual): the entity's own output/artifacts.
    "action": "pratica",
    "artifact": "pratica",
    "evidence": "pratica",
    # Relations (q3, interior-collective): culture/roles/people.
    "person": "relacoes",
    "role": "relacoes",  # a role is a relationship/expectation
    "meeting": "relacoes",
    "holon": "relacoes",
    "relationship_map": "relacoes",
    # Systems (q4, exterior-collective): the process/channel/tooling infrastructure.
    "process": "sistemas",
    "source": "sistemas",
    "source_config": "sistemas",
    "ingestion_event": "sistemas",
    "input_channel": "sistemas",
    "input_stage": "sistemas",
    "dashboard": "sistemas",
    # Structural — not a lens
    "root_entity": None,
    "root_index": None,
    "context_hub": None,
    "ontology_index": None,
    "source_registry": None,
    "source_catalog": None,
    "system_log": None,
}

# Secondary signal: the typed relation edge, when the neighbor's page_type is
# unknown/ambiguous. moc_parent/markdown_link are structural (None).
DEFAULT_EDGE_FACET: dict[str, str | None] = {
    "moc_parent": None,
    "markdown_link": None,
    "source_ref": "sistemas",  # points at a source (q4 system)
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
    default → edge_type default → None (structural, shown outside the lenses).
    """
    if overrides and neighbor_page_type and neighbor_page_type in overrides:
        candidate = overrides[neighbor_page_type]
        return candidate if candidate in FACET_QUADRANTS else None
    if neighbor_page_type in DEFAULT_PAGE_TYPE_FACET:
        return DEFAULT_PAGE_TYPE_FACET[neighbor_page_type]
    if edge_type in DEFAULT_EDGE_FACET:
        return DEFAULT_EDGE_FACET[edge_type]
    return None


def facet_labels(language: str = "en") -> dict[str, str]:
    return dict(_FACET_LABELS_PT if is_portuguese(language) else _FACET_LABELS_EN)


def facet_contract(language: str = "en") -> dict[str, object]:
    """Serializable facet contract for the snapshot + cockpit (labels, hints,
    order, and the honest facet→quadrant mapping)."""
    portuguese = is_portuguese(language)
    labels = _FACET_LABELS_PT if portuguese else _FACET_LABELS_EN
    hints = _FACET_HINTS_PT if portuguese else _FACET_HINTS_EN
    return {
        "schema_version": FACET_SCHEMA_VERSION,
        "order": list(FACETS),
        "facets": {
            facet: {
                "label": labels[facet],
                "hint": hints[facet],
                "quadrants": list(FACET_QUADRANTS[facet]),
            }
            for facet in FACETS
        },
    }
