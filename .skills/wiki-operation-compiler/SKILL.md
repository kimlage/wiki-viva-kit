---
name: wiki-operation-compiler
description: Compile or review the living-wiki operation cockpit with current Git state, pending decisions, agent actions, source queues, stale contexts and validation links.
---

# Wiki Operation Compiler

## Workflow

1. Run [scripts/wiki_operation_compile.py](../../scripts/wiki_operation_compile.py) to review the daily cockpit.
2. Run [scripts/wiki_operational_pass.py](../../scripts/wiki_operational_pass.py) when the task needs source/action/context consolidation, next-step compilation, or cross-context backlog review.
3. Review decisions, actions, stale contexts, source queues, sources needing attention and problems/uncertainties.
4. Run both compilers with `--write` when the compiled pages are correct.
5. Confirm [memories/operations.md](../../memories/operations.md) has `stale_after_days: 1`.
6. Record relevant memory changes in [memories/system/log.md](../../memories/system/log.md).
