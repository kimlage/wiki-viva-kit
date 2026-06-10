---
page_id: sistema-mapa-relacoes-wiki
page_type: relationship_map
title: "Relationship map - living wiki system"
aliases:
  - Living wiki map
  - System relationships
tags:
  - wiki/percepcao
  - wiki/mapa
  - status/active
status: active
context: sistema
visibility: private_self
updated_at: 2026-06-09
stale_after_days: 60
sources_policy: derivado_da_arquitetura_real
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
status_epistemologico: percepcao
purpose: "Map how the real system modules connect, to see the organism (not islands) at a glance."
moc_parent: memorias/sistema/percepcao/index.md
related_pages:
  - memorias/sistema/percepcao/2026-06-09-journal-construcao-wiki.md
  - memorias/sistema/cobertura-metodologia-v5.md
perception_policy:
  layer: perceptiva
  is_canonical_truth: false
  subjective_inputs_allowed: true
  preferred_outputs:
    - diagrama_texto
    - lista_de_arestas
  accessibility:
    alt_text_required: true
    color_only_encoding_forbidden: true
    plain_language_summary_required: true
attachment_policy: "Optional diagram in data/derived with a Markdown link. Private repo: people's names are normal operational data; never embed access secrets."
---

# Relationship map - living wiki system

Updated on: 2026-06-09.

> **Private** page and **perception** (an at-a-glance reading of the architecture),
> not a contract. The source of truth for the modules is the code in [wiki_core/](../../../wiki_core/)
> and [scripts/](../../../scripts/).

## Plain-language summary

A text diagram of how the system pieces connect: ingestion pulls the source,
generates artifacts, triggers the privacy pre-scan, assembles the package for the
reading agent, and feeds the scoreboard and the cockpit. The gate by PR sits in
the middle, watching.

## Diagram (text, accessible)

```
            fonte (data/raw, Drive)
                     |
                     v
        [orquestrador de ingestao]  wiki_core/ingest/pipeline.py
        manifesto -> texto/chunks -> indice
                     |
        +------------+-------------------------------+
        |                          |                 |
        v                          v                 v
 [pre-scan]               [pacote de contexto    [score-event]
 detectores:              LLM]  wiki_core/llm/    wiki_core/score/
 segredo BLOQUEIA;        emite -request.json     karma 8 dimensoes
 PII informativa                |                       |
        |                       v                       v
        |             [agente do repo le e        [cockpit]
        |              grava resultado no cache]   operacao.md
        |                       |                  (le karma, decisoes, acoes)
        |                       v
        |             [auditor: gate de honestidade]
        +-----------> wiki_audit.py: required_context_pass,
                      segredo bloqueado, PII so na fronteira publica
                                |
                                v
                      [gate por PR no GitHub]
                      maquina de estados: created -> ... -> approved/superseded
```

## Main edges (origin -> target : relationship)

- `orquestrador -> detectores` : privacy pre-scan at capture (secret blocks).
- `orquestrador -> pacote LLM` : emits the `-request.json` that the auditor watches.
- `orquestrador -> score` : records `ingestar_fonte_valida` (karma).
- `pacote LLM -> agente do repo` : deep reading delegated (no LLM in Python).
- `agente -> cache` : writes the result; closes the `required_context_pass` gate.
- `score -> cockpit` : the cockpit displays karma per dimension.
- `auditor -> gate PR` : blocks the merge while there is a pending pass or secret.
- `gate PR -> memoria canonica` : only after human review does the proposal become memory.

## Perceptive reading

The drawing makes clear what was previously invisible: no module is an island.
Ingestion is the axis; privacy and scoreboard are by-products of the same pass; the
gate by PR is the valve that keeps honesty. Wherever an arrow disappears, an island
reappears.

## Related

- MOC: [index.md](index.md).
- Journal: [2026-06-09-journal-construcao-wiki.md](2026-06-09-journal-construcao-wiki.md).
- Coverage: [cobertura-metodologia-v5.md](../cobertura-metodologia-v5.md).
