---
title: "Wiki Viva v6.8.4"
page_id: release-wiki-viva-v6-8-4
page_type: release_note
context: system
visibility: public_candidate
updated_at: 2026-06-26
stale_after_days: 365
sources_policy: release_note
gate: github_pr
sensitive_data_policy: no_personal_data
---

# Wiki Viva v6.8.4

Operational-pass short-memory balancing release.

## What Changed

- [operational_pass.py](../../../wiki_core/operational_pass.py) now selects
  `Review now` rows with a context-balanced round-robin instead of taking only
  the first rows from the full attention table.
- The complete `Problems and uncertainty` table remains unchanged; the change
  affects only the short top-of-page memory block.
- [test_operational_pass.py](../../../tests/test_operational_pass.py) covers the
  regression where one noisy context could hide active signals from finance,
  professional or other contexts.

## Validation

```sh
python3 -m pytest tests/test_operational_pass.py
```
