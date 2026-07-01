# Wiki Cockpit App

Local-first web cockpit for Wiki Viva.

## Run with sample data

```sh
npm install
npm run dev
```

The app falls back to `public/sample-snapshot/` when no local operator API is
running.
Open `/demo` to force the bundled sample snapshot even when a local operator API
is available.

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

The static build can be hosted later with a configured snapshot URL or bundled
sample/open data. Vercel should be treated as static/read-only unless a separate
trusted operator runner exists. GCP/Cloud Run can host a controlled operator
adapter later, but credentials and private snapshots stay outside the public kit
and writes still go through branch/PR workflows.
