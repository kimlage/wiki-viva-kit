---
name: wiki-memory-router
description: Generic router for Markdown/Git living-wiki repos that use memories/, docs/references/, wiki.config.yaml, wiki_core, PR gates, source manifests, normalized ingestion events, and operation cockpit pages.
---

# Wiki Memory Router

Use this generic skill in repos that adopted the portable wiki kit.

## Workflow

1. Confirm repository root and read [wiki.config.yaml](../../wiki.config.yaml).
2. Read [memories/index.md](../../memories/index.md).
3. Open the configured `root_entity` page and
   [memories/system/input-stage.md](../../memories/system/input-stage.md) when
   present.
4. Open [memories/operations.md](../../memories/operations.md) when it exists.
5. Open [memories/system/operational-pass.md](../../memories/system/operational-pass.md)
   when it exists and read the top "Short-term memory" section before older
   execution/event pages.
6. Run `python3 scripts/wiki_consolidate.py --check` ([scripts/wiki_consolidate.py](../../scripts/wiki_consolidate.py)) when resuming: sources stuck mid-flow (deep read without integration) show up immediately.
7. Select the context-specific local skill only after the root memory explains the context.
8. Treat [docs/references/](../../docs/references/README.md) as references, templates and audit history, not as live memory.
9. For new sources, create or confirm input-stage context, manifest, text/chunks, event, LLM context plan, integration (consolidated event with `consolidated_into` closed) and PR-ready proposal.
10. Before finalizing, run [scripts/wiki_audit.py](../../scripts/wiki_audit.py), [scripts/wiki_consolidate.py](../../scripts/wiki_consolidate.py) with `--check`, [scripts/wiki_quality_report.py](../../scripts/wiki_quality_report.py) with `--check`, [scripts/wiki_input_stage.py](../../scripts/wiki_input_stage.py) with `--check`, [scripts/wiki_check_methodology_coverage.py](../../scripts/wiki_check_methodology_coverage.py) when methodology files changed, [scripts/wiki_operation_compile.py](../../scripts/wiki_operation_compile.py) and [scripts/wiki_pr_summary.py](../../scripts/wiki_pr_summary.py).

## Rules

- Do not persist access secrets.
- Private useful operational context may be extracted in private repos when the repo policy allows it.
- Every local file, directory, script, template or page reference in Markdown should be a real Markdown link.
- Canonical memory changes go through a branch and human PR gate.
- Keep navigation hierarchical: root MOC -> context/domain hub -> entity/subdomain hub -> relation/evidence pages -> execution/event pages.
- Use the configured root entity as the semantic top page; the root MOC remains
  the technical map of content.
- Relation pages (`action`, `claim`, `decision`, `meeting`, `person`, `project`, `source`, `source_config`) need a declared `moc_parent`; do not treat `source_refs` as the parent.
- Consolidate current synthesis into hubs first, then link down to typed child pages when detail or audit history needs its own page.
