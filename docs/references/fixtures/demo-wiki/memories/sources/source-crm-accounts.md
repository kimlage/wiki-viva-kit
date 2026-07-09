---
visibility: private_self
stale_after_days: 30
page_id: source-crm-accounts
page_type: source
title: CRM accounts export
context: clientes
updated_at: '2026-07-03'
moc_parent: memories/clientes/index.md
source_type: live
platform: CRM
owner: root-alex-rivera
region_expectations:
  intencao:
    state: not_applicable
    basis: This blocked CRM adapter exposes account evidence, not intent records.
    next_interaction: openDock:source
sync:
  last_run_at: '2026-07-03'
  last_status: needs_auth
  last_event_ref: ''
source_blocked_reason: Authorization is required; no credential value is stored in
  the fixture.
source_lifecycle:
  state: blocked
  freshness_state: never_synced
  last_attempt_state: needs_auth
  pipeline_stage: configured
  adoption_state: pending
  last_attempt_at: '2026-07-03'
  secret_safe_log_refs:
  - logs/demo/source-crm-accounts-needs-auth
---

# CRM accounts export

A live source. Its content is born by ingestion — manual creation under it is off. (The bank export is intentionally overdue.)
