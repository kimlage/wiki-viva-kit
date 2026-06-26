---
title: "Wiki Viva v6.8.7"
page_id: release-wiki-viva-v6-8-7
page_type: release_note
context: system
visibility: public_candidate
updated_at: 2026-06-26
stale_after_days: 365
sources_policy: release_note
gate: github_pr
sensitive_data_policy: no_personal_data
---

# Wiki Viva v6.8.7

Input-stage ready queue precision release.

## What Changed

- [input_stage.py](../../../wiki_core/input_stage.py) no longer places
  `configured` sources in `ready_inputs`; configured sources remain visible in
  the full catalog but are not treated as immediate work.
- The input-stage status mapper now preserves `staged`, `ready_for_ingest` and
  `blocked` source states instead of collapsing them into `configured`.
- [wiki_input_stage.py](../../../scripts/wiki_input_stage.py) `--ready` now
  reports only `staged` or `ready_for_ingest` rows.
- The command reference, ingestion flow and default process guide now document
  the boundary between configured catalog entries and actionable ready inputs.
- [test_input_stage.py](../../../tests/test_input_stage.py) covers the
  configured-versus-staged boundary so downstream repos do not get noisy
  "ready" queues from dormant or merely configured sources.

## Validation

```sh
python3 -m pytest tests/test_input_stage.py
```
