# Wiki Cockpit App

Local-first web cockpit for Wiki Viva. The 3D scene is the primary navigation
surface: one continuous knowledge world where drill level is camera altitude
bound to the URL and reading happens inside the world.

## The navigable world

The canonical share grammar is one real center plus registered query state:
`/w?view=<view>&center=<page>&lens=<lens>&overlay=<metric>`. Browser history,
breadcrumbs and deep links restore the same semantic question. Legacy
positional `/w/:perspective/:context?/:group?/:pageId?` links remain readable,
but canonical writers normalize them into query-owned state rather than
extending that old grammar. When an old projection still needs its positional
context to preserve meaning, normalization carries it only as
`compat_context=...` together with `runtime=compat`; native v8 routes never
author that compatibility field.

The five native v8 views preserve the same page identities and runtime:

- **Quadrants** — the AQAL map around the current real center.
- **Radar** — what needs attention and why.
- **Sources** — evidence, source lifecycle and ingestion reachability.
- **Work** — decisions, actions and human-gated operational state.
- **Timeline / Chronoscope** — a 2D temporal workbench over typed semantic
  events. It switches strictly between semantic-anchor, occurrence and
  recording time; missing clocks stay missing. It supports date/lane filters,
  deep-linked event cursors, keyboard roving focus and a full provenance/state
  inspector while suspending the WebGL scene.

**Atlas**, **Focus**, **Districts** and **Trails** are explicit compatibility
views. They keep old bookmarks meaningful with a visible warning, but they are
not presented as native v8 destinations. Old `/pages/:id` links enter the same
world with the reader open.

The URL also carries real family group, selected page, reader/dock,
`tray=packet|missions`, temporal filters and optional `pack_view`. Hover, camera coordinates, focus rings,
safe-area measurements and performance tiers remain ephemeral. A center change
clears stale group/reader state; opening a reader, tray or dock preserves the
single-primary-surface contract. A hand-written conflict normalizes with the
fixed precedence `dock > reader > tray`; toggles, close, refresh and
Back/Forward all read and write that same route state while returning keyboard
focus to the opener. `Esc` closes one layer at a time and then
retreats through page → group → context → world.

Large worlds cap the spatial draw set while exposing true totals and an
equivalent semantic 2D fallback. Timeline uses a bounded visible window over
the complete integrity-checked static event set; selected deep links do not
silently truncate or fabricate a prefix.

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
remain readable source with an explicit optional-renderer notice; the core v8
reader does not claim to execute or render them. A future diagram experience
pack must supply a lazy renderer, strict SVG sanitization, zoom and its own
bundle/accessibility evidence before changing that capability claim. Raw-data records
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

## Appearance and information density

The appearance control is a product setting, not a visual-debug switch. It
persists one of two contrast-checked themes — light `luminous-observatory` or
dark `night-mission-control` — and one of three density contracts:

- **Focus**: wider spacing and a calmer reading surface;
- **Balanced**: the default mixed navigation/reading mode;
- **Command**: denser operational scanning without shrinking touch targets.

Themes change semantic tokens, not the data grammar: overlay hue still means
the active metric, shapes still mean kind and lines still mean typed
relations. Both themes, all densities, reduced motion, mobile geometry and the
2D fallback are versioned test surfaces. Visible image/icon assets must be
licensed and hash-declared in the asset manifest. The UI's Lucide dependency
is pinned to an exact package/lock integrity, ISC identifier and versioned
third-party notice; the gate fails on version, tarball, license or notice drift.
The UI does not manufacture placeholder SVG/CSS artwork.

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
- **Body hue/ring** = the selected overlay's state. Radar normally uses the
  freshness overlay, so fresh/stale/unknown tokens answer that question
  directly; switching to evidence, actions, ownership, attention or quality
  changes the color meaning visibly and atomically. **Context** stays in
  position, wedge/keyline accents, labels, group pills and beacons — never as a
  competing body-color channel. **Shape** = kind (crystal = evidence source,
  faceted hub = navigation, sphere = content). **Lines** = typed relations
  (navigation, evidence, review impact, ingestion chains); hovering a node
  reveals its full neighborhood. Salience stays inverted: healthy is calm,
  problems gain stronger rings/emissive treatment.
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
**title screen** with five primary doors plus seven executable validation labs:

