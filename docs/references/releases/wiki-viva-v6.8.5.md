---
title: "Wiki Viva v6.8.5"
page_id: release-wiki-viva-v6-8-5
page_type: release_note
context: system
visibility: public_candidate
updated_at: 2026-06-26
stale_after_days: 365
sources_policy: release_note
gate: github_pr
sensitive_data_policy: no_personal_data
---

# Wiki Viva v6.8.5

Operational-pass short-action balancing release.

## What Changed

- [operational_pass.py](../../../wiki_core/operational_pass.py) now selects the
  short `Primary actions` block with the same context-balanced round-robin used
  by `Review now`.
- Pending and attention-action eligibility remains unchanged; only the top
  short-memory excerpt is balanced before truncation.
- [test_operational_pass.py](../../../tests/test_operational_pass.py) covers the
  regression where one context with many actions could hide active actions from
  other contexts.

## Validation

```sh
python3 -m pytest tests/test_operational_pass.py
```
