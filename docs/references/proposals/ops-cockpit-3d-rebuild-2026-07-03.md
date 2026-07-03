# The Operations Cockpit — 3D-first rebuild (plan)

**Status:** proposal (no code yet) · **Date:** 2026-07-03 · **Kit-first, then private, PR-gated.**

## 0. Why

The cockpit drifted into a **menu-and-docks** app with a 3D backdrop. The
things that matter — the data sources, the four quadrants, the health of the
wiki, the pending approvals — got pushed into a left rail and side panels. The
3D world became decoration.

This plan flips it: **the 3D world IS the interface.** A real operations
cockpit where you *operate* your wiki. Sources are objects you fly to; the four
AQAL quadrants are the persistent skeleton of the world; health is the world's
weather; approval is a pending glow; creating a page is a gesture in space. The
left menu dies.

### Owner decisions (locked 2026-07-03)

1. **The four quadrants become a persistent spatial frame** — the world is
   always divided into Intenção (q1) / Prática (q2) / Relações (q3) / Sistemas
   (q4); every page and source has a home region; you navigate *by* quadrant.
2. **Kill the side menu** — sources become objects in the world (Sistemas
   region), health becomes the ambient condition/weather, approval becomes
   glowing pending objects acted on in place; only a minimal command bar stays.
3. **A bold rebuild into a professional 3D operations cockpit.** Plan first,
   then implement kit-first behind the PR gate.

Plus three concrete asks: the **source template must be rich enough to fully
configure and sync a source**; **page templates + creation are TERRIBLE** and
must be reworked; the **buttons look unprofessional** (the "Atualizar com Codex"
mission button, etc.).

### The non-negotiable contract (unchanged)

Everything below obeys the honest-encoding contract that already governs the
scene: **no visual may imply data that does not exist**; layouts are **pure,
deterministic, worker-computable** (snapshot clock, never wall-clock; positions
`toFixed`-rounded); every ambient signal traces 1:1 to a real count; EN+PT
parity; PR-gated writes. The red-team below **killed** several attractive ideas
precisely because they violated this. Two of those kills are load-bearing and
called out in §6.

---

## 1. Pillar A — The Quadrant perspective

**Quadrants are a first-class perspective, not the fixed frame** (owner decision
2026-07-03: keep them as *one of the perspective options*, alongside Radar/
Atlas/Districts/Trails — **Radar stays the default landing view**). Switching to
the `quadrants` perspective (key **5** / a command-bar glyph) carves the ground
plane into four **fixed 90° AQAL regions** with diegetic ray separators and
always-four rim labels, plus an explicit central **q0-core disc** for structural
pages that honestly have no quadrant. This makes the quadrants **discoverable and
navigable** (fixing the original "não vejo os quadrantes" complaint — today Focus
only opens with a page locked + `F`) without displacing the muscle-memory of the
default view.

### Why it stays honest

- **Radius means shelf-depth, not freshness.** Inside a hard-fixed 90° sector,
  radius cannot double-encode both the freshness deadline *and* a within-sector
  fan without lying (a mid-radius node would read as "near deadline" when it is
  just mid-fan). So the quadrant home map uses `radial: "shelf"` (like
  Districts): radius = family-shelf depth, freshness stays on **tone**
  (`agedColor`) where it already lives. The deadline ring + "sem dados" band stay
  exclusive to Radar. We factor the shelf sub-layout out of `districtsLayout`
  into a shared `familyShelfSubLayout(...)` so both use identical honest math.
- **Structural pages go to a labeled core, not a fake quadrant.**
  `homeQuadrant(pageType)` returns `PAGE_TYPE_FACET[pt]` — already `null` for the
  ~200 structural nodes (root/hub/index/registry/log). We do **not** invent a
  non-null fallback (rejected: forcing them into Sistemas is a lie). Null-home
  nodes render in the q0-core disc, explicitly labeled **"Estrutura / Core."**
- **The frame never shrinks.** Four 90° regions are constant even when a
  quadrant is sparse (an empty quadrant shows a dimmed rim pill + its ray, count
  0 — honest absence). The q0-core group is emitted **only when populated** (the
  core is not a fifth quadrant).

### Mechanisms

- `homeQuadrant(pageType): SceneFacet | null` in `scene/facets.ts` (mirror
  `home_quadrant(page_type)` in `wiki_core/facets.py = facet_of(pt, None,
  overrides)`); `QUADRANT_CENTER_ANGLE` exported so layout, compass and minimap
  place sectors from one source.
- `quadrantsLayout(request)` in `perspectives.ts`: fixed 4×90° + q0-core,
  `radial:"shelf"`, `familyShelfSubLayout` per region, `splitBudget` over the
  five region sizes, one `ClusterStar` per region (true hidden count +
  histogram), four `ray` guides, four `kind:"quadrant"` groups always + a
  conditional core group.
- New: `"quadrant"` in the `GroupKind` union; `quadrant?: SceneFacet` on
  `WorldRequest`/`WorldLayout`/`WorldRoute`; `cameraTarget?` on `WorldLayout`
  (region centroid for fly-to).
- Dispatch: `computeWorldLayout` routes `perspective==="quadrants"`; **append it
  as the fifth entry of `PERSPECTIVE_ORDER`** (bare key 5; radar stays 1 and the
  default; atlas/districts/trails stay 2–4; focus stays page-only). **Bare 1–N
  stays perspective-switch** (rejected: rebinding keys to quadrant-fly-to breaks
  muscle memory); inside the quadrants perspective, `Q/W/E/R` (free at L0) fly to
  the four quadrants.
- **Lenses fold in, selectively.** `radarLayout` and `districtsLayout` scope to
  `request.quadrant` (filter to home-quadrant nodes) so "Radar within Sistemas"
  works. `atlasLayout`/`trailsLayout` **ignore** the quadrant filter — a page's
  `moc_parent` or ego-neighbor legitimately lives in another quadrant, and
  scoping them would fake orphans.
- **Cross-quadrant relations** render only on hover/lock: the one active node's
  typed 1-hop edges as center-bowed béziers colored by edge type (capped to one
  node to bound axis-cross clutter).
- HUD: a `QuadrantCompass` (2×2, live shown/total + attention dots,
  click-to-fly) in `WorldView`; a `quadrants` glyph in the command bar; the
  minimap's drill target carries `{quadrant}` (today it only drills on
  `group.drill.context`).
- URL: a **`?quadrant=<facet>` query param** (O1, decided) carried in
  `WorldQuery`, meaningful only under `perspective==="quadrants"`;
  `patchWorld`/`retreat` learn that quadrants may carry a quadrant without a
  context (retreat pops quadrant → galaxy). Defaults are unchanged — `/`, `/ops`,
  `/w` stay `radar`.

### Phasing (A)

- **A0** — pure seed: `homeQuadrant` + `home_quadrant` + `QUADRANT_CENTER_ANGLE`
  + parity tests (a type per quadrant, a structural type → null, front/back
  agreement). No scene change.
- **A1** — layout: factor `familyShelfSubLayout`; implement `quadrantsLayout`;
  add to `PERSPECTIVE_ORDER` + dispatch. `perspectives.test.ts` pins: always
  four quadrant groups, core group only when populated, fixed 90° regardless of
  population, counts over ALL home nodes, exact hidden counts, determinism.
- **A2** — routing: `quadrant` on route/request/layout, `?quadrant=<facet>`
  parse, `patchWorld`/`retreat`. **Radar stays the default** (no landing change);
  `quadrants` is reachable via key 5 / the glyph.
- **A3** — scene: `cameraTarget` fly-to + top-down preset; render the frame;
  wire minimap + compass + command-bar glyph (5th) + `Q/W/E/R`.
- **A4** — scope radar+districts to the active quadrant; leave atlas+trails
  unfiltered (documented + tested).
