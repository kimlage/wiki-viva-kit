---
title: "Wiki Viva v6.8.6"
page_id: release-wiki-viva-v6-8-6
page_type: release_note
context: system
visibility: public_candidate
updated_at: 2026-06-26
stale_after_days: 365
sources_policy: release_note
gate: github_pr
sensitive_data_policy: no_personal_data
---

# Wiki Viva v6.8.6

Daily cockpit owner-action filtering release.

## What Changed

- [wiki_operation_compile.py](../../../scripts/wiki_operation_compile.py) now
  excludes explicitly closed or resolved action pages from the generated
  `Owner actions` table.
- The pending queue file remains unchanged and deterministic; this release only
  prevents completed historical actions from reappearing as current owner work.
- Closed states cover English and Portuguese status/state values, including
  dated forms such as `concluida_em_YYYY-MM-DD` and `resolved_at_YYYY-MM-DD`.
- [test_operation_compile.py](../../../tests/test_operation_compile.py) covers
  body `Estado:` values and frontmatter `status` values so downstream cockpits
  do not regress into completed-action noise.

## Validation

```sh
python3 -m pytest tests/test_operation_compile.py
```
