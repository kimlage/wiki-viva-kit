# Wiki Cockpit App

Local-first web cockpit for Wiki Viva.

## The freshness radar

The home view (`/ops`) centers on a full-bleed 3D "freshness radar" where every
coordinate is operational data:

- **Angle** = context: each context owns a labeled wedge sized by its page
  count, with a rim pill showing per-status dot counts (click it to select the
  context hub).
- **Distance from center** = time since verification: trusted content orbits
  near the root core; anything past the amber **deadline arc** is beyond its
  freshness window and drifts toward the rim.
- **Height** = approval state: draft changes float above the disc on visible
  stems; approved content stays on the plane.
- **Color** = trust, with inverted salience: healthy pages are dark and quiet,
  while stale, draft and risk-flagged pages glow. **Shape** = kind (crystal =
  evidence source, faceted hub = navigation, sphere = content). **Lines** =
  typed relations (navigation, evidence, review impact, ingestion chains);
  hovering a node reveals its full neighborhood.
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

HUD: a top intent bar (task selector + workspace gate chip), a bottom status
strip whose trust chips filter the map in place, a hover tooltip with links and
evidence counts, and a dismissable selection card. Under
`prefers-reduced-motion`, without WebGL or with `?visual=1`, the map renders a
deterministic 2D SVG plan view of the same layout, and all motion (ambient
pulses and particles) stops when the tab is hidden or reduced motion is set.

## Run with sample data

```sh
npm install
npm run dev
```

The app falls back to `public/sample-snapshot/` when no local operator API is
running.
Open `/demo` to force the bundled sample snapshot even when a local operator API
is available.

### Demo data vs your wiki

`public/sample-snapshot/` is a **synthetic interface example**: a fictional
product-team wiki (product/research/finance/example/system contexts) with
evidence chains, stale content, draft decisions and risk flags, built to
showcase every cockpit affordance. It is not this repository's wiki. The kit's
own operational wiki lives in `memories/` and is what you see when the cockpit
runs against a real checkout snapshot. The UI shows a persistent banner while
demo data is active so the two are never confused.

## Run against a local checkout

From the repo root:

```sh
python3 scripts/wiki_web_snapshot.py --out data/derived/wiki/web-snapshot --clean
python3 scripts/wiki_web_server.py --host 127.0.0.1 --port 8765
```

Then, in this directory:

```sh
npm run dev
```

Vite proxies `/api` to `http://127.0.0.1:8765`. The Python server exposes:

- `/api/snapshot/*.json` for the deterministic read model;
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
compares screenshot baselines for `/demo`, `/review`, `/sources`, `/health` and
`/pages/:id` using the bundled sample data. Use `npm run test:visual:update`
only when intentionally accepting visual changes.

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
- `snapshot_base`: optional static snapshot base URL. When empty, the app tries
  `${api_base}/snapshot` and then bundled sample data.
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
    "financeiro": { "label": "Finanças", "accent": "#ffb454" }
  },
  "trust_colors": {
    "stale": "#ff9c54"
  }
}
```

- `page_types.<type>`: override `label` (shown across lists, previews and the
  3D map), `shape` (one of `sphere`, `hub`, `crystal`, `diamond`, `comet`,
  `slab`, `spark`), `family` (legend grouping) and `accent`.
- `contexts.<name>`: override the display `label` and the orbit/legend `accent`
  color of a context.
- `trust_colors`: override the freshness/approval palette (`fresh`, `stale`,
  `unknown`, `proposal`, `root`, `risk`).

Unknown page types fall back to a readable default (underscores become spaces,
sphere shape), so localized repos with custom `wiki.page-types.yaml` entries
work without any frontend change. In the 3D map, **color always means trust
state, shape always means content kind, and lines always mean typed relations**
(`moc_parent` navigation, `source_ref` evidence, links, PR impact, ingestion
chains) — overrides restyle those encodings but must not repurpose them.

The static build can be hosted later with a configured snapshot URL or bundled
sample/open data. Vercel should be treated as static/read-only unless a separate
trusted operator runner exists. GCP/Cloud Run can host a controlled operator
adapter later, but credentials and private snapshots stay outside the public kit
and writes still go through branch/PR workflows.
