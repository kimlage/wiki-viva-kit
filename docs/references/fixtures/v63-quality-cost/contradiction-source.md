---
title: "Synthetic v6.3 fixture - contradiction source"
page_id: fixture-v63-contradiction-source
page_type: reference_fixture
context: system
visibility: private_self
updated_at: 2026-06-12
stale_after_days: 180
sources_policy: synthetic_fixture
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
---

# Synthetic v6.3 fixture - contradiction source

This source tests whether the integration process records conflict instead of
silently replacing an older page.

## Source body

An older memory says Project Alpha shipped the adapter on 2026-06-10. This
source says the adapter did not ship until 2026-06-12 because the quality report
showed repeated prose across two equivalent pages. The new source should mark
the older claim as superseded or time-bounded, not delete the historical claim.

## Expected v6.3 behavior

| Concern | Expected result |
| --- | --- |
| Quality | Detect the contradiction as a verification target. |
| History | Preserve the older state with a supersession note. |
| Cost | Reuse existing chunks/results where hashes match; report rereads when they do not. |

## Related

- v6.3 proposal: [wiki-viva-v6.3-quality-cost-control-2026-06-12.md](../../proposals/wiki-viva-v6.3-quality-cost-control-2026-06-12.md).
