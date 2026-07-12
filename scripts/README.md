# Scripts

Command-line entry points for operating the wiki viva kit.

The scripts wrap deterministic behavior from [wiki_core](../wiki_core/README.md):
ingestion, audit, source registry, operation cockpit, quality reports, PR
summaries and format conversions. They do not call an LLM directly; model
reading remains delegated to the agent running the repo.

Use [wiki_audit.py](wiki_audit.py), [wiki_input_stage.py](wiki_input_stage.py),
[wiki_operation_compile.py](wiki_operation_compile.py) and
[wiki_pr_summary.py](wiki_pr_summary.py) as the default PR gate surface.

Use [wiki_quadrant_contract.py](wiki_quadrant_contract.py) when an external
consumer needs the canonical Wilber/AQAL `q1/q2/q3/q4` mapping without scraping
templates or historical proposals.

Use [wiki_web_snapshot.py](wiki_web_snapshot.py) to generate the local/static
JSON read model for the web cockpit, and [wiki_web_server.py](wiki_web_server.py)
to run the localhost-only operator API with allowlisted commands. Live snapshot
publication stores immutable, content-addressed revisions and atomically swaps
one repository-contained relative pointer; supported filesystem readers resolve
that pointer once, hold a shared revision lease and validate the strict
no-symlink/no-extra inventory, owner repo, manifest repo and complete hashed
envelope from descriptor-pinned bytes instead of reopening the compatibility
path for every file. Post-commit cleanup is receipted; recognizable
`.cleanup-*` tombstones are removable only with a separately fsynced,
random-ID/SHA-bound receipt in the owned store, so a user-created prefix match
is preserved. Revision install/archive use atomic no-replace primitives and
never overwrite a broken or external-target SHA symlink.
Filesystem health uses the same pinned contract, with a one-second successful
validation cache whose hits still recheck metadata and report cold/warm cost
against a 100 ms diagnostic budget. This is distinct from the operator's live
`/api/snapshot` build cache. `--flat-build` (and static auto-mode on Windows)
creates only an offline artifact; its host must activate the complete build.
Use [wiki_web_deploy_bundle.py](wiki_web_deploy_bundle.py) when one
implementation needs portable static deploy inputs plus a deployment proof
without choosing Vercel, GCP or any other host inside the core kit.

Use [wiki_release_receipt.py](wiki_release_receipt.py) after the public and
downstream required matrices have emitted normalized gate-result JSON. It binds
their counts, skips, flaky/retry usage and evidence hashes to the exact Git SHA,
tree and canonical staged/unstaged/untracked/submodule fingerprint. Version 1
is deliberately **browser-evidence-only**: `--promote-e5` always exits `2` with
`e5_external_authority_required`. A future E5 claim needs an external signed
CI/reviewer authority; repository-authored JSON is not a signature.

```sh
python3 scripts/wiki_release_receipt.py \
  --evidence data/derived/wiki/release-evidence.json \
  --base-sha "$BASE_SHA" \
  --promote-e5
python3 scripts/wiki_release_receipt.py --check --base-sha "$BASE_SHA"
```

The receipt schema is
[wiki-release-receipt-v1.schema.json](../docs/references/schemas/wiki-release-receipt-v1.schema.json).
Evidence and receipts must stay under ignored paths so writing a receipt cannot
change the subject it attests. Receipt outputs are POSIX-only create-once files:
an existing target or symlinked ancestor is a refusal, never a replacement.
Mutable release-evidence operations fail closed on Windows while offline flat
snapshot generation remains supported. `public_release` output is secret/PII/entity scanned and
marked `public_safe`; `private_adoption` remains `private_internal` but is still
secret-scanned. Neither is an E5 receipt.

Use [wiki_adapter_manifest.py](wiki_adapter_manifest.py) in a downstream
consumer to compile `wiki.adapter-manifest.json` from an explicit ordered set of
tracked adapter files, then run `check` from the committed clean consumer HEAD.
The aggregate hash excludes the manifest and `wiki-cockpit.config.json` to avoid
self-reference, while the downstream Node preflight and release receipt reopen
and rehash every declared file. The manifest is consumer-owned and blocked from
the public import. See the
[downstream adapter manifest guide](../docs/references/guides/downstream-adapter-manifest.md).

Use [wiki_pack.py](wiki_pack.py) for the review-first lifecycle of declarative
experience packs: list, inspect and preview are read-only; install, upgrade,
disable and remove support `--dry-run`, fail before mutation on dependency,
capability or slot conflicts, and refuse real writes outside an already
checked-out `wiki/*` branch. `compile-fixture` materializes only declared
dense/failure scenarios below the managed `.wiki-viva/fixture-output/`
namespace; it cannot replace canonical memory or an unowned directory. Source
manifest and whole-tree hashes are pinned in the registry and installed pack
bytes are pinned in
`wiki.packs.lock.yaml`; the mutation boundary excludes user-authored
`memories/`. `validate --all` resolves every registered source version and
verifies the complete installed composition; it is the release gate and does
not ignore a broken uninstalled source. See the
[experience-pack authoring guide](../docs/references/guides/experience-pack-authoring.md).

The evidence manifest is intentionally a list of file references, not pasted
test claims. Each gate-result file uses `wiki_test_gate_result.v1` and carries
the exact allowlisted `id`/`command_id`, matching `scope`, `status`, counts,
subject SHA/tree, full worktree fingerprint and mandatory raw evidence; the
generator reads each file once, hashes those bytes and reloads it during
`--check`. Free command strings and sensitive metadata paths are rejected.
Browser gate results additionally bind the
versioned release-matrix contract as `supporting_evidence`; the downstream gate
also binds its exact repo/revision/hash/capability/min-pages preflight. Every
supporting file is independently path-checked and re-hashed by the receipt.
Direct artifacts use a closed registry: `release_note` Markdown,
`snapshot_manifest` JSON (`wiki_web_snapshot.v2`) or a
`visual_evidence_manifest` JSON (`wiki_visual_evidence_manifest.v1`) that lists
the hashes and visual context of screenshots. Binary screenshots are never
bound directly. Public and downstream gates are attested in separate
repository receipts; the other scope is explicit `not_applicable` until an
external authority combines both for E5. A clean `browser_closure` also
requires an exact ancestor `--base-sha`.

```json
{
  "release_id": "v8-rc2",
  "receipt_kind": "public_release",
  "artifacts": [
    {"id": "snapshot-manifest", "kind": "snapshot_manifest", "path": "data/derived/wiki/web-snapshot/manifest.json"}
  ],
  "test_scopes": {
    "public_required": {"gate_results": ["apps/wiki-cockpit/test-results/release-runs/public_required/<run_id>/gate-result.json"]}
  },
  "review": {"human_product_gate": "passed", "human_privacy_gate": "passed"},
  "waivers": []
}
```

The v8 downstream release flow is read-only by default:

- [wiki_upgrade_inventory.py](wiki_upgrade_inventory.py) validates the
  public-safe consumer/wave inventory.
- [wiki_upgrade_preflight.py](wiki_upgrade_preflight.py) checks the pinned
  release, consumer branch/worktree, current gate receipts, portable drift,
  snapshot, overrides and privacy/redaction without copying files.
- [wiki_upgrade_report.py](wiki_upgrade_report.py) validates allowlisted import
  evidence and compiles deterministic JSON/Markdown migration reports with
  gates, visual QA and rollback.

The package and runbook live under
[docs/references/upgrades/wiki-viva-v8](../docs/references/upgrades/wiki-viva-v8/upgrade-package.yaml)
and
[wiki-viva-v8-downstream-upgrade.md](../docs/references/guides/wiki-viva-v8-downstream-upgrade.md).
