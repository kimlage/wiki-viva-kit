from __future__ import annotations

from wiki_core.facets import (
    FACETS,
    FACET_QUADRANTS,
    facet_contract,
    facet_labels,
    facet_of,
)
from wiki_core.quadrants import DEFAULT_QUADRANT_MAP


def test_four_facets_cover_the_four_quadrants() -> None:
    covered = {q for quads in FACET_QUADRANTS.values() for q in quads}
    assert covered == set(DEFAULT_QUADRANT_MAP)  # q1..q4 all reachable
    # Practice aggregates the two exterior quadrants; the interior-individual
    # quadrant carries two lenses (intention + perception).
    assert set(FACET_QUADRANTS["pratica"]) == {"q2", "q4"}
    assert FACET_QUADRANTS["intencao"] == FACET_QUADRANTS["percepcao"] == ("q1",)


def test_facet_of_by_page_type() -> None:
    assert facet_of("decision") == "intencao"
    assert facet_of("insight") == "percepcao"
    assert facet_of("action") == "pratica"
    assert facet_of("person") == "relacoes"
    # Structural types are not a lens.
    assert facet_of("root_entity") is None
    assert facet_of("context_hub") is None


def test_facet_of_falls_back_to_edge_type() -> None:
    assert facet_of("unknown_type", edge_type="source_ref") == "pratica"
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
    assert en["facets"]["percepcao"]["label"] == "Perception"
    assert pt["facets"]["percepcao"]["label"] == "Percepção"
    assert pt["facets"]["pratica"]["quadrants"] == ["q2", "q4"]
    assert facet_labels("pt")["relacoes"] == "Relações"
