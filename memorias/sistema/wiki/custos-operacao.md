---
page_id: sistema-wiki-custos-operacao
page_type: source_catalog
title: "Meta-wiki: operating costs and discipline"
aliases:
  - Living wiki costs
  - Cost discipline
tags:
  - wiki/meta
  - wiki/custo
  - status/active
status: active
context: sistema
visibility: private_self
updated_at: 2026-06-09
stale_after_days: 120
sources_policy: documentacao_do_proprio_sistema
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
purpose: "Where the cost of operating the living wiki actually goes, and the levers to reduce it without losing quality."
moc_parent: memorias/sistema/wiki/index.md
related_pages:
  - memorias/sistema/wiki/fluxo-ingestao.md
  - memorias/sistema/wiki/referencia-comandos.md
---

# Meta-wiki: operating costs and discipline

Last updated: 2026-06-09.

This page summarizes **where the money actually goes** when operating the living
wiki, and the levers to cut cost without touching the quality of the gates.

## Where the cost actually goes

1. **The session of the agent that operates the repo** (Claude Code, etc.) — this
   is the DOMINANT cost. Each thematic PR consumes hundreds of thousands of
   context tokens. This is where the spend concentrates, not in ingestion.
2. **Human time** for PR review — the real scaling bottleneck is a single owner
   reviewing proposals, not the algorithm.
3. **LLM ingestion** (deep read per chunk) — this is pocket change: cents per
   source, tens of dollars per month even in a heavy scenario.
4. **CI** — zero inside the free tier (each run costs ~1-3 min).

## Levers (without losing quality)

### Agent session discipline (biggest lever)

- Fewer burst sessions: group related work into one session instead of many
  short sessions that rebuild context from scratch.
- Reuse the prompt cache: keeping the stable prefix (instructions, fixed context)
  at the start reduces the cost of repeated tokens.
- Give the full, well-specified task up front (fewer back-and-forth round trips).

### Budget alert

- Billing is consulted separately (outside the toolkit, to avoid coupling the kit
  to a provider): consult your provider's billing/usage dashboard and act when
  spend crosses the budget. Historical spend tends to concentrate in a few burst
  days, so a periodic check catches the spikes.

### Batches API for the deep read (-50%)

- [scripts/wiki_export_batch.py](../../../scripts/wiki_export_batch.py) exports the
  pending context packets in the Message Batches API format, **deterministically
  and without calling any model** (the intelligence stays delegated to the agent
  — see [arquitetura.md](arquitetura.md)). Whoever runs the repo submits the
  JSONL and records the results back with
  [scripts/wiki_llm_context_pass.py](../../../scripts/wiki_llm_context_pass.py)
  `--record-result` (the `custom_id` is the chunk's `cache_key`).
- Batches cuts ingestion cost ~50% without changing extraction quality.

### Model by profile

- For simple chunks, a cheaper model (Haiku/Sonnet) on the deep read cuts cost.
  Pass `--model` when exporting the batch. Keep the most capable model for dense
  sources.

## What does NOT cost tokens

- The honesty gates (auditor, coverage, cockpit `--check`) are **deterministic**
  and cost zero model tokens — keep the intelligence out of them. See
  [gates-e-auditoria.md](gates-e-auditoria.md).

## Related

- Ingestion flow: [fluxo-ingestao.md](fluxo-ingestao.md).
- Command reference: [referencia-comandos.md](referencia-comandos.md).
