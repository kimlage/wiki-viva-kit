# Operating — the daily loop

The loop is: **select inputs → ingest → deep read → consolidate + integrate →
PR/review/gates → main → result readback → wiki reconciliation → post-merge
cleanup → settle the accepted scope**. Follow the existing [closeout contract](../../../docs/references/guides/context-coordinators.md#thread-continuity-and-closeout).
Retire integrated local/remote branches and inactive worktrees under the adopted
[post-merge cleanup policy](../../../docs/references/guides/context-coordinators.md#post-merge-cleanup), preserving WIP and active proposals. Reuse still-valid
review and test evidence for unchanged deliveries.
The commands have their own effect and retry boundaries; the
model steps — the deep read and the integration it feeds — are yours. The full per-CLI catalog is the
command-reference page in the meta-wiki (linked from [AGENTS.md](../../../AGENTS.md)).

```mermaid
flowchart LR
    S["Compile input stage"] --> A["Ingest source"]
    A --> B["Deep read (you)"]
    B --> C["Record result"]
    C --> CI["Consolidate + integrate"]
    CI --> D["Gate transition"]
    D --> E["Recompile cockpit"]
    E --> F["Run gates"]
    F --> G["PR + review + gates"]
    G --> H["Integrate main"]
    H --> I["Read back result"]
    I --> J["Reconcile wiki"]
    J --> K["Clean integrated workspace"]
    K --> L["Settle accepted scope"]
```

## 1. Compile the input stage

The input stage is a deterministic catalog compiled from the configured root
entity, input channels, source pages and source configs. It does not fetch
external systems. An authorized coordinator may use it for global routing; a
scoped executor does not need to open it or expand beyond its selected packet.

```sh
python3 scripts/wiki_input_stage.py --check
python3 scripts/wiki_input_stage.py --write
python3 scripts/wiki_input_stage.py --ready
```

## 2. Ingest a source

For a new approved folder-policy request, use the existing host-bound
`prepare` source stage via [wiki_coordination.py](../../../scripts/wiki_coordination.py).
Select the authorized context, current approved revision, physical entry and
index, source and explicit context inputs. When the executor cannot own the
derived artifacts, select an already authorized ancestor integrator. Exact
payloads, formats, budgets and limits are in [bounded ingestion](../../../docs/references/guides/bounded-ingestion.md).
An independently authorized Git file can be included as evidence only through
the host-pinned [repository selection](../../../docs/references/guides/protected-independent-git.md).

The old `--approved-revision` and `--policy-context` flags on
[wiki_ingest.py](../../../scripts/wiki_ingest.py) are refused for new v1
operations. The separately authorized working-tree folder route remains
available without those flags, but does not apply approved folder policy.

## 3. Deep read (delegated LLM pass)

Read the complete prepared request, selected context, v5 prompt and source
chunks. Produce result objects bound to each chunk and submit them using
`wiki_coordination.py --source-stage record` with the same selectors, limits
and authorization. The agent performs the reading; the scripts do not call a
model. Missing coverage, unsupported formats and denied inputs remain explicit
blockers or limitations. See [wiki-llm-context-agent](../../wiki-llm-context-agent/SKILL.md).

The old approved-v1 flags on [wiki_llm_context_pass.py](../../../scripts/wiki_llm_context_pass.py)
are refused for new recording and checks. The compatibility route has its own
local cache and selectors; do not use its result as an approved folder result.
Generic audit, cache and batch-export commands do not inspect protected
artifacts and cannot establish that the protected request was read.

## 4. Consolidate and integrate

Use the host-bound `consolidate` source stage with the same selections, a
permitted source page, canonical event path and explicit candidates. Repository
evidence needs the separate host-pinned publication grant for a derived event.
The stage produces event and packet proposal material; it does not review or
incorporate the information. The source-page association is operator-selected
and not automatically proven. Inspect any partial effects before retrying.

An authorized integrator reviews the packet, updates the affected pages and
closes `consolidated_into` according to the applicable repository policy. Run
the required gates on the final proposal and obtain independent review before
an authorized integration and readback. Do not mark the source ingested merely
because a request, result, event or packet exists.

## 5. Review the applicable proposal

The [wiki_gate.py](../../../scripts/wiki_gate.py) list and rebase commands scan
flat Markdown proposals in the configured ingestion directory. Protected source
events live in its events directory; they are not listed by `--list` and are
not automatically advanced as flat proposals. Review and incorporate the event
and affected pages under the repository's existing PR policy.

For a flat proposal that actually uses the gate, inspect its current state
first. Voluntary transitions must follow the state machine: for example,
`ready_for_review` can move to the legacy state `needs_human_gate`, and that
state can move to `approved`. The legacy state name does not itself impose a
human reviewer beyond the repository's independent-review policy. Do not assume
that an arbitrary current state can transition directly to `approved`.

```sh
python3 scripts/wiki_gate.py --list
```

The [state machine](../../../wiki_core/gate/state_machine.py) defines valid
transitions. The existing [wiki_archive.py](../../../scripts/wiki_archive.py)
handles eligible resolved proposals and associated events; inspect its dry run
and the applicable policy before any archive operation. The approval cycle is
the git-approvals page in the meta-wiki (routed from [AGENTS.md](../../../AGENTS.md)).

## 6. Recompile the cockpit

Never hand-edit the cockpit — recompile it from real Git/memory state:

```sh
python3 scripts/wiki_operation_compile.py --write    # regenerate the cockpit page
python3 scripts/wiki_operation_compile.py --check    # CI: fails if semantically stale
python3 scripts/wiki_input_stage.py --write          # regenerate root/channel/source stage
python3 scripts/wiki_input_stage.py --check          # CI: fails if stale
python3 scripts/wiki_operational_pass.py --write     # regenerate source/action/context pass
python3 scripts/wiki_operational_pass.py --check     # CI: fails if stale
```

## 7. Run the gates and open the PR

The commands below are a menu, not a requirement to run every compiler for
every change. Apply the repository's mandatory gates and select additional
checks for the affected behavior and generated outputs. Before running a
command, qualify its complete read scope under the applicable authority. A
required gate whose reads cannot be authorized remains blocked; omitting it is
not a pass and a candidate policy cannot authorize its own review.

```sh
python3 scripts/wiki_audit.py --check
python3 scripts/wiki_consolidate.py --check                  # shared-cache coverage only
python3 scripts/wiki_quality_report.py --check               # quality/hierarchy thresholds
python3 scripts/wiki_check_methodology_coverage.py --check   # when methodology files changed
python3 scripts/wiki_operation_compile.py --check
python3 scripts/wiki_input_stage.py --check
python3 scripts/wiki_operational_pass.py --check
python3 scripts/wiki_pr_summary.py                           # paste into the PR
```

Canonical memory changes go on a `wiki/<theme>` branch; the PR review follows
[AGENTS.md](../../../AGENTS.md). Select additional local tests for the actual
change as specified there; normal public CI runs the full suites. Consumers
retain their own review policy.
Generic checks do not inspect protected source caches; inspect the bound
request, results and event through the applicable protected stages as well.
The PR summary is a helper, not an approval: its current implementation reads
configuration and examines the local Git/worktree diff, so its own read scope
also needs qualification.
Gate semantics and privacy: [gates-and-privacy.md](gates-and-privacy.md).

## Optional layers

- **Karma / vitality** (append-only by-product):
  ```sh
  python3 scripts/wiki_score.py --add --event ingestar_fonte_valida --actor owner --context system
  python3 scripts/wiki_score.py --summary
  ```
- **Information → Insight cycle**: gather signals about a theme and emit an
  insight proposal with [wiki_insight_job.py](../../../scripts/wiki_insight_job.py).
- **Raw via Drive**: keep raw sources (statements, invoices) outside Git and
  retrieve authorized existing sources with [wiki-raw-drive](../../wiki-raw-drive/SKILL.md).
  Publish authorized artifacts through [wiki_drive_publish.py](../../../scripts/wiki_drive_publish.py)
  within the authorized file and destination scope, preserving privacy and secret
  safeguards. Its dry-run is local and does not verify Drive. Reconcile name or
  destination conflicts and uncertain upload results before repeating an effect;
  see the [publisher's concurrency and recovery limits](../../../scripts/README.md#task-entry-points).
  Existing links remain available subject to their own access and retention.
- **Atualização do kit**: revise primeiro o B0 e então sincronize C1/C2/C3 com
  [wiki_sync_from_kit.py](../../../scripts/wiki_sync_from_kit.py); a PR do
  consumidor é a fronteira reversível de revisão e promoção.
