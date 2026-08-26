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
# --- Source identity read by the cockpit's source read model (wiki_core/web/sources.py) ---
platform: ""            # slack | gmail | whatsapp | web | repo | manual … (feeds the recipe too)
source_locator: ""      # the stable address on that platform (workspace/channel, label, url, repo)
config_ref: ""          # the source_config page that carries this source's `recipe:` block
# Versioned SYNC telemetry -- a successful receipt + closed event is canonical
# evidence and survives clean clones. Per-stream derived cursors are preferred;
# for exactly one selected stream, this receipt is the safe clean-clone fallback.
sync:
  last_run_at: ""       # ISO datetime of the last sync attempt (empty until the first run)
  last_status: never    # never | ok | partial | failed | running | queued
  last_event_ref: ""    # link to the ingestion_event that recorded the last run
stewards: []            # [{id: person-..., role: owner|curator}] -- who owns/curates this source
# Legacy ingestion hints, still read by wiki_source_registry.py / the audit gate.
# source_type feeds the registry's Type column; the recipe's schedule supersedes refresh_policy.
source_type: reference
ingestion_state: unread   # unread | partial | ingested | stale
last_ingested_at: ""
refresh_policy: event_driven   # recurring | event_driven | on_demand | archival
refresh_cadence_days: 45       # used with last_ingested_at/updated_at to suggest next refresh
# next_refresh_at: YYYY-MM-DD  # optional explicit override when a known event drives the next read
# refresh_trigger: "what should cause the next read"
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

## Ingestion log

This page is the hierarchical node holding this source's ingestion log: each
ingestion becomes a row linking the normalized event. The source registry
([system/source-registry.md](../../../../memories/system/source-registry.md))
indexes these pages with state and date.

Freshness now comes from the **recipe** in `config_ref`: each stream declares
its own `cadence_days`, and the cockpit prefers its derived cursor. Derived
state is intentionally absent from a clean clone; when a source has exactly one
selected stream, the versioned successful `sync:` receipt is the safe fallback.
For multiple selected streams, individual cursors remain mandatory because one
source-level date cannot prove which subset was processed.
`refresh_policy`/`refresh_cadence_days` remain for the legacy registry.

| Date | Event | State |
| --- | --- | --- |
|  |  |  |

## Related

- MOC:
- Manifest:
- Derivatives:
- Impacted pages:
