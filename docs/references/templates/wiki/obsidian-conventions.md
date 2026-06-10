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
  - wiki/methodology
  - status/template
status: template
context: system
visibility: private_reference
updated_at: YYYY-MM-DD
stale_after_days: 180
sources_policy: contrato_wiki_e_llm_wiki
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
owner: {{owner_id}}
moc_parent: memories/index.md
related_pages:
  - docs/references/templates/wiki/page-contract.md
  - docs/references/templates/wiki/operation.md
  - docs/references/templates/wiki/ingestion-proposal.md
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
page_id: context-stable-slug
page_type: context_hub
title: "Human title"
aliases:
  - Short name
  - Name used in wikilink
tags:
  - wiki/context
  - context/system
  - status/active
status: active
context: system
visibility: private_self
owner: {{owner_id}}
updated_at: YYYY-MM-DD
stale_after_days: 30
moc_parent: memories/index.md
related_pages: []
backlinks_expected: []
source_counts:
  live_sources: 0
  references: 0
  derived_artifacts: 0
attachment_policy: "Attachments go in data/raw, data/derived, or docs/references with a Markdown link."
---
```

## MOCs and indexes

- A MOC is a map-of-content page, usually with `page_type:
  root_index`, `context_hub`, or `moc`.
- [memories/index.md](../../../../memories/index.md) is the root MOC of the memory.
- [memories/operations.md](../../../../memories/operations.md) is the MOC for daily
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
- **Bring information WITH links.** A title, person, source, decision, or tool
  named in the body must become a link to its page — information without a link
  is a defect (an orphan title). The auditor WARNS when a known entity is named
  without a link (`wiki_audit.py`, warning level).
- **A person mention becomes a link** to that person's page (contacts/perspective).

## Single purpose and rules on a separate page

- Each page has **one purpose**. Heavy ingestion, search, and business rules do
  NOT go inline on the content page: they go to a separate config page, linked
  from frontmatter via `config_ref:`. That keeps the content page lean and the
  config versioned and linkable on its own.
- Example: a source page points `config_ref:` at its rules page; the
  [source registry](../../../../memories/system/source-registry.md) indexes the
  sources with state and last update.

## Tags for Dataview

Recommended tags:

- `wiki/methodology`, `wiki/template`, `wiki/source`, `wiki/operations`;
- `context/system`, `context/finance`, `context/companies`;
- `status/active`, `status/proposal`, `status/template`, `status/stale`;
- `visibility/private-self`, `visibility/private-reference` when useful.

Dataview can query `status`, `context`, `updated_at`, `stale_after_days`,
`owner`, `moc_parent`, `source_counts`, and `related_pages`, but no page should
depend on a Dataview query to be understandable.

## Attachments

- Raw sources go in [data/raw](../../../../data/raw) when they are a local
  cache, or in the declared external live source.
- Derivatives, OCR, chunks, indexes, and caches go in
  [data/derived](../../../../data/derived).
- Immutable references and templates go in [docs/references/](../).
- The page must link the attachment or artifact, record its origin, and declare its limits.
- Never attach tokens, cookies, passwords, access codes, credentials, or
  individualized secure links.

## Rich representation by default (diagrams + tables)

A living wiki page is not a wall of prose. By **default**, pages SHOULD illustrate
their content with **Mermaid diagrams** and **Markdown tables**, and keep prose for
nuance, caveats, and the "why". Rich representation is the norm, not an optional
afterthought: reviewers and agents read structure faster than paragraphs, and the
same structure survives in any Markdown editor (GitHub renders fenced `mermaid`
code blocks natively; tables are plain Markdown).

**When a page MUST carry at least one diagram.** Any page whose job is to explain
an architecture, a flow/pipeline, a relationship between entities, or a process
MUST include at least one Mermaid diagram. Pages that only enumerate facts may use
a table instead, but a diagram is encouraged whenever there is structure to show.

**Which diagram for what** — pick the type that fits the thing you are explaining:

| You are documenting | Use | Mermaid type |
| --- | --- | --- |
| A pipeline or an architecture / module map | Flowchart | `flowchart LR` or `flowchart TD` |
| A gate, lifecycle, or status machine | State diagram | `stateDiagram-v2` |
| An exchange between agent, toolkit and human | Sequence diagram | `sequenceDiagram` |
| The page / entity ontology or relationships | Entity / class diagram | `erDiagram` or `classDiagram` |
| A map of contents (MOC) or a topic map | Mindmap or flowchart | `mindmap` or `flowchart` |
| A history or a timeline | Timeline | `timeline` or `gantt` |

**Tables for enumerated structured facts.** Whenever a page lists things with the
same shape — modules, gates, states, costs, CLI commands, the eight karma
dimensions, the four quadrants — present them as a Markdown table, not a bullet
list. A table makes columns (id, purpose, owner, gate) scannable and diff-friendly.
Reserve bullet lists for short, unstructured notes.

**Prose stays for nuance.** Diagrams and tables carry the structure; prose carries
the reasoning, the exceptions, and anything a box-and-arrow cannot say. Use all
three together.

**Diagram authoring rules** (so diagrams pass the audit and render everywhere):

- Keep each diagram readable: roughly under a dozen nodes; split a large picture
  into two focused diagrams instead of one dense one.
- Node **labels** must be plain, friendly text. Never put a repo path (such as a
  `*.md` file path) inside a node label — refer to pages in the surrounding prose
  as normal Markdown links instead. The contract auditor flags raw local paths,
  and a path buried in a label is unreviewable.
- Quote any label that contains spaces or punctuation, for example
  `A["LLM context package"]`.
- Do not use HTML inside diagrams; keep every Mermaid code fence balanced.
- Keep an ASCII diagram only when Mermaid genuinely cannot express it; the default
  is to replace ASCII art with a Mermaid diagram.

## Safe format for Obsidian

- Use simple YAML, explicit lists, and strings without proprietary syntax.
- Prefer a Markdown table over a list for any enumeration of structured facts; keep
  bullet lists for short, unstructured notes (see *Rich representation by default*).
- Keep headings stable for backlinks and anchors.
- Mermaid diagrams and Markdown tables are portable Markdown and the preferred way
  to illustrate; HTML, proprietary embeds, and plugins are never a requirement.
- Prefer kebab-case file names and a `page_id` that is even more stable than the
  current path.
