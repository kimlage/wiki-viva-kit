# Template - perspective

```yaml
---
page_id: perspective-example
page_type: perspective
title: "Perspective - example"
aliases:
  - Example perspective
tags:
  - wiki/perspective
  - status/active
status: active
context: system
visibility: private_self
updated_at: YYYY-MM-DD
stale_after_days: 90
sources_policy: perspective_contract
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
applies_to_source_types:
  - meeting
concerns: "What this perspective is responsible for extracting."
extracts:
  - decisions
target_page_types:
  - project
zoom_attenuation: "Leaf pages receive detail; parent hubs receive status deltas."
conflict_policy: invalidate_not_delete
metric_contract:
  required_metrics:
    - decision_count
prompt_profile: perspective_example
quadrant: q4
inherits_from_root: true
target_obligation: "updated_or_no_change_reason"
---
```

# Perspective - example

## Concern

State the stakeholder concern this viewpoint answers.

## Quadrant

| Field | Value |
| --- | --- |
| Quadrant | `q1` / `q2` / `q3` / `q4` / `boundary` |
| Inherits from root entity | `true` / `false` |
| Target obligation | `updated_or_no_change_reason` |

## Extraction Questions

- What should the reader extract?
- What should count as absence?

## Target Pages

- Which page types can this perspective update?

## Correspondence Rules

- Which other perspectives or pages must remain consistent?

## Inheritance Rules

- When declared in a root entity bundle, this perspective applies to matching
  input channels unless a source config skips it with a reason.
- When declared directly in a source config, it is source-specific and overrides
  optional root defaults.
