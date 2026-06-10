---
page_id: memorias-index
page_type: source_catalog
title: "Memory - root MOC"
aliases:
  - Memory
  - General index
tags:
  - wiki/moc
  - status/active
status: active
context: sistema
visibility: private_self
updated_at: 2026-06-09
stale_after_days: 30
sources_policy: memoria_consolidada
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
purpose: "Root content map of the wiki: entry point to contexts and to the method."
related_pages:
  - memorias/operacao.md
  - memorias/sistema/processo-ingestao.md
---

# Memory - root MOC

Updated at: 2026-06-09.

[memorias/](.) is the main consolidated memory. [docs/](../docs/) holds
references, templates, and snapshots; [data/raw](../data/raw) and
[data/derived](../data/derived) are cache (gitignored).

## Memory policy

- `main` is the approved wiki. `wiki/*` branches are live proposals; the PR is the
  human gate.
- On private pages, memory may record personal data (PII) when useful; access
  secrets never go anywhere.
- Every local reference to a file inside the repo must be a clickable Markdown link.

## Resume

- Meta-wiki (how the wiki works): [sistema/wiki/index.md](sistema/wiki/index.md).
- Cockpit: [operacao.md](operacao.md).
- Ingestion process: [sistema/processo-ingestao.md](sistema/processo-ingestao.md).
- Wiki contract: [sistema/contrato-wiki-operacional.md](sistema/contrato-wiki-operacional.md).
- Change log: [sistema/log.md](sistema/log.md).
- Method coverage: [sistema/cobertura-metodologia-v5.md](sistema/cobertura-metodologia-v5.md).

## Contexts

- [exemplo/index.md](exemplo/index.md) — demonstration context.

## Sources and perception

- Methodology (source): [fontes/metodologia-wiki-viva-v5.md](fontes/metodologia-wiki-viva-v5.md).
- Perceptive layer: [sistema/percepcao/index.md](sistema/percepcao/index.md).
