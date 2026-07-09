---
visibility: private_self
stale_after_days: 30
page_id: source-reference-folder
page_type: source
title: Reference folder mirror
context: estudio
updated_at: '2026-07-03'
moc_parent: memories/index.md
source_type: live
platform: Drive folder
owner: root-alex-rivera
region_expectations:
  intencao:
    state: optional
    basis: The reference folder may be evidence-only; an empty intent lens is explicitly
      healthy.
    next_interaction: openDock:source
source_lifecycle:
  state: ready
  freshness_state: never_synced
  last_attempt_state: never
  pipeline_stage: configured
  adoption_state: pending
---

# Reference folder mirror

A live source. Its content is born by ingestion — manual creation under it is off. (The bank export is intentionally overdue.)
