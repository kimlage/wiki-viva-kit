---
name: wiki-operation-compiler
description: Compile or review the living-wiki operation cockpit with current Git state, pending decisions, agent actions, source queues, stale contexts and validation links.
---

# Wiki Operation Compiler

## Workflow

1. Run [scripts/wiki_operation_compile.py](../../scripts/wiki_operation_compile.py) to review the daily cockpit.
2. Run [scripts/wiki_operational_pass.py](../../scripts/wiki_operational_pass.py) when the task needs source/action/context consolidation, next-step compilation, or cross-context backlog review.
3. Run [scripts/wiki_input_stage.py](../../scripts/wiki_input_stage.py) when root
   entity, input channels, source pages or source configs changed.
4. Review the top "Short-term memory" section first: review-now items, primary actions and latest updates are the resume surface.
5. Review decisions, actions, stale contexts, source queues, sources needing attention, input-stage warnings and problems/uncertainties.
6. Run the relevant compilers with `--write` when the compiled pages are correct.
7. Confirm the pages resolved by `WikiPaths.operation_page`,
   `WikiPaths.input_stage_page` and `WikiPaths.operational_pass_page` have the
   intended `stale_after_days`.
8. Record relevant memory changes in the configured `WikiPaths.log_page`.
