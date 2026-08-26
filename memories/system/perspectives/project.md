---
page_id: perspective-project
page_type: perspective
title: "Project perspective"
aliases:
  - Project lens
  - Initiative perspective
tags:
  - wiki/perspective
  - status/active
status: active
context: system
visibility: private_self
updated_at: 2026-06-11
stale_after_days: 90
sources_policy: perspective_contract
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
source_refs:
  - sources-wiki-viva-methodology
applies_to_source_types:
  - meeting
  - transcript
  - manual_note
  - repo
concerns: "Goals, status, deliverables, metrics, risks, stakeholders and next milestones."
extracts:
  - goals
  - status
  - deliverables
  - metrics
  - risks
  - action_items
target_page_types:
  - project
  - initiative
  - action
  - claim
zoom_attenuation: "Leaf projects receive concrete deltas; parent hubs receive concise rollups."
conflict_policy: invalidate_not_delete
prompt_profile: perspective_project
moc_parent: memories/system/perspectives/index.md
related_pages:
  - memories/system/perspectives/index.md
---

# Project perspective

## Concern

What changed in the initiative's goal, status, planned delivery, risk profile or
next action.

## Extraction Questions

- What milestone, delivery or status changed?
- Which metric or risk should be carried forward?
- Who owns the next action?

## Target Pages

- Project and initiative pages for status and metrics.
- Action pages for next steps.
- Claim pages when a durable project fact needs provenance.

## Correspondence Rules

- Status and metric deltas must not contradict technical or operational pages
  that cite the same source.
