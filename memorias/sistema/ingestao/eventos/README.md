---
page_id: sistema-ingestao-eventos-readme
page_type: source_catalog
title: "Normalized ingestion events"
aliases:
  - Ingestion events
tags:
  - wiki/ingestao
  - status/active
status: active
context: sistema
visibility: private_self
updated_at: 2026-06-09
stale_after_days: 90
sources_policy: eventos_normalizados
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
purpose: "Normalized ingestion events: each one declares the four quadrants or explicit absence."
moc_parent: memorias/sistema/ingestao/README.md
related_pages:
  - memorias/sistema/ingestao/README.md
  - docs/referencias/templates/wiki/ingestao-evento.md
---

# Normalized ingestion events

Updated at: 2026-06-09.

Each relevant ingested source generates a normalized event here, following the template
[ingestao-evento.md](../../../../docs/referencias/templates/wiki/ingestao-evento.md).
Every event declares the four quadrants (interior/exterior, individual/collective)
or makes the absence explicit - the absence is a finding, not an empty field.

## Related

- Proposals: [README.md](../README.md).
- Template: [ingestao-evento.md](../../../../docs/referencias/templates/wiki/ingestao-evento.md).
