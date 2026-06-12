---
page_id: perspective-financial
page_type: perspective
title: "Financial perspective"
aliases:
  - Money and reconciliation lens
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
  - statement
  - invoice
  - transaction_export
  - spreadsheet
  - manual_note
concerns: "Amounts, counterparties, categories, reconciliation state, evidence and operational risk."
extracts:
  - amounts
  - counterparties
  - categories
  - reconciliation_state
  - evidence
target_page_types:
  - claim
  - action
  - decision
  - context_note
zoom_attenuation: "Ledgers stay in tabular artifacts; wiki pages receive explanations, rules and reconciliation deltas."
conflict_policy: invalidate_not_delete
prompt_profile: perspective_financial
moc_parent: memories/system/perspectives/index.md
related_pages:
  - memories/system/perspectives/index.md
---

# Financial perspective

## Concern

What amount, counterparty, classification rule, reconciliation state or financial
risk should be preserved without turning the wiki into a full ledger.

## Extraction Questions

- Which amount, account, counterparty, category or period is materially relevant?
- Is the item reconciled, pending, duplicated, excluded or waiting for evidence?
- Which rule or explanation prevents future misclassification?

## Target Pages

- Claim pages for durable financial facts.
- Action pages for pending reconciliation work.
- Decision pages for classification or evidence-policy decisions.
- Context notes for recurring rules and explanations.

## Correspondence Rules

- Keep complete ledgers in spreadsheets or derived artifacts; summarize only the
  context needed for decisions and future classification.
- Net-flow categories must preserve entries, exits and net balance when relevant.
