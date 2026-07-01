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
  GitHub Pull Request human gate.
