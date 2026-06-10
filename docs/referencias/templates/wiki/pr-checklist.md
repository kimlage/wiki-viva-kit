---
page_id: template-pr-checklist-wiki
page_type: operational_template
title: "Wiki PR checklist"
aliases:
  - Wiki PR checklist
  - Wiki review
tags:
  - wiki/template
  - wiki/pr
  - status/template
status: template
context: sistema
visibility: private_reference
updated_at: YYYY-MM-DD
stale_after_days: 90
sources_policy: contrato_wiki_operacional
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
owner: {{owner_id}}
moc_parent: docs/referencias/templates/wiki/obsidian-conventions.md
related_pages:
  - docs/referencias/templates/wiki/page-contract.md
  - docs/referencias/templates/wiki/obsidian-conventions.md
---

# Template - wiki PR checklist

## Objective

-

## Sources consulted

-

## Pages changed

-

## Privacy risks

-

## Validations

- [ ] `python3 scripts/wiki_audit.py --check`  Links: [scripts/wiki_audit.py](../../../../scripts/wiki_audit.py).
- [ ] `python3 scripts/wiki_new_ingest.py --source data/raw/exemplo.pdf --context sistema --dry-run`  Links: [scripts/wiki_new_ingest.py](../../../../scripts/wiki_new_ingest.py).
- [ ] `python3 scripts/wiki_pr_summary.py`  Links: [scripts/wiki_pr_summary.py](../../../../scripts/wiki_pr_summary.py).
- [ ] `rg -n "docs/2026|docs/memorias" AGENTS.md memorias docs scripts .skills`  Links: [AGENTS.md](../../../../AGENTS.md), historical path: [docs/2026](../../../).
- [ ] `git diff --check`

## Approval

- [ ] [memorias/](../../../../memorias/) contains an actionable synthesis.
- [ ] [docs/](../../../) did not become the primary memory.
- [ ] Relevant personal data (names, values, dates, relationships, documents) was extracted when useful -- private repo, no warning.
- [ ] No full dump without criteria was copied into Markdown.
- [ ] No token, cookie, password, access code, credential or individualized secure link was copied (anywhere).
- [ ] [memorias/sistema/log.md](../../../../memorias/sistema/log.md) was updated.
- [ ] Local paths in the diff are real Markdown links.
- [ ] New pages declare aliases, tags, `status`, parent MOC and related pages.

## Related

- Obsidian conventions: [obsidian-conventions.md](obsidian-conventions.md)
- Page contract: [page-contract.md](page-contract.md)
