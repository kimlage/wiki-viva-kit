from __future__ import annotations

from wiki_core.facets import (
    FACETS,
    FACET_QUADRANTS,
    facet_contract,
    facet_labels,
    facet_of,
    home_quadrant,
)
from wiki_core.quadrants import DEFAULT_QUADRANT_MAP


def test_four_facets_map_one_to_one_onto_the_four_quadrants() -> None:
    covered = {q for quads in FACET_QUADRANTS.values() for q in quads}
    assert covered == set(DEFAULT_QUADRANT_MAP)  # q1..q4 all reachable
    # Faithful 1:1: each lens presents exactly one quadrant, no doubling/merging.
    assert FACETS == ("intencao", "pratica", "relacoes", "sistemas")
    assert FACET_QUADRANTS["intencao"] == ("q1",)
    assert FACET_QUADRANTS["pratica"] == ("q2",)
    assert FACET_QUADRANTS["relacoes"] == ("q3",)
    assert FACET_QUADRANTS["sistemas"] == ("q4",)
    assert all(len(quads) == 1 for quads in FACET_QUADRANTS.values())


def test_facet_of_by_page_type() -> None:
    assert facet_of("decision") == "intencao"
    # Perception is interior-individual (q1) → lives in the Intention lens now.
    assert facet_of("insight") == "intencao"
    assert facet_of("claim") == "intencao"
    assert facet_of("action") == "pratica"
    assert facet_of("person") == "relacoes"
    # Systems/processes (q4) are their own lens — no longer buried in Practice.
    assert facet_of("process") == "sistemas"
    assert facet_of("source") == "sistemas"
    assert facet_of("dashboard") == "sistemas"
    # Structural types are not a lens.
    assert facet_of("root_entity") is None
    assert facet_of("context_hub") is None


def test_home_quadrant_is_page_type_only_and_honest_about_null() -> None:
    # A page's own quadrant comes from its page_type, NOT an edge (that is the
    # difference from facet_of).
    assert home_quadrant("decision") == "intencao"
    assert home_quadrant("action") == "pratica"
    assert home_quadrant("person") == "relacoes"
    assert home_quadrant("source") == "sistemas"
    # Structural + unknown types have NO quadrant (q0-core), never forced.
    assert home_quadrant("context_hub") is None
    assert home_quadrant("root_index") is None
    assert home_quadrant("totally_unknown_type") is None
    assert home_quadrant(None) is None


def test_home_quadrant_registry_override_wins_and_is_validated() -> None:
    # A wiki may editorially place a structural type into a real quadrant (O4).
    assert home_quadrant("context_note", overrides={"context_note": "relacoes"}) == "relacoes"
    # An override to a non-facet is ignored (falls through to None here).
    assert home_quadrant("context_note", overrides={"context_note": "nonsense"}) is None


def test_facet_of_falls_back_to_edge_type() -> None:
    assert facet_of("unknown_type", edge_type="source_ref") == "sistemas"
    assert facet_of("unknown_type", edge_type="moc_parent") is None
    assert facet_of("unknown_type", edge_type=None) is None


def test_registry_override_wins_and_is_validated() -> None:
    assert facet_of("action", overrides={"action": "relacoes"}) == "relacoes"
    # An override to a non-facet is ignored (falls through to None here).
    assert facet_of("weird", overrides={"weird": "nonsense"}) is None


def test_facet_contract_is_localized_and_ordered() -> None:
    en = facet_contract("en")
    pt = facet_contract("pt")
    assert en["order"] == list(FACETS)
    assert en["facets"]["sistemas"]["label"] == "Systems"
    assert pt["facets"]["sistemas"]["label"] == "Sistemas"
    assert pt["facets"]["sistemas"]["quadrants"] == ["q4"]
    assert facet_labels("pt")["relacoes"] == "Relações"
