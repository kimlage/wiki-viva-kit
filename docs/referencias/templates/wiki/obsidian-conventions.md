---
page_id: template-obsidian-conventions
page_type: reference_template
title: "Obsidian conventions for the living wiki"
aliases:
  - Obsidian conventions
  - Obsidian LLM Wiki
  - Dataview living wiki
tags:
  - wiki/template
  - wiki/obsidian
  - wiki/metodologia
  - status/template
status: template
context: sistema
visibility: private_reference
updated_at: YYYY-MM-DD
stale_after_days: 180
sources_policy: contrato_wiki_e_llm_wiki
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
owner: {{owner_id}}
moc_parent: memorias/index.md
related_pages:
  - docs/referencias/templates/wiki/page-contract.md
  - docs/referencias/templates/wiki/operacao.md
  - docs/referencias/templates/wiki/ingestao-proposta.md
source_counts:
  live_sources: 0
  references: 1
  derived_artifacts: 0
---

# Obsidian conventions for the living wiki

This template documents the Obsidian-portable layer of the wiki. The repository must
remain readable in any Markdown editor; Obsidian, the graph, and Dataview are
optional accelerators.

## Minimal frontmatter

```yaml
---
page_id: contexto-slug-estavel
page_type: context_hub
title: "Human title"
aliases:
  - Short name
  - Name used in wikilink
tags:
  - wiki/contexto
  - contexto/sistema
  - status/active
status: active
context: sistema
visibility: private_self
owner: {{owner_id}}
updated_at: YYYY-MM-DD
stale_after_days: 30
moc_parent: memorias/index.md
related_pages: []
backlinks_expected: []
source_counts:
  live_sources: 0
  references: 0
  derived_artifacts: 0
attachment_policy: "Attachments go in data/raw, data/derived, or docs/referencias with a Markdown link."
---
```

## MOCs and indexes

- A MOC is a map-of-content page, usually with `page_type:
  root_index`, `context_hub`, or `moc`.
- [memorias/index.md](../../../../memorias/index.md) is the root MOC of the memory.
- [memorias/operacao.md](../../../../memorias/operacao.md) is the MOC for daily
  operational resumption.
- Each context must point to its parent MOC in `moc_parent` and list sibling or
  dependent pages in `related_pages`.
- The `## Related` section must repeat these links in Markdown for humans,
  PR review, and auditing.

## Aliases and wikilinks

- `aliases` must contain short human names, acronyms, and likely search names.
- Wikilinks may point to aliases, but do not replace real Markdown links.
- When citing a local file, always use a clickable Markdown link, for example
  [page-contract.md](page-contract.md).
- If a wikilink helps the graph, it may appear alongside the Markdown link, but
  the Markdown link remains the auditable source.

## Tags for Dataview

Recommended tags:

- `wiki/metodologia`, `wiki/template`, `wiki/fonte`, `wiki/operacao`;
- `contexto/sistema`, `contexto/financeiro`, `contexto/empresas`;
- `status/active`, `status/proposta`, `status/template`, `status/stale`;
- `visibility/private-self`, `visibility/private-reference` when useful.

Dataview can query `status`, `context`, `updated_at`, `stale_after_days`,
`owner`, `moc_parent`, `source_counts`, and `related_pages`, but no page should
depend on a Dataview query to be understandable.

## Attachments

- Raw sources go in [data/raw](../../../../data/raw) when they are a local
  cache, or in the declared external live source.
- Derivatives, OCR, chunks, indexes, and caches go in
  [data/derived](../../../../data/derived).
- Immutable references and templates go in [docs/referencias/](../).
- The page must link the attachment or artifact, record its origin, and declare its limits.
- Never attach tokens, cookies, passwords, access codes, credentials, or
  individualized secure links.

## Safe format for Obsidian

- Use simple YAML, explicit lists, and strings without proprietary syntax.
- Avoid very wide tables when a list is more reviewable in a diff.
- Keep headings stable for backlinks and anchors.
- Do not use HTML, proprietary embeds, or plugins as a requirement.
- Prefer kebab-case file names and a `page_id` that is even more stable than the
  current path.
