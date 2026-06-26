---
title: "Wiki Viva v6.8.8"
page_id: release-wiki-viva-v6-8-8
page_type: release_note
context: system
visibility: public_candidate
updated_at: 2026-06-26
stale_after_days: 365
sources_policy: release_note
gate: github_pr
sensitive_data_policy: no_personal_data
---

# Wiki Viva v6.8.8

Operational-pass insight claim noise release.

## What Changed

- [operational_pass.py](../../../wiki_core/operational_pass.py) now treats claim
  status `insight` and accepted-insight aliases as consolidated, non-actionable
  claim states.
- Body status parsing now accepts `Status:` in addition to `State:` and
  `Estado:`, matching claim pages that keep epistemic status in prose instead
  of frontmatter.
- The operational pass still surfaces open hypotheses, proposals, uncertainties
  and claims without closed/accepted epistemic status when they contain attention
  terms such as risk, gap, pending or blocker.
- Factual/confirmed claims still surface when they explicitly preserve an open
  qualifier such as open risk, open gap, `risco aberto` or `lacuna que segue
  aberta`, or when `risk of`/`risco de` appears as an explicit bullet item.
- [test_operational_pass.py](../../../tests/test_operational_pass.py) covers the
  accepted-insight case, accepted insight text that says `risk of`, factual
  claims with open gaps, and factual claims with open-risk bullets.

## Validation

```sh
python3 -m pytest tests/test_operational_pass.py
```
