---
visibility: private_self
stale_after_days: 30
page_id: source-publication-queue
page_type: source
title: Publication queue
context: sistema
updated_at: '2026-07-03'
moc_parent: memories/index.md
source_type: live
platform: Review queue
owner: root-alex-rivera
sync:
  last_run_at: '2026-07-03'
  last_status: secret_blocked
  last_event_ref: ''
source_blocked_reason: Secret scanning blocked the synthetic attempt before publication.
source_lifecycle:
  state: blocked
  freshness_state: never_synced
  last_attempt_state: secret_blocked
  pipeline_stage: extracted
  adoption_state: pending
  last_attempt_at: '2026-07-03'
  secret_safe_log_refs:
  - logs/demo/source-publication-queue-secret-block
---

# Publication queue

A live source. Its content is born by ingestion — manual creation under it is off. (The bank export is intentionally overdue.)
