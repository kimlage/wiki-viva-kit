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
`dbd158a482dca20ab823968467fec931d67ca050` and proposed in [draft PR #61](https://github.com/kimlage/wiki-viva-kit/pull/61).
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
`b942735f` closes the real short-mobile hit-collision blocker found during the
final in-app Browser audit. It preserves the five disjoint 44 px semantic
landmarks introduced by `39b28fe8`, and extends the regression to a dense
synthetic center with repeated families across quadrants and multiple families
inside Q2. In both worlds, the visual hit target resolves to the intended
group and every mouse/keyboard activation preserves quadrant, breadcrumb,
collection and the same runtime/canvas. Resolved Markdown links remain proven
by mouse and keyboard without remounting the world.
`1d801f1c` closes the source-hierarchy integrity blocker discovered in the
in-app Browser: generated ingestion events now use their canonical source page
path, or the canonical source ID fallback, as `moc_parent`. The source registry
therefore remains a source-only collection instead of flattening normalized
events into its hierarchy.
`a483ad02` closes the final reader-navigation P0 discovered while traversing
registry -> source -> event: the persistent reader resets its internal
scrollport before each page paints, and wide Markdown tables remain readable in
an accessible, keyboard-focusable horizontal scroll region without creating
document overflow or per-character wrapping.
`d4a3c890` closes the remaining tall-mobile P0 found at `390x844`: semantic
group landmarks keep disjoint 44 px native controls and stable per-quadrant
lanes on both short and tall phones, including repeated families in real
downstream worlds. The regression covers both heights, hit-testing, overflow,
collection progress and canvas continuity.
`f7f95119` closes the WebKit/Linux route race found by remote visual CI: a
query debounce can no longer replay the pre-close Create dock over an
Enter-opened reader. The submitted marker is bounded to the uncommitted query,
stays active for that exact draft until a genuine edit, and is never retained
when the query had already committed, so the same search remains reusable.
`877b586b` closes the desktop counterpart of the semantic-group blocker found
in the final downstream Browser audit. Stable quadrant/family lanes keep every
full explanatory group target disjoint at `1280x900`, including repeated Q2
families and the Q4 area/content pair, while preserving the same phone contract
at `390x664` and `390x844`. The regression waits for the authored spatial
transition to settle, then proves pairwise geometry, native hit ownership,
mouse/keyboard collection progress, breadcrumb/lens truth, no document scroll
and one persistent canvas in the instructional and dense synthetic worlds.
`dbd158a4` closes the final adaptive-fallback blocker surfaced only by the
private Linux/WebKit run. Phone offsets authored for projected 3D labels are
now explicitly disabled for the semantic 2D map, so `family:source` and
`family:event` remain untransformed, scrollable and touchable after the measured
`performance_budget` transition. The strengthened test preserves the scene
shell, accepts only a one-way canvas-to-map change, waits for outgoing
reader/collection surfaces, and revalidates every Q2 target in the active
renderer rather than assuming the session stayed in 3D.

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

- Python: 706 passed, 4 skipped; audit 0 errors with 3 known staleness
  warnings; methodology 22/22. Every command in the remote `audit-and-test`
  workflow passes locally, including operational-pass freshness.
- Snapshot: 24-payload v2 contract, deterministic demo drift and atomic
  sidecar promotion/rollback checks pass.
- Frontend: 395 unit tests across 51 files and 15 gate tests pass; architecture reports
  0 violations and 0 legacy debt.
- Bundle: initial JS 139.11 kB gzip, CSS 1.73 kB gzip and largest lazy/worker
  chunk 53.88 kB gzip, all below the committed budgets.
- Browser matrix: 57 passed with 2 environment-gated real-endpoint skips across
  59 scenarios. A dedicated clean Chromium performance project passes both
  normal and dense windows under the strict 33.33 ms p95 budget. The P0 Alex
  journey also passed three consecutive focused repetitions and exercises all
  visible Q1-Q4 pages/groups, native mouse/keyboard/focus behavior, collection
  explanation, reader/recenter, breadcrumb/lens, no loop and one persistent
  canvas. Mobile WebKit proves the same two-step path and mission foreground at
  `390x664`; the short-mobile regression additionally proves disjoint semantic
  group targets in both the instructional and dense repeated-family worlds,
  correct `elementFromPoint`, focus, route, lens, breadcrumb, collection and
  canvas identity. The final regression also measures both instructional and
  repeated-family dense worlds at `1280x900`: every full explanatory label is
  disjoint, hit-owned by its intended native button and inside the viewport.
  The in-app Browser covered `1280x900`, `390x664` and `390x844` with no
  document/shell overflow.
- Manual public browser QA covered four views, six overlays, four lenses,
  semantic motion, docks, reader, fallback and mobile. It preserved one canvas,
  had no document overflow, measured p95 12.1 ms on the normal world and proved
  atomic 400 ms overlay crossfades plus reader/Guide focus restoration.
- Downstream pilot: portable source `dbd158a4`; the prior private proof at
  `fa65d5f9` had toolkit drift 0 and a real snapshot v2
  with 24 payloads and complete private/redacted-public migration reports with
  zero validation errors. Redacted desktop, mobile and fallback evidence uses
  real operator provenance, no sample fallback, clean console/network state
  and exactly one fallback scroll axis across 560 real pages.
  The controlled private refresh to `dbd158a4` passes the complete local
  desktop/mobile/fallback/Firefox matrix against 561 real pages and remains
  behind the remote and human evidence gates
  in PR #208; no private content is claimed by this public candidate.

## Superseded planning surfaces

v8 is the single release boundary. Earlier v7 living-world drafts, recursive
quadrant-center plans, modular-template implementation notes and visual-region
refactor proposals are historical input absorbed by the v8 execution plan; they
are not separate compatibility lines or independent releases.
