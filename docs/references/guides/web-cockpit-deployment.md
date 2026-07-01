---
page_id: guide-web-cockpit-deployment
page_type: reference
title: "Web cockpit deployment adapters"
context: system
visibility: public_candidate
updated_at: 2026-07-01
stale_after_days: 90
source_refs:
  - plan-threejs-operational-dashboard-2026-07-01
---

# Web Cockpit Deployment Adapters

The first supported path is local operation from a real checkout. Hosted
deployment is an adapter choice owned by each implementation.

## Runtime Contract

The Vite app reads `/wiki-cockpit.config.json` at runtime:

| Key | Meaning | Local default |
| --- | --- | --- |
| `api_base` | Operator API base URL. | `/api` |
| `snapshot_base` | Static snapshot base URL. Empty means try `${api_base}/snapshot`, then sample data. | empty |
| `repo_label` | Display label for the deployed surface. | empty |
| `mode` | Runtime label shown in the UI. | `local_operator` |

The static build never needs repository write credentials. Any hosted writer
must still operate through proposal branches and Pull Requests.

Static snapshots include operational JSON files such as `manifest.json`,
`operations.json`, `git.json`, `timeline.json` and `diff.json`. Treat
`diff.json` as review evidence: public deployments should use synthetic/open
snapshots, while private implementations should keep real branch diffs behind
their private deployment boundary.

## Implementation Deploy Bundle

Each implementation should generate its own deploy inputs and review proof:

```sh
python3 scripts/wiki_web_deploy_bundle.py \
  --out data/derived/wiki/web-cockpit-deploy \
  --target vercel_static \
  --mode static \
  --snapshot-base /snapshot \
  --data-boundary synthetic_or_public \
  --clean
```

The command writes:

- `wiki-cockpit.config.json` with the runtime API/snapshot contract;
- `snapshot/*.json` from the deterministic web snapshot;
- `DEPLOYMENT.md` with the declared target, mode, data boundary and review
  checklist.

The output stays under `data/derived/` by default. Copy it into a host-specific
build only after reviewing the data boundary for that implementation.

## Vercel Static Review

Use Vercel as a static/read-only review surface.
Start from
[vercel.static.json](../templates/deploy/web-cockpit/vercel.static.json) when an
implementation wants a copyable host config.

```sh
cd apps/wiki-cockpit
npm ci
npm run build
```

Recommended runtime config for a public sample deploy:

```json
{
  "api_base": "",
  "snapshot_base": "/sample-snapshot",
  "repo_label": "wiki-viva-kit sample",
  "mode": "static"
}
```

Do not attach a mutating Git runner to Vercel unless a separate trusted operator
design is reviewed. Serverless functions should not receive broad repository
tokens by default.

## GCP Cloud Run Operator Adapter

Cloud Run can host a controlled operator service when an implementation needs
remote review or team access. The adapter must define:

| Concern | Required decision |
| --- | --- |
| Repository checkout | Which repo/branch is mounted or cloned. |
| Identity | GitHub App or narrowly scoped token, never personal broad tokens. |
| Writes | Proposal branches only; no direct writes to the approved branch. |
| Secrets | Stored in Secret Manager, not in repo snapshots or static assets. |
| Data boundary | Private snapshots stay private; public deploys use synthetic/open data. |
| Audit | PR body records build command, runtime mode and data boundary. |

Recommended runtime config for a trusted operator adapter:

```json
{
  "api_base": "https://<cloud-run-service>/api",
  "snapshot_base": "",
  "repo_label": "<repo label>",
  "mode": "controlled_operator"
}
```

The copyable example files are
[cloud-run.operator.Dockerfile](../templates/deploy/web-cockpit/cloud-run.operator.Dockerfile)
and
[cloud-run-service.template.yaml](../templates/deploy/web-cockpit/cloud-run-service.template.yaml).
They intentionally omit credentials; each implementation must supply identity
and access control outside the public kit.

The open-source kit provides this contract and local server. Each downstream
deployment must provide its own proof, credentials design and rollback plan.
