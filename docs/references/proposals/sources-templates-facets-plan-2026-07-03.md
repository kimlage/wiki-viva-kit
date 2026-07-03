# Sources, Templates, Facets — the entity rebuild (2026-07-03)

Owner asks, decided scope (2026-07-03):

1. **Sources as strong entities** — configurable, clearly identifiable, with last
   updates and logs; chat sources (Slack, Google Chat, WhatsApp) must describe
   their channels and how to ingest them on demand.
2. **Conscious, visible templates** — the page TYPE changes how a page is
   rendered AND how you interact with it (controls, visuals); custom wikis can
   create new templates: that is the system's customization power.
3. **Multi-perspective center view** — select a page, put it at the center, and
   see it through multiple lenses: perception, vision, intention integrated
   with tools, processes, people, culture, meetings.
4. **Ingestion reorganization** — more efficient, complete, philosophically
   grounded (deep integral roots, without surfacing the jargon).

Decisions locked with the owner:

- Templates: **declarative YAML** (config, no code, no fork).
- Center view: **explicit facets** (4 named lenses + a depth axis).
- Sources: **executable manual** — agent runs on demand, PR-gated (no
  scheduler in this plan).
- Rebuild: **assisted migration** (deterministic scripts via the PR gate),
  kit first, then the private wiki with the owner's approval.

---

## 1. Research grounding

A deep-research pass (5 search angles → sources fetched → 3-vote adversarial
verification per claim) produced **11 high-confidence findings** on source
modeling, all from first-party documentation of mature systems (DataHub,
OpenMetadata, Backstage, Singer/Meltano). Two additional first-party
confirmations were fetched directly (Obsidian Bases, Tana supertags).

**Verified mechanisms this plan adopts:**

- **F1 — Compound identity.** A source is identified by a typed tuple
  (platform + platform-native locator + qualifier), not a bare name; a
  `(schema, kind)` envelope selects how the payload is parsed
  (DataHub dataset URN; Backstage `apiVersion`/`kind`).
- **F2 — Aspect split.** Machine-sync writes and human edits live in
  parallel, non-colliding regions, so re-syncs never clobber human notes
  (DataHub system vs `editable*` aspects). Caveat verified: this is write
  *routing*, not hard enforcement — it needs an audit check.
- **F3 — Typed, provenance-tracked ownership.** One required accountable
  owner; optional typed stewards; provenance per assignment (DataHub
  ownership aspect; Backstage `spec.owner` required).
- **F4 — Append-only run telemetry, out of the versioned contract**, with a
  richer-than-binary status (six states incl. `partialSuccess`)
  (DataHub versioned vs timeseries aspects; OpenMetadata pipeline status).
- **F5 — Recipe as data, one file per source**: identity + job kind +
  sourceConfig + cadence (DataHub recipes; Singer/Meltano config).
- **F6 — Multiple typed pipelines per source**, independently cadenced
  (OpenMetadata `pipelineType`: metadata / usage / profiler / …).
- **F7 — Cursors in a separate mutable state artifact**, per-stream and
  per-partition bookmarks, never in the static config (Singer STATE).
- **F8 — State-write timing invariant**: persist the cursor only after every
  failure point has passed; prefer duplicates over silent loss
  (Singer/Meltano at-least-once).
- **F9 — Stream/field selection is declarative data** (`selected` per node,
  metadata keywords), not code (Singer catalog/discovery).
- **F10 — Types themselves can be config**: the entity-type set declared in
  YAML composing named, reusable aspects (DataHub `entity-registry.yml`).
  Verified limit: YAML composes an existing vocabulary of primitives —
  brand-new primitives still require code.
- **F11 — Relations are derived, not authored**: authors declare source
  facts; a deterministic step derives the graph; hand-written relation
  fields are rejected (Backstage `relations`).
- **F12 — Declarative view specs are proven UX** (fetched first-party):
  Obsidian **Bases** `.base` YAML (global `filters`, `formulas`,
  `properties`, then `views:` each with `type/name/filters/order/groupBy/
  limit/summaries`); Tana **supertags** (tag = schema of typed fields +
  default content template + **pinned fields** that drive filter/sort/group
  controls + inheritance via *extend*).

