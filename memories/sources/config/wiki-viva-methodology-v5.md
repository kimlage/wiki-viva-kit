---
page_id: source-config-wiki-viva-methodology
page_type: source_config
title: "Source config - Living wiki methodology"
aliases:
  - Living wiki methodology config
tags:
  - wiki/source
  - status/active
status: active
context: system
visibility: private_self
updated_at: 2026-06-25
stale_after_days: 90
sources_policy: operational_wiki_contract
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
owner: root-wiki-viva-kit
moc_parent: memories/system/wiki-viva-kit.md
source_refs:
  - sources-wiki-viva-methodology
input_channel_ref: input-channel-methodology-reference
process_refs:
  - process-wiki-methodology-maintenance
target_pages:
  - memories/system/wiki-viva-kit.md
  - memories/system/wiki/index.md
  - memories/system/wiki/architecture.md
  - memories/system/wiki/ingestion-flow.md
quadrants:
  - q1
  - q2
  - q3
  - q4
perspectives_required:
  - perspective-identity-intent
  - perspective-artifacts-evidence
  - perspective-roles-relationships
  - perspective-systems-processes
perspectives_optional:
  - perspective-privacy-publication
perspectives_skip_with_reason: []
related_holons: []
roles: []
responsibilities: []
claims: []
decisions: []
actions: []
evidence_refs:
  - memories/sources/wiki-viva-methodology-v5.md
---

# Source config - Living wiki methodology

Governs the source: [Living wiki methodology](../wiki-viva-methodology-v5.md).

## Ingestion rules

- Fetch/extract from the versioned repository only.
- Re-read when methodology proposals, page-type contracts, templates, skills or
  gates change.
- Never copy private downstream examples into public docs.

## Perspectives

- Required: identity/intent, artifacts/evidence, roles/relationships and
  systems/processes.
- Optional: privacy/publication when a change affects public docs, releases or
  examples.

## Inheritance

| Layer | What it contributes |
| --- | --- |
| Root entity | Default perspective bundle and target strategy. |
| Input channel | Q1/Q2/Q3/Q4 scope and methodology maintenance process. |
| Source config | Source-specific targets for the meta-wiki and root entity. |

## Input channel and process map

- Input channel: [Methodology reference input](../../system/input-channels/methodology-reference.md)
- Processes: [Wiki methodology maintenance](../../system/processes/wiki-methodology-maintenance.md)
- Target pages: root entity, meta-wiki index, architecture and ingestion flow.
- Quadrants: Q1, Q2, Q3, Q4.

## Search rules

- Search the source and current docs for methodology terms, page types, source
  models, perspective names, input-stage behavior and gates.

## Business rules

- Core/toolkit corrections land in the open-source repo before private
  downstream migration.
- Green gates are necessary but do not replace conceptual review.
- Derived data is cache; canonical truth is the merged Markdown wiki.

## Privacy boundaries

- Open-source examples must be public-safe and synthetic.
- Access secrets are blocked everywhere.
