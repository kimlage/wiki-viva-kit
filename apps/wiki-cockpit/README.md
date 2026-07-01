# Wiki Cockpit App

Local-first web cockpit for Wiki Viva.

## Run with sample data

```sh
npm install
npm run dev
```

The app falls back to `public/sample-snapshot/` when no local operator API is
running.

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
- `/api/git/workflow` for proposal-branch workflows, dry-run by default;
- `/api/sources/triage` for local source pre-triage before ingestion.

It does not provide arbitrary shell access. Mutating Git operations are scoped
to proposal branches and the Pull Request handoff remains the human gate.

## Build

```sh
npm test
npm run build
```

The static build can be hosted later with a configured snapshot URL or bundled
sample/open data. Vercel should be treated as static/read-only unless a separate
trusted operator runner exists. GCP/Cloud Run can host a controlled operator
adapter later, but credentials and private snapshots stay outside the public kit
and writes still go through branch/PR workflows.
