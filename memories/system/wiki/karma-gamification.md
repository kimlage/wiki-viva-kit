---
page_id: system-wiki-karma-gamification
page_type: source_catalog
title: "Gamification and karma"
tags:
  - wiki/meta
  - status/active
status: active
context: system
visibility: private_self
updated_at: 2026-06-09
stale_after_days: 90
sources_policy: documentacao_do_proprio_sistema
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
purpose: "8-dimension karma as an append-only byproduct, with no toxic leaderboard, with anti-gaming, decay, per-context vitality, badges and levels."
moc_parent: memories/system/wiki/index.md
related_pages:
  - memories/system/wiki/index.md
---

# Gamification and karma

Updated on: 2026-06-09.

The gamification layer of the living wiki exists to make visible the care taken with
knowledge, not to create competition. It is a byproduct of normal work:
every useful contribution (ingesting a traceable source, fixing a metadata field, closing
the cycle of an action) generates a scoring event, and the sum of those events becomes
karma. The deterministic code lives in [karma.py](../../../wiki_core/score/karma.py)
and the command-line interface in [wiki_score.py](../../../scripts/wiki_score.py).

Two design principles separate this layer from a toxic points system:

- Append-only: the "Score Keeper" only writes events, never edits or deletes the
  history. Each event is a JSON line in [data/](../../../data/) under
  `derived/wiki/score-events.jsonl` (created at runtime).
- No global person-versus-person ranking: the aggregate is always by dimension
  (who you are becoming) and by context (the collective health of a page or
  circle), never a leaderboard.

For the PR gate that decides what becomes a source of truth, see
[Approvals via Git](../git-approvals.md) and [Gates and auditing](gates-and-audit.md);
for the flow that triggers the events, see [Ingestion process](../ingestion-process.md).

## The 8 dimensions of karma

Karma is not a single number: it is a vector of 8 dimensions, defined in
`DIMENSIONS` inside [karma.py](../../../wiki_core/score/karma.py). Each event
credits exactly one dimension. The dimensions represent *which quality* the
contribution exercised:

| Dimension | What it recognizes |
| --- | --- |
| clareza | making information legible and well-labeled |
| confiabilidade | bringing traceable sources and fixing the canonical |
| cuidado | protecting privacy and visibility |
| stewardship | tending the garden: approving within SLA, recompiling pages |
| conexao | weaving links and connecting contexts |
| aprendizado | distilling scattered information into insight |
| acao | closing action cycles with a result |
| inspiracao | generating maps, infographics, visual narrative |

Because the aggregate is by dimension, the system answers "you have become a good
source curator" instead of "you are in 3rd place".

## Events and base points

`EVENT_TYPES` in [karma.py](../../../wiki_core/score/karma.py) is the closed catalog
of event types. Each type fixes the credited dimension and the base points. The
base points grow with the effort and consequence of the contribution: adding a
link is worth 1, closing an action cycle is worth 5.

| event_type | dimension | base points |
| --- | --- | ---: |
| ingestar_fonte_valida | confiabilidade | 1 |
| corrigir_metadado_contexto | clareza | 1 |
| adicionar_link | conexao | 1 |
| aprovar_no_sla | stewardship | 2 |
| pedir_evidencia | confiabilidade | 2 |
| corrigir_info_canonica | confiabilidade | 3 |
| recompilar_pagina_antiga | stewardship | 3 |
| criar_insight_aceito | aprendizado | 4 |
| gerar_infografico_mapa | inspiracao | 4 |
| fechar_ciclo_acao | acao | 5 |
| detectar_risco_privacidade | cuidado | 5 |
| conectar_dois_contextos | conexao | 5 |

An event is an immutable `ScoreEvent` (`frozen` dataclass) with `event_id`,
`event_type`, `dimensao`, `actor`, `context`, `base_points`, `quality`,
`multiplier`, `final_points` and `ts`. `build_event` assembles the event and computes the
`final_points`; the date (`ts`) is injectable instead of calling the clock directly,
which makes the scoring testable and reproducible.

## Anti-gaming multipliers

The base points are merely the starting point. `combined_multiplier` applies four
factors that make it hard to inflate karma by volume of shallow contributions:

- Quality (`quality_multiplier`): points only grow when the result is accepted.
  Below the `QUALITY_THRESHOLD` (0.5) the credit is zeroed; above it the
  quality is clamped to [0,1], that is, sending "quality 5" does NOT multiply anything.
- Collaboration (`collaboration_multiplier`): a contribution made by N people
  divides the credit by N (2 people -> 0.5 each). No one earns full points for
  work that was collective.
