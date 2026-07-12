---
title: "Canonical entity navigation"
page_id: guide-canonical-entity-navigation
page_type: reference_guide
context: system
visibility: private_self
updated_at: 2026-06-12
stale_after_days: 90
sources_policy: navigation_guide
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
---

# Canonical entity navigation

Use this guide when an ingestion creates or touches people, organizations,
projects, sources, claims or decisions. The goal is simple: one real entity gets
one canonical page, and every other page links to it.

## Rules

- Pick the canonical page before adding links. Prefer the page already used by
  meetings, sources and index pages; otherwise prefer the clearest stable slug.
- Put stable names in `title:` and `aliases:` on the canonical page. Use aliases
  for spelling variants, short names and public/private naming differences.
- Do not create a second page just because the source used a fuller name. Merge
  the new evidence into the existing page and add the fuller name as an alias
  only when the source supports it.
- If a duplicated page already exists, merge useful content into the canonical
  page, update inbound links, then remove the duplicate page in the same PR.
- If a name is uncertain, keep the conservative canonical name and record the
  uncertainty in the page body. Do not promote an unverified surname or legal
  name into the index.
- Link human-readable labels to the canonical page. Avoid path-shaped labels in
  prose unless the point of the sentence is the file path itself.

## Validation

Run the normal gates after a merge:

```sh
BASE_SHA="<reviewed-base-commit-sha>"
python3 scripts/wiki_audit.py --check
python3 scripts/wiki_page_graph.py --check --impact --base "$BASE_SHA"
python3 scripts/wiki_quality_report.py --check
python3 scripts/wiki_pr_summary.py
git diff --check
```

Replace the placeholder with the exact reviewed commit SHA. Impact mode does
not infer an upstream branch: it requires the resolved base to be an ancestor
of `HEAD`, fails closed on Git errors and emits one parseable JSON receipt with
`base_sha`, `head_sha`, untracked paths, removed pages, exact-base backlinks and
graph diagnostics. CI derives this SHA from the pull request base or the push's
`before` commit; a local reviewer should copy the same immutable commit.

[wiki_audit.py](../../../scripts/wiki_audit.py) fails when two linkable entity
pages expose the same canonical name through `title:`, `aliases:` or their first
Markdown heading. This catches the common failure mode where all Markdown links
resolve, but navigation still splits a person or project across multiple pages.
