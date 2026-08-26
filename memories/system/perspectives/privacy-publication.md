---
page_id: perspective-privacy-publication
page_type: perspective
title: "Privacy and publication perspective"
aliases:
  - Privacy boundary lens
  - Publication boundary lens
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
  - public_profile
  - proposal
  - reference
  - email
  - transcript
  - manual_note
concerns: "Privacy boundary, public-safe claims, redaction needs and publication readiness."
extracts:
  - privacy_boundaries
  - public_claims
  - redaction_requirements
  - publication_actions
target_page_types:
  - root_entity
  - claim
  - decision
  - action
  - context_note
prompt_profile: perspective_privacy_publication
quadrant: boundary
inherits_from_root: true
target_obligation: updated_or_no_change_reason
moc_parent: memories/system/perspectives/index.md
related_pages:
  - memories/system/perspectives/index.md
  - memories/system/perspectives/publication.md
---

# Privacy and publication perspective

## Concern

What must stay private, what can be made public, and which publication claims
need redaction or current evidence.

## Quadrant

| Field | Value |
| --- | --- |
| Quadrant | `boundary` |
| Inherits from root entity | `true` |
| Target obligation | `updated_or_no_change_reason` |

## Extraction Questions

- Does the source introduce a public-facing claim?
- Which details must remain private?
- Which publication action or redaction checklist is required?

## Target Pages

- Root entity, claim, decision, action and context-note pages.

## Correspondence Rules

- Public candidates must pass `wiki_audit.py --check --public-export`.

## Inheritance Rules

- Optional by default; required when a source affects public docs, examples or
  release notes.
