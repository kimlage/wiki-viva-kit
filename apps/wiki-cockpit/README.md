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

Vite proxies `/api` to `http://127.0.0.1:8765`. The Python server exposes the
snapshot and allowlisted action runner only; it does not provide arbitrary shell
access.

## Build

```sh
npm test
npm run build
```

The static build can be hosted later with a configured snapshot URL or bundled
sample/open data. Hosted deployments must keep private snapshots and credentials
outside the public kit and continue writing through branch/PR workflows.
