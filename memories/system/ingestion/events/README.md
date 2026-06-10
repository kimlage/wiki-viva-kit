---
page_id: system-ingestion-events-readme
page_type: source_catalog
title: "Normalized ingestion events"
aliases:
  - Ingestion events
tags:
  - wiki/ingestion
  - status/active
status: active
context: system
visibility: private_self
updated_at: 2026-06-09
stale_after_days: 90
sources_policy: eventos_normalizados
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
purpose: "Normalized ingestion events: each one declares the four quadrants or explicit absence."
moc_parent: memories/system/ingestion/README.md
related_pages:
  - memories/system/ingestion/README.md
  - docs/references/templates/wiki/ingestion-event.md
---

# Normalized ingestion events

Updated at: 2026-06-09.

Each relevant ingested source generates a normalized event here, following the template
[ingestion-event.md](../../../../docs/references/templates/wiki/ingestion-event.md).
Every event declares the four quadrants (interior/exterior, individual/collective)
or makes the absence explicit - the absence is a finding, not an empty field.

## Related

- Proposals: [README.md](../README.md).
- Template: [ingestion-event.md](../../../../docs/references/templates/wiki/ingestion-event.md).
