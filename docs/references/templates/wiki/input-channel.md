# Template - input channel

```yaml
---
page_id: {{page_id}}
page_type: input_channel
title: "{{title}}"
aliases:
  - "{{title}}"
tags:
  - wiki/input-channel
  - status/active
status: active
context: {{context}}
visibility: private_self
updated_at: {{updated_at}}
stale_after_days: {{stale_after_days}}
sources_policy: input_stage_contract
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
owner: {{owner_id}}
moc_parent: memories/index.md
channel_type: document
input_status: declared
quadrants:
  - q4
perspectives_required: []
perspectives_optional: []
source_refs: []
source_config_refs: []
process_refs: []
target_pages: []
claims: []
decisions: []
actions: []
evidence_refs: []
refresh_policy: on_demand
refresh_cadence_days: 30
privacy_boundary: private_self
---
```

# {{title}}

## Channel

| Field | Value |
| --- | --- |
| Type | `repository` / `work_tracker` / `communication` / `meeting_calendar` / `document` / `email` / `dashboard` |
| Status | `declared` / `configured` / `staged` / `blocked` / `ready_for_ingest` / `ingesting` / `integrated` / `no_ingest` |
| Refresh policy |  |
| Privacy boundary |  |

## Sources and Configs

| Source | Config | Status |
| --- | --- | --- |
|  |  |  |

## Quadrants and Perspectives

| Quadrant | Required perspectives | Optional perspectives |
| --- | --- | --- |
|  |  |  |

## Process Links

- Process:
- Target pages:

## Fetching Rules

- Connector or agent action required:
- What never to copy:
- Staging location or external reference:

## Related

- Root entity:
- Input stage:
