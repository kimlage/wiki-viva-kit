---
page_id: sistema-wiki-index
page_type: source_catalog
title: "Meta-wiki: how the living wiki works"
aliases:
  - Meta-wiki
  - Wiki documentation
tags:
  - wiki/meta
  - status/active
status: active
context: sistema
visibility: private_self
updated_at: 2026-06-09
stale_after_days: 90
sources_policy: documentacao_do_proprio_sistema
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
purpose: "Meta-wiki: the living wiki itself documenting its operation and its process."
moc_parent: memorias/index.md
related_pages:
  - memorias/sistema/processo-ingestao.md
  - memorias/sistema/contrato-wiki-operacional.md
  - memorias/sistema/cobertura-metodologia-v5.md
---

# Meta-wiki: how the living wiki works

Last updated: 2026-06-09.

This is the **meta-wiki**: the living wiki itself used to document, in a
complete and organized way, how the system **operates** and what its **process** is.
It serves equally the personal project and the open-source version — the system (method +
tools) is the same in both.

## Where to start

- Never used it? Read [arquitetura.md](arquitetura.md) and then
  [operacao-diaria.md](operacao-diaria.md).
- Going to ingest a source? [fluxo-ingestao.md](fluxo-ingestao.md).
- Going to open a PR? [governanca-pr.md](governanca-pr.md) and [gates-e-auditoria.md](gates-e-auditoria.md).

## Map of the meta-wiki

| Page | What it covers |
| --- | --- |
| [arquitetura.md](arquitetura.md) | Overview, principles and map of the modules. |
| [operacao-diaria.md](operacao-diaria.md) | The daily loop: cockpit, resumption and gates before the PR. |
| [fluxo-ingestao.md](fluxo-ingestao.md) | Source -> manifest -> chunks -> index -> LLM -> event -> consolidation. |
| [gates-e-auditoria.md](gates-e-auditoria.md) | The honesty gates: audit, coverage, freshness, LLM pass. |
| [privacidade.md](privacidade.md) | Two axes: PII free in private; secrets blocked always. |
| [gamificacao-karma.md](gamificacao-karma.md) | 8-dimension karma as a by-product, without a leaderboard. |
| [camada-perceptiva-insight.md](camada-perceptiva-insight.md) | Journal/map and the Information -> Insight cycle. |
| [governanca-pr.md](governanca-pr.md) | Human gate by PR, review, split and status across two dimensions. |
| [custos-operacao.md](custos-operacao.md) | Where the cost goes (agent session, human) and levers: Batches, model by profile, budget. |
| [referencia-comandos.md](referencia-comandos.md) | Reference of all the `wiki_*` CLIs. |

## Related method pages

- Ingestion process: [processo-ingestao.md](../processo-ingestao.md).
- Operational wiki contract: [contrato-wiki-operacional.md](../contrato-wiki-operacional.md).
- Methodology coverage: [cobertura-metodologia-v5.md](../cobertura-metodologia-v5.md).
- Approvals and gate by PR: [aprovacoes-git.md](../aprovacoes-git.md).
- Operational cockpit: [operacao.md](../../operacao.md).
