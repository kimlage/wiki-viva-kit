# Template - source or artifact

```yaml
---
page_id: source-example
page_type: source
title: "Source - example"
aliases:
  - Source example
tags:
  - wiki/source
  - status/active
status: active
context: system
visibility: private_self
updated_at: YYYY-MM-DD
stale_after_days: 45
sources_policy: metadados_sem_dump
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
owner: {{owner_id}}
related_holons: []
roles: []
responsibilities: []
source_refs: []
source_counts:
  original_sources: 1
  derivative_markdown: 0
  derived_artifacts: 0
claims: []
decisions: []
actions: []
evidence_refs: []
moc_parent: memories/sources/index.md
related_pages: []
backlinks_expected: []
attachment_policy: "Keep the original traceable; attachments and derivatives must be Markdown links."
---
```

# Source - example

> Illustrate by default: record the source's attributes as a table, not loose
> prose. See the representation conventions in
> [obsidian-conventions.md](obsidian-conventions.md).

## Attributes

| Attribute | Value |
| --- | --- |
| Type | `memory` / `reference` / `artifact` / `raw` / `no_ingest` |
| Origin | where it comes from |
| Captured at | YYYY-MM-DD |
| Format | pdf / email / sheet / chat / repo / image / audio / note |
| Original location | Markdown link to the traceable original |
| Reliability | `low` / `medium` / `high` |

## Type

`memory` | `reference` | `artifact` | `raw` | `no_ingest`

## Policy

- This repo is personal and private: the source may be read and have personal data
  (PII -- names, values, dates, CPF, CNPJ, counterparties, address) extracted into
  Markdown whenever it improves operational memory, classification, CRM,
  reconciliation, decision, or context. On a private page it does not raise a warning.
- Keep a link to the original.
- Never copy a token, cookie, password, access code, credential, individualized
  secure link, or full dump without judgment -- anywhere.

## Related

- MOC:
- Manifest:
- Derivatives:
- Impacted pages:
