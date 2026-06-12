---
page_id: perspective-stakeholder
page_type: perspective
title: "Stakeholder perspective"
aliases:
  - People and stakeholder lens
tags:
  - wiki/perspective
  - status/active
status: active
context: system
visibility: private_self
updated_at: 2026-06-12
stale_after_days: 90
sources_policy: perspective_contract
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
applies_to_source_types:
  - meeting
  - transcript
  - email
  - manual_note
concerns: "People, roles, relationships, incentives, commitments and privacy boundaries."
extracts:
  - people
  - roles
  - relationships
  - commitments
  - privacy_boundaries
target_page_types:
  - person
  - meeting
  - claim
  - action
zoom_attenuation: "Person pages receive durable relationship facts; hubs receive only role/status deltas."
conflict_policy: invalidate_not_delete
prompt_profile: perspective_stakeholder
moc_parent: memories/system/perspectives/index.md
related_pages:
  - memories/system/perspectives/index.md
---

# Stakeholder perspective

## Concern

Who is involved, what role they play, how they relate to the work, and which
commitments or boundaries changed.

## Extraction Questions

- Which person, role, stakeholder group or relationship is newly relevant?
- What commitment, expectation, conflict or privacy boundary appears?
- Does the source change how a person or group should be represented?

## Target Pages

- Person pages for durable role and relationship facts.
- Meeting pages for participant-specific decisions and commitments.
- Claim and action pages when a relationship fact needs provenance or follow-up.

## Correspondence Rules

- Do not promote a private relationship into a public-facing page without an
  explicit publication decision.
- If a name is uncertain, keep the uncertainty attached to the source/event.
