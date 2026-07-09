# Wiki Cockpit App

Local-first web cockpit for Wiki Viva. The 3D scene is the primary navigation
surface: one continuous knowledge world where drill level is camera altitude
bound to the URL and reading happens inside the world.

## The navigable world

URL grammar: `/w/:perspective/:context?/:group?/:pageId?` — browser back,
breadcrumbs and deep links are the same thing. Six deterministic,
worker-computed perspectives re-arrange the same node identities (MORPH keeps
identity on switch, keys `1–5` + `F`):

- **Quadrants** (`/w/quadrants`, key `5`, the default landing view) — the AQAL
  home map for the active recursive center. Four fixed 90° regions come from
  that center's compiled `quadrant_assignments`; the center page sits at the
  crossing of the axes, and structural pages that honestly have no quadrant
  remain in q0-core. The same page can project differently under different
  centers, with the reason stored in `quadrant_projections`. `?center=<anchor>`
  preserves an explicit root/company/project/source/template center separately
  from the reader page; without it, the selected page's nearest anchor is used
  for old links. A selected quadrant scopes the quadrant-aware views
  (quadrants/radar/districts). Bare `/`, `/ops` and `/w` normalize to the
  STACK's home view — the default view is a template decision (`ui_views`), not
  a platform constant.
- **Radar** (`/w/radar`, key `1`) — verification: what needs attention now.
- **Atlas** (`/w/atlas`, key `2`) — hierarchy navigation over `moc_parent`
  orbits; replaces the retired `/pages` list (old `/pages/:id` bookmarks
  redirect into the world with the reader open).
- **Distritos** (`/w/districts`, key `3`) — identification: the world shelved
  by content kind.
- **Trilhas** (`/w/trails`, key `4`) — context exploration: the locked page's
  ego-graph in typed relation sectors (Hierarquia / Evidência / Links /
  Citado por).
- **Focus** (`/w/focus`, key `F`, needs a locked page) — one page through the
  four AQAL lenses, empty lenses shown as honest absences.

Drill levels: galaxy → context (WARP) → group → page (target-lock + reader).
Every level caps rendering at ~160 nodes while cluster-stars carry the TRUE
hidden counts (click = drill or reveal). **Esc is the universal exit, one
layer at a time**: an open tray/panel closes first, then any open dock, then
the reader, then the page lock, then Esc retreats exactly one level up the
drill — always the exact reverse of the path that got you there. Horizon
beacons jump laterally between contexts; `M` toggles the minimap; a
radial quick-action ring (`Q/W/E/R` — Ler / Pacote / Conexões / Atualizar)
surrounds the locked node. Keyboard-only traversal covers the full loop (Tab
groups, arrows siblings, Enter drill/lock) with aria-live announcements.

## The interface materializes from the block stack

Every scope surface exists only when a template block provides it
(`src/data/surfaces.ts` reads the root's resolved stack from
`block_stacks.json`): no gamification package → no missions and no weather; no
quadrants block → no quadrant map; an **empty world has no instruments at all**
— its only interface is the **founding rite** (3+1 cards in the void, a ghost
root, one name question). Creating a page is the **spatial seed flow**: the
scope's curated catalog (`ui_create`, creatable-filtered — generated/system/
rite-owned types are never offered) as cards over the world, a ghost at the
type's home quadrant, one anchored question. Clicking a node opens a summary
**plate at the node**; the full reader is the second, chosen step. The
**Blocks dock** (`?dock=blocks`) is the X-ray: every resolved block with its
origin ring, the composed interface, the identity and the derived outputs. See
[modular-blocks.md](../../docs/references/guides/modular-blocks.md).

Reading is in-world: the PageReader dock renders the full markdown
(marked + DOMPurify) from `GET /api/pages/{id}/content` or static
`content/{page}.json` sidecars, with server-resolved wiki-links that fly the
camera instead of leaving the app, grouped uncapped relation lists and an
evidence walk (`n`/`N`). Press `F` (or the expand button) for the comfortable
reading modal — a centered column with larger type. Fenced ```mermaid blocks
render as real diagrams (lazy-loaded, strict security). Raw-data records
(sources, intake pages, ingestion events) are tagged distinctly everywhere —
◆ chips in the reader, tags in search results, and a dedicated map filter —
so untreated inputs never read as conclusions. Without content the reader
degrades honestly to the sanitized summary plus an operator notice — never a
dead end.

## Learning system and honest missions

First visit opens a guided tour of the world (reopen anytime with `?` or the
guide button); every piece of system jargon — approve a change, run the
checks, packet, freshness, evidence — carries a "?" help tip explaining what
it means, what to look at and what happens when you act. The **Missions** tray
exists only when the `gamification` package is attached on the root stack, and
turns maintenance into visible progress: missions are derived from the real
wiki state (refresh stale pages, reconnect with people past their contact
cadence, fill empty required quadrants, review changes) and clear themselves
when the wiki improves. The rewards layer is the
kit's karma system (`scripts/wiki_score.py`) — append-only events across 8
dimensions, badges, journey levels and context vitality, with anti-gaming
rules and no person-vs-person ranking. The cockpit only displays it
(`score.json` in the snapshot); no XP is fabricated in the UI.

## Language

The base system ships in English. Set `language` in `wiki.config.yaml` (or
`wiki-cockpit.config.json`) to a `pt*` value and the whole cockpit UI flips to
Portuguese — content language stays free. Individual strings can be overridden
via `strings: { "key": "..." }` in the runtime config, same pattern as the
presentation registry.

## The freshness radar

The radar perspective centers on a full-bleed 3D "freshness radar" where every
coordinate is operational data:

- **Angle** = context: each context owns a labeled wedge sized by its page
  count, with a rim pill showing per-status dot counts (click it to select the
  context hub).
- **Distance from center** = time since verification: trusted content orbits
  near the root core; anything past the amber **deadline arc** is beyond its
  freshness window and drifts toward the rim. Pages without freshness data sit
  on a discrete labeled "sem dados" band — radius never fakes a date.
- **Height** = approval state: draft changes float above the disc on visible
  stems; approved content stays on the plane.
- **Hue** = area (context): every page keeps its area's color everywhere —
  wedge rims, group pills, beacons and node bodies all agree. **State** shows
  as aging, never as hue: up-to-date pages sit vivid and quiet, overdue pages
  darken and radiate amber heat (emissive pulse + rising embers), never-checked
  pages wash out behind a gray veil, and drafts bleach toward white while
  floating on stems. Salience stays inverted: healthy is calm, problems glow.
  **Shape** = kind (crystal = evidence source, faceted hub = navigation,
  sphere = content). **Lines** = typed relations (navigation, evidence, review
  impact, ingestion chains); hovering a node reveals its full neighborhood.
- The attention set (risk flags, overdue pages, drafts, review items, hubs)
  carries always-on labels with annotations such as `8d overdue` or
  `draft change`, so the map answers "what needs attention" without a click.

Particle simulation adds living signals — every emitter maps to real data:
the core aura's density tracks the last 7 days of wiki activity, sparks travel
along evidence/ingestion/review arcs (provenance in motion, intensified on the
selected node), amber embers rise from overdue pages, and purple sparks climb
the stems of drafts waiting at the human gate. Particles are analytic
functions of time (deterministic, seeded, no physics state), scale down on the
balanced tier and disable entirely on the compact tier.

HUD: a top breadcrumb strip (URL-derived, registry labels) with the condition
strip (weather + honest counts, only with the gamification package), a left
mission card with do-now rows, a right reader dock, and a bottom command bar
(search `/`, dock destinations gated by the block stack, perspective glyphs
`1–5`, decision-packet tray, minimap hint). The trust
chips of the status strip filter the map in place via `?filter=`. Under
`prefers-reduced-motion`, without WebGL or with `?visual=1`, the shell renders
a deterministic 2D fallback that navigates the exact same topology at the same
URLs, and all motion stops when the tab is hidden or reduced motion is set.
Every animation is eased, ≤900ms, interruptible and user-initiated — no fog of
war, no fake latency, no decorative motion implying data change.

## Run with sample data

```sh
npm install
npm run dev
```

The operational routes fail closed when no real snapshot is available; they
never substitute the bundled sample universe. Open `/demo` to opt into the
bundled sample snapshot even when a local operator API is available — it is a
**title screen** with two doors:

- `/demo/genesis` — **start from zero**: the genesis tutorial. The world
  starts EMPTY (the founding rite is the only interface) and each step is a
  real pre-built snapshot under `sample-snapshot/stages/<k>/` — found the
  root, attach the quadrant lenses, seed an area, a person, the gamification
  package, a source. The tutorial swaps bundles; it never simulates state
  client-side, so the interface materializing between stages is the real
  stack gating.
- `/demo/world` — the **full world** straight away (stage 8 equals it).

The demo universe is sealed: every generated URL is prefixed with `/demo`,
synthetic ids never resolve against the real snapshot, and mutating actions
are disabled.

### Demo data vs your wiki

`public/sample-snapshot/` is a **synthetic interface example**: a fictional
consultant's wiki (Alex Rivera — pessoal/financeiro/clientes/estudio/sistema
contexts) generated by `python3 scripts/wiki_build_demo.py` from a real
fixture tree (`docs/references/fixtures/demo-wiki/`) compiled by the SAME
snapshot builder any wiki uses, exercising every template, block, lens, the
relations module and the quadrant interior. It is not this repository's wiki.
The kit's own operational wiki lives in `memories/` and is what you see when
the cockpit runs against a real checkout snapshot. The UI shows a persistent
banner while demo data is active so the two are never confused.

## Run against a local checkout

From the repo root:

```sh
python3 scripts/wiki_web_snapshot.py --out data/derived/wiki/web-snapshot --clean --content-sidecars
python3 scripts/wiki_web_server.py --host 127.0.0.1 --port 8765
```

`--content-sidecars` also writes `content/{page}.json` files so a static deploy
of the same snapshot can serve the full in-world reader.

Then, in this directory:

```sh
npm run dev:proxy
```

`dev:proxy` replaces the bundled demo provenance with `api_base=/api`,
`snapshot_base=/api/snapshot` and `mode=local_operator`, then proxies `/api`
to `http://127.0.0.1:8765`. This prevents real data from being mislabeled as
demo data while leaving the static `/demo` build unchanged. The Python server
refuses non-loopback binds; it is a local operator, not a remotely exposed
service. It exposes:

