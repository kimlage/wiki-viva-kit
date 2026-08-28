---
visibility: private_self
stale_after_days: 30
page_id: source-banco-export
page_type: source
title: Extrato do Banco
context: financeiro
updated_at: '2026-05-04'
moc_parent: memories/financeiro/index.md
source_type: live
platform: Banco
owner: root-alex-rivera
sync:
  last_run_at: '2026-05-04'
  last_status: ok
  last_event_ref: memories/system/ingestion/events/event-ingest-banco-2026-05.md
source_lifecycle:
  state: consolidated
  freshness_state: stale
  last_attempt_state: ok
  pipeline_stage: gate_pending
  adoption_state: pending
  last_sync_success_at: '2026-05-04'
  last_attempt_at: '2026-05-04'
  emitted_page_ids:
  - claim-custos-sobem
  - artifact-relatorio-recon
  proposal_ids:
  - event-ingest-banco-2026-05
  raw_artifact_count: 1
  secret_safe_log_refs:
  - logs/demo/source-banco-export-attempt
---

# Extrato do Banco

A live Banco source. Its content is born by ingestion — manual creation under it is off. This fixture demonstrates lifecycle `consolidated`, freshness `stale` and last attempt `ok`. The bank export is intentionally overdue so the refresh mission has real evidence.