- **A5** — cross-quadrant hover/lock arcs; i18n EN+PT; tour copy ("quadrants =
  where everything lives; focus = one page's own cross").

---

## 2. Pillar B — Diegetic operations (kill the menu)

**Everything the menu did becomes the world.** One pure selector drives every
ambient channel; Health/Gates/Approval/Sources/Work stop being destinations.

### The spine — one pure condition

`scene/condition.ts` → `computeCondition(bundle, activeJobs): WorldCondition`,
pure and unit-pinned (like `facets.ts`/`presentation.ts`), no wall-clock. Shape:

```
{ weather: 'clear' | 'aging' | 'unverified' | 'blocked';
  freshRatio; staleCount; unknownCount;
  gatesFailing: string[]; gatesNotRun;
  pendingApproval; pendingSourceIntake; agentsActive }
```

Every field traces 1:1 to a real bundle field; `condition.test.ts` asserts no
field can be non-zero without a corresponding real count. It lives in `scene/`
(shares the scene's purity contract) but is **not** part of `computeWorldLayout`
— worker determinism is untouched.

### What each surface becomes

- **Health → weather.** `condition.weather` feeds the existing `StarField`
  density + a global fog/vignette tint. It **never** touches per-node
  `instanceColor`/`agedColor`/`emissive` (hue=context, tone=aging stay
  sovereign). The tint is *only* allowed because an honest **Condition strip** in
  the top HUD prints the exact counts beside it (numbers-beside-art).
- **Approval → in-place glow.** Changed **memory** pages glow purple always (not
  only when a dock is open) and each glowing node's `TargetLock` ring gains an
  act (read diff / packet / open review). Approval stops being a place.
- **Gates → a world condition + inline fix.** A failing gate sets
  `weather="blocked"` and a center-ring act point that runs the gate + shows
  output + composes a fix (the `GateChecks` per-gate block, extracted reusable).
  The `GatesDock` destination is removed.
- **Sources → glowing objects** in the Sistemas region (Pillar C).
- **Agent work → visible activity.** `listCodexJobs` polling lifts into
  `WorldView` (reusing WorkDock's interval, only while jobs active + capability
  usable); running jobs flow-pulse on their brief's `grounding.page_ids`
  resolved to on-screen nodes; a delivered job flips its target to the purple
  approval glow. `WorkDock` survives as a **deep-linkable monitor**.
- **The command bar** replaces the rail: search + perspective glyphs + the
  Condition cluster + one Ops tray toggle (packet/work/missions tabs). The `Nav`
  rail and `dockHref` plumbing are deleted; `/review`, `/health`, `/sources`
  redirects and `?dock=` deep links still resolve into the world with the act
  point focused.

### Phasing (B)

- **B0** — `scene/condition.ts` + `condition.test.ts` (count→weather mapping +
  the worktree-scoped approval filter). Green before any R3F change.
- **B1** — honest approval glow in place (drop the dock guard, **add the
  worktree filter** — see §6) + `TargetLock` act on a glowing node.
- **B2** — Condition HUD strip + rewire `activityLevel` to
  `condition.agentsActive` + weather tint (CVD-guarded). Numbers land before any
  menu is removed.
- **B3** — agent work visible (poll lift, flow-pulses, delivered→glow; absent
  target pages become a horizon beacon, never dropped).
- **B4** — gates + sources as act points; remove `GatesDock`.
- **B5** — delete the `Nav` rail + collapse trays into one Ops toggle; keep all
  redirects + `?dock=` deep links; update `App.visual.test`/`router.test`.
- **B6** — polish + demo parity (532-page legibility; demo reflects condition
  offline, no Codex, no cross-link into the real snapshot).

---

## 3. Pillar C — The rich source template + "Sincronizar com Codex"

### The load-bearing correction (read this)

The Codex sandbox runs **network-off** under `workspace-write`
(`codex_jobs.py:62`). A sandboxed job **physically cannot reach Slack/Drive/
Gmail** to pull live data. So **"Sincronizar com Codex" must NOT mean "Codex
fetches from the network"** — that would be a UI implying an action the system
cannot do. It means:

> Codex composes the deterministic **ingest plan** against the recipe + the
> **RAW the operator already exported** (the Drive raw-cache / export file the
> recipe's `how_to_export` + the raw-drive skill describe), **integrates** it
> into the target pages, and **advances the per-stream cursors after commit**
> (F8) — all inside the always-draft PR.

The **live fetch stays operator-side** (the MCP/CLI the auth pointer names, or a
manual export). This is the single honesty correction that makes the pillar
real. See Open Question O3 — this is an owner decision to confirm.

### Rich recipe v2 (additive on `wiki_source_recipe.v1`)

Keep the same `schema_version` (parse is lenient, validate is a separate pass —
a hard `.v2` would force-migrate every config page for no gain). Add
**optional** fields in `wiki_core/source_recipe.py`:

- `AuthPointer { method: env|keychain|onepassword|oauth_file|mcp|none, ref,
  scopes, note }` — a **pointer only, never a secret**. The existing
  `_SECRET_KEYS`/`_SECRET_VALUE` scan over `recipe.raw` already rejects a pasted
  token as both key and value; add a soft guard (warn when `method==env` and
  `ref` is not `UPPER_SNAKE`; warn when `mcp`/`keychain` `ref` looks like a
  URL/blob).
- `StreamFilter { since, until, query, labels, include_threads, max_units }` per
  stream (typed), plus a per-stream `cadence_days` override.
- `SyncSchedule { mode: on_demand|recurring|event_driven, cadence_days,
  cron_hint }`.

`validate_recipe` extends (same pass): known `auth.method`; `ref` required when
`method!=none`; ISO sanity on filter dates; `max_units>0`; per-stream
`cadence_days>0`. Read model (`web/sources.py`) threads `auth`
(method+ref+scopes+note, **never a value**) and `schedule`, computes
`next_due_days`, and honors the per-stream cadence override with the existing
pipeline-cadence fallback (both paths test-pinned).

### Fix the drifted templates

`docs/references/templates/wiki/source.md` still uses the stale
`ingestion_state`/`refresh_policy` block — it does **not** emit the `sync:` block
+ `config_ref` the read model reads, which is why a freshly-scaffolded source can
read "never." Rewrite it to the machine identity the read model actually
consumes; rewrite `source-config.md` prose into an authored recipe-v2 YAML with
per-platform examples (slack via mcp, drive via oauth_file, web via none).

### The flow

- The **enriched brief** (`compose_source_brief_spec`) enumerates, per stale
  stream, its filters + target pages; one auth line ("read the token from
  `<method>` `<ref>`; if absent, STOP and report"); the deterministic
  `ingest_argv` + `mcp_hint`; and an explicit **"network is OFF in the sandbox —
  ingest the already-exported RAW; do not attempt a live fetch"** line; plus the
  existing F8 write-after-commit line.
- **One click:** `syncSourceWithCodex(sourceId)` = compose → save brief → submit
  Codex job (dry-run) → `?dock=work`; every hop surfaces `ok:false` (Codex-
  unusable degrades honestly).
- **In world (minimal):** a source node's existing `GlowSprite` shows a stale
  tone from `breached`/`pending_streams` and a running pulse from the live
  `ingest-<source_id>` job — via the bounded `sceneShell`, no new draw call, no
  hue/radius change.
- **Console (`SourceDock` detail):** a read-only auth-pointer row (method + ref
  badge + lock glyph + "pointer only" tooltip, **no value field**); schedule +
  `next_due_days`; the primary action renamed **"Sincronizar com Codex."**

### Phasing (C)

C1 backend data model (additive, tests) → C2 template rewrites (round-trip a
scaffolded source through `build_sources_payload` with correct freshness) → C3
enriched brief + one-click + auth-row + i18n → C4 in-world glow (532-page scale
check). **Deferred:** editable-in-console recipe (per-row toggles, cadence
steppers, filter drawer) writing YAML back through the PR-gated `/pages` PUT.

---

## 4. Pillar D — In-world creation + page templates

Creation today is a raw-slug dropdown that **silently fails** (`IntakeDock:147`
passes `--page-type`; the CLI wants `--type`). Rebuild it as **"Semear no
quadrante"** — a diegetic gesture where the type drives everything.

### The flow

1. A single **`+` "Semear"** affordance in the command bar enters CREATE mode.
2. CREATE mode is a **perspective-independent overlay** (reuses `GroupRimPills`
   geometry + the `SCENE_FACETS` angular partition — **not** the Focus sectors,
   so it works under any perspective without redefining what radius means)
   highlighting the four quadrant wedges. Clicking a quadrant filters the type
   palette.
3. The palette lists only `page_type`s whose **home quadrant** matches, each
   rendered as its true `scene.shape` glyph + registry label (shape=kind) —
   killing the raw-slug dropdown. Structural (null-home) types are excluded.
4. Selecting a type plants a **translucent proposal-tone seed** in that quadrant
   at a fixed nursery radius — a **scene overlay** (like `GlowSprites`), **never
   a `LayoutNode`** through `computeWorldLayout`, so worker determinism holds.
5. A **mold panel** (the template experience that beats a dropdown) built purely
   from `templateSpec(bundle, pageType)`: the pinned fields become **fillable**
   rows grouped under their facet-lens headers (reusing `TemplateInspector`'s
   rendering, now editable), a title, a context picker, and the `body_template`
   as the "mold provenance" line.
6. Submit composes a first-class **`create` brief** (`mission_kind: "create"` in
   `briefs.py`, typed grounding `{page_type,title,context,home_facet,pinned}`,
   secret-scanned) whose renderer emits the **correct** command
   `python3 scripts/wiki_new.py --type <pt> --title <title> --context <ctx>` +
   a "set these pinned fields, never invent" block. PR-gated.
7. **Predicted-id reconciliation:** the client derives
   `f"{page_type}-{slugify(title)}"`; when the next snapshot carries that id the
   ghost reconciles away and the real node MORPHs in at the same quadrant.

### Phasing (D)

- **D0** — one-line fix: `IntakeDock` `--page-type` → `--type` (creation stops
  silently failing). Ships alone, immediately.
- **D1** — backend: `home_facet` in the contract; `create` mission_kind + typed
  grounding + secret-scan + renderer; `BriefSpec.grounding` in lockstep; parity
  + normalize/render tests.
- **D2** — `CreateDock` via `?dock=create`: quadrant-filtered glyph palette +
  fillable mold form from `templateSpec`; route the old dropdown into it and
  delete it.
- **D3** — the in-world gesture: `+` affordance + CREATE-mode quadrant overlay +
  translucent seed (deep-linked so it survives reload).
- **D4** — close the loop: predicted-id reconciliation, ghost expiry on job
  completion / after N snapshots.
- **D5 (optional)** — `--set field=value` in `wiki_new.py` so pinned values land
  at scaffold time and the page is green on first commit.

---

## 5. Pillar E — Professional visual system

544 hardcoded hex, zero CSS variables, the reserved state colors retyped by
hand, 18 button classes, duplicate `.missionRow` blocks. The chrome looks
amateur and can silently collide with the data encoding.

- **Token spine.** Prepend a static `:root{}` header to `styles.css`: a neutral
  ramp (`--surface-0..3`, `--ink-1..4`, `--line-1/2`), the **state colors
  aliased by-value from `presentation.ts` `DEFAULT_TRUST_COLORS`** (with a
  `presentation.test.ts` drift-pin so HUD tokens and the 3D scene provably never
  diverge), and space/radius/type/motion scales. **Context hue stays scene-only**
  (it lives in `instanceColor`; the HUD never needs a per-context var — this
  also avoids the mis-ordered boot-time injection the red-team caught).
- **One `.btn` system** — `--primary` (filled cyan) / `--secondary` (outline) /
  `--ghost` (text) × `--sm`/`--md` × `--hud`/`--world` surface × `--run`
  (Codex-cyan pulse) / `--danger` (risk red) — replaces all 18 legacy classes.
  Concretely: rewrite `.actionButton` (the lime "candy pill"); the **"Atualizar
  com Codex"**, gate-run, and compose-brief buttons all become
  `.btn--secondary.btn--sm.btn--run` — **cyan, not purple**, so a delegated-agent
  action never reads as pending-approval (that purple is reserved). Delete the
  duplicate `.missionRow`/`.missionRowMain` blocks.
- **The QuadrantFrame overlay** (Pillar A's rays + rim labels) renders at OKLCH
  `C<=0.02` near-neutral tints, CVD-guarded, with the honest "unaligned" core —
  it must be distinct from amber/purple/cyan/risk-red on the near-black void
  (Open Question O5).
- **The WorldWeather driver** (Pillar B) tints **only** fog/void, never node
  color/emissive/radius, clamped and reduced-motion-pinned, always beside a
  literal count + `weatherReason` (EN+PT).

### Phasing (E)

E0 delete duplicate `.missionRow` blocks (snapshot-guarded) → E1 static `:root`
tokens + drift-pin → E2 the `.btn` system, worst offenders first
(`.actionButton`, the `--run` buttons) → E3 incremental hex→`var()` migration,
token-group by token-group (never one sweep) → E4 the QuadrantFrame overlay +
CVD guard → E5 the WorldWeather driver → **E6 (separate PR, deferred)** angular
quadrant-bias that actually relocates nodes toward their bearing.

---

## 6. Two load-bearing honesty corrections

The red-team killed several attractive ideas for lying to the operator. Two are
critical and shape the whole build:

1. **Approval glow must be worktree-scoped.** `bundle.diff` is a
   **branch-vs-default** compare. Kim's private cockpit lives permanently on a
   long-lived proposal branch, so "glow every changed memory page" would light
   up **hundreds** of already-committed pages as "pending approval." The glow +
   `pendingApproval` must filter to `file.category==="memory"` **and**
   `change_sources` includes `working_tree`/`staged` (genuinely local,
   unreviewed edits) — the same honest signal the top-bar pill now uses.
2. **"Sync with Codex" is compose-and-integrate, not live-fetch** (§3). The
   sandbox has no network; the brief ingests operator-exported RAW and advances
   cursors, never claims to pull from Slack/Drive.

---

## 7. Unified sequencing

Land in this order so each step is shippable and low-risk. Foundations (pure,
tested, no pixels) first; the menu is removed **last**, only after its
replacements are proven.

1. **Foundations** — A0 (home quadrant seed) · B0 (condition selector) · D0
   (`--type` fix) · E0/E1 (dedupe + tokens). All pure/mechanical, fully tested.
2. **The frame** — A1–A3 (quadrantsLayout + routing + scene + compass). The
   world gains its skeleton; quadrants become visible and navigable.
3. **Diegetic signals** — B1–B3 (approval glow worktree-scoped, Condition strip,
   weather, agent work) + E2 (buttons). The world starts *reading* as an ops
   surface.
4. **Sources + creation** — C1–C4 (rich recipe + sync) · D1–D4 (seed-in-quadrant
   create). The two operator workflows become first-class in-world.
5. **Kill the menu** — A4 (lens scoping) · B4–B5 (gates as act points, delete
   the rail) · E3–E5 (hex migration, frame overlay, weather). The rail dies once
   every destination lives in the world.
6. **Polish + cascade** — B6 · E6(deferred) · adversarial review · docs · then
   cascade code to the private wiki (owner's gate).

Each phase: kit-first, `pytest`+`vitest`+`tsc`+build+`wiki_audit` green,
browser-verified, PR-gated. Estimated in cockpit-days, not calendar promises.

---

## 8. Owner decisions (resolved 2026-07-03)

- **Quadrants placement:** NOT a fixed/default view — a **first-class
  perspective option** (key 5) alongside Radar/Atlas/Districts/Trails. Radar
  stays the default. (Updates Pillar A above.)
- **O1 — Quadrant URL:** **`?quadrant=<facet>` query param** (consistent with the
  other `WorldQuery` params).
- **O2 — q0-core geometry:** implementer's call — plan to lift the core disc
  slightly off the plane to clear the axis-cross HUD + any central root node,
  tuning against real render.
- **O3 — Source sync model: CONFIRMED.** "Sincronizar com Codex" = compose the
  ingest plan + integrate the operator-exported RAW + advance cursors
  (network stays operator-side), never a live sandbox fetch. (Confirm the
  exported-RAW location convention — the Drive raw-cache path — during C3.)
- **O4 — Structural types' editorial home:** ship the pure `null → core` default
  AND **let the wiki override** it via the template registry (a per-type
  `home_quadrant:` override), so a wiki can editorially place e.g. `context_note`
  in Relações.
- **O5 — Quadrant tints:** **test it during implementation** (E4) — verify four
  tints stay both CVD-distinct from amber/purple/cyan/risk-red AND visible at
  `C<=0.02` on the near-black void; if not, lean on position + labels and drop
  the tint.
- **O6 — Node movement:** ship the frame as a **view** (nodes placed into regions
  by `quadrantsLayout`) now; **defer** the angular-bias that relocates nodes
  toward their bearing inside other perspectives to a later separate PR.

---

*Produced from a design workflow (architecture map → two divergent proposals per
pillar under a game-UX and an information-architect lens → red-team synthesis).
No code has been written; this document is the contract to review before any
implementation.*
