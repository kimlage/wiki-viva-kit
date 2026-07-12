# Downstream adapter identity manifest

`wiki_downstream_adapter_manifest.v1` turns a consumer's local adapter identity
into reproducible evidence. The downstream release gate no longer accepts an
`adapter_hash` merely because `wiki-cockpit.config.json` repeats the expected
environment value.

The consumer owns `wiki.adapter-manifest.json`. It is tracked in that consumer,
blocked from the public-kit import, and never copied upstream. Its only fields
are the exact schema, a canonical ordered file inventory and the aggregate
`adapter_sha256`:

```json
{
  "schema_version": "wiki_downstream_adapter_manifest.v1",
  "files": [
    {
      "path": "adapters/local-presentation.json",
      "sha256": "<sha256 of the reopened bytes>",
      "bytes": 321
    }
  ],
  "adapter_sha256": "<sha256 of canonical {schema_version,files}>"
}
```

`adapter_sha256` excludes itself. It also excludes
`apps/wiki-cockpit/public/wiki-cockpit.config.json`: that config publishes the
hash, so including it would create a cycle. The manifest itself is excluded for
the same reason.

## Safe consumer workflow

Choose only the consumer-owned adapter code or declarative overrides that
materially distinguish the downstream integration. Every file must already be
Git-tracked. The build command may read reviewed working-tree edits so the
adapter and manifest can be committed together:

```sh
python3 scripts/wiki_adapter_manifest.py build \
  --file adapters/local-presentation.json \
  --file scripts/wiki_private_snapshot_adapter.py
```

Copy the emitted `adapter_sha256` into the consumer-owned runtime config and
declare the fixed manifest path:

```json
{
  "adoption": {
    "public_release_sha": "<exact adopted public commit>",
    "adapter_manifest": "wiki.adapter-manifest.json",
    "adapter_hash": "<exact adapter_sha256>"
  }
}
```

Commit the adapter files, manifest and runtime config, then verify from the
clean commit before running the downstream browser matrix:

```sh
git add wiki.adapter-manifest.json adapters/ scripts/wiki_private_snapshot_adapter.py \
  apps/wiki-cockpit/public/wiki-cockpit.config.json
git commit -m "adopt: bind downstream adapters"
python3 scripts/wiki_adapter_manifest.py check
npm --prefix apps/wiki-cockpit run test:e2e:operator
```

The check and Node preflight independently reopen every file, compare
SHA-256/byte counts, recompute the canonical aggregate and require manifest,
files and runtime hash to agree. The release receipt repeats the verification
against the same clean consumer subject.

## Fail-closed boundary

The manifest rejects:

- absolute paths, traversal, backslashes and non-canonical spellings;
- symlinked ancestors/targets, hard links, non-regular or oversized files;
- untracked or, during `check`/release, dirty files;
- `memories/`, `memorias/`, `data/raw/`, `data/derived/`, `.wiki-viva/`,
  generated outputs, test results and dependency/build trees;
- `.env*`, credential/token/password/private-key names;
- `wiki.adapter-manifest.json` and any `wiki-cockpit.config.json`.

This contract proves the bytes of declared adapters. It does not claim those
files are correct product choices, authorize an operation, publish private
memory, or replace the human PR/release gate.

Schema: [wiki-downstream-adapter-manifest-v1.schema.json](../schemas/wiki-downstream-adapter-manifest-v1.schema.json).
