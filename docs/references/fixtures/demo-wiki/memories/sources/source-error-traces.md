---
visibility: private_self
stale_after_days: 30
page_id: source-error-traces
page_type: source
title: Error trace export
context: clientes
updated_at: '2026-07-03'
moc_parent: memories/clientes/product-ops/index.md
source_type: live
platform: Observability
owner: root-alex-rivera
relation_cases:
- type: markdown_link
  target: source-health-checks
  direction: directed
  basis: synthetic_allowed_cycle
  provenance:
    fixture: failures
    field: relation_cases
- type: unknown_demo_relation
  target: missing-demo-page
  direction: directed
- type: source_ref
  target: source-health-checks
  direction: reverse
region_expectations:
  intencao:
    state: unknown
    basis: No template or operator rule has decided whether error traces should project
      intent.
    next_interaction: openDock:blocks
sync:
  last_run_at: '2026-07-03'
  last_status: parser_error
  last_event_ref: ''
source_blocked_reason: The synthetic trace export is malformed.
source_lifecycle:
  state: blocked
  freshness_state: stale
  last_attempt_state: parser_error
  pipeline_stage: extracted
  adoption_state: pending
  last_attempt_at: '2026-07-03'
  raw_artifact_count: 1
  secret_safe_log_refs:
  - logs/demo/source-error-traces-parser
---

# Error trace export

A live Observability source. Its content is born by ingestion — manual creation under it is off. This fixture demonstrates lifecycle `blocked`, freshness `stale` and last attempt `parser_error`.
