---
title: "Wiki Viva v6.3 synthetic pilot metrics"
page_id: report-wiki-viva-v6-3-synthetic-pilot-2026-06-12
page_type: evaluation_report
context: system
visibility: private_self
updated_at: 2026-06-12
stale_after_days: 90
sources_policy: synthetic_pilot
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
---

# Wiki Viva v6.3 synthetic pilot metrics

Status: open-source synthetic pilot completed before private-data application.

## Pilot inputs

| Fixture | Purpose |
| --- | --- |
| [multiperspective-source.md](../fixtures/v63-quality-cost/multiperspective-source.md) | Test extract-once and perspective-specific integration. |
| [contradiction-source.md](../fixtures/v63-quality-cost/contradiction-source.md) | Test conflict preservation instead of silent replacement. |
| [no-new-information-source.md](../fixtures/v63-quality-cost/no-new-information-source.md) | Test no-delta closure without repeated prose. |

## Deterministic report

Command:

```sh
python3 scripts/wiki_quality_report.py --format json
```

Observed summary in the open-source kit after v6.3 implementation:

| Metric | Value |
| --- | ---: |
| Pages total | 34 |
| Low information density pages | 0 |
| Thin link pages | 0 |
| Repeated blocks | 0 |
| Bad repetition blocks | 0 |
| Ingestion events | 1 |
| Events without `consolidated_into` | 1 |
| Chunk sources | 0 |
| Estimated context tokens | 0 |
| Cached calls | 0 |
| Pending calls | 0 |

The one event without `consolidated_into` is the historical synthetic example
event already reported by the audit as a warning. It is not introduced by v6.3.

## Interpretation

- Quality measurement works without private data and without an LLM client.
- Cost measurement is visible even when there are no derived chunks yet; the
  report stays explicit that cost is telemetry and not a hard budget.
- Repetition control is deterministic: same context + same page type repetition
  is flagged; repetition across a different perspective/context is tracked but
  not automatically considered bad.
- The kit is ready for a private repo backport, but not yet for automatic
  private-source rewriting.

## Validation

```sh
python3 -m pytest tests/test_quality_report.py
python3 scripts/wiki_quality_report.py
```

Expected result: tests pass and the report emits Markdown/JSON.

## Related

- Roadmap: [wiki-viva-v6.3-quality-cost-control-2026-06-12.md](../proposals/wiki-viva-v6.3-quality-cost-control-2026-06-12.md).
- Release notes: [wiki-viva-v6.3.md](../releases/wiki-viva-v6.3.md).
- CLI: [wiki_quality_report.py](../../../scripts/wiki_quality_report.py).
