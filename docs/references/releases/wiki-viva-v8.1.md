---
title: "Wiki Viva v8.1.0"
page_id: release-wiki-viva-v8-1-0
page_type: release_note
context: system
visibility: public_candidate
updated_at: 2026-08-28
stale_after_days: 365
sources_policy: release_note
gate: github_pr
sensitive_data_policy: no_personal_data
---

# Wiki Viva v8.1.0

Wiki Viva v8.1.0 consolidates the v8 living-world runtime and the complete,
self-contained two-dimensional workspace for operating data sources. It is the
public baseline for migrating additional consumer repositories.

Runtime anchor: `wiki_core.__version__ = "8.1.0"`.

## What changed

- Replaced the source modal over the 3D world with a dedicated source workspace.
- Added a resizable and collapsible registry with editable groups, inferred
  categories and representative platform or consumer-owned brand icons.
- Added an initial pending-updates overview and governed batch refresh entry
  point without conflating source operations with other perspectives.
- Distinguished `source_kind` (`item`, `collection`, `account`, `endpoint`,
  `repository`) from lifecycle (`one_shot`, `on_demand`, `event_driven`,
  `recurring`). Only recurring sources become overdue through elapsed time.
- Made a collection refresh inventory the declared folder/account recursively
  and deterministically so new, changed, removed and inaccessible records are
  visible before ingestion. A selected record is inspection scope, not the
  whole update scope.
- Added governed configuration previews, immutable operation receipts,
  deterministic script execution, connector capability checks, authorization
  diagnostics, Codex and Claude adapters, and monitored delegated runs.
- Preserved v8 operator security: all source mutations use the nonce-bound,
  default-deny operator client and fail closed on stale previews or missing
  authorization.
- Made snapshot freshness deterministic from `generated_at`, avoiding results
  that drift with the machine's current date.

## Upgrading

1. Check out the public kit at `v8.1.0` in a clean worktree.
2. Run B0 against a clean consumer branch:

   ```sh
   python3 /path/to/wiki-viva-kit/scripts/wiki_sync_from_kit.py \
     --kit /path/to/wiki-viva-kit \
     --consumer /path/to/consumer \
     --dry-run
   ```

3. Review additions, changes and removals. Do not apply a plan that replaces a
   v8 consumer with a v6 tree.
4. Apply C1/C2 plus explicit consumer-owned C3 migrations:

   ```sh
   python3 /path/to/wiki-viva-kit/scripts/wiki_sync_from_kit.py \
     --kit /path/to/wiki-viva-kit \
     --consumer /path/to/consumer \
     --c3-command "python3 scripts/wiki_migrate_templates.py --apply" \
     --c3-command "python3 scripts/wiki_source_registry.py --write" \
     --c3-command "python3 scripts/wiki_operation_compile.py --write"
   ```

5. Review all inferred source contracts and consumer-owned icons. Configure
   real locators and authorization pointers without committing credentials.
6. Run B0 again; C1 should be idempotent. Run the complete consumer gates and a
   real local visual readback before merging its PR.

The consumer PR is the rollback boundary. `kit.lock` pins the exact public kit
SHA, manifest/tree hashes, managed paths and file modes without private data or
host paths.

## Compatibility

- Existing v8 source pages remain readable while the additive migration fills
  the explicit source-kind and schedule contract.
- One-shot and on-demand sources are never marked stale merely because time
  passed.
- A source already represented by a closed ingestion event is shown as
  ingested even when legacy mutable cursor state is absent.
- Consumer memories, configuration, RAW data, credentials and private source
  definitions remain outside C1 and are never copied into the public kit.