- `/demo/genesis` — **start from zero**: the genesis tutorial. The world
  starts EMPTY (the founding rite is the only interface) and each step is a
  real pre-built snapshot under `sample-snapshot/stages/<k>/`. Across nine
  stages numbered 0–8, found the root, attach the quadrant lenses, seed an area
  and a person, then attach the gamification package and a source. The tutorial
  swaps bundles; it never simulates state
  client-side, so the interface materializing between stages is the real
  stack gating.
- `/demo/w?center=root-alex-rivera&view=quadrants&tour=0` — the canonical
  **full world** route straight away (stage 8 equals it). `/demo/world` remains
  the deliberate title-screen shortcut that normalizes into this world.
- `/demo/w?demo_scenario=study_research_showcase&center=root-study-research-showcase&view=quadrants&overlay=evidence&tour=0`
  — the installed **Study/Research** conformance pack: 6 public synthetic
  pages, 11 temporal events, 4 pack-owned event kinds and a generic pack
  workbench.
- `/demo/w?demo_scenario=personal_finance_showcase&center=finance-transaction-income&view=timeline&time_mode=event&tour=0`
  — the installed **Personal Finance** vertical: 11 public synthetic pages,
  19 temporal events, 5 pack-owned event kinds and recurring operation
  descriptors. It is a product fixture, not a live ledger or financial advice.
- The guided-tour and free-exploration doors both enter the full world; their
  different `tour` values are deliberate, shareable state.

The expandable validation gallery is not decorative documentation. Its seven
isolated fixture repositories compile walking-skeleton, normal, dense,
source-lifecycle, governed-failure, compatibility and accessibility worlds.
Together their executable manifests bind 22 claims to 12 canonical `/demo/w`
routes; each claim names concrete test IDs and expected warning/failure states.

The demo universe is sealed: every generated URL is prefixed with `/demo`,
synthetic ids never resolve against the real snapshot, and mutating actions
are disabled.

Installed pack contributions are read from the integrity-covered
`experience_packs.json` composition. The catalog exposes its version, slots,
block packages and declared commands/operations. Registered `pack_view`
contributions open a generic, keyboard-accessible workbench over canonical
pack pages and can hand off to the reader or Chronoscope. The static demo never
pretends that a declared operation ran: execution remains disabled until a
pack-specific, human-gated operator adapter exists.

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
service. The proxy removes the browser `Origin` before forwarding; the operator
does not grant direct CORS access by default. Vite dev and preview also disable
their permissive loopback CORS default, so only the page's same origin can read
the proxy or static private snapshot. If a separate loopback frontend
must call the operator directly, explicitly set an exact trusted origin such as
`WIKI_COCKPIT_CORS_ORIGINS=http://127.0.0.1:5173` before starting the Python
server. Wildcards, remote hosts and URL credentials/path/query/fragment values
are rejected. The `/api/health` handshake advertises `wiki_web_server.v6`,
`operator_security_v2`, `cors_default_deny_v1`,
`action_state_transitions_v1` and
`wiki_operator_security.v2`; the cockpit refuses writes through a still-running
v1 process and asks for a restart. Origin-less same-origin proxy and CLI clients
continue to work, and explicitly allowlisted loopback origins retain direct
browser access. It exposes:

- `/api/snapshot/*.json` for the deterministic read model;
- `/api/pages/{id}/content` for the in-world reader: typed frontmatter, full
  markdown body, server-resolved internal links, backlinks and source refs
  (path-validated against the memory root);
