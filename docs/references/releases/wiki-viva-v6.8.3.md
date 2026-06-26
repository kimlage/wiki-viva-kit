---
title: "Wiki Viva v6.8.3"
page_id: release-wiki-viva-v6-8-3
page_type: release_note
context: system
visibility: public_candidate
updated_at: 2026-06-26
stale_after_days: 365
sources_policy: release_note
gate: github_pr
sensitive_data_policy: no_personal_data
---

# Wiki Viva v6.8.3

Small operational-pass cleanup release.

## What Changed

- [operational_pass.py](../../../wiki_core/operational_pass.py) no longer treats
  claims with explicit factual or closed epistemic statuses as operational
  attention items merely because their title or historical body text contains
  words such as "pending", "risk" or "unknown".
- Statusless claims and claims with open/non-factual status still surface when
  their text contains attention markers.
- [test_operational_pass.py](../../../tests/test_operational_pass.py) now covers
  the regression with a synthetic factual claim whose title/body still mention a
  formerly pending state.

## Validation

```sh
python3 -m pytest tests/test_operational_pass.py
```