- `/api/snapshot/*.json` for the deterministic read model;
- `/api/pages/{id}/content` for the in-world reader: typed frontmatter, full
  markdown body, server-resolved internal links, backlinks and source refs
  (path-validated against the memory root);
- `/api/actions/run` for allowlisted fixed checks and derived writes;
- `/api/git/workflow` for proposal-branch workflows and draft PR
  open/update handoff, dry-run by default;
- `/api/sources/triage` for local source pre-triage before ingestion.
- `/api/ingestion/plan` and `/api/ingestion/run` for the source ingestion
  wizard, including proposal preview, ingest dry-run and LLM request handoff.

It does not provide arbitrary shell access. Mutating Git operations are scoped
to proposal branches and the Pull Request handoff remains the human gate.
The ingestion wizard executes read/dry-run steps directly, while write steps
stay behind an explicit UI toggle and proposal-branch checks.

## Build

```sh
npm test
npm run build
npm run test:visual
```

`npm run test:visual` builds the static app, serves it with Vite preview and
compares screenshot baselines for the world perspectives (`/demo/w/radar`,
`/demo/w/atlas`, `/demo/w/districts`), the 2D routes (`/demo/review`,
`/demo/sources`, `/demo/health`), the legacy `/pages/:id` redirect and a
keyboard-only drill → lock → read → retreat loop, all over the bundled sample
data. Use `npm run test:visual:update` only when intentionally accepting
visual changes.

## Deployment inputs

Each implementation can prepare its own static deploy inputs from the repo root:

```sh
python3 scripts/wiki_web_deploy_bundle.py --out data/derived/wiki/web-cockpit-deploy --target vercel_static --mode static --clean
```

The bundle contains `wiki-cockpit.config.json`, `snapshot/*.json` and a
`DEPLOYMENT.md` review proof. Keep private snapshots under the implementation's
own deployment boundary; the public kit should only ship sample/open data.

## Runtime config

The app loads `/wiki-cockpit.config.json` at runtime:

```json
{
  "api_base": "/api",
  "snapshot_base": "",
  "repo_label": "",
  "mode": "local_operator"
}
```

- `api_base`: operator API base URL. Use `/api` for local Vite proxy or a
  trusted Cloud Run operator adapter.
- `snapshot_base`: optional static snapshot base URL. When empty, operational
  routes try `${api_base}/snapshot` and show an explicit unavailable state if
  it fails. Bundled sample data is reachable only through `/demo`.
- `repo_label`: optional display label for hosted review surfaces.
- `mode`: display/runtime mode label such as `static`, `local_operator` or
  `github_connected`.

## Presentation config (per-implementation customization)

Every implementation can restyle page types, contexts and trust colors without
forking the app. The same `wiki-cockpit.config.json` accepts optional
presentation overrides consumed by `src/data/presentation.ts`:

```json
{
  "page_types": {
    "claim": { "label": "hipótese", "shape": "diamond", "accent": "#e8c268" },
    "meu_tipo_local": { "label": "nota de campo", "family": "content", "shape": "sphere" }
  },
  "contexts": {
    "financeiro": { "label": "Finanças", "accent": "#4cb58c" }
  },
  "trust_colors": {
    "stale": "#ff9c54"
  }
}
```

- `page_types.<type>`: override `label` (shown across lists, previews and the
  3D map), `shape` (one of `sphere`, `hub`, `crystal`, `diamond`, `comet`,
  `slab`, `spark`), `family` (legend grouping) and `accent`.
- `contexts.<name>`: override the display `label` and the area `accent` color
  (node bodies, wedge rims, group pills, legend). Without an override, sorted
  context names get distinct slots from the built-in 12-color palette. Avoid
  the reserved state accents (amber `#ffb454`, purple `#c57cff`, risk red
  `#ff7a8a`) — an area must never impersonate a state.
- `trust_colors`: override the state-accent palette used by annotations —
  chips, deadline arcs, embers/stems, glows (`fresh`, `stale`, `unknown`,
  `proposal`, `root`, `risk`).

Unknown page types fall back to a readable default (underscores become spaces,
sphere shape), so localized repos with custom `wiki.page-types.yaml` entries
work without any frontend change. In the 3D map, **hue always means the page's
area, tone/aging always means state, shape always means content kind, and
lines always mean typed relations** (`moc_parent` navigation, `source_ref`
evidence, links, PR impact, ingestion chains) — overrides restyle those
encodings but must not repurpose them.

The static build can be hosted later with a configured snapshot URL or bundled
sample/open data. Vercel should be treated as static/read-only unless a separate
trusted operator runner exists. GCP/Cloud Run can host a controlled operator
adapter later, but credentials and private snapshots stay outside the public kit
and writes still go through branch/PR workflows.
