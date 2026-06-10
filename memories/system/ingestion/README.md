---
page_id: system-ingestion-readme
page_type: source_catalog
title: "Ingestion - proposals"
aliases:
  - Ingestion
tags:
  - wiki/ingestion
  - status/active
status: active
context: system
visibility: private_self
updated_at: 2026-06-09
stale_after_days: 90
sources_policy: propostas_de_ingestao
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
purpose: "Directory of ingestion proposals (one per source), with gate_state and normalized events."
moc_parent: memories/index.md
related_pages:
  - memories/system/ingestion-process.md
  - memories/system/ingestion/events/README.md
---

# Ingestion - proposals

Updated at: 2026-06-09.

Each ingestion proposal is born from [scripts/wiki_new_ingest.py](../../../scripts/wiki_new_ingest.py)
or from the orchestrator [scripts/wiki_ingest.py](../../../scripts/wiki_ingest.py), with
`gate_state: created` and one `rebase_key` per logical target. Normalized events
live in [events/](events/README.md).

## States of a proposal

A proposal is born `created` and advances through review toward `approved` and
`published`; when two proposals compete for the same logical target, the rebase keeps
the most recent one and marks the rest `superseded`. The full state machine is in
[gates-and-audit.md](../wiki/gates-and-audit.md).

```mermaid
stateDiagram-v2
    [*] --> created
    created --> review
    review --> approved
    review --> superseded
    approved --> published
    review --> rejected
    published --> [*]
```

The auditor requires a valid `gate_state` on every proposal in this directory.

## Related

- Process: [ingestion-process.md](../ingestion-process.md).
- Events: [events/README.md](events/README.md).
