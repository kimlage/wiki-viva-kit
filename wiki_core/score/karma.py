"""Operational karma and context vitality (gamification layer of the living wiki).

Implements Section 13 of the v5 methodology: scoring across 8 dimensions, events
with base points, anti-gaming multipliers (quality, collaboration, rarity,
impact, soft decay), qualitative badges and journey levels.

Principles:
  - TWO LEVELS: personal operational karma (private, per dimension) and context
    vitality (a collective health indicator for a context/page/circle).
  - APPEND-ONLY: the "Score Keeper" only writes events, never edits history.
    `record_event` appends ONE JSON line per event; it never rewrites.
  - NO TOXIC GLOBAL RANKING: the aggregate is per dimension and per context, not
    a person-versus-person leaderboard.

stdlib only (json, math, datetime, dataclasses, pathlib).
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

# --------------------------------------------------------------------------- #
# Dimensions (use exactly these keys)                                           #
# --------------------------------------------------------------------------- #

DIMENSIONS: tuple[str, ...] = (
    "clareza",
    "confiabilidade",
    "cuidado",
    "stewardship",
    "conexao",
    "aprendizado",
    "acao",
    "inspiracao",
)

# --------------------------------------------------------------------------- #
# Events and base points (Section 13 of v5)                                     #
# --------------------------------------------------------------------------- #

EVENT_TYPES: dict[str, dict[str, object]] = {
    "ingestar_fonte_valida": {"dimensao": "confiabilidade", "pontos_base": 1},
    "corrigir_metadado_contexto": {"dimensao": "clareza", "pontos_base": 1},
    "adicionar_link": {"dimensao": "conexao", "pontos_base": 1},
    "aprovar_no_sla": {"dimensao": "stewardship", "pontos_base": 2},
    "pedir_evidencia": {"dimensao": "confiabilidade", "pontos_base": 2},
    "corrigir_info_canonica": {"dimensao": "confiabilidade", "pontos_base": 3},
    "recompilar_pagina_antiga": {"dimensao": "stewardship", "pontos_base": 3},
    "criar_insight_aceito": {"dimensao": "aprendizado", "pontos_base": 4},
    "gerar_infografico_mapa": {"dimensao": "inspiracao", "pontos_base": 4},
    "fechar_ciclo_acao": {"dimensao": "acao", "pontos_base": 5},
    "detectar_risco_privacidade": {"dimensao": "cuidado", "pontos_base": 5},
    "conectar_dois_contextos": {"dimensao": "conexao", "pontos_base": 5},
}

# --------------------------------------------------------------------------- #
# Anti-gaming parameters                                                          #
# --------------------------------------------------------------------------- #

# Quality threshold: below it the event yields no credit (final points only
# grow when the result is accepted). The quality default is 1.0 (accepted).
QUALITY_THRESHOLD: float = 0.5

# Rarity: caring for a forgotten page is worth +50%.
RARITY_MULTIPLIER: float = 1.5

# Soft decay: half-life in days. Old events weigh less in the aggregate, but the
# history is not erased (the JSONL line stays intact).
DECAY_HALF_LIFE_DAYS: float = 90.0


@dataclass(frozen=True)
class ScoreEvent:
    """A scoring event, immutable. One JSON line in score-events.jsonl."""

    event_id: str
    event_type: str
    dimensao: str
    actor: str
    context: str
    base_points: int
    quality: float
    multiplier: float
    final_points: float
    ts: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ScoreEvent":
        return cls(
            event_id=str(data["event_id"]),
            event_type=str(data["event_type"]),
            dimensao=str(data["dimensao"]),
            actor=str(data["actor"]),
            context=str(data["context"]),
            base_points=int(data["base_points"]),
            quality=float(data["quality"]),
            multiplier=float(data["multiplier"]),
            final_points=float(data["final_points"]),
            ts=str(data["ts"]),
        )


# --------------------------------------------------------------------------- #
# Anti-gaming multipliers                                                        #
# --------------------------------------------------------------------------- #


def quality_multiplier(quality: float) -> float:
    """Final points only grow when the result is accepted.

    Below the quality threshold the credit is zeroed (prevents gaming by volume
    of bad contributions). Above the threshold, it scales linearly with quality.
    """
    if quality < QUALITY_THRESHOLD:
        return 0.0
    # Clamp to [0,1]: quality above 1.0 does NOT inflate points (anti-gaming).
    return min(1.0, quality)


def collaboration_multiplier(collaborators: int) -> float:
    """Contributions made with N people split credit equally.

    N<=1 -> 1.0 (full credit). N=2 -> 0.5 each, etc.
    """
    if collaborators <= 1:
        return 1.0
    return 1.0 / float(collaborators)


def rarity_multiplier(rare: bool) -> float:
    """Caring for a forgotten/orphan page is worth +50%."""
    return RARITY_MULTIPLIER if rare else 1.0


def impact_multiplier(impact_contexts: int) -> float:
    """An insight used by many contexts is worth more (soft-log scale).

    impact=0/1 -> 1.0. impact=N -> 1 + log2(N), without exploding for high values.
    """
    if impact_contexts <= 1:
        return 1.0
    return 1.0 + math.log2(float(impact_contexts))


def combined_multiplier(
    quality: float,
    collaborators: int,
    rare: bool,
    impact_contexts: int,
) -> float:
    """Product of the anti-gaming multipliers (except decay, which belongs to the aggregate)."""
    return (
        quality_multiplier(quality)
        * collaboration_multiplier(collaborators)
        * rarity_multiplier(rare)
        * impact_multiplier(impact_contexts)
    )


def decay_weight(ts: str, *, now: date | None = None, half_life_days: float = DECAY_HALF_LIFE_DAYS) -> float:
    """Soft decay: an event's weight in the aggregate based on its age.

    Recent events weigh ~1.0; events one half-life old weigh ~0.5. The history is
    NEVER erased, it just weighs less in the aggregated karma.
    """
    now = now or _today()
    event_day = _parse_day(ts)
    if event_day is None:
        return 1.0
    age_days = max(0.0, (now - event_day).days)
    return 0.5 ** (age_days / half_life_days)


# --------------------------------------------------------------------------- #
# Date/ID helpers                                                                #
# --------------------------------------------------------------------------- #


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _now_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _parse_day(ts: str) -> date | None:
    if not ts:
        return None
    try:
        return date.fromisoformat(ts[:10])
    except ValueError:
        return None


def _make_event_id(event_type: str, actor: str, context: str, ts: str, seq: int) -> str:
    import hashlib

    seed = f"{event_type}|{actor}|{context}|{ts}|{seq}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _dedup_event_id(dedup_key: str) -> str:
    """Stable event_id from a business key (idempotency)."""
    import hashlib

    return "ddk" + hashlib.sha256(dedup_key.encode("utf-8")).hexdigest()[:13]


# --------------------------------------------------------------------------- #
# Recording (append-only) and reading                                            #
# --------------------------------------------------------------------------- #


def build_event(
    event_type: str,
    actor: str,
    context: str,
    *,
    quality: float = 1.0,
    collaborators: int = 1,
    rare: bool = False,
    impact: int = 0,
    ts: str | None = None,
    seq: int = 0,
    dedup_key: str | None = None,
) -> ScoreEvent:
    """Build a ScoreEvent (without writing), computing final_points.

    `ts` is injectable (ISO date): we do NOT call datetime.now directly without
    allowing injection. When ts is None we fall back to today's UTC date.
    """
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unknown event_type: {event_type!r}")
    spec = EVENT_TYPES[event_type]
    dimensao = str(spec["dimensao"])
    base_points = int(spec["pontos_base"])

    ts_value = ts or _now_iso()
    multiplier = combined_multiplier(quality, collaborators, rare, impact)
    final_points = round(base_points * multiplier, 6)
    event_id = _dedup_event_id(dedup_key) if dedup_key else _make_event_id(event_type, actor, context, ts_value, seq)

    return ScoreEvent(
        event_id=event_id,
        event_type=event_type,
        dimensao=dimensao,
        actor=actor,
        context=context,
        base_points=base_points,
        quality=float(quality),
        multiplier=round(multiplier, 6),
        final_points=final_points,
        ts=ts_value,
    )


def record_event(events_path: Path, **kwargs: object) -> ScoreEvent:
    """Compute final_points and APPEND-ONLY a JSON line to the JSONL.

    Never rewrites or deletes existing lines. Creates the file/directory if
    needed. The accepted kwargs are those of `build_event` (event_type, actor,
    context, quality, collaborators, rare, impact, ts, seq).
    """
    events_path = Path(events_path)
    dedup_key = kwargs.get("dedup_key")
    if dedup_key is not None and events_path.exists():
        target_id = _dedup_event_id(str(dedup_key))
        for existing in load_events(events_path):
            if existing.event_id == target_id:
                return existing  # idempotent: event already recorded for this key
    # automatic seq based on the current count, for a stable/unique event_id.
    if "seq" not in kwargs:
        kwargs["seq"] = _count_lines(events_path)
    event = build_event(**kwargs)  # type: ignore[arg-type]
    events_path.parent.mkdir(parents=True, exist_ok=True)
    with events_path.open("a", encoding="utf-8") as handle:
        handle.write(event.to_json() + "\n")
    return event


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    count = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                count += 1
    return count


EVENTS_FILENAME = "score-events.jsonl"
# VERSIONED mirror of the ledger (the live one lives in data/derived/**, gitignored).
# Without it, karma reset to zero on a clean clone/CI. It is only metadata
# (event_type, actor, context, points) — never a secret.
EVENTS_MIRROR_FILENAME = "score-events-mirror.jsonl"


def resolve_events_path(derived_root: Path) -> Path:
    """Read path for events: the live one if it exists, otherwise the versioned mirror."""
    live = Path(derived_root) / EVENTS_FILENAME
    if live.exists():
        return live
    mirror = Path(derived_root) / EVENTS_MIRROR_FILENAME
    return mirror if mirror.exists() else live


def mirror_events(derived_root: Path) -> Path | None:
    """Copy the live ledger to the versioned mirror. Returns the path or None."""
    live = Path(derived_root) / EVENTS_FILENAME
    if not live.exists():
        return None
    mirror = Path(derived_root) / EVENTS_MIRROR_FILENAME
    mirror.write_text(live.read_text(encoding="utf-8"), encoding="utf-8")
    return mirror


def load_events(events_path: Path) -> list[ScoreEvent]:
    """Read all events from the JSONL (empty list if the file does not exist)."""
    events_path = Path(events_path)
    if not events_path.exists():
        return []
    events: list[ScoreEvent] = []
    with events_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            events.append(ScoreEvent.from_dict(json.loads(line)))
    return events


# --------------------------------------------------------------------------- #
# Aggregation: personal karma and context vitality                               #
# --------------------------------------------------------------------------- #


def compute_karma(
    events: Iterable[ScoreEvent],
    *,
    apply_decay: bool = True,
    now: date | None = None,
) -> dict[str, object]:
    """Aggregated personal operational karma.

    Returns:
      {
        "by_dimension": {dim: total, ...},   # all 8 dimensions present
        "by_context":   {ctx: {dim: total}}, # per context, non-zero dimensions
        "total":        float,
      }

    Applies optional soft decay (old events weigh less). The history is not
    changed: decay is only a read-time weight.
    """
    events = list(events)
    by_dimension: dict[str, float] = {dim: 0.0 for dim in DIMENSIONS}
    by_context: dict[str, dict[str, float]] = {}
    total = 0.0

    for event in events:
        weight = decay_weight(event.ts, now=now) if apply_decay else 1.0
        points = event.final_points * weight
        if event.dimensao in by_dimension:
            by_dimension[event.dimensao] += points
        else:  # tolerate unknown dimensions without breaking
            by_dimension[event.dimensao] = by_dimension.get(event.dimensao, 0.0) + points
        ctx = by_context.setdefault(event.context, {})
        ctx[event.dimensao] = ctx.get(event.dimensao, 0.0) + points
        total += points

    by_dimension = {dim: round(value, 6) for dim, value in by_dimension.items()}
    by_context = {
        ctx: {dim: round(value, 6) for dim, value in dims.items()}
        for ctx, dims in by_context.items()
    }
    return {
        "by_dimension": by_dimension,
        "by_context": by_context,
        "total": round(total, 6),
    }


# Vitality indicators that add health (more is better) or weigh negatively.
_VITALITY_POSITIVE = (
    "paginas_atualizadas",
    "aprovacoes_no_sla",
    "fontes_recentes",
    "insights_revisados",
    "acoes_com_resultado",
    "riscos_privacidade_resolvidos",
)
_VITALITY_NEGATIVE = (
    "pendencias",
    "paginas_orfas",
    "responsabilidades_sem_dono",
)


def context_vitality(
    events: Iterable[ScoreEvent],
    context: str,
    pages_meta: dict[str, object] | None = None,
    *,
    now: date | None = None,
) -> dict[str, object]:
    """Collective health indicator of a context (not a person ranking).

    Aggregates the context's score-events and combines them with injected
    operational indicators (`pages_meta`) into a 0-100 index. Positive indicators
    pull the index up; pending/orphan items pull it down.

    `pages_meta` (all optional, default 0):
      paginas_atualizadas, aprovacoes_no_sla, fontes_recentes,
      insights_revisados, acoes_com_resultado, riscos_privacidade_resolvidos,
      pendencias, paginas_orfas, responsabilidades_sem_dono, paginas_total.
    """
    pages_meta = dict(pages_meta or {})
    ctx_events = [e for e in events if e.context == context]

    karma = compute_karma(ctx_events, now=now)
    score_aggregado = float(karma["by_context"].get(context, {}) and sum(karma["by_context"][context].values()) or 0.0)
    actors = sorted({e.actor for e in ctx_events})

    positive = sum(float(pages_meta.get(key, 0)) for key in _VITALITY_POSITIVE)
    negative = sum(float(pages_meta.get(key, 0)) for key in _VITALITY_NEGATIVE)

    # 0-100 index: operational health + score activity, penalized by pending items.
    # Uses soft saturation to avoid exploding; each positive point ~ +6, score ~ +2/point.
    raw = positive * 6.0 + score_aggregado * 2.0 - negative * 8.0
    index = _saturate_0_100(raw)

    indicadores: dict[str, object] = {key: float(pages_meta.get(key, 0)) for key in _VITALITY_POSITIVE}
    indicadores.update({key: float(pages_meta.get(key, 0)) for key in _VITALITY_NEGATIVE})

    return {
        "context": context,
        "indicadores": indicadores,
        "score_aggregado": round(score_aggregado, 6),
        "eventos": len(ctx_events),
        "participantes": actors,
        "participacao_distribuida": len(actors),
        "indice_vitalidade": index,
    }


def _saturate_0_100(raw: float) -> float:
    """Map a raw value (which may be negative) to 0-100 smoothly."""
    if raw <= 0.0:
        # still respects penalties: anything below zero becomes 0
        return 0.0
    # soft logistic saturation centered to grow fast at the start.
    index = 100.0 * (1.0 - 0.5 ** (raw / 50.0))
    return round(min(100.0, max(0.0, index)), 1)


# --------------------------------------------------------------------------- #
# Badges (simple criteria over events)                                           #
# --------------------------------------------------------------------------- #


def _count_event_type(events: list[ScoreEvent], event_type: str) -> int:
    return sum(1 for e in events if e.event_type == event_type)


def _count_dimension(events: list[ScoreEvent], dimensao: str) -> int:
    return sum(1 for e in events if e.dimensao == dimensao)


@dataclass(frozen=True)
class Badge:
    """Symbolic recognition for a contribution pattern (qualitative).

    `nome`/`criterio` hold the canonical (pt) display strings for backward
    compatibility; language-aware output must go through `badge_display`.
    """

    badge_id: str
    nome: str
    criterio: str
    test: Callable[[list[ScoreEvent]], bool]

    def earned_by(self, events: list[ScoreEvent]) -> bool:
        return bool(self.test(events))


# DISPLAY-ONLY table per language (same pattern as the other generated-output
# string tables: pt and en ALWAYS with the same keys). Keyed by badge_id; inner
# keys are "name" and "criterion". The PERSISTED/functional values — badge_id
# (JSONL ledger, earned_badges), EVENT_TYPES, DIMENSIONS — never change here:
# this table only drives how generated output is rendered per config language.
BADGE_DISPLAY: dict[str, dict[str, dict[str, str]]] = {
    "pt": {
        "guardiao_de_contexto": {
            "name": "Guardiao de Contexto",
            "criterion": "mantem paginas de um contexto atualizadas (>=3 recompilacoes)",
        },
        "tecelao_de_links": {
            "name": "Tecelao de Links",
            "criterion": "cria conexoes uteis entre paginas (>=5 links)",
        },
        "curador_de_fontes": {
            "name": "Curador de Fontes",
            "criterion": "adiciona fontes boas e rastreaveis (>=5 fontes validas)",
        },
        "guardiao_de_privacidade": {
            "name": "Guardiao de Privacidade",
            "criterion": "identifica e corrige riscos de visibilidade (>=1 risco detectado)",
        },
        "alquimista_de_insights": {
            "name": "Alquimista de Insights",
            "criterion": "transforma informacoes dispersas em insight aprovado (>=3 insights)",
        },
        "cartografo_integral": {
            "name": "Cartografo Integral",
            "criterion": "preenche mapas/infograficos com qualidade (>=2 mapas)",
        },
        "revisor_vivo": {
            "name": "Revisor Vivo",
            "criterion": "resolve aprovacoes e corrige diffs com consistencia (>=5 stewardship)",
        },
        "jardineiro_da_wiki": {
            "name": "Jardineiro da Wiki",
            "criterion": "cuida de paginas orfas/desatualizadas (>=3 eventos raros)",
        },
    },
    "en": {
        "guardiao_de_contexto": {
            "name": "Context Guardian",
            "criterion": "keeps a context's pages up to date (>=3 recompiles)",
        },
        "tecelao_de_links": {
            "name": "Link Weaver",
            "criterion": "creates useful connections between pages (>=5 links)",
        },
        "curador_de_fontes": {
            "name": "Source Curator",
            "criterion": "adds good, traceable sources (>=5 valid sources)",
        },
        "guardiao_de_privacidade": {
            "name": "Privacy Guardian",
            "criterion": "identifies and fixes visibility risks (>=1 risk detected)",
        },
        "alquimista_de_insights": {
            "name": "Insight Alchemist",
            "criterion": "turns scattered information into an approved insight (>=3 insights)",
        },
        "cartografo_integral": {
            "name": "Integral Cartographer",
            "criterion": "fills maps/infographics with quality (>=2 maps)",
        },
        "revisor_vivo": {
            "name": "Living Reviewer",
            "criterion": "resolves approvals and fixes diffs consistently (>=5 stewardship)",
        },
        "jardineiro_da_wiki": {
            "name": "Wiki Gardener",
            "criterion": "cares for orphan/outdated pages (>=3 rare events)",
        },
    },
}


def _badge(badge_id: str, test: Callable[[list[ScoreEvent]], bool]) -> Badge:
    """Build a Badge whose legacy nome/criterio come from the pt display table."""
    display = BADGE_DISPLAY["pt"][badge_id]
    return Badge(badge_id, display["name"], display["criterion"], test)


BADGES: dict[str, Badge] = {
    "guardiao_de_contexto": _badge(
        "guardiao_de_contexto",
        lambda evs: _count_event_type(evs, "recompilar_pagina_antiga") >= 3,
    ),
    "tecelao_de_links": _badge(
        "tecelao_de_links",
        lambda evs: _count_event_type(evs, "adicionar_link") >= 5,
    ),
    "curador_de_fontes": _badge(
        "curador_de_fontes",
        lambda evs: _count_event_type(evs, "ingestar_fonte_valida") >= 5,
    ),
    "guardiao_de_privacidade": _badge(
        "guardiao_de_privacidade",
        lambda evs: _count_event_type(evs, "detectar_risco_privacidade") >= 1,
    ),
    "alquimista_de_insights": _badge(
        "alquimista_de_insights",
        lambda evs: _count_event_type(evs, "criar_insight_aceito") >= 3,
    ),
    "cartografo_integral": _badge(
        "cartografo_integral",
        lambda evs: _count_event_type(evs, "gerar_infografico_mapa") >= 2,
    ),
    "revisor_vivo": _badge(
        "revisor_vivo",
        lambda evs: _count_dimension(evs, "stewardship") >= 5,
    ),
    "jardineiro_da_wiki": _badge(
        "jardineiro_da_wiki",
        lambda evs: sum(1 for e in evs if e.multiplier >= RARITY_MULTIPLIER) >= 3,
    ),
}


def badge_display(badge_id: str, language: str = "en") -> dict[str, str]:
    """Display name/criterion of a badge in the given language (generated output).

    Falls back to English for unknown languages and degrades to the badge_id
    itself for unknown badges — display helpers never raise.
    """
    table = BADGE_DISPLAY.get(language) or BADGE_DISPLAY["en"]
    return table.get(badge_id, {"name": badge_id, "criterion": ""})


def earned_badges(events: Iterable[ScoreEvent]) -> list[str]:
    """List of badge_ids earned by the set of events."""
    events = list(events)
    return [badge.badge_id for badge in BADGES.values() if badge.earned_by(events)]


# --------------------------------------------------------------------------- #
# Journey levels                                                                 #
# --------------------------------------------------------------------------- #

# (level id, minimum threshold of total points). Ascending order. The first
# element is the PERSISTED/functional level id returned by `level_for` — it
# never changes; per-language rendering goes through LEVEL_DISPLAY below.
LEVELS: tuple[tuple[str, float], ...] = (
    ("Explorador", 0.0),
    ("Mapeador", 10.0),
    ("Curador", 25.0),
    ("Steward", 50.0),
    ("Tecelao", 100.0),
    ("Guardiao", 175.0),
    ("Catalisador", 275.0),
)

# DISPLAY-ONLY level names per language, keyed by LEVEL INDEX (same order and
# length as LEVELS; pt and en always with the same keys/positions).
LEVEL_DISPLAY: dict[str, tuple[str, ...]] = {
    "pt": ("Explorador", "Mapeador", "Curador", "Steward", "Tecelao", "Guardiao", "Catalisador"),
    "en": ("Explorer", "Mapper", "Curator", "Steward", "Weaver", "Guardian", "Catalyst"),
}


def level_for(total: float) -> str:
    """Journey level id for a total of points (persisted id, not display)."""
    name = LEVELS[0][0]
    for level_name, threshold in LEVELS:
        if total >= threshold:
            name = level_name
        else:
            break
    return name


def level_display(level_id: str, language: str = "en") -> str:
    """Display name of a journey level id (as returned by `level_for`).

    Falls back to English for unknown languages and to the id itself for
    unknown level ids — display helpers never raise.
    """
    names = LEVEL_DISPLAY.get(language) or LEVEL_DISPLAY["en"]
    for index, (level_id_known, _threshold) in enumerate(LEVELS):
        if level_id_known == level_id and index < len(names):
            return names[index]
    return level_id
