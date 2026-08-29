---
title: "Wiki Viva v8 downstream upgrade runbook"
page_id: guide-wiki-viva-v8-downstream-upgrade
page_type: reference_guide
context: system
visibility: public_candidate
updated_at: 2026-08-28
stale_after_days: 90
sources_policy: release_runbook
gate: github_pr
sensitive_data_policy: no_personal_data
---

# Wiki Viva v8 downstream upgrade runbook

Upgrade a consumer through one readable, reversible PR. The current contract is
B0 → C1 → C2 → C3; the previous Lane A/Lane B certification machinery is
retired and is not a gate.

```mermaid
flowchart LR
    B0["B0 dry-run"] --> PR["Consumer branch / PR"]
    PR --> C1["C1 kit-owned sync"]
    C1 --> C2["C2 regenerate"]
    C2 --> C3["C3 consumer migration"]
    C3 --> Gates["Consumer gates"]
    Gates --> Human["Human review + merge"]
```

## 1. Pin the kit source

Checkout the desired tag or commit in a clean kit worktree. Review its release
notes and **Upgrading** section. The source SHA recorded by `kit.lock` is the
portable version pin.

For the consolidated source-management release, use `v8.1.0` or newer. Do not
sync a v6 tag into a consumer whose `kit.lock` already records the v8 runtime;
that is a downgrade and its B0 removal plan must not be applied.

## 2. Run B0 without mutation

```sh
python3 /path/to/wiki-viva-kit/scripts/wiki_sync_from_kit.py \
  --kit /path/to/wiki-viva-kit \
  --consumer /path/to/consumer \
  --dry-run
```

B0 reports source SHA, portable tree digest, dirty consumer state, C1
add/change/remove paths, C2 generators and declared C3 commands. It never writes
the consumer. `--json` provides machine-readable output.

Review the conceptual diff. A first adoption does not delete unknown consumer
files. Later adoptions may remove only paths listed as managed in the prior
`kit.lock` and no longer present in the kit contract.

## 3. Create the consumer PR boundary

Start from current consumer `main`, create one focused branch and ensure the
worktree is clean. The PR is the rollback mechanism: before merge, discard or
close it; after merge, use a normal revert PR.

## 4. Apply C1, C2 and explicit C3

```sh
python3 /path/to/wiki-viva-kit/scripts/wiki_sync_from_kit.py \
  --kit /path/to/wiki-viva-kit \
  --consumer /path/to/consumer \
  --c3-command "python3 scripts/consumer_migration.py"
```

- **C1:** copies Git-tracked kit-owned regular files byte-for-byte and preserves
  executable mode. Blocklisted paths win.
- **C2:** runs deterministic generator argv declared by `sync-manifest.yaml`.
- **C3:** runs only commands supplied explicitly by the consumer operator.
  Adapters, configuration and domain content are consumer-owned.

Apply refuses a dirty consumer unless `--allow-dirty` is deliberately supplied.
Do not use that override merely for convenience; a focused PR should normally
start clean.

### Source-management C3 for existing consumers

The kit can copy the source runtime, but it cannot infer a consumer's real
folders, accounts, authorization pointers or update policy. Existing consumers
should run the deterministic migration and rebuild their generated read models
as explicit C3 commands:

```sh
python3 /path/to/wiki-viva-kit/scripts/wiki_sync_from_kit.py \
  --kit /path/to/wiki-viva-kit \
  --consumer /path/to/consumer \
  --c3-command "python3 scripts/wiki_migrate_templates.py --apply --operational-recipes" \
  --c3-command "python3 scripts/wiki_source_registry.py --write" \
  --c3-command "python3 scripts/wiki_input_stage.py --write" \
  --c3-command "python3 scripts/wiki_operation_compile.py --write"
```

Review every inferred `source_kind`, lifecycle schedule, stream, locator and
authorization pointer in the consumer PR. A recipe stores only a pointer to an
authorized mechanism, never a token. Local organization icons belong under
`apps/wiki-cockpit/public/source-icons/` with provenance recorded in
`apps/wiki-cockpit/SOURCE_BRAND_NOTICES.md`; known platforms use the bundled
portable identities.

From v8.1.5 onward, `--operational-recipes` promotes an earlier TODO recipe only
when its complete block still exactly matches the framework-generated scaffold,
including the assisted-migration marker. Any owner edit makes the recipe
canonical and protects it from replacement. Rebuilding the input stage after
source migration also converts generated warning paths into clickable relative
links, so strict `require_markdown_links` consumers do not need to hand-edit a
generated page.

After success, `kit.lock` records:

- kit source SHA;
- sync-manifest SHA-256;
- portable-tree SHA-256;
- every managed relative path, content SHA-256 and Git file mode.

It contains no absolute host path, private route, screenshot, PII or receipt.

## 5. Prove idempotence and consumer behavior

Run B0 again. C1 should report only unchanged files. Then run the consumer's
own gates, at minimum:

```sh
python3 scripts/wiki_audit.py --check
python3 -m pytest tests/
npm --prefix apps/wiki-cockpit test
npm --prefix apps/wiki-cockpit exec -- tsc -p apps/wiki-cockpit/tsconfig.json --noEmit
npm --prefix apps/wiki-cockpit run build
```

Start the local operator and visually read back the affected flows using real
consumer data. Keep screenshots and console/network evidence private and
ignored. Privacy and access-secret failures are always fail-closed.

## 6. Promote

Inspect `kit.lock`, the conceptual diff, generated artifacts and consumer-owned
C3 changes. Merge only through the human PR gate after consumer CI and visual
readback are green. Publish the local or deployed test URL separately; never
embed private routes in public kit evidence.

## Historical package

`docs/references/upgrades/wiki-viva-v8/upgrade-package.yaml` is frozen historical
documentation of the retired certification experiment. It must not be edited,
executed as a release gate or used to force retired tests green.
