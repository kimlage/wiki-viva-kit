---
page_id: sistema-revisao-docs
page_type: operational_rule
context: sistema
visibility: private_self
updated_at: 2026-06-09
stale_after_days: 180
sources_policy: fronteira_docs_memoria
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
---

# Review of the docs vs. memory boundary

Updated on: 2026-06-09.

Maintains the separation between consolidated memory ([memorias/](../)) and
reference material ([docs/](../../docs/)).

## Rule

- [memorias/](../) is the primary memory: actionable synthesis, decisions, rules, and context.
- [docs/referencias/](../../docs/referencias/) holds templates, snapshots, and reference
  material — it is not the primary memory and must not duplicate the memory.
- When a reference material becomes operational knowledge, synthesize it into the
  memory and keep the original linked.

## Review checklist

- [ ] No page in [docs/](../../docs/) is being used as primary memory.
- [ ] Every cited local path is a clickable Markdown link.
- [ ] New pages declare complete frontmatter (see
  [page-contract.md](../../docs/referencias/templates/wiki/page-contract.md)).

## Related

- Contract: [contrato-wiki-operacional.md](contrato-wiki-operacional.md).
