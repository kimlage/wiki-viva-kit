---
page_id: operational-pass-wiki-viva-kit
page_type: dashboard
context: system
visibility: private_self
updated_at: 2026-10-26
stale_after_days: 1
sources_policy: memorias_fontes_acoes_contextos
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
purpose: cross-context compilation of sources, actions, uncertainty and next steps
moc_parent: memories/index.md
projection_inputs:
- paths:
  - wiki.config.yaml
  fields:
  - body
- page_types: []
  contexts: []
  fields:
  - page_id
  - context
  - title
  - updated_at
  title_fallback: true
  exclude_paths:
  - memories/system/operational-pass.md
- page_types:
  - claim
  - action
  contexts: []
  fields:
  - body
  - title
  - context
  - status
  - action_state
  - actions
  - responsibilities
- page_types:
  - decision
  contexts: []
  fields:
  - context
  - status
  - actions
- page_types:
  - decision
  contexts: []
  fields:
  - body
  status_excludes:
  - ''
  - active
  - ativa
  - ativo
  - closed
  - complete
  - completed
  - concluded
  - concluida
  - concluido
  - decided
  - decidida
  - decidido
  - done
  - resolved
  - resolvida
  - resolvido
  status_exclude_prefixes:
  - closed_at_
  - closed_em_
  - completed_at_
  - completed_em_
  - concluida_at_
  - concluida_em_
  - concluido_at_
  - concluido_em_
  - concluded_at_
  - concluded_em_
  - done_at_
  - done_em_
  - resolved_at_
  - resolved_em_
  - resolvida_at_
  - resolvida_em_
  - resolvido_at_
  - resolvido_em_
- page_types:
  - source
  - artifact
  contexts: []
  fields:
  - source_type
  - ingestion_state
  - structured_ingestion_state
  - context
- page_types:
  - role
  - responsibility
  - assignment
  contexts: []
  fields:
  - context
  - roles
  - responsibilities
  - actions
---

# Operational pass - sources, actions and contexts

Updated at: 2026-10-26.

Deterministic compilation for contexts: all. Use this page to compress next steps into actions, problems, claims, decisions and target pages; it does not replace human reading of live sources.

## Short-term memory

Read this first: a compact daily state of items that still need review, decision or action. Full diagnostic sections remain below.

### Review now

- No attention items.

### Primary actions

- No prioritized pending actions.

### Pending decisions

- No pending decisions.

### Latest updates

- **system:** [Operations - wiki-viva-kit](../operations.md)<!-- wiki-link-role.v2 projection consumes:body,context,page_id,page_type,title,updated_at produces:body sha256:97bc71cdfdc7a27351cf0235dc1ccaa607463796431c7552715b89bca201c622 --> (2026-10-26)
- **system:** [Meta-wiki: operating costs and discipline](wiki/operation-costs.md)<!-- wiki-link-role.v2 projection consumes:context,page_id,page_type,title,updated_at produces:body sha256:541646add117756bd8e979db687ac14fed3388d15d4003284c1918d0e8ea61a9 --> (2026-10-26)
- **system:** [Input stage](input-stage.md)<!-- wiki-link-role.v2 projection consumes:context,page_id,page_type,title,updated_at produces:body sha256:d7dd403f2b2ef424cff23b80b5e749c40b30d2bddb3107dd356619026fa975af --> (2026-10-26)
- **system:** [Ingestion process](ingestion-process.md)<!-- wiki-link-role.v2 projection consumes:body,context,page_id,page_type,title,updated_at produces:body sha256:8dc054b50ccf49168564b8a12702352eb466705a576fe2560ae0b73fa7b9a190 --> (2026-10-26)
- **system:** [Governance and PR flow](wiki/pr-governance.md)<!-- wiki-link-role.v2 projection consumes:context,page_id,page_type,title,updated_at produces:body sha256:b2d4479052df807204f438bbf08c12c1cc9d55031c6d4303f3303d504d651c0b --> (2026-10-26)


## Context summary

| Context | Hub | Vitality | Sources | Sources needing attention | Actions | Actions needing attention | Claims / decisions | Next steps |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| example | [Example context - hub](../example/index.md)<!-- wiki-link-role.v2 projection consumes:context,page_id,page_type,stale_after_days,title,updated_at produces:body sha256:b82f3e67868dbc583ee9582b1eaf1c63ecd4fa84f4ed7fa5834bcd8cb50a0592 --> | stale | 0 | 0 | 0 | 0 | 0 / 0 | - |
| system | [Memory - root MOC](../index.md)<!-- wiki-link-role.v2 projection consumes:context,page_id,page_type,stale_after_days,title,updated_at produces:body sha256:96b60a7605fb31aa92fba9ea7ed685eb015c2d4b34455acc46dc50ba6c01d226 --> | fresh | 1 | 0 | 0 | 0 | 0 / 0 | - |

## Consolidation output matrix

| Context | Actions | Problems | Claims | Decisions | Dense contexts | Non-ingested sources | Signal |
| --- | --- | --- | --- | --- | --- | --- | --- |
| example | 0 | 0 | 0 | 0 | 0 | 0 | ok |
| system | 0 | 0 | 0 | 0 | 0 | 0 | ok |

## Sources by state

| Source | Context | Ingestion | Last update | Next refresh | Status | Linked actions |
| --- | --- | --- | --- | --- | --- | --- |
| [Living wiki methodology (source)](../sources/wiki-viva-methodology-v5.md)<!-- wiki-link-role.v2 projection consumes:actions,context,ingestion_state,last_ingested_at,next_refresh_at,page_id,page_type,refresh_cadence_days,source_type,stale_after_days,status,structured_ingestion_state,title,updated_at produces:body sha256:b6f6b20c7b26aa778cc2d50e7b076f85f6199eb5ae410f4570168d13cfb2a114 --> | system | `ingested` | 2026-08-26 | 2027-02-22 | ok | - |

## Compiled actions

| Action | Context | State | Updated | Sources | Signal |
| --- | --- | --- | --- | --- | --- |
| No actions recorded. | - | - | - | - | - |

## Pending decisions

| Decision | Context | State | Updated | Linked actions | Signal |
| --- | --- | --- | --- | --- | --- |
| No pending decisions detected. | - | - | - | - | - |

## Actions gated by pending decisions

| Decision | Action | Action context | Decision state | Action state |
| --- | --- | --- | --- | --- |
| No action gated by a pending decision. | - | - | - | - |

## Problems and uncertainty

| Context | Type | Page | Reason |
| --- | --- | --- | --- |
| No heuristic problems or uncertainty detected. | - | - | - |

## Operational model by context

_(no roles filled per context.)_

## Resume links

- Index: [memories/index.md](../index.md)<!-- wiki-link-role.v1 navigation sha256:5c6096601ed8df9237c28ba72e14ac7d7dcd7eaab60e30462f0a7e724f4e9484 -->
- Operations: [memories/operations.md](../operations.md)<!-- wiki-link-role.v1 navigation sha256:4571d90787a4f4a89b8df779e92190c24d01646908d71787ac9efea69983351b -->
- Source registry: [memories/system/source-registry.md](source-registry.md)<!-- wiki-link-role.v1 navigation sha256:01b677487c574acbb55327efd54b0c65fa99f1f54ca818d50ac196dd82dc040a -->
- Pending actions: -

Generated by [scripts/wiki_operational_pass.py](../../scripts/wiki_operational_pass.py); run `--write` to update and `--check` before the PR.
