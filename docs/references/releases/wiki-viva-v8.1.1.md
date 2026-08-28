---
title: "Wiki Viva v8.1.1"
page_id: release-wiki-viva-v8-1-1
page_type: release_note
context: system
visibility: public_candidate
updated_at: 2026-08-28
stale_after_days: 365
sources_policy: release_note
gate: github_pr
sensitive_data_policy: no_personal_data
---

# Wiki Viva v8.1.1

Wiki Viva v8.1.1 is the corrective public baseline for source-operations
adoption. It preserves the complete v8.1 two-dimensional source workspace and
closes the documentation and additive-migration gaps found during real consumer
readback.

Runtime anchor: `wiki_core.__version__ = "8.1.1"`.

## Corrections

- Documents the complete source-management workspace directly in the root
  README, including registry organization, pending updates, lifecycle, whole
  collection inventory, authorization and Codex/Claude execution boundaries.
- Makes assisted migration add the inferred `platform` to a `source_config`
  even when that page already contains a valid recipe. The recipe remains
  byte-for-byte authoritative and is never replaced.
- Restores operational recipe migration from existing source/config facts:
  selected streams, targets, cadence, read-only authorization pointers and
  versioned lifecycle evidence are preserved without inventing credentials.
- Keeps the optional, separately authorized `admin` interface surface valid in
  downstream template registries during kit synchronization.
- Preserves the v8.1 rule that only `recurring` sources can become overdue due
  to elapsed time and that registration is not equivalent to ingestion proof.

## Upgrading

1. Check out `v8.1.1` in a clean kit worktree.
2. Run the read-only B0 plan against the consumer.
3. Apply C1/C2 in a dedicated consumer branch and use explicit C3 commands for
   consumer-owned source migration and generated pages. For existing registered
   sources, use `wiki_migrate_templates.py --apply --operational-recipes` so
   reviewed metadata becomes selected operational streams without fabricating
   provider data.
4. Review inferred platforms, locators, source kinds, schedules, groups and
   authorization pointers. Never commit credentials.
5. Run the complete consumer gates and verify the real source workspace through
   its local operator before merging.

The full commands and rollback boundary remain in the
[v8 downstream upgrade runbook](../guides/wiki-viva-v8-downstream-upgrade.md).
