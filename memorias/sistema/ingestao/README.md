---
page_id: sistema-ingestao-readme
page_type: source_catalog
title: "Ingestion - proposals"
aliases:
  - Ingestion
tags:
  - wiki/ingestao
  - status/active
status: active
context: sistema
visibility: private_self
updated_at: 2026-06-09
stale_after_days: 90
sources_policy: propostas_de_ingestao
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
purpose: "Directory of ingestion proposals (one per source), with gate_state and normalized events."
moc_parent: memorias/index.md
related_pages:
  - memorias/sistema/processo-ingestao.md
  - memorias/sistema/ingestao/eventos/README.md
---

# Ingestion - proposals

Updated at: 2026-06-09.

Each ingestion proposal is born from [scripts/wiki_new_ingest.py](../../../scripts/wiki_new_ingest.py)
or from the orchestrator [scripts/wiki_ingest.py](../../../scripts/wiki_ingest.py), with
`gate_state: created` and one `rebase_key` per logical target. Normalized events
live in [eventos/](eventos/README.md).

## States of a proposal

- `created` -> under review -> `approved` or `superseded` (rebase by logical target).
- The auditor requires a valid `gate_state` on every proposal in this directory.

## Related

- Process: [processo-ingestao.md](../processo-ingestao.md).
- Events: [eventos/README.md](eventos/README.md).
