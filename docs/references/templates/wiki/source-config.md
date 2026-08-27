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

## Recipe (machine-readable)

The cockpit's source read model parses THIS fenced block (`wiki_core/source_recipe.py`
→ `wiki_core/web/sources.py`). It is the executable ingestion manual, as data: the
platform + locator, the typed pipelines and their cadences, the selected streams with
their filters/targets, an **auth pointer** (never a secret), and the sync schedule.
"Sincronizar com Codex" composes an ingest brief from it. Fill the empty fields; the
read model reports what is still invalid until you do.

```yaml
recipe:
  schema_version: wiki_source_recipe.v1
  platform: ""            # slack | gchat | chatgpt | whatsapp | gmail | drive | google_photos | web | repo | file | calendar | manual
  locator: ""             # the stable address on that platform (must match the source page)
  pipelines:
    - { kind: metadata, cadence_days: 30 }
    - { kind: content, cadence_days: 7 }
  streams:
    - id: ""              # the concrete channel/label/tab id inside the source
      label: ""
      selected: true
      privacy: private_sensitive_allowed
      cadence_days: 0     # 0 = inherit the content pipeline's cadence; >0 overrides it
      filters: {}         # e.g. { after: 2026-01-01, label: finance }
      target_pages: []    # the memory pages this stream keeps fresh
  auth:
    method: none          # none | env | mcp | keychain | oauth_ref
    ref: ""               # env VAR name / mcp server id / keychain item — a POINTER, never a secret
    scopes: []
    note: ""
  schedule:
    mode: on_demand       # on_demand | recurring
    cadence_days: 0       # >0 when mode is recurring (days between scheduled syncs)
  how_to_export: |
    Describe exactly how a human exports the already-authorized RAW for this source
    (the sandbox has NO network). Point at the export location the agent should read.
  mcp_hint: ""            # optional connector/tool hint, e.g. google_drive.list_folder
  ingest:
    argv: ["python3", "scripts/wiki_ingest.py", "--source", "{path}"]
```

The interface only runs `ingest.argv` directly when it is an allowlisted
`python`/`python3` command whose program is repository-relative under
[scripts](../../../../scripts/), and `{path}` resolves to a hashed file under
[data/raw](../../../../data/raw/). If
`ingest.argv` is empty and `mcp_hint` is present, the update is delegated to a
usable agent that actually exposes that connector. Otherwise the manual export
instructions are shown as the honest next step.

## Ingestion rules

- How to fetch/extract (format, frequency, scope); what to NEVER copy (access
  secrets, a full dump without judgment).
- The machine truth lives in the `recipe:` block above; this section is the human
  narrative that explains it.

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
