# Template - ingestion proposal

```yaml
---
page_id: ingestao-YYYY-MM-DD-tema
page_type: source_catalog
title: "Ingestion proposal - topic"
aliases:
  - Ingestion topic
  - Proposal topic
tags:
  - wiki/ingestao
  - wiki/proposta
  - status/draft
status: draft
context: sistema
visibility: private_self
updated_at: YYYY-MM-DD
stale_after_days: 30
sources_policy: proposta_privada_com_links_reais
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
status: draft
manifest_ref:
event_ref:
llm_context_status: pending | cached | justified_skip
owner: {{owner_id}}
moc_parent: memorias/sistema/ingestao/
related_pages: []
backlinks_expected: []
source_counts:
  live_sources: 0
  references: 0
  derived_artifacts: 0
attachment_policy: "Link attachments and derived files via Markdown; do not embed dumps."
---
```

# Ingestion proposal - topic

## Consulted source

- Use a real link to the original source whenever it is linkable.
- For a local source within the repo, use a Markdown link with a real relative target.
- For a private source outside Markdown: link the secure original or the canonical
  directory and extract the content needed for operational memory.
- Do not copy tokens, cookies, passwords, access codes, credentials, individualized
  secure links, or indiscriminate dumps.

## Target context

-

## Classification

- Type: `memory` | `reference` | `artifact` | `raw` | `no_ingest`
- Epistemological status: `fato` | `percepcao` | `hipotese` | `insight` | `proposta` | `decisao`

## Normalized event

- Event:
- Manifest:
- Text/chunks:
- Contextual LLM passage:

## Quadrants

| Quadrant | Extracted content | Absence/limit |
| --- | --- | --- |
| Interior individual |  |  |
| Exterior individual |  |  |
| Interior collective |  |  |
| Exterior collective |  |  |

## Proposed synthesis

-

## Impacted pages

- Use real Markdown links for each impacted page.

## Related

- MOC:
- Event:
- Source:
- Related pages:
- Expected backlinks:

## Privacy risks

-

## Recommended decision

-

## Checklist

- [ ] Extracted relevant personal data (names, values, dates, CPF/CNPJ, counterparties) when useful -- private repo, no warning.
- [ ] Did not copy a full dump without criteria.
- [ ] Did not copy a token, cookie, password, access code, credential, or individualized secure link.
- [ ] Indicated source and context.
- [ ] Indicated impacted pages.
- [ ] Local paths were written as clickable Markdown links.
- [ ] Indicated PR gate.
- [ ] Filled in the quadrants or made the absence explicit.
- [ ] Indicated the manifest, chunks, and contextual LLM passage or a justification.
- [ ] Filled in aliases, tags, parent MOC, and related pages for Obsidian/Dataview.
