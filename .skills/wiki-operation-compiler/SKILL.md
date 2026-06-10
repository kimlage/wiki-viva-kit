---
name: wiki-operation-compiler
description: Compile or review the living-wiki operation cockpit with current Git state, pending decisions, agent actions, source queues, stale contexts and validation links.
---

# Wiki Operation Compiler

## Workflow

1. Run [scripts/wiki_operation_compile.py](../../scripts/wiki_operation_compile.py) with `--dry-run`.
2. Review decisions, actions, stale contexts and source queues.
3. Run with `--write` when the compiled page is correct.
4. Confirm [memorias/operacao.md](../../memorias/operacao.md) has `stale_after_days: 1`.
5. Record relevant memory changes in [memorias/sistema/log.md](../../memorias/sistema/log.md).
