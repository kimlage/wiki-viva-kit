---
name: wiki-viva
description: Single entry skill to set up AND operate a Markdown/Git living operational wiki (the "wiki viva kit") — configure wiki.config.yaml, scaffold or adopt the tree, ingest sources through the deterministic pipeline, run the delegated LLM deep read, keep the honesty gates green, compile the daily cockpit, and ship changes through the PR gate. Install this one skill to adopt and run the whole system; it points to the deeper per-step playbooks when you need them.
---

# Wiki Viva — set up and operate the living wiki

Use this skill whenever you work in a repo that uses (or should use) the **wiki
viva kit**: a living operational wiki in Markdown/Git with a deterministic
Python core, honesty gates in CI, and the deep reading (LLM) delegated to *you*,
the agent running the repo — there is no LLM client in the toolkit.

This is the **single entry point**. It covers the whole lifecycle — adopt →
configure → ingest → deep read → consolidate → cockpit → gates → PR — and links
to the focused playbooks and the meta-wiki for depth. You do not need any other
skill installed to operate; the others ([listed below](#deeper-references)) are
optional detail.

## The model in one picture

```mermaid
flowchart LR
    src["Source (file / URL)"] --> man["Deterministic manifest"]
    man --> chunks["Stable chunks"]
    chunks --> idx["FTS index"]
    idx --> scan["Secret pre-scan"]
    scan -->|secret found| stop["Blocked at origin"]
    scan -->|clean| pkg["LLM context package"]
    pkg -.delegated deep read.-> agent["Agent (you)"]
    agent --> result["Recorded result (cache)"]
    result --> ev["Normalized event"]
    ev --> prop["Ingestion proposal"]
    prop --> gate["PR gate (human)"]
    gate --> mem["Consolidated memory"]
```

Everything left of the dashed arrow is deterministic Python you can re-run for
free. The deep read is the only model step, and it is yours.

## How to start, every session

1. Confirm the repo root and read [wiki.config.yaml](../../wiki.config.yaml):
   `language`, `contexts`, `paths` (English defaults, or a localized layout
   pinned per repo), the privacy policy and the gates.
2. Read the root MOC [memories/index.md](../../memories/index.md), then the
   cockpit [memories/operations.md](../../memories/operations.md) if present.
3. The wiki **documents itself**: the meta-wiki at
   [memories/system/wiki/index.md](../../memories/system/wiki/index.md) is the
   official documentation, kept honest by the same gates. Read it when you need
   the *why*, not just the *how*.
4. Pick the lifecycle step you are in (below) and open the matching reference.

## Lifecycle

| Step | What you do | Reference |
| --- | --- | --- |
| **Adopt / configure** | Copy the kit into a repo, set `wiki.config.yaml` + `wiki.targets.yaml`, declare contexts, choose English defaults or pin a localized layout | [reference/setup.md](reference/setup.md) |
| **Ingest** | Turn a source into manifest → chunks → index → pre-scan → context package → event → proposal | [reference/operating.md](reference/operating.md) |
| **Deep read** | Perform the delegated LLM pass over the emitted package and record the result | [reference/operating.md](reference/operating.md) + [wiki-llm-context-agent](../wiki-llm-context-agent/SKILL.md) |
| **Consolidate** | Move the proposal through the gate, open the PR (the human gate) | [reference/operating.md](reference/operating.md) |
| **Cockpit + gates** | Recompile the cockpit and run the honesty gates before the PR | [reference/gates-and-privacy.md](reference/gates-and-privacy.md) |

## Rich representation is the default

Pages and architectures **illustrate by default** — Markdown tables for any
enumerated structured facts, and Mermaid diagrams for structure and flow
(`flowchart` for pipelines/architecture, `stateDiagram-v2` for the gate,
`sequenceDiagram` for agent↔human exchanges, `er`/`classDiagram` for the
ontology, `mindmap`/`flowchart` for a map of contents, `timeline` for history).
Prose carries nuance; it does not carry structure that a table or a diagram
shows better. Architecture, flow, relationship and process pages should each
carry at least one diagram. The page conventions live in
[docs/references/templates/wiki/obsidian-conventions.md](../../docs/references/templates/wiki/obsidian-conventions.md);
the templates ship the skeletons.

## Hard rules (never break these)

- **Determinism stays in the toolkit, intelligence stays in you.** Never add an
  LLM client to the Python. The pipeline emits a context package; you read and
  record the result.
- **Access secrets are blocked everywhere.** Tokens, passwords, keys, cookies
  never get versioned. The pre-scan blocks at the origin (exit `2`).
- **Privacy by boundary.** Personal data (PII) is welcome on private pages and
  raises no warning; it only blocks at the public boundary (`--public-export`).
- **Canonical memory changes go through a `wiki/<theme>` branch and a PR.** Never
  hand-edit the generated cockpit [memories/operations.md](../../memories/operations.md) —
  recompile it.
- **Gates must be green before the PR**, and stay deterministic (zero tokens).

## Deeper references

The kit ships focused playbooks; this skill orchestrates them. Reach for one
when you need the full procedure for a single step:

- [wiki-memory-router](../wiki-memory-router/SKILL.md) — load the wiki and route context.
- [wiki-ingestion-agent](../wiki-ingestion-agent/SKILL.md) — source → event → proposal.
- [wiki-llm-context-agent](../wiki-llm-context-agent/SKILL.md) — the delegated LLM pass.
- [wiki-operation-compiler](../wiki-operation-compiler/SKILL.md) — the daily cockpit.
- [wiki-source-auditor](../wiki-source-auditor/SKILL.md) — source traceability.
- [wiki-privacy-publication](../wiki-privacy-publication/SKILL.md) — private vs public.
- [wiki-raw-drive](../wiki-raw-drive/SKILL.md) — raw sources from a single Drive folder (never versioned).

Agent-facing entry point for the repo: [AGENTS.md](../../AGENTS.md). Full CLI
catalog: [command reference](../../memories/system/wiki/command-reference.md).
