---
page_id: perspective-roles-relationships
page_type: perspective
title: "Roles and relationships perspective"
aliases:
  - Roles lens
  - Relationship lens
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
  - meeting
  - transcript
  - email
  - manual_note
  - reference
concerns: "People as participants, roles, responsibilities, relationships, rituals, expectations and culture."
extracts:
  - people
  - roles
  - responsibilities
  - relationships
  - rituals
target_page_types:
  - root_entity
  - person
  - role
  - responsibility
  - meeting
  - relationship_map
prompt_profile: perspective_roles_relationships
quadrant: q3
inherits_from_root: true
target_obligation: updated_or_no_change_reason
moc_parent: memories/system/perspectives/index.md
related_pages:
  - memories/system/perspectives/index.md
---

# Roles and relationships perspective

## Concern

Who participates, what roles and responsibilities exist, how relationships work
and which shared meanings, norms or social expectations shape the operation.

## Quadrant

| Field | Value |
| --- | --- |
| Quadrant | `q3` |
| Inherits from root entity | `true` |
| Target obligation | `updated_or_no_change_reason` |

## Extraction Questions

- Which person as participant, role or responsibility appears or changes?
- Which relationship, ritual, expectation or cultural rule matters?
- Which uncertainty about a person or role must stay attached to the source?

## Target Pages

- Root entity, person, role, responsibility, meeting and relationship-map pages.

## Correspondence Rules

- Do not promote private relationship facts to public pages without a
  publication decision.
- A plain roster is not enough for Q3; capture the relationship, role,
  expectation, ritual, norm or culture that makes the roster meaningful.

## Inheritance Rules

- Applies by default to team/company/person roots and communication/meeting
  channels.
