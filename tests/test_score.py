"""Tests for the gamification layer (operational karma + context vitality)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wiki_core.score import (
    BADGES,
    DIMENSIONS,
    EVENT_TYPES,
    LEVELS,
    build_event,
    compute_karma,
    context_vitality,
    earned_badges,
    level_for,
    load_events,
    record_event,
)


# --------------------------------------------------------------------------- #
# Structure/contract                                                            #
# --------------------------------------------------------------------------- #


def test_dimensions_exact_keys():
    assert DIMENSIONS == (
        "clareza",
        "confiabilidade",
        "cuidado",
        "stewardship",
        "conexao",
        "aprendizado",
        "acao",
        "inspiracao",
    )


def test_event_types_map_to_known_dimensions():
    assert len(EVENT_TYPES) == 12
    for event_type, spec in EVENT_TYPES.items():
        assert spec["dimensao"] in DIMENSIONS, event_type
        assert isinstance(spec["pontos_base"], int)


def test_event_base_points_from_v5():
    assert EVENT_TYPES["ingestar_fonte_valida"] == {"dimensao": "confiabilidade", "pontos_base": 1}
    assert EVENT_TYPES["fechar_ciclo_acao"] == {"dimensao": "acao", "pontos_base": 5}
    assert EVENT_TYPES["detectar_risco_privacidade"] == {"dimensao": "cuidado", "pontos_base": 5}
    assert EVENT_TYPES["criar_insight_aceito"] == {"dimensao": "aprendizado", "pontos_base": 4}


# --------------------------------------------------------------------------- #
# record_event append-only                                                      #
# --------------------------------------------------------------------------- #


def test_record_event_is_append_only(tmp_path):
    events_path = tmp_path / "score-events.jsonl"
    e1 = record_event(events_path, event_type="ingestar_fonte_valida", actor="kim", context="sistema", ts="2026-06-01")
    e2 = record_event(events_path, event_type="adicionar_link", actor="kim", context="sistema", ts="2026-06-02")

    lines = events_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2  # 2 events -> 2 lines
    # each line is valid JSON and matches the returned event
    parsed = [json.loads(line) for line in lines]
    assert parsed[0]["event_type"] == "ingestar_fonte_valida"
    assert parsed[1]["event_type"] == "adicionar_link"
    assert e1.event_id != e2.event_id

    # a third append does not rewrite the two previous lines
    record_event(events_path, event_type="aprovar_no_sla", actor="ana", context="sistema", ts="2026-06-03")
    lines2 = events_path.read_text(encoding="utf-8").splitlines()
    assert len(lines2) == 3
    assert lines2[0] == lines[0]
    assert lines2[1] == lines[1]


def test_load_events_roundtrip(tmp_path):
    events_path = tmp_path / "score-events.jsonl"
    assert load_events(events_path) == []  # nonexistent file -> empty
    record_event(events_path, event_type="adicionar_link", actor="kim", context="sistema", ts="2026-06-01")
    record_event(events_path, event_type="adicionar_link", actor="kim", context="sistema", ts="2026-06-02")
    events = load_events(events_path)
    assert len(events) == 2
    assert events[0].dimensao == "conexao"


# --------------------------------------------------------------------------- #
# final_points and multipliers                                                  #
# --------------------------------------------------------------------------- #


def test_final_points_default_multiplier_is_one():
    event = build_event("criar_insight_aceito", "kim", "sistema", ts="2026-06-01")
    assert event.base_points == 4
    assert event.multiplier == 1.0
    assert event.final_points == 4.0


def test_quality_below_threshold_zeroes_credit():
    event = build_event("criar_insight_aceito", "kim", "sistema", quality=0.2, ts="2026-06-01")
    assert event.final_points == 0.0


def test_collaboration_divides_credit():
    solo = build_event("fechar_ciclo_acao", "kim", "sistema", ts="2026-06-01")
    duo = build_event("fechar_ciclo_acao", "kim", "sistema", collaborators=2, ts="2026-06-01")
    assert solo.final_points == 5.0
    assert duo.final_points == pytest.approx(2.5)


def test_rarity_adds_fifty_percent():
    event = build_event("recompilar_pagina_antiga", "kim", "sistema", rare=True, ts="2026-06-01")
    assert event.base_points == 3
    assert event.final_points == pytest.approx(4.5)  # 3 * 1.5


def test_impact_scales_up():
    base = build_event("criar_insight_aceito", "kim", "sistema", ts="2026-06-01")
    high = build_event("criar_insight_aceito", "kim", "sistema", impact=4, ts="2026-06-01")
    assert high.final_points > base.final_points
    # 4 contexts -> multiplier 1 + log2(4) = 3.0 -> 4 * 3 = 12
    assert high.final_points == pytest.approx(12.0)


# --------------------------------------------------------------------------- #
# compute_karma aggregates by dimension and context                             #
# --------------------------------------------------------------------------- #


def test_compute_karma_aggregates_dimension_and_context():
    events = [
        build_event("ingestar_fonte_valida", "kim", "sistema", ts="2026-06-09"),
        build_event("pedir_evidencia", "kim", "sistema", ts="2026-06-09"),
        build_event("adicionar_link", "kim", "financeiro", ts="2026-06-09"),
    ]
    # no decay for a clean arithmetic check
    karma = compute_karma(events, apply_decay=False)

    # confiabilidade = 1 (source) + 2 (evidence) = 3; conexao = 1 (link)
    assert karma["by_dimension"]["confiabilidade"] == 3.0
    assert karma["by_dimension"]["conexao"] == 1.0
    # all 8 dimensions present
    assert set(karma["by_dimension"]) >= set(DIMENSIONS)
    # per context
    assert karma["by_context"]["sistema"]["confiabilidade"] == 3.0
    assert karma["by_context"]["financeiro"]["conexao"] == 1.0
    assert karma["total"] == 4.0


def test_decay_reduces_old_events(tmp_path):
    from datetime import date

    old = [build_event("fechar_ciclo_acao", "kim", "sistema", ts="2020-01-01")]
    now = date(2026, 6, 9)
    with_decay = compute_karma(old, apply_decay=True, now=now)
    without = compute_karma(old, apply_decay=False, now=now)
    assert with_decay["total"] < without["total"]
    assert without["total"] == 5.0


# --------------------------------------------------------------------------- #
# context vitality                                                              #
# --------------------------------------------------------------------------- #


def test_context_vitality_index_in_range():
    events = [
        build_event("ingestar_fonte_valida", "kim", "sistema", ts="2026-06-09"),
        build_event("aprovar_no_sla", "ana", "sistema", ts="2026-06-09"),
    ]
    vit = context_vitality(
        events,
        "sistema",
        pages_meta={"paginas_atualizadas": 4, "aprovacoes_no_sla": 2, "pendencias": 1},
    )
    assert 0.0 <= vit["indice_vitalidade"] <= 100.0
    assert vit["eventos"] == 2
    assert vit["participacao_distribuida"] == 2  # kim + ana
    assert vit["score_aggregado"] > 0


def test_context_vitality_penalizes_pending():
    events = [build_event("ingestar_fonte_valida", "kim", "sistema", ts="2026-06-09")]
    healthy = context_vitality(events, "sistema", pages_meta={"paginas_atualizadas": 5})
    unhealthy = context_vitality(events, "sistema", pages_meta={"paginas_atualizadas": 5, "pendencias": 10, "paginas_orfas": 5})
    assert unhealthy["indice_vitalidade"] < healthy["indice_vitalidade"]


# --------------------------------------------------------------------------- #
# journey levels                                                                #
# --------------------------------------------------------------------------- #


def test_level_for_thresholds():
    assert level_for(0.0) == "Explorador"
    assert level_for(9.9) == "Explorador"
    assert level_for(10.0) == "Mapeador"
    assert level_for(25.0) == "Curador"
    assert level_for(50.0) == "Steward"
    assert level_for(100.0) == "Tecelao"
    assert level_for(175.0) == "Guardiao"
    assert level_for(275.0) == "Catalisador"
    assert level_for(10_000.0) == "Catalisador"


def test_levels_are_monotonic():
    thresholds = [t for _, t in LEVELS]
    assert thresholds == sorted(thresholds)


# --------------------------------------------------------------------------- #
# badges                                                                        #
# --------------------------------------------------------------------------- #


def test_badges_catalog_has_required_eight():
    expected = {
        "guardiao_de_contexto",
        "tecelao_de_links",
        "curador_de_fontes",
        "guardiao_de_privacidade",
        "alquimista_de_insights",
        "cartografo_integral",
        "revisor_vivo",
        "jardineiro_da_wiki",
    }
    assert expected <= set(BADGES)
    assert len(BADGES) >= 8


def test_badge_tecelao_de_links_fires():
    # 5 links -> "Tecelao de Links" badge
    events = [build_event("adicionar_link", "kim", "sistema", ts="2026-06-09") for _ in range(5)]
    badges = earned_badges(events)
    assert "tecelao_de_links" in badges
    # 4 links does not fire
    fewer = [build_event("adicionar_link", "kim", "sistema", ts="2026-06-09") for _ in range(4)]
    assert "tecelao_de_links" not in earned_badges(fewer)


def test_badge_guardiao_de_privacidade_fires():
    events = [build_event("detectar_risco_privacidade", "kim", "sistema", ts="2026-06-09")]
    assert "guardiao_de_privacidade" in earned_badges(events)


def test_quality_multiplier_clamped_to_one():
    # quality > 1.0 does NOT inflate points: base_points(1) * clamp(1.0) == 1.0
    ev = build_event("ingestar_fonte_valida", "kim", "sistema", quality=10.0, ts="2026-06-09")
    assert ev.final_points == 1.0


def test_record_event_idempotent_with_dedup_key(tmp_path: Path):
    events_path = tmp_path / "score-events.jsonl"
    a = record_event(events_path, event_type="ingestar_fonte_valida", actor="kim",
                     context="sistema", ts="2026-06-09", dedup_key="ingest:src-1")
    b = record_event(events_path, event_type="ingestar_fonte_valida", actor="kim",
                     context="sistema", ts="2026-06-09", dedup_key="ingest:src-1")
    assert a.event_id == b.event_id
    assert len(load_events(events_path)) == 1  # same key -> no duplicate
    record_event(events_path, event_type="ingestar_fonte_valida", actor="kim",
                 context="sistema", ts="2026-06-09", dedup_key="ingest:src-2")
    assert len(load_events(events_path)) == 2  # new key -> new event
