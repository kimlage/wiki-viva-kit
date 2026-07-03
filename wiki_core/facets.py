"""Facets — the natural-language presentation of the canonical AQAL quadrant
contract (:mod:`wiki_core.quadrants`) for the page-centered "Focus" view.

The cockpit shows one page at the center surrounded by FOUR named lenses, in
plain language, with NO jargon at the surface:

    intencao  — why it exists: identity, intent, priorities, decisions
    percepcao — how it is lived/perceived: experience, insight, felt states
    pratica   — what is done and with what: behavior, artifacts, actions,
                tools, processes, evidence, metrics
    relacoes  — who and how together: people, roles, meetings, culture

These map onto the four quadrants honestly: the interior-individual quadrant
(q1) is rich enough to carry two lenses (intention AND experience/perception);
the interior-collective quadrant (q3) is Relações; and the two EXTERIOR
quadrants (q2 individual behavior, q4 collective systems) are both "doing" and
merge into Prática. This module is the single source of that mapping. It is
pure and deterministic; the quadrant IDs (q1..q4) stay internal.
"""

from __future__ import annotations

from wiki_core.quadrants import is_portuguese

FACET_SCHEMA_VERSION = "wiki_facets.v1"

# Canonical facet order (drives the sector order in the Focus view).
FACETS: tuple[str, ...] = ("intencao", "percepcao", "pratica", "relacoes")

# Facet -> the quadrant ID(s) it presents. Prática aggregates the two exterior
# quadrants; Intenção and Percepção are two reads of the interior-individual.
FACET_QUADRANTS: dict[str, tuple[str, ...]] = {
    "intencao": ("q1",),
    "percepcao": ("q1",),
    "pratica": ("q2", "q4"),
    "relacoes": ("q3",),
}

_FACET_LABELS_EN = {
    "intencao": "Intention",
    "percepcao": "Perception",
    "pratica": "Practice",
    "relacoes": "Relations",
}
_FACET_LABELS_PT = {
    "intencao": "Intenção",
    "percepcao": "Percepção",
    "pratica": "Prática",
    "relacoes": "Relações",
}
_FACET_HINTS_EN = {
    "intencao": "Why it exists: identity, intent, priorities, decisions.",
    "percepcao": "How it is lived and perceived: experience, insight, felt states.",
    "pratica": "What is done and with what: actions, artifacts, tools, processes, evidence.",
    "relacoes": "Who and how together: people, roles, meetings, culture.",
}
_FACET_HINTS_PT = {
    "intencao": "Por que existe: identidade, intenção, prioridades, decisões.",
    "percepcao": "Como é vivido e percebido: experiência, insight, estados sentidos.",
    "pratica": "O que se faz e com quê: ações, artefatos, ferramentas, processos, evidências.",
    "relacoes": "Quem e como juntos: pessoas, papéis, reuniões, cultura.",
}

# Default lens a NEIGHBOR page falls under when read from the center, keyed by
# the neighbor's page_type. Per-type registry overrides win over this table.
# Structural/index types map to None (they are navigation, not a lens).
DEFAULT_PAGE_TYPE_FACET: dict[str, str | None] = {
    # Intention (interior-individual, the "intent" read)
    "decision": "intencao",
    "operational_rule": "intencao",
    "responsibility": "intencao",
    "role": "relacoes",  # a role is a relationship/expectation (q3)
    "project": "intencao",
    "initiative": "intencao",
    # Perception (interior-individual, the "experience" read)
    "insight": "percepcao",
    "journal_entry": "percepcao",
    "claim": "percepcao",
    "perspective": "percepcao",
    # Practice (exterior: behavior + systems)
    "action": "pratica",
    "process": "pratica",
    "artifact": "pratica",
    "evidence": "pratica",
    "source": "pratica",
    "source_config": "pratica",
    "ingestion_event": "pratica",
    "input_channel": "pratica",
    "input_stage": "pratica",
    "dashboard": "pratica",
    # Relations (interior-collective: culture/roles/people)
    "person": "relacoes",
    "meeting": "relacoes",
    "holon": "relacoes",
    "relationship_map": "relacoes",
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
    "source_ref": "pratica",
    "pr_impact": "pratica",
    "ingestion_chain": "pratica",
    "decision": "intencao",
    "claim": "percepcao",
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
