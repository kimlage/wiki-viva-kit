---
page_id: perspective-operations
page_type: perspective
title: "Operations perspective"
aliases:
  - Operational process lens
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
  - runbook
  - meeting
  - incident
  - manual_note
  - code_change
concerns: "Process state, runbooks, failure modes, validation gates, ownership and next operating action."
extracts:
  - process_state
  - runbook_steps
  - failure_modes
  - validation_gates
  - ownership
target_page_types:
  - operational_rule
  - action
  - decision
  - project
  - context_note
zoom_attenuation: "Runbooks receive exact operating deltas; hubs receive concise state and escalation changes."
conflict_policy: invalidate_not_delete
prompt_profile: perspective_operations
moc_parent: memories/system/perspectives/index.md
related_pages:
  - memories/system/perspectives/index.md
---

# Operations perspective

## Concern

How the operating process changes: runbook steps, ownership, failure modes,
validation gates and next action.

## Extraction Questions

- What operational rule, runbook step or validation gate changed?
- Which failure mode or escalation condition should be preserved?
- Who owns the next operating action and what evidence proves completion?

## Target Pages

- Operational-rule pages for durable process contracts.
- Action pages for pending operating work.
- Decision pages for rule changes.
- Project or context-note pages for status and runbook deltas.

## Correspondence Rules

- If a workflow cannot read its live source, record an operational failure rather
  than substituting stale local state.
- Process pages should link to the command, gate or readback evidence they rely on.
