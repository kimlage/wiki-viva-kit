---
page_id: system-operational-wiki-contract
page_type: operational_rule
context: system
visibility: private_self
updated_at: 2026-10-23
stale_after_days: 180
sources_policy: contrato_do_metodo
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
---

# Operational wiki contract

Updated at: 2026-10-23.

The canonical wiki is [memories/](../index.md); the GitHub PR is the review gate. This contract
defines what enters memory, how it enters, and how it is approved.

## Principles

- `main` is the approved wiki. Relevant changes enter through a `wiki/*` branch and go
  through a PR.
- Memory consolidates actionable synthesis, not just links to sources.
- Privacy along two axes: personal data (PII) is allowed on private pages; access
  secrets (tokens, passwords, keys, cookies) never enter.
- Rich representation by default: pages illustrate structure with Mermaid diagrams
  and Markdown tables, keeping prose for nuance; architecture/flow/relationship/
  process pages carry at least one diagram. See the guideline in
  [obsidian-conventions.md](../../docs/references/templates/wiki/obsidian-conventions.md).
- [docs/](../../docs/README.md) holds references, templates and snapshots - it is not the main memory.

## Delegated work

Every agent uses this same memory and ingestion/consolidation process. The
action page remains canonical and the board projects it; delegation does not
create a second backlog or memory. Include the consumer's current approval,
operational and ingestion policies in the coordination policy's `common_context`,
alongside its router and root page. See the
[context and delegation contract](../../docs/references/guides/context-coordinators.md#delegation-contract)
and [subagent brief](../../docs/references/templates/wiki/subagent-brief.md).

Bind the handoff to the action/base revision, source evidence and destination
pages. The executing instance verifies its own tools, host and account within
the authorized scope; a parent's access or a prepared packet proves none of
these. Record an exact blocker and a bounded recovery condition on the same
action, preserving its IDs and independent work. Completion requires the
result's consolidation and applicable review, not merely a finished agent run.

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
- Independent review under [AGENTS.md](../../AGENTS.md), all applicable local
  gates (audit, coverage, cockpit, tests) and normal CI must pass before merge. See [git-approvals.md](git-approvals.md) and
  [ingestion-process.md](ingestion-process.md).
