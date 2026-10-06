# Web Cockpit Deployment Templates

Copy these templates into an implementation repo when that repo owns a hosted
deployment. They are examples, not a required deployment path for the kit.

## Static Review

Use `vercel.static.json` for a read-only Vercel or static-host deploy. Generate
implementation-owned inputs first:

```sh
python3 scripts/wiki_web_deploy_bundle.py \
  --out data/derived/wiki/web-cockpit-deploy \
  --target vercel_static \
  --mode static \
  --snapshot-base /snapshot \
  --data-boundary synthetic_or_public \
  --clean
```

Then copy the generated `wiki-cockpit.config.json` and `snapshot/` directory
into the deployed static root. Public deploys should use sample/open snapshots.
Private snapshots stay behind the implementation's private boundary.

## Synthetic Vercel Function Preview

An opt-in adapter prepares Vercel Build Output API v3 using only the committed
public `walking_skeleton` fixture. It leaves the static template, local operator
and consumer configuration unchanged:

```sh
npm --prefix apps/wiki-cockpit ci
npm --prefix apps/wiki-cockpit run build
python3 scripts/wiki_vercel_preview.py --demo --out tmp/vercel-preview
```

The output is `tmp/vercel-preview/.vercel/output`; its separate
`preview-receipt.json` records the Git source, snapshot revision and byte hashes
without account identities or host paths. Use a new output directory each time.
The generator refuses dirty fixtures, invalid snapshot/reader contracts,
symlinks, external outputs and existing directories. It does not read consumer
memories, export private snapshots, create projects, configure ACLs or deploy.

All HTML, JSON, assets and the synthetic attachment pass through one Node.js 22
function; no `static/` payload bypass exists. Only `/w` serves the shell. Missing
resources, including `/snapshot/boot`, return JSON 404 so the existing loader can
fall back to individual snapshot files. Reader requests require the current
`snapshot_id`; stale or duplicate revisions return JSON 409. GET/HEAD responses,
errors and redirects use `private, no-store`; writes return JSON 405. A pinned
manifest and complete payload checks freeze one release before serving it.

Before an operator deploys the prebuilt directory, configure and read back
[Vercel Authentication](https://vercel.com/docs/deployment-protection/methods-to-protect-deployments/vercel-authentication)
for **All Deployments**, then check the eligible team/project audience, grants,
share links and automation bypasses. The runtime does not authenticate request
headers or cookies. Its local tests prove routing/integrity/cache behavior, not
the provider's authentication, TLS, logout or deployment URL protection.
Validate those on the first protected synthetic Preview before considering any
private-data adapter. This command deliberately has no private-data option.

Downstream compatibility follows the existing sync manifest: C1 copies the
optional script/core/runtime byte-for-byte; C2 keeps generating the public demo.
Consumers that audit their own command catalog need an explicit C3 catalog entry
for `wiki_vercel_preview.py`. Their memory, configuration, authentication and
deployment policies remain consumer-owned. Commit the regenerated demo before
using this command, because the package verifies its fixture against Git HEAD.
No schema migration or change to the default cockpit route is required.

Vercel's [Build Output API](https://vercel.com/docs/build-output-api/primitives)
packages the function and its immutable bundle together. The existing normal
Python tests and `npm --prefix apps/wiki-cockpit run test:gates` cover this adapter.

## Cloud Run Operator

Use `cloud-run.operator.Dockerfile` and `cloud-run-service.template.yaml` only
for a controlled operator service. The container exposes the Python operator API;
the frontend can point `api_base` at the Cloud Run URL.

Before deploying, the implementation must decide:

- which repo/branch is cloned or mounted;
- which identity is allowed to publish proposal branches;
- where credentials are stored outside the repo;
- whether the service is internal-only or publicly reachable;
- how PR review proves that writes still go through proposal branches and the
  GitHub Pull Request review policy.
