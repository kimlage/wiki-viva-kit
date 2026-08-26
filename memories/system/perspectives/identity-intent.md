---
page_id: perspective-identity-intent
page_type: perspective
title: "Identity and intent perspective"
aliases:
  - Identity lens
  - Intent lens
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
source_refs:
  - sources-wiki-viva-methodology
applies_to_source_types:
  - manual_note
  - proposal
  - meeting
  - reference
concerns: "Identity, intent, priorities, constraints, preferences and subjective stance."
extracts:
  - identity
  - intent
  - priorities
  - constraints
  - preferences
target_page_types:
  - root_entity
  - person
  - project
  - claim
  - decision
prompt_profile: perspective_identity_intent
quadrant: q1
inherits_from_root: true
target_obligation: updated_or_no_change_reason
moc_parent: memories/system/perspectives/index.md
related_pages:
  - memories/system/perspectives/index.md
---

# Identity and intent perspective

## Concern

What the root entity or stakeholder is trying to be, do, protect or prioritize.
For non-person roots, this is declared intent, self-description, mission or
stakeholder stance; it is not a claim that a product, company or team has literal
individual consciousness.

## Quadrant

| Field | Value |
| --- | --- |
| Quadrant | `q1` |
| Inherits from root entity | `true` |
| Target obligation | `updated_or_no_change_reason` |

## Extraction Questions

- What intent, priority, constraint or preference changed?
- What first-person or identity statement should be preserved?
- For a non-person root, who expressed the intent or where is it declared?
- What absence matters because the source does not speak from this viewpoint?

## Target Pages

- Root entity pages.
- Person, project, claim and decision pages.

## Correspondence Rules

- Intent extracted here must not contradict process or artifact evidence without
  a conflict note.

## Inheritance Rules

- Applies by default when declared in a root entity perspective bundle.
