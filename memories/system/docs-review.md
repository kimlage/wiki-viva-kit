---
page_id: system-docs-review
page_type: operational_rule
context: system
visibility: private_self
updated_at: 2026-06-09
stale_after_days: 180
sources_policy: fronteira_docs_memoria
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
---

# Review of the docs vs. memory boundary

Updated on: 2026-06-09.

Maintains the separation between consolidated memory ([memories/](../index.md)) and
reference material ([docs/](../../docs/README.md)).

## Rule

- [memories/](../index.md) is the primary memory: actionable synthesis, decisions, rules, and context.
- [docs/references/](../../docs/references/README.md) holds templates, snapshots, and reference
  material — it is not the primary memory and must not duplicate the memory.
- When a reference material becomes operational knowledge, synthesize it into the
  memory and keep the original linked.

## Review checklist

- [ ] No page in [docs/](../../docs/README.md) is being used as primary memory.
- [ ] Every cited local path is a clickable Markdown link.
- [ ] New pages declare complete frontmatter (see
  [page-contract.md](../../docs/references/templates/wiki/page-contract.md)).

## Related

- Contract: [operational-wiki-contract.md](operational-wiki-contract.md).
