---
page_id: perspective-technical
page_type: perspective
title: "Technical perspective"
aliases:
  - Technical lens
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
  - code_change
  - manual_note
concerns: "Architecture, dependencies, technical decisions, risks, debt and validation."
extracts:
  - architecture
  - dependencies
  - decisions
  - risks
  - tests
target_page_types:
  - project
  - initiative
  - claim
  - decision
  - action
zoom_attenuation: "Leaf project pages receive detail; parent hubs receive one-line status or risk deltas."
conflict_policy: invalidate_not_delete
prompt_profile: perspective_technical
moc_parent: memories/system/perspectives/index.md
related_pages:
  - memories/system/perspectives/index.md
---

# Technical perspective

## Concern

What changes in architecture, dependencies, operational risk, implementation
strategy or validation.

## Extraction Questions

- What technical decision, dependency or risk appears in the source?
- Which commands, tests or validation evidence matter?
- Does the source supersede a previous technical claim?

## Target Pages

- Project and initiative pages for status/risk deltas.
- Claim and decision pages for durable technical facts.
- Action pages for follow-up implementation work.

## Correspondence Rules

- A decision extracted here should agree with project status pages.
- Superseded claims are invalidated or moved to history, not deleted silently.