**Honest note on verification:** broad claims about PKM type systems and
about operationalizing Integral Theory in software did **not** survive
adversarial verification (killed or unverifiable). Pillar C is therefore
grounded in (a) the kit's own canonical quadrant contract — already shipped
in `wiki_core/quadrants.py` with operational tests, a boundary rule and
anti-patterns — and (b) explicit design judgment, labeled as such. No
external "integral software" precedent is claimed.

---

## 2. What already exists (build on, don't duplicate)

The kit already carries the seeds of all three pillars:

- `wiki.page-types.yaml` (v1): per-type `template`, `allowed_dirs`,
  `required_frontmatter`, `field_types` — **validation** contract.
- 43 body skeletons in `docs/references/templates/wiki/` +
  `wiki_core/templates.py` (`resolve_template`, `instantiate_template`) +
  `scripts/wiki_new.py` (typed page creation, CLI only).
- Source types exist: `source`, `source_config`, `source_catalog`,
  `source_registry`, `input_channel`, `input_stage`; source pages point to
  config pages (`config_ref`), configs carry `perspectives_required/
  optional/skip_with_reason`, `input_channel_ref`, `target_pages` and an
  (unused) `quadrants: []` field.
- `wiki_core/quadrants.py`: canonical 4-quadrant contract — q1 identity/
  intent, q2 artifacts/evidence, q3 roles/relationships, q4 systems/
  processes — each with an **operational test**, a perspective map, a
  boundary rule and anti-patterns. The deep-read consolidation already
  renders a per-source Quadrants table.
- Ingestion: source → deterministic manifest → chunks → FTS → secret
  pre-scan → context package → **normalized event** → proposal (PR gate);
  `ingestion_event` pages exist.
- Cockpit: presentation registry (type→family/shape/accent; context
  palette), perspectives engine (radar/atlas/districts/trails + MORPH),
  PageReader, world docks (`approve/intake/gates/codex/work`), snapshot
  slices + localhost operator API, briefs/jobs (Codex) with
  continue-current-branch.

**The gaps this plan closes:** sources have no telemetry, no structured
channel descriptors, no cockpit surface; page types validate but do not
drive **views or controls**; templates are invisible in the UI and only
reachable via CLI; the quadrant contract never reaches the 3D world; typed
relations are authored lists with no derivation/bidirectionality check.

---

## 3. Design

### 3.1 Pillar A — the Source entity ("a fonte é um lugar")

**Contract (frontmatter, human-authored region)** — `source` pages gain:

```yaml
platform: slack            # slack|gchat|whatsapp|gmail|drive|web|repo|file|manual
source_locator: "T024/..." # platform-native id (workspace, chat JID, folder id)
env: prod                  # optional qualifier (F1)
owner: person-kim          # required accountable owner (F3)
stewards:                  # optional, typed, with provenance
  - { ref: person-x, kind: technical, via: declared }
config_ref: memories/sources/config/<id>.md
```

**Machine-owned sync block (F2, F4)** — written ONLY by tooling/agent sync
commits, never edited by hand (audit-checked):

```yaml
sync:
  last_run_at: 2026-07-03T10:20:00Z
  last_status: partial      # ok|partial|failed|running|queued|never
  last_event_ref: memories/sources/events/<id>-2026-07-03.md
  streams_fresh: 3
  streams_total: 5
```

**Recipe as data (F5, F6, F9)** — the `source_config` page gains a fenced
machine-readable block, schema `wiki_source_recipe.v1`, one per source:

```yaml
recipe:
  schema_version: wiki_source_recipe.v1
  platform: slack
  locator: "T024/..."
  pipelines:                    # typed, independently cadenced (F6)
    - kind: metadata            # channel/roster discovery
      cadence_days: 30
    - kind: content
      cadence_days: 7
    - kind: deep_read
      cadence_days: 7
  streams:                      # channels as first-class rows (F9)
    - id: "#financeiro"
      label: "Finanças do time"
      selected: true
      filters: { participants: [], after: null, keywords: [] }
      privacy: private_sensitive_allowed
      target_pages: [memorias/financeiro/...]
    - id: "dm:joao"
      selected: false
      skip_reason: "pessoal, fora do escopo da wiki"
  how_to_export: |              # the human/agent manual (WhatsApp etc.)
    1. WhatsApp > canal > exportar conversa (sem mídia)
    2. salvar em data/raw/<context>/whatsapp/
  ingest:
    argv: ["python3", "scripts/wiki_ingest.py", "--source", "{path}", "--context", "{context}"]
    mcp_hint: null              # optional MCP tool name for live platforms
```

