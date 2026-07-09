---
visibility: private_self
stale_after_days: 30
page_id: source-action-ledger
page_type: source
title: Action ledger export
context: sistema
updated_at: '2026-07-03'
moc_parent: memories/index.md
source_type: live
platform: Action tracker
owner: root-alex-rivera
region_expectations:
  intencao:
    state: required
    basis: The action-ledger source contract requires at least one declared intent
      or reviewed no-change receipt.
    expected_type_hints:
    - action
    expected_action_hints:
    - review_source_contract
    next_interaction: seedPage
source_lifecycle:
  state: configured
  freshness_state: never_synced
  last_attempt_state: never
  pipeline_stage: configured
  adoption_state: pending
---

# Action ledger export

A live source. Its content is born by ingestion — manual creation under it is off. (The bank export is intentionally overdue.)
