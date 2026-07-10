---
title: "Wiki Viva v8 release candidate"
page_id: release-wiki-viva-v8
page_type: release_note
context: system
visibility: public_candidate
updated_at: 2026-07-10
stale_after_days: 365
sources_policy: release_note
gate: github_pr
sensitive_data_policy: no_personal_data
---

# Wiki Viva v8 release candidate

Status: **release candidate / human gate pending**. The v8 payload is pinned to
`cfa32594e42e5309ebb658aa1288ae4b3cb696c1` and proposed in [draft PR #61](https://github.com/kimlage/wiki-viva-kit/pull/61).
This is reviewable release evidence, not proof of a merged/tagged stable release.
The major rendered review payload is `4e4ee631`; `3e5c0867` adds the
downstream preflight safety boundary, `5179dc5c` makes nested centers
relation-aware and `27f3b369` refreshes the deterministic snapshots against
that final portable contract. `206da2ca` keeps the same guide valid in both
demo and real-operator routes; `d2ddcb5f` closes the final downstream review by
scoping every local world to its compiler-owned members, preserving inherited
quadrant projections, fixing Focus center ownership and refining long fallback
labels; `487f7935` closes the last responsive review with one vertical fallback
scrollport and no horizontal/document overflow. `fa65d5f9` closes the final
upgrade audit by honoring wildcard-bearing portable skill allowlists, with
synthetic block-precedence coverage. `3813ff45` through `5b09ca0b` add explicit
collection membership without rewriting hierarchy, canonical action-state
authoring, nested canonical-source discovery, generic collection-capable
anchors and Node 24-backed CI actions. `2da6c73a` closes the final integrity
review: generated artifacts are idempotent, action has one schema declaration,
and scene LOD uses the full scoped-world count before strict performance QA.
`d27bf316` moves the retained browser-evidence upload to the official Node 24
action after the final CI surfaced the last deprecated-action warning.
`cfa32594` closes the P0 rendered-navigation blocker: every Alex quadrant now
contains reachable real pages, technical buckets are translated into semantic
collections with counts/descriptions/examples, group navigation cannot loop to
itself, recenter resets the lens, and the same runtime/canvas survives the
complete journey. The same payload makes the canonical action template and
demo author `action_state`, valid ownership, next action, priority/attention
basis, blockers and terminal receipts under one validated contract. It also
normalizes semantic family target IDs across the 3D and adaptive 2D renderers;
when a measured WebKit session falls back for performance, the same collection
and real-page journey remains touchable without pretending the canvas survived.

## Product boundary

v8 consolidates the cockpit into one center-relative living world:

- real pages are entities; quadrants, regions, lenses, overlays and UI surfaces
  are projections/controls;
- `WorldRuntime` and a pure reducer own semantic state and transitions;
- registered interactions distinguish inspect, select, read, recenter and
  operator execution;
- an atomic, integrity-checked snapshot envelope prevents mixed revisions;
- registries own views, overlays, surfaces, scene systems, visual primitives,
  effects, commands and typed relations;
- source lifecycle, freshness and last attempt remain separate;
- collections add typed `collection_member` edges and linked sub-worlds while
  keeping `moc_parent` as the canonical location contract;
- quadrant family handles are density controls only: each explains a semantic
  collection and reaches a reader or real center in at most two steps without
  inventing a page, stale breadcrumb or second canvas;
- action pages expose canonical runtime state, ownership, next action,
  blockers, priority and completion/cancellation receipts without discarding
  useful editorial `status` wording;
- a primary-surface contract keeps quadrant/HUD instruments behind readers and
  docks, while the reader exposes decision-ready action facts before prose;
- one semantic motion grammar drives CSS and WebGL view/lens/travel/retreat
  timing, per-entity overlay resolution, reduced-motion cuts and real surface
  enter/exit presence without remounting the world;
- static demo, localhost operator and private adapter have explicit capability
  and security boundaries.

The architecture contract is documented in
[wiki-viva-v8-runtime-architecture.md](../guides/wiki-viva-v8-runtime-architecture.md).

## Versioned contracts

| Contract | v8 version |
| --- | --- |
| Canonical route | `wiki_world_route.v8` |
| Snapshot/envelope | `wiki_web_snapshot.v2` |
| Templates/block vocabulary | `wiki_templates.v2` |
| Resolved block stacks | `wiki_web_block_stacks.v1` |
| Visual grammar | `wiki_visual_grammar.v8` |
| Semantic visual tokens | `wiki_semantic_visual_tokens.v1` |
| Runtime | `wiki_world_runtime.v8` |
| Source lifecycle | `wiki_source_lifecycle.v2` |
| Freshness payload | `wiki_web_freshness.v1` |

The authoritative machine list is
[upgrade-package.yaml](../upgrades/wiki-viva-v8/upgrade-package.yaml).

## Route migration

| Legacy input | Canonical v8 state | Compatibility |
| --- | --- | --- |
| `/w/quadrants/...` | `view=quadrants` with explicit center/lens/overlay | Read and normalize through v8. |
| `/w/radar/...` | `view=radar&overlay=freshness` | Preserve the freshness question. |
| `/w/districts/...` | `mode=compat&view=districts&lens=type&overlay=actions` | Direct links retain the legacy geometry even when native navigation hides it; no native view is falsely selected. |
| `/w/trails/...` | `mode=compat&view=trails&lens=relations&overlay=evidence` around a real center | Direct links retain the ego-graph identity; a missing page normalizes to root with warning. |
| `quadrant=<id>` | `lens=<quadrant-id>` | `lens` wins when both exist. |
| short `intencao/pratica/relacoes/sistemas` | `q1_intencao/q2_pratica/q3_relacoes/q4_sistemas` | Legacy read, canonical write. |
| `group=region:*` | real `family:*` group or ephemeral visual focus | Never written by v8. |

## Breaking and operational changes

- Components no longer own semantic navigation/transport in the native runtime.
- New docks/interactions are registry modules, not manual branches across the
  router, app shell and command bar.
- Snapshot consumers must validate revision, hashes, capabilities and schema
  versions before committing state.
- Optional reader/diagram/operator/specialized capabilities must be genuinely
  lazy and respect public bundle budgets.
- Local/private overrides extend public contracts but cannot weaken semantic,
  privacy, secret, operator or sample-fallback invariants.
- Downstream imports require an inventory, read-only preflight, portable
  allowlist, three commit boundaries, migration report, rollback point and
  redacted visual QA.

## Upgrade and rollback

Use the [v8 downstream runbook](../guides/wiki-viva-v8-downstream-upgrade.md).
Its tools validate inventory, compile preflight, enforce allowlist/blocklist and
produce deterministic JSON/Markdown migration reports. First-line rollback is
`runtime=compat`/`legacy`; second-line rollback reverts adaptation, artifact and
import commits while preserving downstream configs and memory roots.

## Compatibility window

Legacy routes, quadrant aliases and block vocabulary remain readable with
warnings through v8. Warnings become errors at the v9 release-candidate boundary
unless completed migration reports prove a blocker. Previous snapshot support
lasts one warning cycle and is removed two release cycles after v8. Legacy local
dock wiring is compat-only and targets removal in v9 stable.

## Required release evidence

The release owner must record one exact source SHA and pass:

```sh
/opt/anaconda3/bin/python scripts/wiki_audit.py --check
/opt/anaconda3/bin/python scripts/wiki_check_methodology_coverage.py --check
/opt/anaconda3/bin/python scripts/wiki_operation_compile.py --check
/opt/anaconda3/bin/python scripts/wiki_input_stage.py --check
/opt/anaconda3/bin/python scripts/wiki_build_demo.py --check
/opt/anaconda3/bin/python scripts/wiki_web_snapshot.py --check-contract
/opt/anaconda3/bin/python -m pytest tests/
npm --prefix apps/wiki-cockpit run test
npm --prefix apps/wiki-cockpit run build
npm --prefix apps/wiki-cockpit run check:architecture
npm --prefix apps/wiki-cockpit run check:bundle
git diff --check
```

Desktop Chromium, mobile WebKit, forced fallback and Firefox smoke evidence are
also release blockers. A green unit/build stack cannot override a runtime crash,
blank world, center error, overlap, unreadable label or sample fallback.

## Remaining external gate and known warnings

- PR #61 still requires the human review/merge gate and a release tag.
- Three explicit stale-page warnings remain visible after the
  deterministic operational pass; they were not reclassified as release
  errors.

## Final candidate evidence

- Python: 705 passed, 4 skipped; audit 0 errors with 3 known staleness
  warnings; methodology 22/22. Every command in the remote `audit-and-test`
  workflow passes locally, including operational-pass freshness.
- Snapshot: 24-payload v2 contract, deterministic demo drift and atomic
  sidecar promotion/rollback checks pass.
- Frontend: 393 unit tests across 51 files and 15 gate tests pass; architecture reports
  0 violations and 0 legacy debt.
- Bundle: initial JS 139.07 kB gzip, CSS 1.73 kB gzip and largest lazy/worker
  chunk 53.87 kB gzip, all below the committed budgets.
- Browser matrix: 55 passed with 2 environment-gated real-endpoint skips across
  57 scenarios. A dedicated clean Chromium performance project passes both
  normal and dense windows under the strict 33.33 ms p95 budget. The P0 Alex
  journey also passed three consecutive focused repetitions and exercises all
  visible Q1-Q4 pages/groups, native mouse/keyboard/focus behavior, collection
  explanation, reader/recenter, breadcrumb/lens, no loop and one persistent
  canvas. Mobile WebKit proves the same two-step path and mission foreground at
  `390x664`; the in-app Browser covered `1280x900` and `390x664` with no
  document/shell overflow.
- Manual public browser QA covered four views, six overlays, four lenses,
  semantic motion, docks, reader, fallback and mobile. It preserved one canvas,
  had no document overflow, measured p95 12.1 ms on the normal world and proved
  atomic 400 ms overlay crossfades plus reader/Guide focus restoration.
- Downstream pilot: portable source `cfa32594`; the prior private proof at
  `fa65d5f9` had toolkit drift 0 and a real snapshot v2
  with 24 payloads and complete private/redacted-public migration reports with
  zero validation errors. Redacted desktop, mobile and fallback evidence uses
  real operator provenance, no sample fallback, clean console/network state
  and exactly one fallback scroll axis across 560 real pages.

## Superseded planning surfaces

v8 is the single release boundary. Earlier v7 living-world drafts, recursive
quadrant-center plans, modular-template implementation notes and visual-region
refactor proposals are historical input absorbed by the v8 execution plan; they
are not separate compatibility lines or independent releases.
