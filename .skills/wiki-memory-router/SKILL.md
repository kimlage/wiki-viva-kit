---
name: wiki-memory-router
description: Route reading, editing and delegation in Markdown/Git living-wiki repositories through their configured memory roots, current policies, source evidence and ingestion/consolidation process. Use before operating a repository that adopted Wiki Viva Kit, including remote checkouts and agent handoffs.
---

# Wiki Memory Router

## Choose the task first

Identify the authorized checkout, read its AGENTS instructions and configured
memory index, then use the [existing task entry points](../../scripts/README.md#task-entry-points).
Consumer-specific context requirements continue to apply.

- For locating or reading a candidate, use direct lookup or the known page.
  Report origin and coverage limits. This alone does not require ingestion,
  a new model run, a server startup or global maintenance.
- For a consolidated factual claim, current-state assertion, absence or total,
  load the relevant domain/relations and original evidence. State incomplete
  coverage explicitly; search hits alone do not prove completeness or freshness.
- For resumed ingestion, canonical changes or delegation, follow the workflow
  below and its applicable gates. A read-only lookup must not silently turn
  into refresh, publication or a write.

## Workflow for synthesis, ingestion, changes and delegation

1. Identify the authorized checkout root, using `git rev-parse --show-toplevel`
   when available. Read that root's [AGENTS.md](../../AGENTS.md) and applicable
   scoped instructions before acting. Resolve paths against the checkout,
   not an agent installation or a fixed host directory.
2. Read [wiki.config.yaml](../../wiki.config.yaml) and the index under configured
   `paths.memory_root`.
3. Read the consumer's current approval policy, operational contract and
   ingestion process identified by its entry instructions. When coordination
   is configured, read `wiki.coordination.yaml`'s `common_context` and check
   that these canonical sources and the router/root are included. Profile
   pages add domain context and do not replace common policies. Report a
   missing policy reference before relying on a packet for handoff; do not
   silently change configuration during a read-only task. Use the consumer's
   existing locations, not assumed English paths. See [context coordinators](../../docs/references/guides/context-coordinators.md#consumer-configuration).
4. Open the configured `root_entity.page` and `root_entity.input_stage_page`
   when present.
5. Open the operation page resolved by `WikiPaths.operation_page` when it exists.
6. Open the operational-pass page resolved by `WikiPaths.operational_pass_page`
   when it exists and read the top "Short-term memory" section before older
   execution/event pages.
7. When resuming ingestion or integration, run `python3 scripts/wiki_consolidate.py --check` ([scripts/wiki_consolidate.py](../../scripts/wiki_consolidate.py)): sources stuck mid-flow (deep read without integration) show up immediately.
8. Select the context-specific local skill only after the root memory explains the context.
9. Treat configured `paths.references_root` as references, templates and audit
   history, not as live memory.
10. For new sources, create or confirm input-stage context, manifest, text/chunks, event, LLM context plan, integration (consolidated event with `consolidated_into` closed) and PR-ready proposal.
11. Before delegating, complete the existing [subagent brief](../../docs/references/templates/wiki/subagent-brief.md)
    under the [delegation contract](../../docs/references/guides/context-coordinators.md#delegation-contract).
    Bind the canonical task/base, policy sources, evidence and destinations.
    Verify tools, host/session and account in the executing instance; do not
    assume the parent's capabilities transfer. Record an exact blocker and a
    bounded condition for resuming the same IDs, preserving independent work.
12. Before finalizing a canonical change, run [scripts/wiki_audit.py](../../scripts/wiki_audit.py), [scripts/wiki_consolidate.py](../../scripts/wiki_consolidate.py) with `--check`, [scripts/wiki_quality_report.py](../../scripts/wiki_quality_report.py) with `--check`, [scripts/wiki_input_stage.py](../../scripts/wiki_input_stage.py) with `--check`, [scripts/wiki_check_methodology_coverage.py](../../scripts/wiki_check_methodology_coverage.py) when methodology files changed, [scripts/wiki_operation_compile.py](../../scripts/wiki_operation_compile.py) and [scripts/wiki_pr_summary.py](../../scripts/wiki_pr_summary.py).

## Rules

- Do not persist access secrets.
- Private useful operational context may be extracted in private repos when the repo policy allows it.
- Every local file, directory, script, template or page reference in Markdown should be a real Markdown link.
- Canonical memory changes go through a branch and the PR review policy in [AGENTS.md](../../AGENTS.md).
- Apply already granted authorization within its stated scope without requesting
  the same consent again. Preserve independent review and technical gates;
  policy does not grant missing tool access or override a tool denial.
- Resolve historical wording through the current canonical policy. Record a
  missing decision or capability on the existing action instead of repeatedly
  assigning the unchanged blocker to new agents.
- Keep navigation hierarchical: root MOC -> context/domain hub -> entity/subdomain hub -> relation/evidence pages -> execution/event pages.
- Use the configured root entity as the semantic top page; the root MOC remains
  the technical map of content.
- Relation pages (`action`, `claim`, `decision`, `meeting`, `person`, `project`, `source`, `source_config`) need a declared `moc_parent`; do not treat `source_refs` as the parent.
- Consolidate current synthesis into hubs first, then link down to typed child pages when detail or audit history needs its own page.
