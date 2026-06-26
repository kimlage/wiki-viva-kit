---
page_id: input-channel-methodology-reference
page_type: input_channel
title: "Methodology reference input"
aliases:
  - Methodology reference channel
tags:
  - wiki/input-channel
  - status/active
status: active
context: system
visibility: private_self
updated_at: 2026-06-25
stale_after_days: 30
sources_policy: input_stage_contract
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
owner: root-wiki-viva-kit
moc_parent: memories/system/wiki-viva-kit.md
channel_type: document
input_status: configured
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
source_refs:
  - sources-wiki-viva-methodology
source_config_refs:
  - source-config-wiki-viva-methodology
process_refs:
  - process-wiki-methodology-maintenance
target_pages:
  - memories/system/wiki-viva-kit.md
  - memories/system/wiki/index.md
  - memories/system/wiki/architecture.md
  - memories/system/wiki/ingestion-flow.md
claims: []
decisions: []
actions: []
evidence_refs:
  - memories/sources/wiki-viva-methodology-v5.md
refresh_policy: event_driven
refresh_cadence_days: 45
privacy_boundary: private_self
---

# Methodology reference input

## Channel

| Field | Value |
| --- | --- |
| Type | `document` |
| Status | `configured` |
| Refresh policy | Event-driven; revisit when methodology, templates, gates or release notes change. |
| Privacy boundary | Private operational docs; public exports must stay synthetic/public-safe. |

## Sources and Configs

| Source | Config | Status |
| --- | --- | --- |
| [Living wiki methodology](../../sources/wiki-viva-methodology-v5.md) | [wiki-viva-methodology-v5.md](../../sources/config/wiki-viva-methodology-v5.md) | configured |

## Quadrants and Perspectives

| Quadrant | Required perspectives | Optional perspectives |
| --- | --- | --- |
| Q1/Q2/Q3/Q4 | identity/intent, outputs/evidence, shared meaning/roles-as-lived, systems/processes | privacy/publication |

## Process Links

- Process: [Wiki methodology maintenance](../processes/wiki-methodology-maintenance.md)
- Target pages: root entity, meta-wiki index, architecture and ingestion flow.

## Fetching Rules

- Connector or agent action required: local repo read only.
- What never to copy: private downstream examples, credentials, cookies, tokens
  or individualized authenticated links.
- Staging location or external reference: versioned repo docs and synthetic
  fixtures.

## Related

- Root entity: [Wiki Viva Kit](../wiki-viva-kit.md)
- Input stage: [input-stage.md](../input-stage.md)