No tokens/credentials ever; channel lists are structural metadata; raw
exports stay under gitignored `data/raw/` with the existing secret pre-scan.

**Cursor state (F7, F8)** — new mutable artifact, gitignored:
`data/derived/wiki/source-state/<source_id>.json`:

```json
{ "streams": { "#financeiro": { "cursor": "2026-06-28T…", "last_unit": "msg-9812", "updated_at": "…" } } }
```

Invariant (F8): the pipeline writes a stream's cursor **only after** the
manifest + normalized event are durably committed on the proposal branch.
Duplicates are tolerated (manifest sha dedup already exists) — never silent
loss.

**Telemetry rollup** — new snapshot slice `sources.json` **v2** computed
from ingestion events + state + recipes: per source: identity, owner, sync
block, per-stream freshness vs `cadence_days`, pending count, last N runs
(status color per F4's six states). Append-only history stays in
`ingestion_event` pages; the slice is a derived view.

**Cockpit surface** —

- New dock `?dock=source&src=<source_id>`: identity card (platform badge,
  locator, owner), sync health, **streams table** (selected, filters,
  cursor age, privacy), the how-to-export manual, ingestion log tail
  (events), and actions: *Compor brief de ingestão* (pre-filled from the
  recipe + stale streams), *Abrir config*, *Marcar canal* (propose
  selected/skip via brief).
- 3D: source crystals keep the area hue; **sync-age drives the aging tone**
  (same agedColor bands) and a thin **coverage ring** (fraction of fresh
  streams) replaces guesswork; clicking a source opens the dock.
- Intake dock lists **per-source pending streams** (cadence breached) as
  the arrival queue, replacing the generic path-only flow.

### 3.2 Pillar B — the Template registry ("o tipo é um molde visível")

**`wiki.templates.yaml` v1 (F10, F12)** — a new registry, merged over kit
defaults by per-wiki `wiki.templates.local.yaml` (same override semantics
as the presentation config). `wiki.page-types.yaml` stays the validation
contract; the templates registry adds the **view/interaction** contract:

```yaml
schema_version: wiki_templates.v1
types:
  meeting:
    extends: relation_base          # Tana-style extension
    body_template: docs/references/templates/wiki/meeting.md
    pinned_fields: [updated_at, participants, decisions]   # drive controls
    facets:                          # lens mapping (see 3.3); overrides defaults
      intencao:    [decisions, claims]
      percepcao:   [insights, journal_refs]
      pratica:     [actions, process_refs, evidence_refs]
      relacoes:    [participants, roles, related_holons]
    view:                            # Obsidian-Bases-style declarative panels
      center: timeline               # reader/center layout hint
      panels:
        - { kind: list,  from: decisions,  label: gate.decisions }
        - { kind: table, from: participants, columns: [title, role] }
      badges: [freshness, evidence]
    controls:                        # type-specific quick actions
      - { kind: brief,  id: meeting-followup }
      - { kind: nav,    rel: moc_parent }
    scene: { shape: slab, emphasis: relations }
```

Semantics and honest limits:

- `panels.kind` / `controls.kind` come from a **fixed vocabulary of
  primitives** implemented once in the cockpit (list, table, timeline,
  badges, brief, nav, filter…). Custom wikis compose them freely in YAML;
  **a brand-new primitive still requires code** (verified limit, F10) — the
  registry documents the vocabulary and versions it.
- Unknown/omitted keys degrade to the current defaults (today's reader),
  so old wikis render unchanged.
- Loader: `wiki_core/templates_registry.py` (deterministic, validated,
  exported into the snapshot as `templates.json`), consumed by
  `presentation.ts` (replacing hardcoded family/shape hints over time).

**Templates visible in the UI:**

- PageReader header gains a **template chip** (type label + molde) opening a
  *template inspector*: contract fields present/missing on THIS page,
  the body skeleton, and conformity state; a "página fora do molde" appears
  as an honest mission with a compose-brief fix.
- **Create-from-template**: the Intake dock gains "Nova página tipada" —
  picks a type, shows pinned fields, and composes a `wiki_new` brief (agent
  executes, PR-gated). No direct filesystem writes from the UI.
- Type changes **interaction**: the quick-action ring and center-view
  controls render from `controls:`; pinned fields surface at the top of the
  reader and as sort/filter defaults in lists (Tana's pinned-fields
  pattern).

**Relations: derived, not only authored (F11)** — authored refs
(`claims/decisions/actions/evidence_refs/…`) remain the *source facts*;
`wiki_page_graph` derives reverse edges deterministically and the audit
warns on asymmetric or dangling authored relations. Hand-written "reverse"
lists become unnecessary and eventually flagged.

**Migration (assisted)** — `scripts/wiki_migrate_templates.py`:
deterministic, dry-run first, PR-gated. Adds `platform/locator/owner` to
existing sources, extracts recipe blocks from prose configs where
detectable (else scaffolds TODO recipes), normalizes frontmatter to the
registry. Kit memories first; the private wiki only with the owner's PR
approval.

### 3.3 Pillar C — the Facet center ("uma página, quatro lentes, um eixo")

**Interaction**: with a page locked, a new **Focus** action (key `F` when
not in reader / URL `?focus=1`) MORPHs the world: the page moves to the
center; its neighborhood rearranges into **four explicit facet sectors**,
labeled in natural language (no jargon):

One lens per AQAL quadrant (faithful 1:1 — decided 2026-07-03 with the owner,
correcting an earlier draft that split q1 into two lenses and merged the two
exterior quadrants, hiding q4/systems):

- **Intenção** (q1, interior-individual) — why it exists AND how it is
  perceived: decisions, priorities, responsibilities, insights, journals,
  claims. (Intent and perception are both interior — they share this lens.)
- **Prática** (q2, exterior-individual) — what the entity does and produces:
  actions, artifacts, evidence.
- **Relações** (q3, interior-collective) — who and how together: people, roles,
  meetings, culture.
- **Sistemas** (q4, exterior-collective) — the systems that coordinate it:
  sources, channels, pipelines, dashboards, processes, governance.

plus a **Profundidade** axis: radial rings encode holon depth (MOC
distance root→page); deeper = further out. (Development *stages* as an
explicit per-page field are deliberately deferred — see §6.)

**Mechanics:**

- The sector of each neighbor is a **deterministic function**
  `facetOf(edgeType, neighborPageType)` seeded from
  `wiki_core/quadrants.py`'s `DEFAULT_QUADRANT_MAP` and overridable per
  type via the registry's `facets:` block. Pure, worker-computed, tested —
  same discipline as the perspectives engine.
- **Boundary rule honored** (from the shipped quadrant contract): facets
  are *views of one page*, not buckets — a page is never "in" a facet; only
  its RELATIONS are seen through lenses. The anti-patterns in
  `quadrants.py` become audit warnings for template authors.
- **Honest absence**: an empty facet renders as a visible "sem lente
  registrada" wedge with a one-click *Compor brief* to look through that
  lens (wired to the existing `perspectives_required/skip_with_reason`
  machinery that claims and configs already carry).
- The center page's **type drives the center**: `view.center` (timeline for
  meetings/journals, dashboard for sources, document for notes) and
  `controls:` render in the ring — the same page contract as the reader.
- MORPH in/out preserves node identity (existing machinery); Esc returns to
  the previous perspective; the URL is shareable.

**Deep-read alignment**: the LLM context package already ships the quadrant
contract; it gains the page-type's facet targets so consolidation fills the
same four lenses the UI shows (the existing "Quadrants" table is renamed at
the surface to the facet labels; internal ids stay `q1..q4`).

### 3.4 Ingestion reorganization

- The **arrival queue becomes per-source/per-stream**: intake shows sources
  whose streams breached cadence, with the exact export/ingest manual one
  click away; "add a loose file" remains as the fallback path.
- Normalized events gain `source_id` + `stream_id` + cursor snapshot;
  proposals link back to the source entity; the source dock's log is just a
  filtered view of events (no new storage).
- Briefs composed from a source embed the recipe (channels, filters,
  targets) so the agent never rediscovers context — the "executable manual"
  is literally the grounding section of the brief.

---

## 4. Anti-patterns we commit to avoid (research + shipped contract)

- **No quadrant-bucketing of pages** — the boundary rule; lenses over
  relations, never four folders.
- **No hand-authored reverse relations** — derived graph (F11).
- **No cursors in config, no config in state** (F7).
- **No sync writes over human prose** — aspect split + audit (F2 caveat:
  convention needs a check, not faith).
- **No jargon at the surface** — Intenção/Percepção/Prática/Relações and
  Profundidade; the AQAL vocabulary stays in `wiki_core` internals.
- **No silent capability inflation** — the registry documents its primitive
  vocabulary; anything beyond it is honestly "needs code".

---

## 5. Technical execution phases

Each phase lands kit-first, PR-gated, with pytest+vitest+browser
verification, then cascades to the private wiki (code only) for the owner's
gate. Estimated in cockpit-days, not calendar promises.

**Phase 0 — Contracts (foundation)**
`wiki_core/templates_registry.py` (+ `wiki.templates.yaml` v1 with the
current 26 types as no-op defaults), `wiki_core/source_recipe.py`
(recipe schema + validator), source-state store module, page-types v1→v1.1
additions (`platform`, `source_locator`, `owner`, `sync` machine block),
audit checks (recipe schema, writer isolation, template conformity —
WARN-first). Tests for every loader/validator.

**Phase 1 — Source entity backend**
`sources.json` v2 rollup in the snapshot (identity+sync+streams+pending);
operator endpoints `GET /api/sources`, `POST /api/sources/{id}/brief`
(compose ingest brief from recipe + stale streams); ingest pipeline writes
per-stream cursors post-commit (F8); events gain `stream_id`;
`wiki_migrate_templates.py` (sources part): dry-run + apply.

**Phase 2 — Cockpit: Fontes**
`?dock=source&src=` entity dock (card, health, streams table, manual, log,
actions); intake per-stream queue; 3D sync-aging + coverage ring on source
crystals; i18n EN/PT; router `src` already exists.

**Phase 3 — Cockpit: Templates**
`templates.json` slice; presentation.ts reads scene hints from the
registry; PageReader template chip + inspector + conformity; quick-ring
controls from `controls:`; "Nova página tipada" (brief-first) in Intake;
missions for out-of-mold pages.

**Phase 4 — Facet center**
`focusLayout` in the perspectives engine (4 sectors + depth rings, pure +
worker + tests); `facetOf()` seeded from quadrants.py + registry overrides;
`?focus=1` routing + MORPH in/out; empty-facet honesty + per-facet brief;
Key teaching row; deep-read facet targets in the context package.

**Phase 5 — Migration, docs, closure**
Assisted migration on kit `memories/`; adversarial multi-agent review of
the whole branch; README/template-authoring guide ("how to create a type in
YAML"); demo snapshot gains a rich source + custom type so the public demo
shows the power; cascade + private migration PR for the owner.

---

## 6. Deliberately deferred (kept honest)

- **Scheduled pulls** — the owner chose on-demand agent runs; the recipe's
  `cadence_days` only powers *staleness display*, not execution.
- **Development stages/levels as a page field** (the vertical axis of the
  depth lens) — needs its own contract discussion; Profundidade v1 =
  structural depth only.
- **Code plugin points for view primitives** — architecture leaves the seam
  (registry-driven), but no plugin API in this plan.
- **States/types dimensions of the underlying model** — out of scope; the
  facet view ships quadrant-lenses + depth only.

## 7. Open questions for the owner (small, non-blocking)

1. ~~Facet wording~~ — DECIDED 2026-07-03 by the owner: **Intenção / Percepção / Prática / Relações** (Percepção over Experiência). Internal ids: intencao/percepcao/pratica/relacoes → q1/q2part/… mapped in the registry.
2. Source ownership default for the private wiki: everything
   `owner: person-kim`, or model household/company stewards from day one?
