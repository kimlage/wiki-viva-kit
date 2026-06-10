---
page_id: fontes-metodologia-wiki-viva
page_type: source
title: "Living wiki methodology (source)"
aliases:
  - Living wiki methodology
tags:
  - wiki/fontes
  - wiki/metodologia
  - status/active
status: active
context: sistema
visibility: private_self
updated_at: 2026-06-09
stale_after_days: 180
sources_policy: fonte_metodologica
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
purpose: "Source page that describes the living wiki methodology implemented by the kit."
moc_parent: memorias/index.md
related_pages:
  - memorias/sistema/cobertura-metodologia-v5.md
owner:
related_holons:
roles:
responsibilities:
source_refs:
claims:
decisions:
actions:
evidence_refs:
---

# Living wiki methodology (source)

Updated on: 2026-06-09.

This page is the methodological source of the kit: it describes, at a high level, the model of
the living operational wiki that the code implements. Implementation coverage is
tracked in [cobertura-metodologia-v5.md](../sistema/cobertura-metodologia-v5.md).

## Principles

- **Markdown/Git as a portable foundation.** The wiki is versioned text; the PR is the gate.
- **Ingestion as compilation.** A source becomes a manifest, text/chunks, an index, a context
  package, a normalized event, and consolidation.
- **Code first, LLM for deep context.** The Python is deterministic; the
  deep reading belongs to the agent that runs the repo, recorded in the cache (gate
  `required_context_pass`).
- **Privacy per page.** PII is welcome on private pages; secrets are
  always blocked; PII only becomes an error at the public boundary.
- **Four quadrants** as an ingestion lens (interior/exterior, individual/
  collective), with explicit absence.
- **Operation page** (cockpit) as the first resumption screen.
- **Karma gamification** as a by-product, without toxic ranking.
- **Perceptive layer** (journal, map) before becoming canonical memory.

## Related

- Coverage: [cobertura-metodologia-v5.md](../sistema/cobertura-metodologia-v5.md).
- Process: [processo-ingestao.md](../sistema/processo-ingestao.md).
