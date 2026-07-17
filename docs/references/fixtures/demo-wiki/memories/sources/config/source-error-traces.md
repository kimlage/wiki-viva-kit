---
visibility: private_self
stale_after_days: 30
page_id: source-config-error-traces
page_type: source_config
title: 'Source config: Error traces'
context: clientes
updated_at: '2026-07-03'
moc_parent: memories/sources/source-error-traces.md
source_refs:
- source-error-traces
---

# Source config: Error traces

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
  platform: observability
  locator: ''
  pipelines: []
  streams:
  - id: traces
    label: Error traces
    selected: true
    privacy: private_self
    target_pages: []
```
