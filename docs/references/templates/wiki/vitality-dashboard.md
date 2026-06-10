# Template - vitality dashboard

```yaml
---
page_id: vitality-dashboard
page_type: dashboard
title: "Wiki vitality"
aliases:
  - Vitality dashboard
  - Wiki health
tags:
  - wiki/vitality
  - wiki/dashboard
  - status/template
status: template
context: system
visibility: private_self
updated_at: YYYY-MM-DD
stale_after_days: 7
sources_policy: auditoria_logs_e_cobertura
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
purpose: track the operational health of the wiki without toxic ranking
owner: {{owner_id}}
moc_parent: memories/operations.md
related_pages:
  - memories/system/wiki-coverage.md
source_counts:
  live_sources: 0
  references: 0
  derived_artifacts: 1
---
```

# Wiki vitality

## Indicators

| Indicator | Source | Weight | State | Action |
| --- | --- | ---: | --- | --- |
| stale pages | audit | 2 |  |  |
| broken links | audit | 3 |  |  |
| claims without source | audit | 3 |  |  |
| actions without outcome | memory | 2 |  |  |
| sources without manifest | derived | 2 |  |  |
| chunks without contextual reading | cache | 2 |  |  |

## Hygiene missions

- Update stale pages.
- Resolve broken links.
- Associate claims with sources.
- Record the outcome of old actions.
- Reprocess sources with a new prompt/schema.

## Score events

Record events in an operational JSONL under
[data/derived](../../../../data/derived/) as `wiki/score-events.jsonl`,
without exposing access secrets or gamifying person against person.

## Related

- MOC: [operations.md](../../../../memories/operations.md)
- Obsidian conventions: [obsidian-conventions.md](obsidian-conventions.md)