- Rarity (`rarity_multiplier`): tending a forgotten or orphan page is worth +50%
  (`RARITY_MULTIPLIER` = 1.5). This directs energy toward what is abandoned,
  not toward what is already shining.
- Impact (`impact_multiplier`): an insight reused by many contexts is worth
  more, but on a soft logarithmic scale (1 + log2(N)), so as not to explode.

The recorded `final_points` is `base_points * multiplier`, rounded. Since the
quality threshold can zero the multiplier, non-accepted contributions stay
in the history but are worth zero points.

## Read decay

`decay_weight` applies a soft decay by age: an event with one half-life
(`DECAY_HALF_LIFE_DAYS` = 90 days) weighs ~0.5 in the aggregate; with two half-lives,
~0.25. This makes karma reflect *recent* care, not an eternal balance accumulated
years ago.

The critical point: decay is merely a read weight. The original JSONL line
remains intact forever. `compute_karma` accepts `apply_decay=False` to see
the raw total, and `now` is injectable to reprocess at any date. The history
is never rewritten; only the *interpretation* of it ages.

## Personal karma vs. context vitality

There are two aggregation levels, deliberately distinct:

- `compute_karma` produces the personal operational karma: `by_dimension` (the 8
  dimensions always present), `by_context` (per context, non-zero dimensions) and
  a `total`. It is private and by dimension.
- `context_vitality` produces a collective indicator of the health of a context/page/
  circle. It combines the score-events of that context with injected operational
  indicators (`pages_meta`) into a 0-100 index. Positive indicators
  (paginas_atualizadas, aprovacoes_no_sla, fontes_recentes, insights_revisados,
  acoes_com_resultado, riscos_privacidade_resolvidos) pull the index up;
  negative ones (pendencias, paginas_orfas, responsabilidades_sem_dono) pull it
  down. The `_saturate_0_100` function saturates the result logistically so as not to
  explode, and zeroes everything that would fall below zero.

Vitality also reports `participacao_distribuida` (how many distinct actors
contributed), reinforcing that context health is something collective, not individual.
The indicators match the weights of the template in
[vitality-dashboard.md](../../../docs/references/templates/wiki/vitality-dashboard.md).

## Badges and levels

`BADGES` defines symbolic and qualitative recognitions: each `Badge` has a
testable criterion over the set of events (e.g.: Source Curator for >=5
valid sources; Privacy Guardian for >=1 detected risk; Wiki Gardener
for >=3 events with a rarity multiplier). `earned_badges` lists the
badge_ids earned. Badges describe *contribution patterns*, not relative
positions.

`LEVELS` defines the journey by increasing thresholds of total points (Explorer ->
Mapper -> Curator -> Steward -> Weaver -> Guardian -> Catalyst), and
`level_for` returns the current level. Since the total carries decay, the level reflects
living contribution, not a permanent trophy.

## How the cockpit displays karma

The cockpit [Operations](../../operations.md) has a "Karma and vitality
(gamification)" section that summarizes: total events, total karma (with decay) and a
dimension x points table. Right above it, the "Context vitality" table
shows the health index per context. All of this is generated by
[wiki_score.py](../../../scripts/wiki_score.py), never edited by hand.

The CLI has three modes:

- `--add` records an event (append-only), requiring `--event`, `--actor` and
  `--context`, and accepting `--quality`, `--collaborators`, `--rare`, `--impact`
  and `--ts`.
- `--summary` prints karma by dimension, vitality by context, badges and level.
- `--dashboard` emits the markdown of the vitality section to paste into the cockpit.

Examples of use (recording an event and generating the summary):

```sh
python3 scripts/wiki_score.py --add --event ingestar_fonte_valida \
    --actor owner --context system
python3 scripts/wiki_score.py --add --event criar_insight_aceito \
    --actor owner --context example --quality 1.0 --impact 3 --rare
python3 scripts/wiki_score.py --summary
python3 scripts/wiki_score.py --dashboard
```

The `--dashboard` closes with an explicit note: "Collective health indicator, with no
toxic global person-versus-person ranking." That is the design limit of the whole
layer: gamification in the service of care with knowledge, never competition.

## Related

- System MOC: [index.md](index.md)
- Operational cockpit: [Operations](../../operations.md)
- Ingestion process (origin of the events): [ingestion-process.md](../ingestion-process.md)
- Gates and auditing: [gates-and-audit.md](gates-and-audit.md)
- Approvals via Git: [git-approvals.md](../git-approvals.md)
