---
title: "Plan - 3D-first navigation, perspectives and the in-world reader"
page_id: plan-cockpit-3d-navigation-2026-07-01
page_type: methodology_plan
aliases:
  - Cockpit 3D navigation plan
  - Perspectives and drill-down plan
  - In-world reader plan
tags:
  - wiki/methodology
  - wiki/operations
  - wiki/interface
  - wiki/threejs
  - status/plan
date: "2026-07-01"
status: plan
context: system
visibility: private_reference
related_pages:
  - docs/references/proposals/threejs-operational-dashboard-plan-2026-07-01.md
  - memories/system/wiki/architecture.md
  - memories/system/wiki/daily-operation.md
target_version: "wiki-viva v7.1 candidate"
audience: "wiki-viva maintainers, downstream wiki owners and implementation agents"
scope: "design plan for making the 3D scene the primary navigation surface: drill-down levels, multiple perspectives, and an in-world content reader"
---

# Plan - 3D-first Navigation, Perspectives and the In-World Reader

Updated on: 2026-07-02.

> Implementation status (2026-07-02): phases 0–5 implemented in the kit —
> pushState router with the `/w/:perspective/:context?/:group?/:pageId?`
> grammar, `GET /api/pages/{id}/content` + static content sidecars, the
> PageReader dock (marked + DOMPurify), the four worker-computed perspectives
> with per-level caps and honest cluster-stars, camera choreography
> (WARP/RETREAT/FOCUS/MORPH), full keyboard scheme, minimap, quick-action
> ring, sealed `/demo` universe and retired `/pages` (alias redirects kept).
> Verified by unit (vitest), e2e (Playwright, incl. keyboard-only loop),
> pytest and a 45-agent navigation audit whose 34 confirmed findings were
> fixed. Timeline and provenance-river perspectives remain deferred.

This plan is the product of a deep critical audit of the cockpit's pages,
cards and navigation, commissioned after the freshness radar shipped. The
owner's brief, translated:

> "Keep the experience inside the 3D visual. Content pages are truncating and
> it is confusing to navigate and understand what is happening. Think
> futuristic, game-like navigation. Today's perspective works for verifying
> updates but not for navigation, identification and context exploration —
> add drill-down navigation and grouping to navigate categories and different
> perspectives/views."

It extends (and partially supersedes the navigation sections of) the
[Three.js operational cockpit plan](threejs-operational-dashboard-plan-2026-07-01.md).
The honest-encoding contract of that plan is untouched and non-negotiable:
**color = trust state, shape = content kind, line = typed relation**, and no
visual may imply data that does not exist.

## North star

The cockpit becomes one continuous, navigable 3D knowledge world — a star-map instrument where the space itself is the navigation. The same 532 node identities are re-arranged by four deterministic, worker-computed perspectives (Radar for verification, Atlas for hierarchy navigation, Districts for type identification, Trails for context/provenance exploration), each sharing the non-negotiable encoding invariants (color=trust, shape=kind, line=relation). Drill-down is camera altitude bound to the URL — galaxy, context, group, page — so the browser back button, breadcrumbs and deep links are all the same thing. Reading happens inside the world: target-locking a node opens a docked holo-reader with fully rendered markdown whose wiki-links fly the camera instead of leaving the app. The freshness radar is demoted from "the app" to one perspective among four; the detached 2D content pages die, replaced by the in-world reader (which doubles as the first-class 2D/reduced-motion fallback). Everything stays honest: every count is a true total, every hidden page is countably represented and one drill away, and game feel (warp, target-lock, reticle, quick-action ring) is adopted only where it serves identification, exploration or action — never fog-of-war, XP, or fake latency.

## Critical audit findings

Four independent audit lenses (content experience, navigation topology,
perspectives/data, game UX) examined the live cockpit against a real
532-page localized snapshot. Consolidated and ranked:

1. CRITICAL — Content is unreadable in-app: there is no reader anywhere; wiki_core/web/snapshot.py _summary hard-cuts at text[:260] mid-word (419/532 pages) with raw markdown leaking literally ('**pessoal**', backticks, broken '[Vivo](vivo.md)' syntax — confirmed in screenshots); the only escape, 'Open Markdown file' (App.tsx:2615), exits the SPA and only works on the dev server. The wiki cockpit cannot display a wiki page.
2. CRITICAL — All navigation is full-document reload: zero pushState calls in App.tsx (only a vestigial popstate listener at :2641); only /pages/:id is URL-addressable; on /ops the entire working state (selection, intent, trust filter, camera, packet) is ephemeral useState, so back/refresh re-boots to defaults. This is the mechanical root cause of 'confusing to navigate and understand what is happening'.
3. CRITICAL — Single hardcoded perspective: computeGalaxyLayout (layout.ts) is the only layout, radius fixed to freshness; the four MAP_INTENTS merely swap highlight sets; rim pills only change the selection card (no camera move, no filter, no re-layout). Navigation, identification and context exploration have no spatial support; the deep moc_parent hierarchy (typed weight-2 edges already in graph.json) is rendered nowhere.
4. CRITICAL — 70% of the wiki is spatially unreachable and the map lies about it: layout.ts:180 slices to maxNodes=160, selecting a hidden page is a silent no-op (nodeIndex miss → null), and wedge counts are computed from the visible slice only (layout.ts:183), so 'financeiro · 44' under-reports real context size while 372 pages collapse into one dead-end chip — an honest-encodings violation at real scale.
5. MAJOR — Three duplicate shallow detail surfaces (in-scene SelectedCard, ops PageActionDrawer, /pages detail) render the same page with divergent fields and two divergent selection states that can silently disagree; every path to 'read this' ejects the user from 3D into a truncated 2D form.
6. MAJOR — Silent hard caps on every list (12 search, 120 rows under a header claiming 'All content 532', 8 related, 6 evidence, 8 timeline) with no grouping, pagination, relation types, or count of what was dropped.
7. MAJOR — Demo universe leaks: /demo card links point to /pages/:id, which full-reloads into the REAL snapshot resolving synthetic ids — cross-universe navigation with no guard.
8. MAJOR — Scene accessibility fails the hard constraint: the only scene keyboard handler is Escape (SystemScene.tsx:1710); nodes cannot be reached, cycled or activated by keyboard; no camera choreography ties selection to space.
9. MINOR — Honesty bugs: unknown freshness placed at DEADLINE_F−0.08 (layout.ts:146) spatially reads as 'nearly stale' though it means 'no data'; App.tsx:2594 shows the raw context slug ('custos') bypassing contextLabel(), breaking Portuguese localization on the same screen that uses it elsewhere.

## Non-goals and anti-gimmick guardrails

Game feel is adopted only where it serves identification, exploration or
action. Explicitly banned, and encoded as test/lint notes during
implementation:

- No fog-of-war or "undiscovered region" mechanics: hidden counts are always
  visible and one drill away.
- No XP, levels, streaks or any progression mechanics.
- No fake loading, scanning effects or artificial latency.
- No decorative motion that implies a data change that did not happen.
- No information that exists only in 3D: every diegetic element has a DOM/aria
  twin, and the 2D fallback navigates the same topology at the same URLs.
- The deterministic Python core stays LLM-free; every mutating action stays
  behind the branch/PR model from the base plan.

## Navigation model

ROUTER: a tiny in-house pushState router (no dependency): intercept all internal anchor clicks, keep the existing popstate listener, load the snapshot bundle once per session — it survives all navigation. URL GRAMMAR: /w/:perspective/:context?/:group?/:pageId? with query params for transient state (?q=search, ?filter=trust, ?intent=task, ?packet=id,id, ?reader=1). Perspective ids (language-neutral slugs; labels via presentation registry): radar | atlas | districts | trails. The :group segment means: atlas → moc_parent hub slug; districts → page_type; radar → attention cluster (moc_parent fallback page_type); trails ignores it (ego-centric on :pageId). DRILL LEVELS = CAMERA ALTITUDE: L0 galaxy (/w/radar) — all 8 contexts, ≤160 real nodes plus cluster-star aggregates; L1 context (/w/radar/financeiro) — WARP: camera dollies into the wedge, the context's FULL page set (40–150 pages) re-lays out deterministically (seed = context id) while the other 7 contexts collapse to labeled, clickable horizon beacons for lateral jumps; L2 group (/w/atlas/financeiro/faturas) — cluster frame showing ALL pages of the moc_parent subtree or page_type; L3 page (/w/atlas/financeiro/faturas/custo-starlink?reader=1) — FOCUS/target-lock: low orbit framing node + 1-hop typed neighbors, reader dock opens. The 160-node cap is PER LEVEL, so all 532 pages are reachable while never rendering more than ~160 at once; residue at any level renders as deterministic cluster-stars (one per context/group, sized by hidden count, trust-histogram ring) whose click = drill — the '372 hidden' chip becomes a real affordance. Selecting an off-level page (search result, wiki-link, packet item) AUTO-DRILLS to its level and pins it: the silent no-op is banned. CAMERA VOCABULARY (all eased ≤900ms, interruptible; instant CUT under reduced motion): WARP (drill in, ~600ms dolly+orbit), RETREAT (one level up, reverse move), FOCUS (target-lock glide, ~350ms), MORPH (perspective switch: nodes keep identity and tween ~800ms with per-context stagger while the camera keeps the focused node framed). HISTORY & BACK: every level/perspective/selection change is a pushState; browser Back / Alt-Left / Backspace = RETREAT along history; Esc = release lock first, then retreat one level; refresh restores exact state from the URL. BREADCRUMBS: URL-derived trail top-left ('Galáxia › financeiro › faturas › Custo — Starlink'), every segment clickable, labels from the presentation registry. ALIASES & SURVIVORS: /ops → /w/radar; /pages/:id → alias redirect to /w/atlas/:context/:group/:id?reader=1 (old links keep working; /pages route retired); /review, /sources, /health remain plain 2D form routes; /demo prefixes ALL generated URLs (/demo/w/...) and is an in-memory bundle switch — demo ids can never resolve against the real snapshot. FALLBACK: the 2D FallbackPlanView gets the same four levels as nested lists with identical URLs, so keyboard/reduced-motion users navigate the exact same topology.

## Perspectives

The same node identities are re-arranged by four deterministic,
worker-computed perspectives. Switching perspectives MORPHs nodes (identity
preserved, focused node stays framed). Perspective ids are language-neutral;
all labels flow through the presentation registry.

### Radar (freshness) (`radar`)

**Purpose.** Verification: what needs attention now. This is the existing strength; it must not regress.

**Spatial metaphor.** Polar attention map: angle = context wedge, radius = time-until-stale with the DEADLINE_F arc, glow + particles on attention items. Fix: 'unknown' freshness moves to a discrete labeled outer 'sem dados' band instead of DEADLINE_F−0.08, so radius never encodes data that does not exist.

**Grouping.** Context wedge → attention cluster (stale/risk first; moc_parent fallback grouping inside L1 immersion). Rim pills show honest shown/total counts computed over ALL context nodes.

**Drill-down.** L0 galaxy → L1 wedge immersion (WARP: the full context re-laid as its own radar, same radius semantics, other contexts as horizon beacons) → L2 attention cluster → L3 target-lock + reader.

**Encodings.** color=trust, shape=kind, radius=freshness, glow/particles=needs-action, deadline arc=stale boundary. Approved/draft/stale always distinguishable.

**Data needs.** Existing graph.json; layout.ts change to compute wedge counts from all nodes (shown/total); no snapshot change.

### Atlas (hierarchy) (`atlas`)

**Purpose.** Navigation: answers 'what lives under financeiro' — the owner's category navigation need. Default target for content browsing (replaces /pages).

**Spatial metaphor.** Orbit-of-orbits: the current drill root at center, its moc_parent children on ring 1, grandchildren on faint outer rings; ring arc-share proportional to subtree size; breadcrumb chain of ancestors recedes behind the camera.

**Grouping.** moc_parent subtree per child hub; deterministic fallback for orphans = path subdirectory (visible 'sem pai' bucket, never hidden).

**Drill-down.** Click/Enter a hub = re-root the orbit to that subtree (existing nodes animate outward/inward, never teleport); Esc climbs to parent. L3 lock identical to all perspectives.

**Encodings.** color=trust, shape=kind, solid line=moc_parent, arc share=subtree size. Selection = candidate re-root + reader.

**Data needs.** moc_parent edges (already in graph.json, snapshot.py:196-207); optional cheap addition: per-page moc_children_count to size rings before full graph parse.

### Distritos (taxonomy) (`districts`)

**Purpose.** Identification: 'show me all decisions / all invoices / all tasks' across or within contexts.

**Spatial metaphor.** Family shelves: the 9 FAMILY_STYLE families (root/hub/content/source/decision/action/rule/event/person from presentation.ts) as concentric arcs within context sectors — literally the world sorted by shape. Within a shelf: context color bands, then stable title sort.

**Grouping.** family → page_type → pages; shelves over the node budget show type cluster-stars sized by count with trust-histogram rings.

**Drill-down.** Family arc → type cluster (expands on click/Enter) → page lock. Context segment of the URL scopes the shelves to one context at L1.

**Encodings.** shape=kind (the organizing axis), color=trust, context=angular sector + accent band. Cluster-stars carry true hidden counts.

**Data needs.** page_type + presentation registry only — zero snapshot changes; Portuguese labels via existing overrides.

### Trilhas (relations + provenance) (`trails`)

**Purpose.** Context exploration around the current page: what is this connected to, and what evidence is it standing on. Subsumes audit 3's provenance-river at selection scope (full river perspective deferred).

**Spatial metaphor.** Ego-graph of the locked page: page at center, 1–2 hop neighbors arranged in typed sectors (Hierarquia / Evidência / Links / Citado por); the evidence walk overlays a stepped animated highlight along the real chain page → source node → ingestion event on the timeline ring.

**Grouping.** Relation-type sectors with true counts; within a sector, group by context.

**Drill-down.** Click a neighbor = re-center the trail (pushes a hop onto the visible jump trail, last 5 hops as chips); evidence walk steps n/N by keyboard; unsourced pages show an explicit 'sem evidência' marker (honest gap, no fabricated edges).

**Encodings.** color=trust, shape=kind; edge grammar: moc_parent solid, source_ref dashed toward the source, markdown_link faint; direction = slow pulse source→target (static arrowheads under reduced motion).

**Data needs.** graph.json edges + resolved source_refs/backlinks from the new content endpoint; optional ingestion-event linkage (source → timeline event id) for the final walk hop — walk renders an explicit gap marker when absent.

## Content experience: the in-world reader

