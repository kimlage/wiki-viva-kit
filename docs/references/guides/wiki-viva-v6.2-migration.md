---
title: "Wiki Viva v6.2 migration guide"
page_id: guide-wiki-viva-v6-2-migration
page_type: reference_guide
context: system
visibility: private_self
updated_at: 2026-06-12
stale_after_days: 90
sources_policy: migration_guide
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
---

# Wiki Viva v6.2 migration guide

This guide is for an existing living wiki that already has Markdown pages and is
adopting the v6.2 graph, page-type, perspective and impact gates.

The migration is intentionally review-first. The kit can inventory legacy pages
and suggest frontmatter, but it should not rewrite personal or operational
memory without a human-reviewed PR.

## Migration order

| Phase | Goal | Exit criteria |
| --- | --- | --- |
| 1. Freeze a branch | Keep the migration reviewable | Work happens on a `wiki/<topic>` branch and existing unrelated edits are isolated. |
| 2. Inventory legacy pages | Know what must be migrated | [wiki_migration_inventory.py](../../../scripts/wiki_migration_inventory.py) lists pages missing frontmatter. |
| 3. Add minimum frontmatter | Bring pages under the v6.2 contract | Every memory page has `page_id`, `page_type`, `context`, `visibility`, `updated_at`, `stale_after_days` and gate metadata. |
| 4. Register page types | Avoid undeclared shapes | [wiki.page-types.yaml](../../../wiki.page-types.yaml) declares every used `page_type`. |
| 5. Connect the graph | Make memory navigable | [wiki_page_graph.py](../../../scripts/wiki_page_graph.py) reports zero errors, and outbound-link warnings are triaged with body links or frontmatter refs such as `moc_parent` and `related_pages`. |
| 6. Close local artifacts | Keep clones and GitHub readable | Non-versioned artifacts are published with [wiki_drive_publish.py](../../../scripts/wiki_drive_publish.py) or replaced with stable external links. |
| 7. Close ingestion impact | Make ingestion mean integration | Events with `affected_pages.must_update` also close `impact_closure`. |
| 8. Validate and PR | Let the owner review the migration | `wiki_audit.py --check`, `wiki_page_graph.py --check --impact`, `wiki_pr_summary.py` and `git diff --check` pass. |

## Inventory command

Run this first:

```sh
python3 scripts/wiki_migration_inventory.py
```

To include suggested frontmatter blocks:

```sh
python3 scripts/wiki_migration_inventory.py --show-frontmatter
```

The suggestions are conservative. They infer context from the configured memory
root and contexts in [wiki.config.yaml](../../../wiki.config.yaml), then infer a
page type from semantic directory names, operational date-like filenames, or a
`context_note` fallback. Treat the output as a draft for review, not as an
automatic migration.

## What to migrate manually

- Choose a precise `page_type` when the fallback is too generic.
- Add `source_refs`, `claims`, `decisions`, `actions` or `related_pages` when
  they make the page more traceable.
- Add one to three real graph references from each operational page to a hub,
  source, rule or related page. Use Markdown body links when the relation is
  useful to readers, or frontmatter refs like `moc_parent`/`related_pages` when
  the relation is structural.
- Review date-only filenames manually. A page like `2026-06-05-sync.md` may be
  a monthly or operational closing, while `2026-auvp-fila.md` is usually an
  artifact or runbook, not a monthly closing.
- Keep private PII on private pages when it is operationally useful.
- Never add access secrets, cookies, tokens, passwords or individualized secure
  links.

## Recommended PR split

For small wikis, one PR is fine. For larger personal or operational wikis, use
two PRs:

1. **Contract migration:** frontmatter, page types and graph errors.
2. **Semantic cleanup:** entity links, local artifacts, source references and
   stale event closure.

This keeps the mechanical part easy to review and avoids hiding semantic changes
inside frontmatter churn.

## Validation commands

```sh
python3 scripts/wiki_migration_inventory.py
python3 scripts/wiki_audit.py --check
python3 scripts/wiki_page_graph.py --check --impact
python3 scripts/wiki_pr_summary.py
git diff --check
```

If a repo has localized paths, do not rename files just to match the kit's
English defaults. Pin the localized layout in [wiki.config.yaml](../../../wiki.config.yaml)
and let the tools read `paths.*`.
