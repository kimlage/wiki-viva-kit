---
title: "Retired two-lane downstream migration strategy"
page_id: guide-downstream-migration-two-lane-strategy
page_type: reference_guide
context: system
visibility: public_candidate
updated_at: 2026-07-15
stale_after_days: 3650
sources_policy: historical_record
gate: github_pr
sensitive_data_policy: no_personal_data
---

# Retired two-lane downstream migration strategy

The Lane A/Lane B strategy, immutable subjects, capsules, attestations,
receipts, resumable state machine and exact release matrices are retired. They
are preserved only in Git history and the frozen v8 `upgrade-package.yaml`.
They are not current release gates and must not be revived by modifying the
historical YAML or by unskipping retired lane tests.

The product decision is intentionally smaller:

```text
kit tag + release notes + upgrading
  -> B0 dry-run
  -> one consumer PR containing C1 + C2 + explicit C3
  -> normal kit/consumer gates
  -> human review and merge
```

See the active [downstream upgrade runbook](wiki-viva-v8-downstream-upgrade.md).
The PR supplies review and rollback. Privacy and access-secret gates remain
fail-closed; no simplification weakens those boundaries.
