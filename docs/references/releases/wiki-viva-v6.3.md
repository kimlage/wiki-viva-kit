---
title: "Release notes - Wiki Viva v6.3"
page_id: release-wiki-viva-v6-3
page_type: release_notes
context: system
visibility: private_self
updated_at: 2026-06-12
stale_after_days: 90
sources_policy: release_notes
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
---

# Release notes - Wiki Viva v6.3

Status: implemented in the open-source kit first.

Runtime anchor: `wiki_core.__version__ = "6.3.3"`.

## Included

- New quality report schema `wiki_quality_report.v1`.
- New deterministic core module
  [quality.py](../../../wiki_core/quality.py), with no LLM client.
- New CLI [wiki_quality_report.py](../../../scripts/wiki_quality_report.py) for:
  - information density;
  - link density;
  - same-context/same-type repetition;
  - ingestion events without consolidation closure;
  - chunk/token telemetry;
  - cache reuse telemetry.
- Cost is explicit telemetry, not a hard budget gate.
- Synthetic v6.3 fixtures:
  - [multiperspective-source.md](../fixtures/v63-quality-cost/multiperspective-source.md);
  - [contradiction-source.md](../fixtures/v63-quality-cost/contradiction-source.md);
  - [no-new-information-source.md](../fixtures/v63-quality-cost/no-new-information-source.md).
- v6.3 roadmap:
  [wiki-viva-v6.3-quality-cost-control-2026-06-12.md](../proposals/wiki-viva-v6.3-quality-cost-control-2026-06-12.md).
- Synthetic pilot report:
  [wiki-viva-v6.3-synthetic-pilot-2026-06-12.md](../reports/wiki-viva-v6.3-synthetic-pilot-2026-06-12.md).
- Unit tests:
  [test_quality_report.py](../../../tests/test_quality_report.py).
- Patch v6.3.1 adds the deterministic operational pass:
  [wiki_core/operational_pass.py](../../../wiki_core/operational_pass.py) and
  [wiki_operational_pass.py](../../../scripts/wiki_operational_pass.py), compiling
  sources, actions, claims, decisions, problems and next steps by context before a
  consolidation round.
- Patch v6.3.2 extends that pass with a consolidation-output matrix and a
  decision/action blocking table, so a source review exposes which contexts
  still need actions, problems, claims, decisions, dense context notes or an
  explicit non-ingestion outcome.
- Patch v6.3.3 makes the daily cockpit pending-action parser tolerant of
  operational detail in the queue file: rows like ``- `action-id`
  (deadline...)`` and Markdown-linked queue rows now still compile into the
  pending queue instead of being silently skipped.

## Why it matters

v6.2 made memory pages typed, connected and auditable. v6.3 makes the review
smarter: before applying the same method to private data, the kit can now show
whether pages are thin, weakly linked, repetitively copied or expensive to read.
This nudges the agent toward dense pages with real links and toward cache reuse
without blocking useful work just because a source is large.

## Validation

```sh
python3 -m pytest tests/test_quality_report.py
python3 scripts/wiki_quality_report.py
```

The full repo gates remain:

```sh
python3 -m pytest
python3 scripts/wiki_audit.py --check
python3 scripts/wiki_page_graph.py --check --impact
python3 scripts/wiki_pr_summary.py
git diff --check
```
