---
title: "Wiki Viva v6.10.1"
page_id: release-wiki-viva-v6-10-1
page_type: release_note
context: system
visibility: public_candidate
updated_at: 2026-08-28
stale_after_days: 365
sources_policy: release_note
gate: github_pr
sensitive_data_policy: no_personal_data
---

# Wiki Viva v6.10.1

Portable downstream synchronization correction for the source operations
release. Consumers should use `v6.10.1` instead of `v6.10.0` when adopting the
new source-management workspace.

Runtime anchor: `wiki_core.__version__ = "6.10.1"`.

## What changed

- Added [wiki_sync_from_kit.py](../../../scripts/wiki_sync_from_kit.py), the
  public B0/C1/C2/C3 synchronization command referenced by the v6.10 upgrade
  procedure.
- Added the stable public
  [sync manifest](../upgrades/sync-manifest.yaml). Only Git-tracked regular
  files selected by the allowlist can be copied; private data, memories,
  configuration and caches are blocked.
- Added synthetic regression coverage for read-only dry runs, dirty-consumer
  refusal, executable modes, allowlist/blocklist precedence, consumer-owned
  files and idempotent `kit.lock` generation.
- `kit.lock` records the exact kit commit, manifest hash, portable tree hash,
  file modes and hashes. It contains no host path or private evidence.

## Upgrading

1. Check out the public kit at `v6.10.1` and create a clean proposal branch in
   the consumer.
2. Preview without writing:

   ```sh
   python3 scripts/wiki_sync_from_kit.py \
     --kit . --consumer /path/to/consumer --dry-run
   ```

3. Review all C1 additions, changes and removals. The command removes only
   paths that were managed by the previous `kit.lock` and are no longer part of
   the public manifest.
4. Apply from the same kit checkout. Add an explicit `--c3-command` only when
   the consumer owns a required domain/configuration migration.
5. Run the same dry run again. A stable consumer must report no C1 delta.
6. Review and commit the consumer diff, regenerate consumer-owned operational
   pages and run its complete local and visual gates before promotion.

The command refuses a dirty consumer by default. `--allow-dirty` is an explicit
override for a reviewed workflow, not the normal migration path.

## Validation

The complete v6.10.0 validation matrix remains required. In addition:

```sh
python3 -m pytest tests/test_wiki_sync_from_kit.py
python3 scripts/wiki_sync_from_kit.py --help
```
