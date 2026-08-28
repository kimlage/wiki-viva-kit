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
# Optional local brand asset. Keep the file below apps/wiki-cockpit/public/source-icons/;
# remote URLs and traversal paths are rejected. Known platforms such as Google
# Drive already have a bundled identity, so declare this only for custom brands.
# visual_identity:
#   key: organization-name
#   label: "Organization name"
#   asset_path: /source-icons/organization-name.webp
#   background: light   # transparent | light | dark
# Versioned SYNC telemetry -- a successful receipt + closed event is canonical
# evidence and survives clean clones. Per-stream derived cursors are preferred;
# for exactly one selected stream, this receipt is the safe clean-clone fallback.
sync:
  last_run_at: ""       # ISO datetime of the last sync attempt (empty until the first run)
  last_status: never    # never | ok | partial | failed | needs_auth | parser_error | secret_blocked | running | queued
  last_event_ref: ""    # link to the ingestion_event that recorded the last run
# Canonical v8 projection used by the cockpit. The audit rejects unknown values
# here before snapshot publication; flattened source_<field> inputs remain
# readable only for compatibility with early v8 pages.
source_lifecycle:
  state: configured
  freshness_state: never_synced
  last_attempt_state: never  # never | ok | failed | needs_auth | parser_error | secret_blocked
  pipeline_stage: configured # configured | manifested | extracted | indexed | deep_read | proposal_ready | integrating | gate_pending | complete
  pipeline_stage_timestamps: {}
  adoption_state: pending    # pending | accepted | reviewed_no_change
  blocked_reason: ""         # required and secret-safe when state=blocked
  emitted_page_ids: []       # required non-empty closure when adoption_state=accepted
  emitted_action_ids: []
  proposal_ids: []
  accepted_ref: ""           # required for accepted/reviewed_no_change
  reviewed_no_change_receipt: "" # required for reviewed_no_change
  secret_safe_log_refs: []
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

Freshness now comes from the **recipe** in `config_ref`, not from this page: each
stream declares its own `cadence_days`, and the cockpit compares it to the stream's
cursor. The `sync:` block above only records the last *run* (status + timestamp);
"Sincronizar com Codex" advances the cursors and writes the receipt it points to.
(`refresh_policy`/`refresh_cadence_days` remain for the legacy registry only.)

Use the nested `source_lifecycle` block for authored v8 telemetry. Legacy
`source_last_attempt_state` values `partial`, `running` and `queued` are still
accepted and normalized to `failed`, `ok` and `ok`, respectively, with an audit
warning. Unknown or translated values are never guessed: the audit names the
field and allowed alternatives, and the final snapshot contract remains
fail-closed. If a flattened compatibility field and its nested equivalent are
both present, their normalized values must agree.

Acceptance is evidence-bound: `accepted` requires `accepted_ref` plus at least
one `emitted_page_ids` closure; `reviewed_no_change` requires `accepted_ref` plus
`reviewed_no_change_receipt`; and `state: ingested` requires one of those two
adoption states. A blocked source requires a secret-safe `blocked_reason`, a
failure-shaped last attempt and pending adoption.

Lifecycle, pipeline and adoption edges follow the explicit transition tables
in `wiki_core/source_lifecycle.py`. The pipeline advances one proven stage at a
time, permits only the declared integration/gate retry edges and starts a new
cycle through `complete -> configured`. This release intentionally has no
Markdown writer for those transitions yet. Changes to an existing source's
lifecycle, pipeline, adoption or last-attempt state therefore fail closed at
the Git-base audit with a receipt-required diagnostic. New sources have no
prior transition and remain valid when their complete initial declaration
passes this contract. The next wave must add an atomic writer with append-only,
content-bound attempt/history receipts before those existing-page edits can be
accepted.

| Date | Event | State |
| --- | --- | --- |
|  |  |  |

## Related

- MOC:
- Manifest:
- Derivatives:
- Impacted pages:
