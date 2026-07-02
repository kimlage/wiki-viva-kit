---
title: "Plan - One-world cockpit: Approve, Add and Health dissolve into the 3D game"
page_id: plan-one-world-cockpit-2026-07-02
page_type: methodology_plan
aliases:
  - One-world cockpit plan
  - Mundo Único
  - Gate, Dock & Weather
  - Kill the 2D pages
  - Codex setup panel
tags:
  - wiki/methodology
  - wiki/interface
  - wiki/operations
  - wiki/agents
  - status/plan
date: "2026-07-02"
status: plan
context: system
visibility: private_reference
related_pages:
  - docs/references/proposals/cockpit-3d-navigation-plan-2026-07-01.md
  - docs/references/proposals/codex-agentic-missions-plan-2026-07-02.md
  - docs/references/proposals/threejs-operational-dashboard-plan-2026-07-01.md
  - AGENTS.md
  - wiki.config.yaml
target_version: "wiki-viva v8 candidate"
audience: "wiki-viva maintainers, downstream wiki owners and implementation agents"
scope: "design plan for dissolving the three legacy 2D pages (Approve /review, Add /sources, Health /health) into the single 3D world UX, adding an honest Codex setup/diagnostics facility, and fixing the dishonest data those pages sit on — kit-first, cascaded to downstream wikis"
---

# Plan - One-World Cockpit: Approve, Add and Health Dissolve Into the 3D Game

Updated on: 2026-07-02.

> Status (2026-07-02): plan only. Nothing here is implemented yet. It builds on
> the [3D navigation plan](cockpit-3d-navigation-plan-2026-07-01.md) (the world,
> perspectives, reader, missions — shipped) and the
> [Codex agentic missions plan](codex-agentic-missions-plan-2026-07-02.md)
> (briefs, Work tray, job runner — implemented on PR #49, in flight). The safety
> spine of both is untouched and non-negotiable here: deterministic LLM-free
> core, every mutation lands as a `wiki/<theme>` branch + draft PR through
> `git_workflows`, the human approve/merge gate stays on GitHub, honest
> degradation everywhere.

The owner's brief, translated and honored:

> "Codex shows *unavailable* and I have NO way to configure it. The Approve, Add
> and Health areas are TERRIBLE — extremely confusing. Let's make a complete new
> plan to integrate everything into ONE 3D UX. Do a full review of the app/game
> within what we already have. Check the private repo's contents to test and
> structure this correctly. You may change wiki structures — but always fix the
> open-source wiki first and cascade."

This plan was produced from a six-lens audit of the real code and the real
532-page private wiki (structural metadata only), three independent design
candidates, and an adversarial judging pass. The three designs converged on the
same skeleton — strong evidence the direction is right.

## North star

**One world, one grammar, one honest loop.** The 3D world is already where the
operator lives: perspectives, reader, packet, missions, briefs, jobs. But three
doors still eject them into pre-rebuild 2D pages — different layout, different
progress models, raw git jargon, and untranslated English — to do the three
most important jobs: approve changes, add knowledge, judge health. This plan
removes the doors.

- **Approve becomes the Gate** — a stance of the world: the scene dims to the
  changed pages (purple approval halos), all non-content changes collapse into
  one honest "workshop crate", the full per-file diff opens in the reader, and
  a single guided station track walks the operator from *understand* to
  *hand off* — ending, honestly labeled, at GitHub: **"o cockpit prepara, o
  GitHub decide."**
- **Add becomes the Intake** — knowledge arrives as matter: drag a file onto
  the canvas (or `+` on the raw chip), it is safely copied into `data/raw/`,
  triaged, and appears as a wireframe **ghost crystal** at its destination
  context; three plain decisions (VERIFICAR → PREPARAR → ENTREGAR) drive the
  existing deterministic pipeline; the crystal solidifies only when the PR
  merges — matter arriving honestly.
- **Health becomes the Weather** — not a page but the ambient state of the
  world: one honest trust pill in the top strip, five **gate pylons** at the
  galaxy rim colored by *real* last-run receipts, freshness-budget gauge, and
  radar filter chips with full honest counts. The radar *is* the health view.
- **Codex becomes a repairable Facility** — a diagnostics dock rendered
  straight from the live probe record: one rung per honest gate, each with a
  plain-PT headline, the raw technical reason, and exactly ONE copyable fix —
  including the state the owner hit today: **operator outdated** (the local
  server predates the code on disk).

The left nav dies. `/review`, `/sources`, `/health` become permanent redirects
into the world's URL grammar. Missions stop ejecting into 2D — every mission
row *launches a flow in-world*.

## Critical findings

From the audits, against the live private repo (93 diffed files at the gate on
PR #203, 532 pages, PT operator). These are the reasons the areas feel
"péssimas" — each is a concrete defect, not a taste issue.

### Aprovar (/review)

1. **CRITICAL — the "approval inbox" cannot approve.** No approve / reject /
   request-changes control exists anywhere; the only decisive control is an
   external GitHub link (`App.tsx:826` "Final approval happens outside the
   cockpit") while the mission tooltip *promises* "approve, ask for fixes, or
   reject" (`i18n.ts:57`). The operator's one mental model is unsatisfiable
   in-app.
2. **CRITICAL — with 93 changed files, at most 8 diffs are viewable, and they
   are the WRONG 8.** `DiffFilmstrip` slices to 8 (`App.tsx:412`); files sort
   category-alphabetical (`diff.py:272`) so cli/core code fills the cut and the
   **2 memorias content pages — the reason a human gate exists — are
   invisible**. 21 untracked files have no preview at all (`git diff` is empty
   for `??`, `diff.py:260`); 61 of 93 previews are hard-cut at 18 lines; no
   pagination, no expand, no full per-file diff anywhere.
3. **HIGH — a false privacy alarm dominates the page.** 19 of 21 privacy
   triggers are the cockpit's own demo assets caught by the substring check
   `if "public" in path` (`diff.py:107`), which forces the header to "Needs
   privacy review" even though PR #203 is already `ready_for_review` (the
   ladder at `App.tsx:523` ranks privacy above the human-gate state). Real risk
   is indistinguishable from noise — the opposite of honest.
4. **HIGH — blockers can never clear.** "Scope review" is pending whenever
   `file_count>0`, "risk review" whenever any hint exists (`App.tsx:561-570`) —
   there is no acknowledge state, and gates default to `not_run`, so every real
   change shows permanent warnings. Alarm fatigue by construction.
5. **HIGH — raw git porcelain as UI.** A paths *textarea* for staging, commit
   message field, 13-row PR-body markdown editor, merge-base hashes, git argv
   lists, and THREE differently-worded dry-run toggles ("Allow online send" /
   "Enable local writes" / "Allow local refresh"). ~13 git concepts and ~16
   buttons; `publish`/`open_draft_pr` duplicated across two panels; the final
   post-merge step (`sync_main`) is disabled unless already on the default
   branch, so **every approval loop ends in the terminal**.
6. **HIGH — three disagreeing progress models on one page** (inbox counters,
   6-station gate track, 5-item checklist — two checklist items are hardcoded
   tautologies), and counts disagree across surfaces (mission chip 37, inbox
   93, live git 67, PR body lists 20 with no remainder marker).
7. **HIGH — the entire surface is hardcoded English** for a PT operator: zero
   `t()` calls inside ReviewView/ApprovalInbox/PrHandoffPanel/GitWorkflowPanel/
   SyncMainPanel (~200 literal strings). The nav says "Aprovar", the page
   answers in English.
8. **MEDIUM — the world never sees the gate.** The scene does not consume
   `diff.json` at all (zero hits in SystemScene/perspectives): changed pages
   are not lit or findable in any perspective, and both mission surfaces eject
   to `/review`.

### Adicionar (/sources)

9. **CRITICAL — the primary job (add a NEW external file) dead-ends.** No
   upload, no drag-drop, no picker — only a free-text path that must already
   resolve INSIDE the repo (`source_triage.py:30-42`); a PDF in `~/Downloads`
   is un-addable and the UI never says why or mentions `data/raw`.
10. **CRITICAL — the "Add Knowledge" inbox is not an inbox.** It flat-lists the
    202 ALREADY-INGESTED source pages of the private wiki (129 source_catalog +
    41 source + 31 source_config + 1 registry) as unsearchable buttons and
    pre-fills the form with the first one — inviting a re-ingest of something
    already ingested.
11. **HIGH — the 7-stage rail demands the pipeline's internals as the mental
    model** (triage → two dry-runs → branch discipline → proposal write → LLM
    request preview → emit), blocks on git state with no in-place remedy
    (`runGitWorkflow` is wired only into ReviewView), and after success **the
    new knowledge appears nowhere** — the bundle loads once per session, so no
    crystal, no node, no confirmation.
12. **HIGH — the client's risk-flag label map doesn't match the server's actual
    flags** (`App.tsx:1275-1285` vs `source_triage.py:69-84`) — real flags like
    `file_not_found` render as raw snake_case; hardcoded English throughout;
    detector findings print the offending PII excerpt verbatim on screen while
    stdout is redacted — inconsistent privacy posture in one view.

### Saúde (/health)

13. **CRITICAL — the verdict can NEVER turn green and never reacts to the
    operator.** `gates.json` status is hardcoded `'not_run'` at snapshot
    generation (`snapshot.py:323-338`); `not_run→warn`; even after running all
    gates successfully the page still says "Check before relying" forever. The
    single most demoralizing dishonesty in the app.
14. **HIGH — "Review warnings: 55" is inflated and dead-end.** The count sums
    the 43 deliberately quality-exempt pages and double-counts
    repeated/bad-repetition subsets (~8 real actionable items), links to
    nothing.
15. **MEDIUM — ~80% of the page duplicates the world with worse fidelity**
    (freshness card / attention list / area tiles = the radar + status strip +
    missions), with dishonest truncation (12 stale render as 8, no remainder);
    `operations.json` is fetched as REQUIRED on every load and rendered
    nowhere.

### The world (receiving surface)

16. **HIGH — the git workflow verbs are unreachable from the world**
    (`runWorkflow` is passed only to ReviewView) — absorbing Aprovar needs one
    prop of plumbing, not new machinery.
17. **MEDIUM — tray state (packet/missions/work) is `useState`, not URL** —
    back button/deep links/refresh lose it, violating the router's own
    contract; the bottom edge is congested (command bar, status strip, minimap,
    trays, output dock all in ~60px); `CommandOutput` — where every action
    lands — is untranslated terminal-speak at z60.
18. **HIGH — trust axis is FLAT on the real wiki**: all 532 pages are
    `approved_state=approved` with zero risk flags, so color=trust renders a
    monochrome world while the real variance (212 pages without sources, 162
    wanted pages, 12 stale vs budget 15) is under-encoded.

### Codex (the owner's immediate complaint)

19. **CRITICAL — operator version mismatch is invisible AND falsifies
    diagnostics.** The private operator predates the code: `/api/codex/
    capability` 404s and the frontend spreads `CODEX_UNAVAILABLE`
    (`installed:false, authed:false`) — *lying* about a machine where codex IS
    installed and OAuth IS valid. No handshake exists to detect a stale
    operator.
20. **HIGH — the Work tray never renders `capability.reason`**
    (`WorkTray.tsx:124` shows only the generic pill); the only reason surface
    in the app is the *title tooltip of a disabled button* (BriefStudio) —
    invisible to touch/keyboard. No fix action, no install/login/restart hint,
    no pointer to `wiki.config.yaml codex.binary/enabled`, no re-probe button
    (capability is fetched once per page load).
21. Today's real machine state, for the record: codex npm wrapper installed,
    vendored native binary missing (ENOENT) → `runnable:false`; `auth.json`
    valid ChatGPT OAuth; fix = `npm install -g @openai/codex` + restart the
    operator. The UI gave the operator no path to discover any of this.

## Non-goals and guardrails

- **GitHub remains the only true approve.** The cockpit prepares the decision
  and walks the operator to it; it never renders an in-app approve/merge
  button or implies one. Every gate surface carries the contract line:
  *"o cockpit prepara, o GitHub decide."*
- **Diegesis has a hard floor: text stays text.** Diffs, PR bodies, triage
  findings and command stdout render in 2D docks with honest boxes. Geometry
  (halos, crate, pylons, ghost crystals, weather) carries *state*, never
  *content*. This is a personal-finance wiki; serious decisions read as text.
- **Honest degradation is a UI feature, not an apology — universally.** Every
  surface that depends on a capability (operator endpoints, codex, gh) renders
  WHY it is unavailable (localized headline + raw technical reason) and ONE
  fix action. Fail closed, never fake.
- **Every count is a true count or shows its remainder.** No more silent
  8-of-93. Census chips, filter counts, N-of-M trackers either show everything
  or show "N de M · ver todas".
- **EN+PT parity is a CI gate before any 2D view dies.** ~200 new strings move
  through `t()`; a JSX-literal i18n lint lands FIRST so partial translation
  can never recreate the bilingual whiplash.
- **LLM-free deterministic core; git gate unchanged.** All new endpoints are
  allowlisted, path-sandboxed, secret-scanned; `git_workflows` stays the only
  mutation path; gate receipts and intake writes live under `derived_root` /
  `data/raw` per existing boundaries.
- **Kit-first, cascade second.** Everything lands in wiki-viva-kit with tests
  and CI; the private wiki receives verbatim code copies per the standing
  playbook (never content, never its runtime config), and its operator must be
  RESTARTED — which rung 0 of the Codex ladder makes visible forever after.
- **Performance at real scale is a gate.** 532 pages: gate-dim adds a
  dimension to instanced grouping; halos/pylons/crate add draw calls. Measure
  on the real snapshot before deleting old views; no radar frame-rate
  regression.

## The design

### (a) One grammar, one dock contract

**URL grammar** (all in `src/router.ts`; the positional spine
`/w/:perspective/:context?/:group?/:pageId?` is untouched). `WorldQuery`
gains:

```
dock:    '' | 'approve' | 'intake' | 'gates' | 'codex'   # task surfaces
src:     string    # intake source (path/url), meaningful with dock=intake
diff:    boolean   # PageReader opens on the Diff tab
station: number    # current station on the gate track
ack:     string[]  # acknowledged blocker ids (scope/risk)
tray:    '' | 'packet' | 'missions' | 'work'             # trays become URL state
filter:  stale|risk|changed|pending|raw|<trust>          # extended filter grammar
```

Back button, deep links, refresh and the demo universe work for free — the
same contract `?reader=1` already proves. The three existing trays migrate
from `useState` to `?tray=`, fixing their reload/back gap as a side effect.

**One dock contract** (a single generic component, five configurations —
"zero new code per dock"): every dock is (1) an honest headline pill computed
only from deterministic payloads; (2) at most THREE operator decisions in the
existing missionRow/stage visual language; (3) one guided track (the
pipelineRail/gateStep components); (4) honest counts with remainders; (5) all
strings `t()`'d; (6) output streaming to the (now localized) CommandOutput
dock. Docks anchor to the sceneShell exactly like PageReader; the world stays
visible and reactive behind them.

**Missions launch, never eject.** `Mission.href` is replaced by
`Mission.launch: WorldPatch` — the approve mission patches `?dock=approve`,
intake patches `?dock=intake`, and the mission card rows stop navigating to
`/review`. New mission kinds join the existing four: `approve`, `intake`,
`gates`, `codex` (emitted only from real state — e.g. `codex` only when
capability is unusable AND there is blocked work). Completing them feeds the
existing karma/vitality loop — no fabricated XP; missions clear only when a
bundle refetch proves the state improved.

### (b) The Gate — Aprovar becomes a place

Entry: the approve mission row, the worldTopStrip gate pill ("7 mudanças
aguardando · PR #203 rascunho"), or the permanent redirect `/review →
/w/radar?dock=approve`.

- **World stance.** `?dock=approve` dims the scene to the changed set: changed
  *content* pages (path→page_id via pages.json) get pulsing **purple approval
  halos** on their real nodes — the existing proposal salience, now fed by
  diff.json at last. All non-content changes (on the real repo: 91 of 93)
  collapse into **ONE workshop crate** object at the gate — an honest "code
  changed here" container, clickable into a 2D file-list dock with category
  chips. The 8-of-93 lie dies.
- **The Approve dock.** Headline = the decision ladder, reordered (once a PR
  is open, `human_gate_state` outranks privacy) and fed by FIXED data (see
  Phase 1). Four decision rows in mission-row language; scope/risk rows gain
  an explicit **acknowledge** toggle (`?ack=`) so blockers can actually clear.
  The three dry-run toggles collapse into the dock's single
  preview-then-confirm contract (the BriefStudio "prepare then commit" shape).
- **Walk the changes.** "Percorrer mudanças" flies the camera node-to-node
  (the trails/evidence-walk machinery, "3 de 8 visitadas"), opening each page's
  **Diff tab in the PageReader** (`?reader=1&diff=1`) — full-length, secret-
  redacted, before/after, fed by a new per-file diff endpoint; untracked files
  via `git diff --no-index /dev/null`. Content first, code in the crate.
- **The station track.** The six `prGateSteps` become stations on the existing
  lock ring / dock track: Entender → Percorrer → Verificar (gates) → Selar
  (stage+commit via the existing verbs) → Publicar (+draft PR) → **Portão
  humano** — an external GitHub link honestly labeled "a decisão final
  acontece no GitHub". `?station=` in the URL. After the merge, one "Atualizar
  aprovado" action chains checkout+sync (closing the loop that today requires
  the terminal).
- **Plumbing:** `runWorkflow` passed into WorldView (one prop); all git verbs
  become reachable from the world; branch discipline stays server-side.

### (c) The Intake — Adicionar becomes an arrival

Entry: `+` on the StatusStrip raw chip, `+` on a context wedge, **drag-and-drop
a file onto the canvas**, or `/sources → /w/radar?dock=intake`.

- **Arrival.** Dropping/choosing a file calls a new allowlisted
  `POST /api/intake/copy`: secret-scan FIRST, then copy into
  `data/raw/<context>/` (path-sandboxed to `paths.raw_root`, refuses symlinks
  and traversal, never auto-pushed). The `~/Downloads` dead-end dies. URLs go
  through the same triage as today.
- **Ghost crystal.** Triage success spawns a wireframe crystal at the
  destination context wedge — pending matter, honestly distinct from real
  nodes. It solidifies into a real node only after the PR merges and the
  snapshot regenerates.
- **Three decisions, not seven stages.** The dock offers VERIFICAR (triage +
  both dry-runs batched) → PREPARAR (`proposal_write` + `llm_request_emit` on
  a `wiki/` branch — the same branch verbs, now reachable in-world) →
  ENTREGAR (jump into the Gate dock for this branch). `ingestion_plan.py`
  stays the engine; the server emits stage KEYS and the client renders `t()`
  labels; the risk-flag map is generated from the server's real flags.
- **The catalog is not an inbox.** The 202 ingested source pages are already a
  district (`/w/districts`, shape=crystal, `?filter=raw`, `?q=` search); the
  fake inbox list and its re-ingest pre-fill die. "What's pending?" is
  answered by an honest arrivals census (raw_root listing + input-channel
  pages) feeding the intake pill.
- **Codex hand-in-glove:** the dock's PREPARAR step offers "Gerar brief de
  ingestão" via the existing `ingest` brief grounding — this plan's Intake
  dock IS where the Codex plan's Phase 4 (ingest chain) plugs in.

### (d) The Weather — Saúde dissolves into the world

- **One trust pill** in the worldTopStrip: "Pronto para confiar" / "Verificar
  antes de usar" / **"não verificado nesta sessão"** — computed by a rewritten
  `healthDecision` from real inputs only: persisted gate receipts, deduplicated
  actionable quality flags (exempt pages excluded, subset flags not double-
  counted), stale counts vs the freshness budget. The eternal amber dies; so
  does the fake green.
- **Five gate pylons** at the galaxy rim (`?dock=gates`), one per gate id,
  colored by REAL last-run receipts. Click a pylon → runs that gate via the
  existing ActionCard machinery, streams to the output dock, the server writes
  a receipt `{gate_id, ok, returncode, finished_at}` under `derived_root`
  (outside content-hash paths — runtime facts, not content facts), the bundle
  refetches, the pylon turns green/red. `not_run` renders unlit, never amber.
- **Freshness budget gauge** on the status strip ("12/15 do orçamento") — the
  near-breach the old page never framed.
- **Radar filter chips with full counts** (`?filter=stale|risk|changed|
  pending|raw`): clicking dims non-matches; every surviving node is clickable;
  no dead-end numbers. `/health → /w/radar?filter=stale`.
- `operations.json` becomes optional in the bundle (it is rendered nowhere
  today) — either consumed by a real surface later or dropped from REQUIRED.

### (e) The Codex Facility — setup and diagnostics

One diagnostics dock at `?dock=codex`, opened from EVERY place capability is
mentioned: the Work tray pill (becomes a chip → navigates), a status LED on
the Work tray button, BriefStudio's disabled Execute (gains a visible reason
line + "Diagnóstico" link — never a tooltip), and the mission row.

The dock renders a **six-rung honesty ladder** straight from the live probe
record, each rung with a tone pill, a localized headline, the raw server
reason as a small technical line, and exactly ONE copyable fix:

| # | Rung | Fix offered |
|---|------|-------------|
| 0 | **Operador atualizado?** — NEW: detected by `/api/health` lacking the `codex` key or capability 404 | "reinicie o operador local (o código no disco é mais novo que o processo)" |
| 1 | Ligado? (`codex.enabled`) | pointer to `wiki.config.yaml` (`codex.enabled`, `codex.binary`) |
| 2 | Instalado? (`installed`) | `npm install -g @openai/codex` (copyable) |
| 3 | Executável? (`runnable`) — today's real failure | reinstall command + the raw ENOENT line |
| 4 | Conectado? (`authed`) | `codex login` (Sign in with ChatGPT) |
| 5 | Pronto (`usable`) | green — "Executar com Codex" everywhere lights up |

A **Re-verificar** button re-probes on demand; capability also refetches on
Work-tray open. Server-side honesty is authoritative regardless: job submit
re-probes on the server, so a stale-green UI can never trick the backend.
`/api/health` gains `{server_version, schema_capabilities}` so operator
staleness is detectable in general — every new endpoint this plan adds renders
the honest "operador desatualizado — reinicie" fallback instead of a raw 404.

### (f) Navigation and chrome

The left nav dies. The command bar becomes the only chrome: search, four
perspective glyphs, and the tray/dock buttons (Packet, Missions, Work, Aprovar,
Intake) with the existing mutual exclusion; health is ambient (pill +
weather), not a destination. Old routes redirect permanently (bookmarks never
break): `/review → ?dock=approve`, `/sources → ?dock=intake`, `/health →
?filter=stale`. Coach marks teach the new entries before the crutch is
removed; `CommandOutput` is localized and de-jargonized as part of Phase 0.

## Wiki-structure changes (owner-authorized, kit-first)

1. **Gate receipts** — new derived artifact `derived_root/gate-receipts/
   <gate_id>.json` written by the gate runner; `_gates_payload` reads them
   (replacing hardcoded `not_run`). Runtime facts live outside content-hash
   paths; snapshots stay reproducible.
2. **`approval.json` snapshot slice** — content-facing view of the diff
   (memory-category files resolved to page ids + PR state + receipts), so the
   scene and dock consume approval state without re-deriving it client-side.
3. **`intake.json` snapshot slice** — honest arrivals census: files under
   `data/raw/` without manifests + input-channel pages; feeds the intake pill
   and the ghost slots.
4. **Privacy hint anchored to the real public boundary** (config-driven), not
   the `"public"` path substring — kills the 19-false-alarm siren class.
5. **Status vocabulary normalization** — the private wiki has 14 free-form
   `status:` values ("fato", "resolvido_em_2026-06-25", "sob demanda"…) making
   rollups unreliable. The kit documents a small canonical set + per-repo
   aliases in `wiki.config.yaml`; the audit warns (not errors) on unknown
   values. Cascades as a config/docs change, content untouched.
6. **Trust-axis enrichment (kit-side derivation only)** — with all 532 pages
   `approved=approved/0 risk`, color=trust is monochrome; the radar's salience
   should also weigh evidence-less content pages (212) and stale-vs-budget, so
   the world shows the real variance. No frontmatter change required.

## Data-contract / API changes

- `GET /api/health` — adds `server_version` + `schema_capabilities` (the
  operator handshake), keeps `codex`.
- `GET /api/diff/file?path=…` — full per-file diff, secret-redacted, untracked
  via `--no-index`; served only in local_operator mode.
- `POST /api/intake/copy` — `{source_path|url, context}` → secret-scan, then
  sandboxed copy into `data/raw/<context>/`; allowlisted; refuses traversal/
  symlinks; never runs ingestion past CHECK without an explicit decision.
- Gate runner persists receipts; `gates.json` reports last-known status.
- New snapshot slices `approval.json`, `intake.json`; `operations.json`
  demoted from REQUIRED.
- Client: `runWorkflow` plumbed into WorldView; `loadCodexCapability` gains
  re-probe + operator-handshake detection (`CODEX_OPERATOR_OUTDATED` state);
  bundle refetch after mutating actions is debounced with an honest loading
  state on the status strip (no flicker, no stale flashes).

## Implementation phases

Each phase ships independently, leaves the cockpit honest, and lands kit-first
with tests + CI before cascading.

### Phase 0 — Foundations: honest strings, grammar, plumbing
i18n lint (no JSX literals) as a CI gate + `CommandOutput` localized; router
grammar (`dock/src/diff/station/ack/tray` + extended `filter`) with full
router.test.ts coverage; trays → URL state; `runWorkflow` into WorldView;
`/api/health` handshake + `OPERATOR_OUTDATED` detection.
**Acceptance:** every existing surface unchanged in behavior; trays survive
reload/back; lint fails CI on a literal string; old operator renders the
honest "operador desatualizado" state.

### Phase 1 — Honest data (server, zero UI teardown)
Fix `diff.py` privacy anchor; per-file full-diff endpoint + untracked
previews; gate receipts + `_gates_payload` from receipts; quality-flag dedup/
exempt fix; `approval.json` + `intake.json` slices; content-first diff sort.
**Acceptance:** on the real private snapshot: privacy alarm only on real
boundary files; the 2 memorias pages sort first; a gate run turns its receipt
(and pylon data) green; warning count drops from 55 to the ~8 real items.

### Phase 2 — The Codex Facility (smallest, highest-leverage — the owner's
immediate pain)
`?dock=codex` ladder (six rungs incl. rung 0), copyable fixes, Re-verificar,
capability refetch on tray open; Work-tray pill → chip + LED; BriefStudio
visible reason + Diagnóstico link.
**Acceptance:** on THIS machine today, the dock shows rung 0 red for the old
operator ("reinicie o operador") and, after restart, rung 3 red with the
reinstall command; after `npm install -g @openai/codex`, Re-verificar flips
everything green with no page reload.

### Phase 3 — The Gate (Aprovar dies)
`?dock=approve` stance: dim + purple halos + workshop crate; Approve dock
(reordered ladder, ack toggles, ≤3 decisions); camera walk + PageReader Diff
tab; station track ending at the honest GitHub handoff; post-merge
checkout+sync chain; `/review` redirect; missions/mission-card launch
in-world.
**Acceptance:** on the real 93-file diff: content pages haloed and walkable
with full diffs; crate holds the 91; the whole prepare→publish→PR loop runs
in-world with ONE preview/confirm model; no English literal anywhere; the
approve mission never leaves `/w`.

### Phase 4 — The Intake (Adicionar dies)
`+` affordances + canvas drag-drop → `/api/intake/copy`; ghost crystal;
VERIFICAR/PREPARAR/ENTREGAR; real-flag label map; `/sources` redirect; catalog
lives in districts; "Gerar brief de ingestão" hook (absorbs Codex plan Phase 4
entry point).
**Acceptance:** a PDF dropped from Downloads lands in `data/raw/<context>/`,
appears as a ghost crystal, and rides to a `wiki/` branch + draft PR without
leaving the world; a URL source does the same; secret-flagged sources block
with the finding shown safely (no raw excerpt).

### Phase 5 — The Weather (Saúde dies)
Trust pill (healthDecision v2, "não verificado" state); gate pylons
(`?dock=gates`) + budget gauge; full-count filter chips; `/health` redirect;
`operations.json` demoted.
**Acceptance:** running all gates turns the pill green in-session (refetch);
12 stale show as 12 with the budget framing; every number on the strip is
clickable into a filtered world.

### Phase 6 — Closure + private rollout
Left nav removed (redirects permanent); coach-mark chapter for the new entry
points; keyboard hints extended; perf pass on the 532-page snapshot (instanced
grouping with the gate-dim dimension, draw-call budget); cascade to the
private wiki per the playbook + **operator restart**; browser verification on
real data end-to-end.
**Acceptance:** no route outside `/w` except redirects; radar frame rate at
532 pages within the pre-plan envelope; the private operator passes the
handshake; all suites green in both repos.

## Risks and mitigations

- **Old-operator window** (top sequencing risk): every new endpoint 404s until
  the private operator restarts → the Phase 0 handshake + honest fallback ship
  FIRST; rung 0 makes the state self-explanatory forever.
- **Grammar collisions**: `dock/tray/station/ack` interacting with the
  positional spine → patchWorld invariants defined + full router test matrix
  in Phase 0, before any feature uses them.
- **Refetch cost at 532 pages**: debounced refetch + honest loading state;
  never morph the scene mid-interaction; measure before/after.
- **Approve-button optics**: a dock named "Aprovar" with decision buttons must
  never imply in-app merge — the contract line is fixed copy on the dock and
  the station track ends visibly outside.
- **Intake writes real files**: secret-scan before copy, sandbox to raw_root,
  no auto-advance past CHECK, PII never echoed raw in findings.
- **Deleting views deletes capabilities**: ReviewView is today's only home of
  seven git verbs — Phase 0 plumbing + Phase 3 parity checklist guarantee no
  verb is lost in the move.
- **i18n regression**: the lint gate + EN/PT parity test (already in CI from
  the Codex work) block merges with literals.
- **Diff→node mapping is partial**: new pages in a diff have no node yet —
  they render in the dock list (and the crate), honestly labeled "nova página,
  ainda sem nó".

## Definition of done

- From `/w`, without ever leaving the world, the operator can: **approve-
  prepare** a real changeset (see the changed pages haloed, walk full diffs,
  run gates, seal, publish, land on the GitHub gate), **add** a file from
  anywhere (drag-drop → ghost crystal → branch + draft PR), **judge health**
  at a glance (trust pill + pylons + budget + full-count filters), and
  **diagnose/configure Codex** (ladder + copyable fixes + re-probe).
- `/review`, `/sources`, `/health` and the left nav are gone as destinations;
  their URLs redirect forever; missions launch in-world.
- Every headline number in the app is either complete or shows its remainder;
  the false privacy siren and the eternal `not_run` amber are dead; the gates
  can actually turn green.
- Every string is `t()`'d EN+PT with the lint enforcing it; the PT operator
  never sees mid-flow English again.
- Honest degradation everywhere, including the new `OPERATOR_OUTDATED` state;
  a stale UI can never trick the server (submit re-probes server-side).
- The deterministic core stays LLM-free; every mutation still lands as a
  `wiki/` branch + draft PR; GitHub remains the only approve.
- Landed in the open-source kit first (tests + CI green at every phase), then
  cascaded to the private wiki with its operator restarted and the full loop
  verified in-browser at 532-page scale.
