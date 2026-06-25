---
page_id: perspective-systems-processes
page_type: perspective
title: "Systems and processes perspective"
aliases:
  - Systems lens
  - Process lens
tags:
  - wiki/perspective
  - status/active
status: active
context: system
visibility: private_self
updated_at: 2026-06-25
stale_after_days: 90
sources_policy: perspective_contract
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
applies_to_source_types:
  - runbook
  - process
  - reference
  - meeting
  - code_change
concerns: "Systems, channels, coordination tools/platforms, processes, cadences, gates, queues and governance."
extracts:
  - systems
  - channels
  - processes
  - cadences
  - gates
target_page_types:
  - root_entity
  - process
  - input_channel
  - source_config
  - operational_rule
  - project
prompt_profile: perspective_systems_processes
quadrant: q4
inherits_from_root: true
target_obligation: updated_or_no_change_reason
moc_parent: memories/system/perspectives/index.md
related_pages:
  - memories/system/perspectives/index.md
---

# Systems and processes perspective

## Concern

Which systems, input channels, coordination tools/platforms, processes,
cadences, gates or governance rules coordinate the work.

## Quadrant

| Field | Value |
| --- | --- |
| Quadrant | `q4` |
| Inherits from root entity | `true` |
| Target obligation | `updated_or_no_change_reason` |

## Extraction Questions

- Which process, channel, system, tool/platform or gate appears or changes?
- What cadence or workflow should be preserved?
- Is a role/responsibility being described as externally administered
  governance rather than shared meaning? If so, keep it in Q4 and link to the
  Q3 relationship context only when one exists.
- Which target page must be updated or explicitly left unchanged?

## Target Pages

- Root entity, process, input-channel, source-config, operational-rule and
  project pages.

## Correspondence Rules

- Process changes should update the root/entity hub or carry a no-change reason.
- Coordination tools such as Slack, Jira, Drive, calendars, CI, CRM, ERP,
  support systems and workflow engines belong here when they structure shared
  work.

## Inheritance Rules

- Applies by default to input channels and source configs inherited from a root
  entity.