- `/api/actions/run` for allowlisted fixed checks and derived writes;
- `/api/actions/transition` for a content-hash-bound, receipt-producing
  transition of a canonical `page_type: action` object; this is distinct from
  executing an operator command card;
- `/api/git/workflow` for proposal-branch workflows and draft PR
  open/update handoff, dry-run by default;
- `/api/sources/triage` for local source pre-triage before ingestion.
- `/api/ingestion/plan` and `/api/ingestion/run` for the source ingestion
  wizard, including proposal preview, ingest dry-run and LLM request handoff.

It does not provide arbitrary shell access. Mutating Git operations are scoped
to proposal branches and the Pull Request handoff remains the human gate.
The ingestion wizard executes read/dry-run steps directly, while write steps
stay behind an explicit UI toggle and proposal-branch checks.

## Required release matrices

The public browser matrix and the real downstream operator matrix are separate
contracts. `npm run test:e2e:release` runs only public/demo specifications with
`retries=0`, then rejects the JSON report if any required test skipped, retried,
flaked or failed. The public Playwright configuration ignores
`e2e/downstream/`, so missing private infrastructure can never appear as a
harmless public-CI skip.

Current worktree collection enumerates **102 public cells in 17 specifications**
and **2 mandatory downstream cells in 1 specification**. The versioned matrix
contains that exact 102+2 inventory; `check:release-matrix` must pass with zero
collection drift before either release command can produce evidence.

The downstream repository must start its exact local operator and same-origin
cockpit, then provide every attestation below — there are no defaults:

```sh
export WIKI_COCKPIT_SNAPSHOT_URL=http://127.0.0.1:5173/api/snapshot/pages.json
export WIKI_COCKPIT_REAL_BASE_URL=http://127.0.0.1:5173
export WIKI_COCKPIT_EXPECT_REPO_ID=<exact-repo-id>
export WIKI_COCKPIT_EXPECT_SNAPSHOT_REVISION=<exact-manifest-snapshot-id>
export WIKI_COCKPIT_EXPECT_SNAPSHOT_HASH=<exact-64-char-manifest-bundle-hash>
export WIKI_COCKPIT_EXPECT_CONSUMER_HEAD=<exact-clean-40-char-consumer-HEAD>
export WIKI_COCKPIT_EXPECT_PUBLIC_RELEASE_SHA=<exact-adopted-public-release-SHA>
export WIKI_COCKPIT_EXPECT_ADAPTER_HASH=<exact-64-char-downstream-adapter-hash>
export WIKI_COCKPIT_EXPECT_SNAPSHOT_VERSION=wiki_web_snapshot.v2
export WIKI_COCKPIT_EXPECT_RUNTIME_VERSION=wiki_world_runtime.v8
export WIKI_COCKPIT_EXPECT_SERVER_VERSION=wiki_web_server.v6
export WIKI_COCKPIT_EXPECT_TEMPORAL_GRAPH_VERSION=wiki_temporal_graph.v1
export WIKI_COCKPIT_EXPECT_TEMPORAL_EVENT_VERSION=wiki_temporal_event.v1
export WIKI_COCKPIT_EXPECT_EXPERIENCE_PACK_COMPOSITION_VERSION=wiki_experience_pack_composition.v1
export WIKI_COCKPIT_EXPECT_COMPOSITION_SHA256=<exact-64-char-experience-packs-composition-sha256>
# Explicit JSON is required. [] is valid when this consumer has no active pack.
export WIKI_COCKPIT_EXPECT_ACTIVE_PACKS='[{"id":"personal-finance","version":"0.1.0"}]'
export WIKI_COCKPIT_EXPECT_CAPABILITIES=operator_security_v2,cors_default_deny_v1,action_state_transitions_v1
export WIKI_COCKPIT_MIN_PAGES=<explicit-positive-minimum>
npm run test:e2e:operator
```

Run that command from the consumer checkout itself: the checker requires the
preflight consumer HEAD, clean snapshot `source_commit` and pre/post tested Git
subject to be the same commit.

### Restart a stale local operator safely

