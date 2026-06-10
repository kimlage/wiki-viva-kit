---
page_id: exemplo-index
page_type: source_catalog
title: "Example context - hub"
aliases:
  - Example
tags:
  - wiki/contexto
  - status/active
status: active
context: exemplo
visibility: private_self
updated_at: 2026-06-09
stale_after_days: 30
sources_policy: fontes_vivas_e_propostas
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
purpose: "Hub of the example context: demonstrates how a memory context is organized in the kit."
moc_parent: memorias/index.md
related_pages:
  - memorias/index.md
  - memorias/sistema/processo-ingestao.md
---

# Example context - hub

Updated on: 2026-06-09.

This is a demonstration context. Each repo that adopts the kit declares its
contexts in [wiki.config.yaml](../../wiki.config.yaml) (`contexts:`) and creates a context
hub like this one (one index page per context, in [memorias/](../)).

## What lives here

- Consolidated synthesis of the context (not just links to sources).
- Decisions, actions, and sources tied to the context.
- Relevant personal data may be included (private repo); secrets never.

## Related

- Root MOC: [memorias/index.md](../index.md).
- Ingestion process: [processo-ingestao.md](../sistema/processo-ingestao.md).
