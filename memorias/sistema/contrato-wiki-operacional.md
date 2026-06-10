---
page_id: sistema-contrato-wiki-operacional
page_type: operational_rule
context: sistema
visibility: private_self
updated_at: 2026-06-09
stale_after_days: 180
sources_policy: contrato_do_metodo
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
---

# Operational wiki contract

Updated at: 2026-06-09.

The canonical wiki is [memorias/](../); the GitHub PR is the human gate. This contract
defines what enters memory, how it enters, and how it is approved.

## Principles

- `main` is the approved wiki. Relevant changes enter through a `wiki/*` branch and go
  through a PR.
- Memory consolidates actionable synthesis, not just links to sources.
- Privacy along two axes: personal data (PII) is allowed on private pages; access
  secrets (tokens, passwords, keys, cookies) never enter.
- [docs/](../../docs/) holds references, templates and snapshots - it is not the main memory.

## What enters memory

- Decisions, actions, rules, context and synthesis per context declared in
  [wiki.config.yaml](../../wiki.config.yaml).
- Useful sensitive data (values, dates, counterparties, documents) when it helps
  operation, reconciliation, decision or context - on a private page.

## What does NOT enter

- Access secrets, individualized secure links, full dumps without criteria.
- Third-party content without an explicit operational need.

## Gate

- Each relevant batch enters through a `wiki/*` branch. The PR must show sources, changed
  pages, privacy risks, validations and pending items.
- The local gates (audit, coverage, cockpit, tests) must pass before the
  merge. See [aprovacoes-git.md](aprovacoes-git.md) and
  [processo-ingestao.md](processo-ingestao.md).
