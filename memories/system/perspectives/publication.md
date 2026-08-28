---
page_id: perspective-publication
page_type: perspective
title: "Publication perspective"
aliases:
  - Public/private boundary lens
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
  - public_profile
  - proposal
  - email
  - transcript
  - manual_note
concerns: "What can be published, what must stay private, and which claims need current public evidence."
extracts:
  - public_claims
  - private_boundaries
  - citations
  - stale_public_evidence
  - publication_actions
target_page_types:
  - claim
  - decision
  - action
  - context_note
zoom_attenuation: "Private pages may keep detail; public candidates receive only reviewed, source-backed summaries."
conflict_policy: invalidate_not_delete
prompt_profile: perspective_publication
moc_parent: memories/system/perspectives/index.md
related_pages:
  - memories/system/perspectives/index.md
---

# Publication perspective

## Concern

Which information is safe and useful to publish, which boundary must remain
private, and which public claim needs current evidence.

## Extraction Questions

- Does the source create or change a public-facing claim?
- Which names, clients, credentials, internal details or private relationships
  must stay out of public artifacts?
- Which citation or readback is needed before publication?

## Target Pages

- Claim pages for public/private fact boundaries.
- Decision pages for publication and redaction rules.
- Action pages for citation refresh or review.
- Context notes for reusable public-positioning guidance.

## Correspondence Rules

- A private claim may inform a public summary, but must not be copied verbatim
  when it exposes people, clients, secrets or internal evidence.
- Stale public evidence creates an action, not an unsupported public claim.
