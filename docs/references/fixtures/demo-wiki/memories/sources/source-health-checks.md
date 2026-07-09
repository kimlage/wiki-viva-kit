---
visibility: private_self
stale_after_days: 30
page_id: source-health-checks
page_type: source
title: Health checks output
context: sistema
updated_at: '2026-07-03'
moc_parent: memories/index.md
source_type: live
platform: Checks
owner: root-alex-rivera
relation_cases:
- type: markdown_link
  target: source-error-traces
  direction: directed
  basis: synthetic_allowed_cycle
  provenance:
    fixture: failures
    field: relation_cases
sync:
  last_run_at: '2026-07-03'
  last_status: failed
  last_event_ref: ''
source_blocked_reason: The synthetic health endpoint returned an operational failure.
source_lifecycle:
  state: blocked
  freshness_state: stale
  last_attempt_state: failed
  pipeline_stage: manifested
  adoption_state: pending
  last_attempt_at: '2026-07-03'
  secret_safe_log_refs:
  - logs/demo/source-health-checks-failed
---

# Health checks output

A live source. Its content is born by ingestion — manual creation under it is off. (The bank export is intentionally overdue.)
