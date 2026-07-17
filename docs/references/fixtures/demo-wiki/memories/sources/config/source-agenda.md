---
visibility: private_self
stale_after_days: 30
page_id: source-config-agenda
page_type: source_config
title: 'Source config: Agenda'
context: pessoal
updated_at: '2026-07-03'
moc_parent: memories/sources/source-agenda.md
source_refs:
- source-agenda
---

# Source config: Agenda

## Ingestion rules

Ingest on demand from the fenced recipe below.

## Search rules

Search normalized events before raw exports.

## Business rules

Consolidation happens only through reviewed proposals.

## Privacy boundaries

Structural metadata only — never credentials or message bodies.

```yaml
recipe:
  schema_version: wiki_source_recipe.v1
  platform: calendar
  locator: demo-calendar/alex-rivera-primary
  auth:
    method: none
    ref: ''
  pipelines:
  - kind: content
    cadence_days: 7
  streams:
  - id: weekly-sync
    label: Weekly sync events
    selected: true
    filters:
      calendar: primary
    privacy: private_self
    target_pages:
    - meeting-weekly-sync
  - id: focus-retro
    label: Focus retrospective
    selected: true
    filters:
      calendar: focus-blocks
    privacy: private_self
    target_pages:
    - insight-calendario-calmo
  how_to_export: Export the demo calendar as ICS and drop it in data/raw.
```
