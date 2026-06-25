---
page_id: system-wiki-relationship-map
page_type: relationship_map
title: "Relationship map - living wiki system"
aliases:
  - Living wiki map
  - System relationships
tags:
  - wiki/perception
  - wiki/map
  - status/active
status: active
context: system
visibility: private_self
updated_at: 2026-06-09
stale_after_days: 60
sources_policy: derivado_da_arquitetura_real
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
status_epistemologico: percepcao
purpose: "Map how the real system modules connect, to see the organism (not islands) at a glance."
moc_parent: memories/system/perception/index.md
related_pages:
  - memories/system/perception/2026-06-09-wiki-construction-journal.md
  - memories/system/methodology-coverage-v5.md
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
> not a contract. The source of truth for the modules is the code in [wiki_core/](../../../wiki_core/README.md)
> and [scripts/](../../../scripts/README.md).

## Plain-language summary

A text diagram of how the system pieces connect: ingestion pulls the source,
generates artifacts, triggers the privacy pre-scan, assembles the package for the
reading agent, and feeds the scoreboard and the cockpit. The gate by PR sits in
the middle, watching.

## Diagram (graph, accessible)

The graph below uses friendly labels and is readable as source text on GitHub; the
plain-language summary above and the edge table below carry the same relations
without relying on the rendered shapes or any color.

```mermaid
flowchart TD
    Source["Source (raw data, Drive)"]
    Orchestrator["Ingestion orchestrator"]
    Prescan["Pre-scan: secret blocks, PII informs"]
    Package["LLM context package"]
    Score["Score event (8-dimension karma)"]
    Agent(["Repo agent: reads and writes the result"])
    Auditor["Auditor: honesty gate"]
    Cockpit["Cockpit"]
    PRGate{"PR gate on GitHub"}
    Memory[("Canonical memory")]

    Source --> Orchestrator
    Orchestrator --> Prescan
    Orchestrator --> Package
    Orchestrator --> Score
    Package --> Agent
    Agent --> Auditor
    Prescan --> Auditor
    Score --> Cockpit
    Auditor --> PRGate
    PRGate --> Memory
```

## Main edges (origin -> target : relationship)

| Origin | Target | Relationship |
| --- | --- | --- |
| orchestrator | detectors | privacy pre-scan at capture (secret blocks) |
| orchestrator | LLM package | emits the `-request.json` that the auditor watches |
| orchestrator | score | records `ingestar_fonte_valida` (karma) |
| LLM package | repo agent | deep reading delegated (no LLM in Python) |
| agent | cache | writes the result; closes the `required_context_pass` gate |
| score | cockpit | the cockpit displays karma per dimension |
| auditor | PR gate | blocks the merge while there is a pending pass or secret |
| PR gate | canonical memory | only after human review does the proposal become memory |

## Perceptive reading

The drawing makes clear what was previously invisible: no module is an island.
Ingestion is the axis; privacy and scoreboard are by-products of the same pass; the
gate by PR is the valve that keeps honesty. Wherever an arrow disappears, an island
reappears.

## Related

- MOC: [index.md](index.md).
- Journal: [2026-06-09-wiki-construction-journal.md](2026-06-09-wiki-construction-journal.md).
- Coverage: [methodology-coverage-v5.md](../methodology-coverage-v5.md).
