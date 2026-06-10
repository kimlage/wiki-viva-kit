---
name: wiki-memory-router
description: Generic router for Markdown/Git living-wiki repos that use memories/, docs/references/, wiki.config.yaml, wiki_core, PR gates, source manifests, normalized ingestion events, and operation cockpit pages.
---

# Wiki Memory Router

Use this generic skill in repos that adopted the portable wiki kit.

## Workflow

1. Confirm repository root and read [wiki.config.yaml](../../wiki.config.yaml).
2. Read [memories/index.md](../../memories/index.md).
3. Open [memories/operations.md](../../memories/operations.md) when it exists.
4. Select the context-specific local skill only after the root memory explains the context.
5. Treat [docs/references/](../../docs/references/) as references, templates and audit history, not as live memory.
6. For new sources, create or confirm manifest, text/chunks, event, LLM context plan and PR-ready proposal.
7. Before finalizing, run [scripts/wiki_audit.py](../../scripts/wiki_audit.py), [scripts/wiki_check_methodology_coverage.py](../../scripts/wiki_check_methodology_coverage.py) when methodology files changed, [scripts/wiki_operation_compile.py](../../scripts/wiki_operation_compile.py) and [scripts/wiki_pr_summary.py](../../scripts/wiki_pr_summary.py).

## Rules

- Do not persist access secrets.
- Private useful operational context may be extracted in private repos when the repo policy allows it.
- Every local file, directory, script, template or page reference in Markdown should be a real Markdown link.
- Canonical memory changes go through a branch and human PR gate.