If the Codex diagnostics dock says the operator is outdated, stop the existing
Python operator and Vite proxy normally with `Ctrl-C`; do not keep or reuse the
old port occupant. From the consumer repository root, start fresh processes:

```sh
# terminal 1 — repository root
python3 scripts/wiki_web_server.py --host 127.0.0.1 --port 8765

# terminal 2 — repository root
npm --prefix apps/wiki-cockpit run dev:proxy
```

With both processes running, verify the same-origin handshake from
`apps/wiki-cockpit/` using the exact shared validator. This prints no nonce:

```sh
node --input-type=module <<'NODE'
import { validateOperatorHandshake } from "./src/contracts/operatorSecurity.js";

const response = await fetch("http://127.0.0.1:5173/api/health", {
  headers: { accept: "application/json" },
  cache: "no-store"
});
const result = validateOperatorHandshake(await response.json());
if (!response.ok || !result.ok) {
  console.error(result.errors.join("; ") || `health failed: ${response.status}`);
  process.exit(1);
}
console.log("operator handshake current: v6 / security v2 / default-deny CORS");
NODE
```

Open the Codex diagnostics dock and choose **Re-verify** / **Re-verificar**. The
operator rung must turn healthy without a page reload. The downstream preflight
now rejects a v4/v1 process even when it exposes a plausible Codex block, and
also rejects missing nonce/header/body bounds, non-POST mutation policy,
non-default-deny browser origin or a non-exact CORS allowlist.

The same-origin `/wiki-cockpit.config.json` served by that UI must independently
publish the adoption identity; expected environment values are comparisons, not
the source of truth:

```json
{
  "adoption": {
    "public_release_sha": "<40-char-public-release-SHA>",
    "adapter_manifest": "wiki.adapter-manifest.json",
    "adapter_hash": "<64-char-consumer-adapter-SHA-256>"
  }
}
```

Build and commit that identity with
[`wiki_adapter_manifest.py`](../../scripts/wiki_adapter_manifest.py) before the
browser gate; the complete workflow is in the
[downstream adapter manifest guide](../../docs/references/guides/downstream-adapter-manifest.md).
If the consumer has not implemented that runtime boundary, preflight stops at
`adoption_identity_unavailable`; it does not infer or echo an identity.

The preflight fetches pages, manifest, `temporal_graph.json`,
`experience_packs.json` and `/api/health` before launching the browser. A
missing variable, remote/non-loopback endpoint, repo/revision/hash
mismatch, dirty/old snapshot source commit, schema/runtime/operator version
drift, absent/mismatched public-release identity, missing/untracked/dirty
adapter manifest, adapter file hash/size drift, runtime/manifest/environment
adapter-hash disagreement, non-empty
`contract_errors`, missing security or required snapshot capability, wrong
temporal event/graph or experience-pack composition version, payload-integrity
drift, semantic composition-hash drift, active-pack mismatch, empty real-data
Timeline, cross-origin
snapshot/UI pair, oversized/slow JSON response or insufficient page count fails
closed. Active packs are an exact, canonically ordered JSON array of
`{"id","version"}` objects; `[]` is an explicit valid core-only state, never an
omitted assumption. The rendered-UI test observes the exact
`pages.json` and `manifest.json` responses used by the page and rechecks the
attested revision/hash, opens the real lazy-loaded Chronoscope, and opens the
generic pack workbench only when a pack is explicitly expected. Pack commands
and operations remain visible but disabled, and the journey asserts that it did
not send a mutation. One 390x844 forced-fallback passage with one non-default
theme/density pair is included as a bounded integration proof; the exhaustive
appearance, viewport and fallback cross-product remains owned by the public
matrix. Matching only `repo_id` is insufficient. The two
exact-repository tests cannot skip. Their normalized `downstream_required` gate
result hashes both the preflight record and the versioned exact
spec/project/test-cell matrix, the exact Playwright config/checkers and the
stable pre/post Git worktree fingerprint. The matrix contract is regenerated
only after reviewing the exact `playwright --list` diff; ordinary checks use
`npm run check:release-matrix`. Each required invocation creates a unique
`run_id` directory. Its report, subject, preflight and passing gate never reuse
a fixed path; every exit writes an atomic `run-result.json` with start/finish
times, the pre/post Git subjects and either a hashed passing gate or an explicit
blocked stage. Thus an early build, Playwright or checker failure remains durable
blocked evidence rather than leaving an older green file at the current run
location. The passing gate can be consumed by
the consumer PR; the public and
downstream gates are closed in their own repository receipts, while only a
future external authority may combine them into E5.

