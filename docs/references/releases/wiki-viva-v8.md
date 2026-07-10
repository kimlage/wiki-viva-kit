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
`4e4ee631d104637c744e6d3f2dbee107b24c2bab` and proposed in [draft PR #61](https://github.com/kimlage/wiki-viva-kit/pull/61).
This is reviewable release evidence, not proof of a merged/tagged stable release.

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
| `/w/districts/...` | compatibility view plus `lens=type` | Warning through v8; removal no earlier than v9. |
| `/w/trails/...` | compatibility focus/relations/evidence state around a real center | Missing page normalizes to root with warning. |
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

## Current blockers

- PR #61 still requires the human review/merge gate and a release tag.
- The private pilot remains paused until it has a clean upgrade branch,
  current gate receipts and a complete migration report.
- Six explicit stale-page/operation-date warnings remain visible after the
  deterministic operational pass; they were not reclassified as release
  errors.

## Final candidate evidence

- Python: 674 passed, 4 skipped; audit 0 errors with 6 known staleness/date
  warnings; methodology 22/22. Every command in the remote `audit-and-test`
  workflow passes locally, including operational-pass freshness.
- Snapshot: 24-payload v2 contract, deterministic demo drift and atomic
  sidecar promotion/rollback checks pass.
- Frontend: 370 unit tests across 48 files and 15 gate tests pass; architecture reports
  0 violations and 0 legacy debt.
- Bundle: initial JS 137.46 kB gzip, CSS 1.73 kB gzip and largest lazy/worker
  chunk 54.24 kB gzip, all below the committed budgets.
- Browser matrix: the last full cross-browser rerun remains 42 passed with 2
  environment-gated real-endpoint tests. The final reader delta adds explicit
  foreground/mobile/fallback regression specs and was exercised in the in-app
  browser at `917x908`, `390x844` and `1280x900` without document/shell overflow.
- Manual public browser QA covered four views, six overlays, four lenses,
  semantic motion, docks, reader, fallback and mobile. It preserved one canvas,
  had no document overflow, measured p95 12.1 ms on the normal world and proved
  atomic 400 ms overlay crossfades plus reader/Guide focus restoration. The
  redacted private read-only pass had real operator provenance, no sample
  fallback and no new console warnings.

## Superseded planning surfaces

v8 is the single release boundary. Earlier v7 living-world drafts, recursive
quadrant-center plans, modular-template implementation notes and visual-region
refactor proposals are historical input absorbed by the v8 execution plan; they
are not separate compatibility lines or independent releases.
