---
title: "Release notes - Wiki Viva v6.2"
page_id: release-wiki-viva-v6-2
page_type: release_notes
context: system
visibility: private_self
updated_at: 2026-06-12
stale_after_days: 90
sources_policy: release_notes
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
---

# Release notes - Wiki Viva v6.2

Status: in progress.

Runtime anchor: `wiki_core.__version__ = "6.2.0"`.

## Included

- Page graph schema `wiki_page_graph.v1`.
- New reusable graph module [wiki_core/graph](../../../wiki_core/graph) for
  page nodes, Markdown links, frontmatter refs, aliases, backlinks, wanted pages,
  orphan detection, reachability and same-PR impact.
- New CLI [wiki_page_graph.py](../../../scripts/wiki_page_graph.py) with
  `--write`, `--check`, `--impact` and `--base`.
- Auditor integration for:
  - orphan pages;
  - reachability from the root MOC;
  - minimum outbound graph links as warning;
  - changed-page escalation for unlinked entity mentions;
  - impact closure with append-only acknowledgements in
    [impact-acks.md](../../../memories/system/ingestion/impact-acks.md).
- Page type registry schema `wiki_page_types.v1`.
- New registry [wiki.page-types.yaml](../../../wiki.page-types.yaml) covering
  the page types used by the kit baseline.
- New [page_types.py](../../../wiki_core/page_types.py) loader and shape
  validator, wired into [wiki_audit.py](../../../scripts/wiki_audit.py), for:
  - declared page types;
  - required frontmatter;
  - simple field types;
  - allowed directories;
  - required sections;
  - template coverage or explicit `template: none` reason.
- Perspective schema anchor `wiki_perspective.v1` represented by the
  `perspective` page type.
- New template [perspective.md](../../../docs/references/templates/wiki/perspective.md)
  and baseline perspective pages:
  - [technical.md](../../../memories/system/perspectives/technical.md);
  - [project.md](../../../memories/system/perspectives/project.md).
- Deep-read schema bumped to `wiki_llm_context_pass.v3` and prompt
  [context_deep_read.v3.md](../../../wiki_core/llm/prompts/context_deep_read.v3.md).
- LLM context requests can declare required and optional perspectives; v3
  results must report each required perspective status or a reasoned absence.
- Auditor gained `audit_perspective_coverage` for requests/results that declare
  `perspectives_required`.
- Integration packet schema bumped to `wiki_integration_packet.v2`.
- `wiki_consolidate.py --packet` now includes `impact.must_update` and
  `impact.should_review`; generated events include `affected_pages` and
  `impact_closure`.
- Auditor gained `audit_impact_closure`: every `must_update` entry must be
  closed as updated, no-change with reason, or blocked with reason.
- Template resolution for base + optional project overlay via
  [templates.py](../../../wiki_core/templates.py).
- New CLI [wiki_new.py](../../../scripts/wiki_new.py) creates typed pages from
  `wiki.page-types.yaml`, stamps template provenance and refuses unknown types.
- New CLI [wiki_migration_inventory.py](../../../scripts/wiki_migration_inventory.py)
  inventories legacy pages without frontmatter and suggests conservative v6.2
  metadata for review.
- Migration guide:
  [wiki-viva-v6.2-migration.md](../../../docs/references/guides/wiki-viva-v6.2-migration.md).
- Generic open-source overlay example:
  [perspective-example.md](../../../docs/references/templates/overlays/perspective-example.md).
- Open-source synthetic pilot report:
  [wiki-viva-v6.2-pilot-metrics-2026-06-11.md](../../../docs/references/reports/wiki-viva-v6.2-pilot-metrics-2026-06-11.md).
- Open-source kit graph baseline fixed by linking:
  - [docs-review.md](../../../memories/system/docs-review.md) from the root MOC;
  - [2026-06-09-example.md](../../../memories/system/ingestion/events/2026-06-09-example.md)
    from the ingestion events catalog.

## Still Planned

- Publication/PR closeout for the local branch.