OPENING: click/Enter on a node = target-lock — reticle converges (150ms), FOCUS camera glide frames node + 1-hop neighborhood (instant under reduced motion), and the PageReader dock slides into the right ~38% of the sceneShell. The scene stays live and dimmed behind it; the panel is focus-trapped; Esc closes back to the scene and returns the camera; the URL gains ?reader=1 so any read state is deep-linkable. ONE COMPONENT: PageReader replaces all three current surfaces (SelectedCard detail, PageActionDrawer, /pages detail) and is the same component used as the first-class 2D/static fallback — one code path, zero drift. RENDERING: fed by GET /api/pages/{id}/content; frontmatter renders as labeled chips via the presentation registry (decision, freshness, evidence count, context — never machine-token prose like 'Estado: `resolvida_em_...`'); the full markdown body renders through marked or micromark + DOMPurify (the one justified new dependency), sectioned by H2 with collapsible sections; ops actions (approve, refresh, add-to-packet) sit on the panel so the review loop never leaves the world. LINKS ARE NAVIGATION: the endpoint returns server-resolved resolved_links[] mapping each internal [text](x.md) to {page_id, title, trust, context}; hovering a link glows its node in the scene; clicking navigates the reader AND flies the camera (auto-drilling and deterministically materializing nodes beyond the current level's cap); the last 5 hops render as a jump-trail of chips atop the panel (click to jump back; Backspace/Alt-Left = back). External/source URLs open in a new tab with the domain shown inline and never touch the trail. RELATED CONTENT: the capped 8-item list is replaced by grouped, typed, uncapped sections — Hierarquia / Evidência / Links / Citado por — each with a true count, first 5 visible, expandable to a virtualized full list; hovering a group isolates that relation's edges in the scene so panel and world always agree. PROVENANCE WALK: the Evidence rail lists source_refs resolved to real source records; activating one steps an animated highlight along the actual chain — page node → source node → ingestion event on the timeline ring — with a keyboard n/N stepper summarizing each hop in the panel; a missing manifest shows an explicit gap marker, never a fabricated edge; the raw-file link is demoted to a dev-only 'ver arquivo fonte' in the provenance footer. STATIC DEGRADATION: the reader loads the content/{id}.json sidecar when the snapshot writer emitted it; otherwise it shows the full sanitized (untruncated-flagged) summary plus an honest notice 'texto completo disponível com o operador local' — never a fake reader, never a 404 dead end.

## HUD and interaction system

TWO-LAYER CONTRACT (every diegetic element has a DOM/aria twin — no critical info exists only in 3D). Diegetic layer (anchored in 3D, billboarded): context rim pills with honest 'shown/total' counts, hub labels, the lock-on reticle, the deadline arc label, cluster-star counts. Screen-space frame (fixed to sceneShell edges — the below-the-fold panel stack on /ops is deleted): TOP strip = breadcrumb trail (URL-derived, registry labels) + snapshot age + mode + honest hidden/total; LEFT mission card = current task intent with do-now rows (replaces HeroGlass + MapIntentPanel and the duplicated radarIntentBar — one intent state, one UI); RIGHT = PageReader/inspector dock; BOTTOM command bar = search field (/), four perspective glyphs (keys 1–4, current one lit), decision-packet tray as a slide-up (replaces ImpactBundlePanel), minimap toggle (M). MINIMAP: the FallbackPlanView SVG reused as a persistent ~120px overview disc bottom-right showing all 8 context wedges with attention badges and a frustum indicator of the current drill level; click-to-jump; M expands it fullscreen as an instant, motion-free 'zoom to galaxy'. TARGET-LOCK: reticle convergence (150ms) + FOCUS glide; a 4-slot radial quick-action ring around the locked node — Ler / Adicionar ao pacote / Conexões / Atualizar — rendered as real buttons with registry labels, activated by Q/W/E/R while locked (perspective keys stay global on 1–4; no collision). KEYBOARD SCHEME (the accessibility requirement and the game-feel backbone): 1–4 switch perspective; Tab/Shift-Tab cycle groups (wedges/systems/shelves) in the layout's stable sort; Left/Right cycle sibling nodes; Up/Down jump moc_parent/first-child in Atlas; Enter = drill or target-lock; Q/W/E/R = ring actions while locked; Esc = release lock, then retreat one level; Backspace/Alt-Left = history back; / = focus search; M = minimap; roving tabindex over groups/nodes plus aria-live announcements ('Custo Starlink, custos, precisa de atualização'). MOTION BUDGET: nothing moves unless the user acted or real data changed; every animation eased, ≤900ms, interruptible; all gated by the existing reduced-motion governor (instant cuts, static arrowheads, no particle drift). ANTI-GIMMICK GUARDRAILS written into the plan and enforced as test/lint notes: no fog-of-war or undiscovered-region mechanics (hidden counts always visible and reachable), no XP/levels/streaks, no fake loading/scanning/latency, no decorative motion implying data change, and every 3D encoding keeps its one-line data justification in presentation.ts.

## Data contract changes

- snapshot.py _summary fix (ship first, independent): strip inline markdown (bold/italic markers, backticks), resolve [text](target.md) to text, cut at a sentence/word boundary near 260 chars, and emit summary_truncated: bool on the page record so every card can honestly show 'resumo parcial — abrir leitor'. ~20 lines + tests; repairs all 532 summaries across every surface in one change.
- New operator endpoint GET /api/pages/{id}/content in wiki_core/web/server.py returning: typed frontmatter, full markdown body, resolved_links[] (each internal link mapped server-side to {page_id, title, trust, context} via the existing graph resolver), backlinks[], and source_refs resolved to source records. Path-validated against memory_root; reuses the snapshot frontmatter parser.
- Static content sidecars: the snapshot writer optionally emits content/{id}.json per page (deterministic, one file per page) behind a manifest flag content_sidecars: true; the reader falls back to the sanitized summary + honest operator notice when absent.
- Honest scene counts: layout.ts computes wedge/rim counts (count/staleCount/freshCount) over ALL nodes in a context, not the visible slice, and exposes {shown, total} per context plus per-group hidden counts to drive cluster-star aggregates.
- Optional per-page moc_children_count in the snapshot (cheap) so the Atlas perspective can size orbit rings before the full graph is parsed in the worker.
- Optional ingestion-event linkage (source record → timeline event id) so the evidence walk can trace page → source → ingestion event end-to-end; the walk renders an explicit gap marker when the linkage is absent — no fabricated hops.
- No snapshot changes required for the Districts perspective (page_type + presentation registry suffice) or for Trails' 1-hop ego-graph (graph.json edges suffice) — noted so scope stays contained.

## Implementation phases

### Phase 0 — Honesty quick wins (independent, ship first)

Deliverables:

- _summary sanitization + summary_truncated flag in wiki_core/web/snapshot.py with unit tests
- Route App.tsx:2594 context display through contextLabel()
- Wedge/rim counts computed over all context nodes; pills labeled shown/total
- Unknown-freshness moved to a discrete labeled 'sem dados' band in layout.ts
- 'resumo parcial' affordance on truncated summaries at all call sites

Acceptance:

- No summary in any of the 532 pages ends mid-word or shows raw markdown syntax
- Rim pills show true per-context totals on the real snapshot (e.g. financeiro 44/96 style)
- Visual tests updated for both demo and real-scale snapshots

### Phase 1 — One world, one history (SPA router + unified state)

Deliverables:

- In-house pushState router intercepting internal anchors; snapshot bundle loads once and survives navigation
- URL grammar /w/:perspective/:context?/:group?/:pageId? + query params for transient state
- Unify explicitSelection (SystemScene) and selectedPageId (OpsView) into a single URL-derived selection
- Demo sealing: in-memory bundle switch, all generated links prefixed /demo/w/...
- Aliases: /ops → /w/radar, /pages/:id → /w/atlas/.../:id?reader=1; /review /sources /health untouched
- Breadcrumb HUD trail rendered from the URL; per-view snapshot refetch removed

Acceptance:

- Zero full-document reloads on any internal navigation; back/forward never re-boot the app
- Refresh restores exact perspective, level, selection and reader state from the URL
- Demo ids can never resolve against the real snapshot; scene card and list selection can never disagree

### Phase 2 — Read inside the world (content endpoint + PageReader)

Deliverables:

- GET /api/pages/{id}/content + optional static sidecar writer + manifest flag
- PageReader dock (marked/micromark + DOMPurify) replacing PageActionDrawer AND /pages detail; same component as 2D fallback
- Live wiki-links: hover-glow in scene, click = reader nav + camera fly + jump trail (last 5 hops, Backspace back)
- Grouped, typed, uncapped related lists (Hierarquia/Evidência/Links/Citado por) with virtualization; scene edge isolation on group hover
- Evidence walk v1 (page → source; event hop when linkage lands) with keyboard stepper and explicit gap markers
- Search/list caps replaced by grouped counts + expand ('show all N in financeiro' drills the scene)

Acceptance:

- Any of the 532 pages fully readable without leaving the 3D shell; internal links navigate the scene
- Static build shows sidecar content or the honest operator notice — no 404 dead ends
- PageActionDrawer and the /pages detail form are deleted; XSS sanitizer tests pass

### Phase 3 — Drill-down navigation (levels + camera + keyboard)

Deliverables:

- Perspective-engine substrate: pluggable pure layout functions in layout.worker.ts, level-scoped deterministic layouts (seed = context/group id)
- Per-level 160-node cap with deterministic cluster-star aggregates (hidden count + trust-histogram ring, click = drill)
- WARP/RETREAT/FOCUS camera choreography with reduced-motion cuts; horizon beacons for lateral context jumps
- Minimap overview disc + fullscreen toggle; auto-drill + pin for off-level selections (search, links, packet)
- Full keyboard scheme (Tab groups, arrows siblings, Enter drill/lock, Esc retreat, / search, M minimap) + roving tabindex + aria-live
- 2D FallbackPlanView nested-list levels sharing the same URLs

Acceptance:

- All 532 pages reachable spatially in ≤4 interactions; hidden-node selection no-op eliminated
- Esc/Backspace/breadcrumb retreat semantics verified by e2e; keyboard-only traversal completes drill→lock→read→retreat
- Layouts deterministic: same snapshot → same positions (worker unit tests per level)

### Phase 4 — Perspectives (Atlas, Distritos, Trilhas + MORPH)

Deliverables:

- Atlas orbit-of-orbits (moc_parent re-rooting, orphan fallback bucket)
- Distritos family shelves (FAMILY_STYLE arcs, type cluster-stars)
- Trilhas ego-graph with typed edge grammar (solid/dashed/faint, directional pulse) + full evidence walk
- MORPH tween on perspective switch (node identity preserved, focused node stays framed, ~800ms staggered, cut under reduced motion)
- Perspective glyphs in the bottom bar with hotkeys 1–4; per-perspective 2D SVG projections in the fallback

Acceptance:

- Switching perspective preserves context/group/selection via the URL; morphs are deterministic and interruptible
- Task checks pass: 'what lives under financeiro' answerable in Atlas, 'all decisions' findable in Distritos, evidence chain walkable in Trilhas
- Visual tests assert approved/draft/stale/unknown distinguishable in every perspective

### Phase 5 — Cockpit shell polish and retirement

Deliverables:

- Target-lock reticle + Q/W/E/R radial quick-action ring (Ler/Pacote/Conexões/Atualizar) with DOM button twins
- Final HUD layering: below-the-fold /ops panel stack deleted; packet slide-up tray; top strip; left mission card
- Motion budget codified (≤900ms, interruptible, governor-gated) + anti-gimmick guardrails encoded as test/lint notes
- /pages route retired (alias redirects kept); 2D list retained only as reduced-motion/static fallback
- Plan document, README and e2e screenshots (demo + real modes) updated

Acceptance:

- Every ops action (approve, refresh, packet) reachable inside the viewport without scrolling
- Anti-gimmick checklist enforced in tests (no fog-of-war, no fake latency, no diegetic-only info)
- Legacy /pages/:id bookmarks still land on the right page in the new world

## Definition of done

- From /w/radar, a user can reach and fully read any of the 532 pages without leaving the 3D shell in ≤4 interactions (drill path or search + auto-drill), verified against the deepest moc_parent chain in the real snapshot.
- Browser back/forward and refresh restore the exact perspective, drill level, selection and reader state; zero full-document reloads on internal navigation.
- Every count shown anywhere is a true total: no list, pill, or scene surface hides items without an explicit count and a drill/expand affordance (no bare slice() truncation remains).
- approved/draft/stale/unknown states are visually distinguishable in all four perspectives, asserted by visual tests on both the demo and real-scale snapshots.
- The reader renders sanitized full markdown (DOMPurify test suite passes); internal wiki-links navigate the scene and never leave the app; external links always show their domain.
- Static deployment has no dead ends: the reader shows sidecar content or an explicit 'requires local operator' notice; 'Open Markdown file' no longer appears outside the dev-only provenance footer.
- Keyboard-only operation covers the full loop — switch perspective, drill, lock, read, act, retreat — with aria-live announcements; reduced-motion users get identical topology via instant cuts and the 2D fallback sharing the same URLs.
- Demo and real universes cannot cross-link in either direction.
- All layouts are deterministic and worker-computed: identical snapshot input produces identical positions per perspective and level (unit-tested).
- Per-level render budget holds ≤160 real nodes; degrade tiers (64/110/160) preserved; perspective morphs and drills stay interruptible.
- All user-facing labels flow through the presentation registry (no raw context/type slugs) — enforced by a registry coverage test on the Portuguese snapshot.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Scope blow-up: a perspective engine plus three new perspectives, a router, and a reader is several weeks of work and could stall half-done. | Strict phase gating with independently shippable phases: Phase 0 (summary fix) and Phase 1 (router) deliver user-visible value alone; the engine ships in Phase 3 powering only radar immersion; each perspective is an isolated pure layout function added one at a time. Timeline and provenance-river perspectives are explicitly deferred (evidence walk in Trilhas covers the trust loop). |
| Performance of morph tweens and per-level re-layouts at 532 nodes / 7.5k edges on modest hardware. | Per-level 160-node cap keeps draw calls bounded; both tween endpoints precomputed in the worker; tween on instanced attributes; existing degrade tiers (64/110/160) and the reduced-motion governor remain the escape hatch; frame-budget check in visual tests. |
| Markdown rendering introduces XSS or a heavy dependency. | micromark or marked + DOMPurify only (small, justified); no raw HTML pass-through; sanitizer unit tests with hostile fixtures; rendering confined to the single PageReader component. |
| Static mode and operator mode diverge into two products (reader works locally, breaks deployed). | One PageReader code path with capability flags; deterministic content sidecars as the static contract; e2e/visual tests run in BOTH modes; honest degradation notices are part of the spec, not an afterthought. |
| Camera choreography causes motion discomfort or disorientation (the current complaint is confusion — motion could make it worse). | Motion budget hard rules (eased, ≤900ms, interruptible, user-initiated only); reduced-motion = instant cuts as a first-class path; the minimap and breadcrumb provide zero-motion navigation alternatives; RETREAT is always the exact reverse of WARP so spatial memory holds. |
| Router migration breaks existing bookmarks, e2e tests, and the review/health workflows. | Alias routes (/ops, /pages/:id) with redirects; /review /sources /health untouched as 2D routes; e2e coverage for legacy URLs added in Phase 1 before any surface is deleted. |
| Encoding honesty drifts as layouts multiply (four perspectives = four chances to lie spatially). | The invariants (color=trust, shape=kind, line=relation) live in presentation.ts with a one-line data justification per encoding; a shared visual test asserts trust-state distinguishability per perspective; the anti-gimmick guardrail list is encoded as test/lint notes in the plan. |
| moc_parent hierarchy is incomplete or cyclic in the real repo, breaking the Atlas layout. | Deterministic fallback grouping by path subdirectory; orphans land in a visible 'sem pai' bucket; cycle detection in the worker with a stable tie-break; layout unit tests run against the real 532-page snapshot fixture. |
| Keyboard map collisions and a11y regressions as HUD grows (perspective 1–4 vs quick-action ring). | Resolved up front: global 1–4 = perspectives, Q/W/E/R = ring only while locked, Esc releases before retreating; the full keyboard map is documented and covered by an e2e keyboard-only traversal test. |

## Relationship to the base cockpit plan

The [operational dashboard plan](threejs-operational-dashboard-plan-2026-07-01.md)
remains the contract for the operator backend, safety model, review/ingestion
flows and the honest-encoding invariants. This plan replaces its navigation
and page-cockpit sections: the `/pages` route is retired in favor of the
in-world reader, the knowledge-galaxy scene becomes one of four perspectives,
and every route gains real URL semantics. The freshness radar built in v7.0
is preserved unchanged as the `radar` perspective and remains the default
landing view for daily operation.
