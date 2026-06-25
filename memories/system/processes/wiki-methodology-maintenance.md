---
page_id: process-wiki-methodology-maintenance
page_type: process
title: "Wiki methodology maintenance"
aliases:
  - Methodology maintenance process
tags:
  - wiki/process
  - status/active
status: active
context: system
visibility: private_self
updated_at: 2026-06-25
stale_after_days: 45
sources_policy: process_contract
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
owner: root-wiki-viva-kit
moc_parent: memories/system/wiki-viva-kit.md
cadence: event_driven
input_channels:
  - input-channel-methodology-reference
related_holons: []
roles: []
responsibilities: []
source_refs:
  - sources-wiki-viva-methodology
claims: []
decisions: []
actions: []
evidence_refs:
  - docs/references/proposals/integral-root-entity-and-input-stage-refactor-2026-06-25.md
---

# Wiki methodology maintenance

## Purpose

Keep the reusable open-source methodology, deterministic code, templates,
skills and documentation aligned before downstream private repos migrate.

## Flow

```mermaid
flowchart LR
    proposal["Methodology proposal"]
    code["Toolkit code/templates"]
    docs["Meta-wiki documentation"]
    gates["Local gates"]
    pr["Human PR gate"]
    proposal --> code --> docs --> gates --> pr
```

## Cadence and Gates

| Item | Value |
| --- | --- |
| Cadence | Event-driven by methodology or source-model changes. |
| Owner | Wiki owner and repo agent. |
| Entry criteria | A proposal or source change affects the reusable kit. |
| Exit criteria | Code, docs, templates, skills and gates align in the open-source repo. |

## Inputs and Outputs

| Input channel | Output artifact | Target page |
| --- | --- | --- |
| [Methodology reference input](../input-channels/methodology-reference.md) | Updated root/input-stage/source model | [Wiki Viva Kit](../wiki-viva-kit.md) |

## Roles and Responsibilities

| Role | Responsibility |
| --- | --- |
| Repo agent | Implements deterministic core and updates docs. |
| Wiki owner | Reviews conceptual diff and approves merge. |

## Related

- Root entity: [Wiki Viva Kit](../wiki-viva-kit.md)
- Input stage: [input-stage.md](../input-stage.md)
