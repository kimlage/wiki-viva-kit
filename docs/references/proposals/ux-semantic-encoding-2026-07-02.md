# UX pass 2 — semantic color, richer approvals, jobs monitoring (2026-07-02)

Owner request, verbatim goals:

1. Color should NOT encode freshness. Use another visual reference for it
   (particles, borders, aging). Reserve color for something semantic —
   groupings like companies, categories, perspectives.
2. Approvals need a better interface / more information, plus a way to FIX
   failing checks with Codex.
3. A place to follow the Codex jobs and agents that are running.

## 1. Re-encoding: hue = WHO, tone = HOW

The old invariant (color = trust) spent the strongest visual channel on a
signal that already had position (freshness radius), particles (embers/stems)
and glow. Meanwhile identity — *which area is this page from?* — had no
channel at all on node bodies, even though wedge rims, group pills and horizon
beacons already used per-context accents.

New encoding, reviewed by a 3-lens judge panel (color-vision accessibility,
salience/attention routing, R3F feasibility):

- **Hue = context (area).** 12-slot palette = 6 hue anchors on the blue↔yellow
  axis dichromats retain (OKLCH 255/210/165/110/45/335) × 2 lightness tiers.
  Sorted context names get distinct slots via `registerContextPalette()`
  (deterministic per wiki, overridable per context via
  `wiki-cockpit.config.json → contexts.<name>.accent`). Reserved state accents
  (amber, purple, search cyan, risk red) are excluded from the palette. A CVD
  simulation test (Viénot protan/deutan) pins pairwise distinctness for 8
  registered contexts.
- **State = aging tone + annotations, never hue.** `agedColor()` normalizes
  each state to a fixed OKLCH lightness band so "darker = staler" holds ACROSS
  contexts (the one channel colorblind users can always trust):
  - draft/proposal ≈ L 0.82 — bleached ghost (+ floats + stem particles + gate ring)
  - fresh ≈ L 0.58 — calm band, chroma capped, **no emissive** (salience
    inversion survives: healthy is quiet)
  - stale ≈ L 0.46 — aged body **+ amber emissive pulse + glow + embers**
    (the brightness of attention comes from the annotation layer)
  - unknown ≈ L 0.35 — washed veil (opacity 0.6)
- **The trust palette survives as the state-accent language** for annotations:
  strip chips, cluster-star histograms, deadline arcs, ember/stem particles,
  2D pills. It just stopped painting node bodies.
- **Implementation:** InstancedMesh partitions stay `shape:state:dim` (keeps
  per-state emissive/opacity/pulse machinery); context hue rides per-instance
  via `setColorAt` in a `useLayoutEffect` keyed on `group.items` (no white
  flash, no interaction with the morph loop). Material base is white × dim.
- **Small sizes: state wins the pixel.** Minimap dots paint stale/draft in the
  state accent with a size bump; fresh/unknown carry the context hue. The 2D
  fallback keeps border = context but adds a TEXT state chip (WCAG 1.4.1 —
  never color alone).
- **No-motion tiers keep the cue:** stale glow static base raised to 0.5 (the
  pulse oscillates around it, never below).
- The Key popover gained a live **"Color = area"** row (context swatches +
  counts); tour + glossary prose rewritten EN+PT.

## 2. Approvals (?dock=approve) v2

- Summary chips: file count, +ins −del, branch, privacy-review flag.
- Content rows now show the HUMAN identity of each changed page — title, area,
  freshness/draft state — via a `pages.path` lookup, plus per-file risk hints.
- Checks section became per-gate rows (shared `GateChecks` component with the
  Checks dock): honest persisted status, argv, last-run time, per-gate Run.
- **Fix with Codex:** receipts persist status only, but the `POST
  /api/gates/run` response carries redacted stdout/stderr — the client type
  now keeps them. A failing gate offers "Fix with Codex", composing a `verify`
  brief (`gateFixSpec`): reproduce command, failure-output tail (≤2000 chars),
  audit state_report grounding, and the contract line *never weaken or skip
  the check itself*. Opens in the Brief studio → Execute → job.
- GatesDock (?dock=gates) uses the same rows, so both surfaces gained output +
  fix actions; its hardcoded PT gate names moved to i18n (`gate.name.*`).

## 3. Jobs monitoring (?dock=work)

- The Work tray was local React state — invisible to the router, gone on
  reload, silent when a job finished. It is now a **dock**: `work` joined the
  DOCKS whitelist, the HUD Work button navigates to `?dock=work`, deep links
  and back button work, dock/tray exclusivity preserved.
- Honest wall-clock: the runner now records `started_at`/`finished_at`
  (updated_at moves on every write, so it can serve as neither); the dock
  shows "3min 30s elapsed / finished in …" per state. Old records without the
  fields degrade gracefully.
- Log tail: renders the last 200 lines by default with "show everything"
  (whole-log DOM dumps stopped); still polls at 2s while open.
- Polling no longer stops when the ACTIVE set empties — a monitoring surface
  must not go quiet exactly when the human wants the outcome. Cancel failures
  now toast instead of failing silently. `GET /api/codex/jobs/<id>/log`
   404s for unknown jobs instead of `ok:true` + empty log.
- After **Execute** in the Brief studio the app lands on `?dock=work`:
  delegated work is watched, not fired-and-forgotten.

## Deferred (honest cuts)

- In-world 3D presence for running jobs (worker sprite orbiting the target
  context) — the dock is the monitoring surface this pass.
- A global "N jobs running" badge outside the dock (needs an app-level poll).
- Districts-perspective recoloring by page-type family (kept hue = context
  everywhere for predictability).
- Playwright visual baselines will need regeneration (`npm run
  test:visual:update`) — color change invalidates screenshots by design.
