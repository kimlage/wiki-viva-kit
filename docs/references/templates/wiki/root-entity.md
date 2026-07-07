# Template - root entity

```yaml
---
page_id: {{page_id}}
page_type: root_entity
title: "{{title}}"
aliases:
  - "{{title}}"
tags:
  - wiki/root-entity
  - status/active
status: active
context: {{context}}
visibility: private_self
updated_at: {{updated_at}}
stale_after_days: {{stale_after_days}}
sources_policy: root_entity_contract
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
root_entity_type: team
primary_contexts:
  - {{context}}
input_stage_ref: memories/system/input-stage.md
input_channels: []
perspective_bundle_required:
  - perspective-identity-intent
  - perspective-artifacts-evidence
  - perspective-roles-relationships
  - perspective-systems-processes
perspective_bundle_optional:
  - perspective-privacy-publication
source_refs: []
related_holons: []
roles: []
responsibilities: []
claims: []
decisions: []
actions: []
evidence_refs: []
---
```

# {{title}}

> Illustrate by default: this page is the semantic entry point of the wiki. It
> maps identity, artifacts, relationships, processes and input channels before
> source ingestion starts.

## Identity and Scope

| Field | Value |
| --- | --- |
| Root type | `person` / `team` / `company` / `project` / `community` / `product` |
| Purpose |  |
| Boundaries |  |
| Primary contexts |  |

## Integral Quadrant Map

Use Wilber/AQAL semantics, not arbitrary buckets:

| Quadrant | AQAL position | Operational test |
| --- | --- | --- |
| Q1 - Interior individual | `I` / interior individual | Interior view of the root holon: lived or declared identity, intent, meaning, priorities or constraints. For a team/company/product, do not invent consciousness; use stated mission, self-description or stakeholder intent. |
| Q2 - Exterior individual | `It` / exterior individual | Exterior view of the root holon as one entity: observable behavior, direct output, owned artifact, evidence or metric. A document/repository belongs here only when it is output/evidence of the root entity. |
| Q3 - Interior collective | `We` / interior collective | Interior view of the collective: shared meaning, culture, roles as lived expectations, relationships, rituals and norms. People are linked here as participants in a social field, not as a plain roster. |
| Q4 - Exterior collective | `Its` / exterior collective | Exterior view of the collective: systems, channels, tools, platforms, workflows, rules, institutions, governance and process infrastructure that coordinate work. |

Boundary rule: apply the quadrant relative to this page as the center. A nested
company can be Q4 for a person/root while its own intentions are Q1 when the
company page is selected as the center. A repository, document or dashboard is
Q2 only when it is an owned artifact/output/evidence of the current center. A
tool or platform such as Slack, Jira, Drive, calendar, CI, CRM or a workflow
engine is Q4 when it coordinates people, process, governance or infrastructure.
People, roles and relationships are Q3 only when read as shared meaning, mutual
expectation or culture; as externally administered structure they belong to Q4.

| Quadrant | What belongs here | Canonical pages | Input channels |
| --- | --- | --- | --- |
| Q1 - Interior individual | Identity, intent, priorities, constraints and first-person or declared stance |  |  |
| Q2 - Exterior individual | Observable behavior, direct outputs, owned artifacts, evidence and metrics of the root holon |  |  |
| Q3 - Interior collective | Shared meaning, culture, relationship quality, rituals, expectations and roles-as-lived |  |  |
| Q4 - Exterior collective | Systems, tools/platforms, channels, processes, cadences, governance, institutions and roles-as-administered |  |  |

```mermaid
flowchart TD
    root["Root entity"]
    q1["Q1 - intent"]
    q2["Q2 - outputs and evidence"]
    q3["Q3 - culture and relationships"]
    q4["Q4 - systems and processes"]
    root --> q1
    root --> q2
    root --> q3
    root --> q4
```

## People, Roles and Responsibilities

| Person or group | Role | Responsibility | Source |
| --- | --- | --- | --- |
|  |  |  |  |

## Artifacts and Observable Outputs

| Artifact/output | Type | Owner | Source/config |
| --- | --- | --- | --- |
|  |  |  |  |

Tools used as coordination platforms belong under
[Processes and Cadences](#processes-and-cadences) or
[Channels and Input Sources](#channels-and-input-sources), not here.

## Channels and Input Sources

| Channel | Type | Status | Source page | Config | Quadrants |
| --- | --- | --- | --- | --- | --- |
|  |  | `declared` |  |  |  |

## Processes and Cadences

| Process | Cadence | Inputs | Outputs | Gate |
| --- | --- | --- | --- | --- |
|  |  |  |  |  |

## Projects and Initiatives

| Project/initiative | Objective | State | Inputs |
| --- | --- | --- | --- |
|  |  |  |  |

## Perspective Bundle

| Perspective | Quadrant | Required? | Target pages |
| --- | --- | --- | --- |
| `perspective-identity-intent` | Q1 | yes | Root entity, decisions, claims |
| `perspective-artifacts-evidence` | Q2 | yes | Source, artifact, project and claim pages |
| `perspective-roles-relationships` | Q3 | yes | Person, role, responsibility and relationship pages when they preserve shared meaning, lived expectations or relationship context |
| `perspective-systems-processes` | Q4 | yes | Process, operation, source-config and project pages |
| `perspective-privacy-publication` | Boundary | optional | Publication and privacy checks |

## Source Ingestion Map

| Source | Input channel | Required perspectives | Target pages | Refresh |
| --- | --- | --- | --- | --- |
|  |  |  |  |  |

## Privacy and Publication Boundaries

- Personal data can stay on private pages when it is operational memory.
- Access secrets, cookies, tokens, passwords and individualized secure links are
  blocked everywhere.
- Public candidates require redaction and `--public-export` validation.

## Open Questions and Blocked Sources

| Item | Status | Owner | Next step |
| --- | --- | --- | --- |
|  |  |  |  |

## Related Pages

- Root MOC:
- Input stage:
- Source registry:
