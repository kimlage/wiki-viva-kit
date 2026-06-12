---
title: "Synthetic v6.3 fixture - multiperspective source"
page_id: fixture-v63-multiperspective-source
page_type: reference_fixture
context: system
visibility: private_self
updated_at: 2026-06-12
stale_after_days: 180
sources_policy: synthetic_fixture
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
---

# Synthetic v6.3 fixture - multiperspective source

This synthetic source is designed to exercise the v6.3 quality workflow without
using personal data.

## Source body

Project Alpha changed its rollout plan on 2026-06-12. The technical concern is
that the ingestion adapter now emits a normalized claim packet before any page
specific synthesis. The project concern is that the owner wants a reviewable
pull request showing which pages changed and which pages were consciously left
unchanged.

The same fact should not be copied verbatim into every page. The project page
should keep the rollout decision and status, while the technical page should
keep adapter behavior, cache reuse and validation commands. A parent index can
carry a one-line rollup that links to both pages.

## Expected v6.3 behavior

| Lens | Expected integration |
| --- | --- |
| Claim packet | Extract the rollout date, adapter change and review expectation once. |
| Project perspective | Update status and next action without copying adapter internals. |
| Technical perspective | Update adapter and validation details without repeating project prose. |
| Cost telemetry | Count one source/chunk read and then smaller perspective applications. |

## Related

- v6.3 proposal: [wiki-viva-v6.3-quality-cost-control-2026-06-12.md](../../proposals/wiki-viva-v6.3-quality-cost-control-2026-06-12.md).
