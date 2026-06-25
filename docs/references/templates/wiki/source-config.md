# Template - source config

Configuration page for **ONE source** (lives in `sources/config/` in memory). It
holds that source's ingestion, search and business rules, kept off the content
page (single purpose). The source page points here via `config_ref:`; the
[source registry](../../../../memories/system/source-registry.md) shows a Config
column linking this page. The rules are READ by the agent during ingestion (the
intelligence lives in the agent, not in the toolkit).

```yaml
---
page_id: source-config-example
page_type: source_config
title: "Source config - example"
aliases:
  - Source config example
tags:
  - wiki/source
  - status/active
status: active
context: example
visibility: private_self
updated_at: YYYY-MM-DD
stale_after_days: 90
sources_policy: operational_wiki_contract
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
owner: person-example
moc_parent: memories/sources/index.md
source_refs: []          # source-... this config governs (bidirectional)
related_holons: []
roles: []
responsibilities: []
claims: []
decisions: []
actions: []
evidence_refs: []
perspectives_required:
  - perspective-technical
perspectives_optional: []
perspectives_skip_with_reason: []
input_channel_ref: ""
process_refs: []
target_pages: []
quadrants: []
---
```

# Source config - example

Governs the source: link to the source page.

## Ingestion rules

- How to fetch/extract (format, frequency, scope); what to NEVER copy (access
  secrets, a full dump without judgment).

## Perspectives

- `perspectives_required` declares the reusable extraction lenses that must be
  present in deep-read requests for this source. Every listed id must resolve to
  a `perspective` page.
- `perspectives_optional` lists useful lenses that can be skipped when the
  source does not contain relevant material.
- `perspectives_skip_with_reason` can skip inherited root/channel perspectives,
  but every skipped perspective must carry an explicit reason in the body or
  linked decision.

## Inheritance

| Layer | What it contributes |
| --- | --- |
| Root entity | Default perspective bundle and target strategy. |
| Input channel | Channel type, process map, quadrants, refresh and privacy. |
| Source config | Source-specific required/optional perspectives and overrides. |

## Input channel and process map

- Input channel:
- Processes:
- Target pages:
- Quadrants:

## Search rules

- How to find what is relevant in this source (filters, windows, tabs, labels).

## Business rules

- Domain logic (e.g. append-only ledger, mandatory readback, cascade
  reconciliation, key-based deduplication).

## Privacy boundaries

- PII is welcome on a private page; redact only before exporting. An access
  secret is never versioned.
