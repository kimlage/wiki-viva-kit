---
title: "Wiki Viva v6.2 pilot metrics"
page_id: report-wiki-viva-v6-2-pilot-metrics-2026-06-11
page_type: release_notes
context: system
visibility: private_self
updated_at: 2026-06-11
stale_after_days: 90
sources_policy: pilot_metrics
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
---

# Wiki Viva v6.2 pilot metrics

Pilot date: 2026-06-11.

## Open-Source Synthetic Pilot

Source: [pilot_source.md](../../../tests/fixtures/e2e/pilot_source.md).

Command path: local sandbox under `tmp/v62-pilot`, using the deterministic
pipeline modules directly.

| Metric | Value |
| --- | --- |
| Source id | `source-pilot-source-md-70ff83e7e5cd` |
| Chunks | 1 |
| Required perspectives | `perspective-technical`, `perspective-project` |
| Cache results recorded | 1 |
| Pending LLM calls after record | 0 |
| Perspective coverage errors | 0 |
| PII/secret exposure | none in synthetic source/result |

Validation:

- `audit_perspective_coverage` over the sandbox returned no errors after
  registering the two perspective pages.
- Full kit suite after PR2-PR6 returned `322 passed, 4 skipped`.
- Full kit audit returned `0 error(s)` and 3 existing warnings unrelated to the
  new gates.

## Private Downstream Pilot

Status: pending until the v6.2 implementation is copied into the private repo and
the private overlays are added. Recommended source: a low-risk system/wiki source
with no credentials and no finance ledger.
