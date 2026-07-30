# Measure the first prototype budget

Type: research
Mode: AFK
Status: resolved
Blocked by: none
Owner: Codex engine-budget research thread, 2026-07-30

## Question

What existing runtime limits, supported devices, accessibility constraints and
observable metrics should bound the first integrated prototype?

The answer must cite current code and tests, distinguish enforced budgets from
aspirational documentation and recommend a deliberately smaller prototype
envelope.

## Answer

The production seam is the cockpit:

`canonical URL → hydrateWorldRoute → WorldRuntime/reducer → 3D and 2D renderers`

`RuntimeWorldView` owns one runtime instance and publishes the same semantic
state through `useSyncExternalStore`. The reducer already separates selection,
inspection, reading, view, lens, overlay and surface. Camera, hover, safe area
and visual tier remain derived presentation state. The 3D Canvas and reader are
lazy chunks, and 2D/3D parity already has fallback and mobile E2E coverage.

Existing product contracts include:

| Budget | Desktop | Mobile |
| --- | ---: | ---: |
| Interactive nodes, normal / stress | 250 / 800 | 120 / 350 |
| Visible relations | 600 | 220 |
| Labels | 80 | 35 |
| Particles | 300 | 80 |
| Target / minimum FPS | 60 / 30 | 45 / 24 |
| Usable route | 3 s | 4 s |
| Interaction feedback | 100 ms | 150 ms |

Renderer tiers are more conservative: compact uses up to 64 nodes, 80 edges and
DPR 1.15; balanced 110/200 and DPR 1.35; rich 160/320 and DPR 1.6. Mobile,
reduced motion and hardware with at most four cores select compact. General
labels are usually capped at 10–16 in overview and 24 in drill.

The adaptive fallback waits for warm-up and 120 samples, requires both median
and p95 below the floor, then latches for the session. A transient spike or a
large graph does not by itself remove 3D. What is missing is a numeric RAM/VRAM
contract: the Canvas may be suspended but remain mounted, preserving both state
and GPU memory.

Existing transfer gates are 300 kB gzip for initial JS, 300 kB gzip per lazy
chunk, 90 kB minified / 25 kB gzip for initial CSS and 20 kB gzip for initial
HTML.

The experimental gallery should remain evidence, not architecture. It uses
React, DOM, SVG, images and videos rather than Three/R3F; its views are eager,
its three world plates decode together, its public assets total about 39.8 MiB,
and cinematic files are roughly 6.6–7.8 MiB each. Its operational progress uses
local storage and synthetic receipts rather than the product runtime.

Use this smaller, provisional envelope for tickets 07 and 08:

| Walking skeleton | Desktop | Mobile |
| --- | ---: | ---: |
| Interactive 3D anchors | 96 | 48 |
| Simultaneous relations | 80 | 40 |
| Diegetic labels | 16 | 12 |
| Particles | 60 | 0 |
| Primary 2D focus surfaces | 1 | 1 |
| Target / minimum FPS | 60 / 30 | 45 / 24 |
| Feedback | at most 100 ms | at most 150 ms |

Prototype constraints:

- one persistent Canvas and one camera;
- 2D DOM anchored over the same state;
- no structural eager pre-rendered image and no video in P0;
- at most 512 kB transferred visual assets;
- recommended active decoded textures below 64 MiB desktop and 32 MiB mobile;
- pointer, keyboard, touch, reduced-motion and no-WebGL paths before polish;
- verify at 360×800, 390×844 and desktop 1280+.

The measured code sources are
`apps/wiki-cockpit/src/world/performance.ts`,
`apps/wiki-cockpit/src/scene/layout.ts`,
`apps/wiki-cockpit/src/components/RuntimeWorldView.tsx`,
`apps/wiki-cockpit/src/world/state/WorldReducer.ts`,
`apps/wiki-cockpit/src/world/input/InputController.ts`,
`apps/wiki-cockpit/scripts/bundle-gate-lib.mjs`,
`apps/wiki-cockpit/e2e/fallback-parity.spec.ts` and
`apps/wiki-cockpit/e2e/mobile-parity.spec.ts`.
