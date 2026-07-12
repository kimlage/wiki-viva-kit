---
visibility: private_self
stale_after_days: 30
page_id: source-product-analytics
page_type: source
title: Product analytics export
context: clientes
updated_at: '2026-07-03'
moc_parent: memories/clientes/index.md
source_type: live
platform: Analytics
owner: root-alex-rivera
sync:
  last_run_at: '2026-07-03'
  last_status: ok
  last_event_ref: memories/system/ingestion/events/event-ingest-product-analytics-2026-07.md
source_lifecycle:
  state: ingested
  freshness_state: fresh
  last_attempt_state: ok
  pipeline_stage: complete
  adoption_state: accepted
  accepted_ref: demo-sha:product-analytics-accepted
  last_sync_success_at: '2026-07-03'
  last_ingested_at: '2026-07-03'
  last_attempt_at: '2026-07-03'
  emitted_page_ids:
  - dashboard-clearpath-activation
  proposal_ids:
  - proposal-ingest-product-analytics-2026-07
  raw_artifact_count: 1
  secret_safe_log_refs:
  - logs/demo/source-product-analytics-attempt
---

# Product analytics export

A live Analytics source. Its content is born by ingestion — manual creation under it is off. This fixture demonstrates lifecycle `ingested`, freshness `fresh` and last attempt `ok`.
