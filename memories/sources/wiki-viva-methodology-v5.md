---
page_id: sources-wiki-viva-methodology
page_type: source
title: "Living wiki methodology (source)"
aliases:
  - Living wiki methodology
tags:
  - wiki/sources
  - wiki/methodology
  - status/active
status: active
context: system
visibility: private_self
updated_at: 2026-08-26
stale_after_days: 180
parent_projection:
  quadrant: q2
  sub_lens: evidencias
  reason: "Methodology source is an observable evidence artifact of the kit."
source_type: reference
ingestion_state: ingested
last_ingested_at: 2026-08-26
refresh_policy: event_driven
refresh_cadence_days: 180
refresh_trigger: "review only when the methodology proposal or implementation contract changes"
config_ref: memories/sources/config/wiki-viva-methodology-v5.md
sources_policy: fonte_metodologica
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
purpose: "Source page that describes the living wiki methodology implemented by the kit."
moc_parent: memories/index.md
related_pages:
  - memories/system/methodology-coverage-v5.md
  - memories/sources/config/wiki-viva-methodology-v5.md
owner: root-wiki-viva-kit
related_holons:
roles:
responsibilities:
source_refs: []
claims:
decisions:
actions:
evidence_refs:
  - memories/system/methodology-coverage-v5.md
platform: repo
source_locator: memories/sources/wiki-viva-methodology-v5.md
sync:
  last_run_at: '2026-08-26'
  last_status: ok
  last_event_ref: memories/system/ingestion/events/2026-08-26-wiki-viva-methodology-v5-md.md
---

# Living wiki methodology (source)

Updated on: 2026-08-26.

This page is the methodological source of the kit: it describes, at a high level, the model of
the living operational wiki that the code implements. Implementation coverage is
tracked in [methodology-coverage-v5.md](../system/methodology-coverage-v5.md).

## Principles

| Principle | What it means |
| --- | --- |
| Markdown/Git as a portable foundation | The wiki is versioned text; the PR is the gate. |
| Ingestion as compilation | A source becomes a manifest, text/chunks, an index, a context package, a normalized event, and consolidation. |
| Source entity + recipe | A source page records identity and sync evidence; its `source_config` carries the executable, secret-free recipe, streams, cadences and target pages. |
| Code first, LLM for deep context | The Python is deterministic; the deep reading belongs to the agent that runs the repo, recorded in the cache (gate `required_context_pass`). |
| Privacy per page | PII is welcome on private pages; secrets are always blocked; PII only becomes an error at the public boundary. |
| Four quadrants | Wilber/AQAL lens crossing interior/exterior with individual/collective: Q1/I identity-intent, Q2/It output-evidence, Q3/We shared meaning/roles-as-lived, Q4/Its systems-processes-governance, with explicit absence. |
| Operation page (cockpit) | The first resumption screen. |
| Karma gamification | A by-product, without toxic ranking. |
| Perceptive layer | Journal and map, before becoming canonical memory. |
| Rich representation by default | Pages illustrate structure with Mermaid diagrams and tables; prose stays for nuance. |

## Ingestion as compilation

The "ingestion as compilation" principle is a pipeline: each stage is deterministic
except the deep reading, which the agent performs and records back into the cache.

```mermaid
flowchart LR
    S["Source"] --> M["Manifest"]
    M --> C["Stable chunks"]
    C --> I["FTS index"]
    I --> P["LLM context package"]
    P --> E["Normalized event"]
    E --> X["Consolidation proposal"]
    X --> G["Human gate (PR)"]
```

## Source configuration and refresh

The canonical source inventory is made of linked records, not an implicit
connector: a `source` page identifies the evidence, a `source_config` page
defines its recipe, an `input_channel` places it in the root entity, and an
`ingestion_event` proves each completed read. The recipe can describe streams,
filters, cadences, an authorization pointer and an on-demand or recurring
schedule, but it never stores a credential and does not make an external fetch
automatic by itself.

As of 2026-08-26 this public kit has exactly one canonical source — this
methodology contract — with one repository-local stream. It is intentionally
on-demand: changes to the methodology, templates, skills, gates or source model
trigger a new read. Downstream repositories declare their own real sources and
connectors; none are implied by this synthetic public foundation.

## Rich representation by default

Pages SHOULD illustrate what they describe with **Mermaid diagrams** and **Markdown
tables** by default, keeping prose for nuance. Architecture, flow, relationship, and
process pages MUST carry at least one diagram. The full guideline — including the
"which diagram for what" mapping and the diagram authoring rules — lives in the page
conventions: [obsidian-conventions.md](../../docs/references/templates/wiki/obsidian-conventions.md).

## Ingestion log

| Date | Event | State |
| --- | --- | --- |
| 2026-08-26 | [Methodology contract refresh](../system/ingestion/events/2026-08-26-wiki-viva-methodology-v5-md.md) | Integrated: recipe migration, implementation readback and meta-wiki alignment. |

## Related

- Conventions (rich representation, frontmatter, links): [obsidian-conventions.md](../../docs/references/templates/wiki/obsidian-conventions.md).
- Coverage: [methodology-coverage-v5.md](../system/methodology-coverage-v5.md).
- Process: [ingestion-process.md](../system/ingestion-process.md).
