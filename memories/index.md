---
page_id: memories-index
page_type: source_catalog
title: "Memory - root MOC"
aliases:
  - Memory
  - General index
tags:
  - wiki/moc
  - status/active
status: active
context: system
visibility: private_self
updated_at: 2026-06-09
stale_after_days: 30
sources_policy: memoria_consolidada
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
purpose: "Root content map of the wiki: entry point to contexts and to the method."
related_pages:
  - memories/operations.md
  - memories/system/ingestion-process.md
---

# Memory - root MOC

Updated at: 2026-06-09.

[memories/](.) is the main consolidated memory. [docs/](../docs/) holds
references, templates, and snapshots; [data/raw](../data/raw) and
[data/derived](../data/derived) are cache (gitignored).

## Memory policy

- `main` is the approved wiki. `wiki/*` branches are live proposals; the PR is the
  human gate.
- On private pages, memory may record personal data (PII) when useful; access
  secrets never go anywhere.
- Every local reference to a file inside the repo must be a clickable Markdown link.

## Summary

- Meta-wiki (how the wiki works): [system/wiki/index.md](system/wiki/index.md).
- Cockpit: [operations.md](operations.md).
- Ingestion process: [system/ingestion-process.md](system/ingestion-process.md).
- Wiki contract: [system/operational-wiki-contract.md](system/operational-wiki-contract.md).
- Change log: [system/log.md](system/log.md).
- Method coverage: [system/methodology-coverage-v5.md](system/methodology-coverage-v5.md).

## Contexts

- [example/index.md](example/index.md) — demonstration context.

## Sources and perception

- Methodology (source): [sources/wiki-viva-methodology-v5.md](sources/wiki-viva-methodology-v5.md).
- Perceptive layer: [system/perception/index.md](system/perception/index.md).