Release evidence is deliberately confined to the explicitly ignored,
tool-owned roots `apps/wiki-cockpit/test-results/**` and
`data/derived/wiki/release/**`. Every caller-controlled report, preflight,
subject, output and clear target must be a canonical repo-relative POSIX path
under its expected root, must remain untracked, and must not cross a symbolic
link in either the ancestor chain or target. Hard-linked targets are refused as
well, so an ignored alias cannot truncate a tracked file. Validation happens before any
mutation; cleanup unlinks regular evidence files only and never recursively
removes a caller-selected path.

## Build

```sh
npm test
npm run build
npm run test:e2e:release
```

`npm run test:e2e:release` builds the static app, serves it with Vite preview
and executes the exact versioned release matrix. That matrix covers the five
native world views (including Timeline / Chronoscope), the explicit
compatibility routes, normal/dense/Genesis demo worlds, installed Study and
Personal Finance pack showcases, both appearance themes and all three density
modes, desktop/mobile/keyboard/forced-fallback journeys, safe-area and
performance budgets, visual baselines, legacy normalization and the
drill → lock → read → retreat loop. It then enforces zero required skips,
flaky results and retries. Use `npm run test:visual:update` only when
intentionally accepting reviewed visual changes, and regenerate the exact
release-matrix contract only after reviewing the collected-cell diff.

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

Public release builds are deliberately synthetic and reproducible. `npm run build`
disables Vite `.env` loading, fails closed when an app-local `.env*`, any
`VITE_*`, `WIKI_COCKPIT_PROXY_API` or caller-provided `NODE_ENV` is present, and
materializes the package-owned
`scripts/public-release-runtime-config.json` into `dist/wiki-cockpit.config.json`.
It never rewrites or serves a downstream's tracked operator config as public
evidence. Consumer-specific deployment remains a separate deploy-bundle/runtime
boundary. Required release runs record those fixed effective inputs alongside
the exact `dist/` inventory in `wiki_release_build_manifest.v2`; the independent
Python receipt validator reopens both contracts.

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
  (wedge/keyline, group pills, beacons, labels and contextual legend — not
  node bodies). Without an override, sorted context names get distinct slots
  from the built-in 12-color palette. Avoid
  the reserved state accents (amber `#ffb454`, purple `#c57cff`, risk red
  `#ff7a8a`) — an area must never impersonate a state.
- `trust_colors`: override the state-accent palette used by annotations —
  chips, deadline arcs, embers/stems, glows (`fresh`, `stale`, `unknown`,
  `proposal`, `root`, `risk`).

Unknown page types fall back to a readable default (underscores become spaces,
sphere shape), so localized repos with custom `wiki.page-types.yaml` entries
work without any frontend change. In the world, **node body hue/ring always
means the active overlay state, context means position/label/keyline, shape
means content kind, and lines mean typed relations** (`moc_parent` navigation,
`source_ref` evidence, links, PR impact, ingestion chains) — overrides restyle
those encodings but must not repurpose them.

The static build can be hosted later with a configured snapshot URL or bundled
sample/open data. Vercel should be treated as static/read-only unless a separate
trusted operator runner exists. GCP/Cloud Run can host a controlled operator
adapter later, but credentials and private snapshots stay outside the public kit
and writes still go through branch/PR workflows.
