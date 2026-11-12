# wiki_core

Deterministic Python core for the wiki viva kit.

This package owns configuration loading, source manifests, extraction, chunking,
indexes, gates, graph checks, page types, score events, quality telemetry,
Wilber/AQAL quadrant contracts, the local web cockpit read/action model and
portable export/import helpers. The retired release-certification and drift
machinery is removed; downstream adoption uses
[wiki_sync_from_kit.py](../scripts/wiki_sync_from_kit.py). The web package also owns safe source triage,
ingestion wizard planning and proposal-branch Git workflow contracts for the
localhost operator API. It intentionally does not embed an LLM client.

[paths.py](paths.py) discovers canonical actions and sources in the configured
directories anywhere under `paths.memory_root`, including nested contexts, while
[traversal.py](traversal.py) prunes symlinks and nested Git repositories. The
legacy global directories remain supported and need not exist in a local-only
layout. Global projections reference those same pages; a shared source keeps
one canonical page referenced by its consumers. Discovery grants no access.

For consumers upgrading this behavior, no relocation or duplicate index is
required. Preserve page IDs, context, owner and existing writer/CAS contracts.
Preserve the consumer's explicit [nested-source selection](../docs/references/guides/source-registry-consumer-policy.md).
Without that policy, recursive discovery remains the default. Configuration
fallback checks the source's own sources directory's `config` subtree before
the legacy global config; explicit `config_ref` still takes precedence. Regenerate
affected projections through the consumer's reviewed sync PR and its gates.

[action_state.py](action_state.py) is the shared read/compatibility vocabulary;
[action_transition.py](action_transition.py) is the fail-closed writer. It
enforces the transition table, action contract fields, safe chained receipts,
atomic persistence and PR-base audit diagnostics without disabling legacy
reads. Concurrent writers share a hashed per-action lock below ignored
`data/derived/` with `flock` on macOS/Linux. Action writes fail closed on
Windows until handle-pinned reparse-point traversal exists; static flat
snapshot builds remain supported there. The temporary file is fsynced before
atomic replacement and POSIX also fsyncs the parent directory.


[temporal.py](temporal.py) owns the canonical semantic-time parser, explicit
precision and conflict rules. [web/temporal.py](web/temporal.py) adapts current
page/source/ingestion/action/decision/receipt read models and emits the
count-reconciled `temporal_graph.json`; the static snapshot is complete, while
the same builder provides fingerprint-bound cursor pagination for a future
transport. See the [temporal kernel guide](../docs/references/guides/temporal-kernel.md).

[experience_packs.py](experience_packs.py) is the public facade for the
declarative pack kernel. Its split validation/state/lifecycle modules verify
registry and immutable tree hashes, exact licensed asset inventories, privacy,
namespaces, dependencies, slots, receipts and installed composition. Mutations
use one POSIX operation lock plus semantic compare-and-swap and rollback; the
consumer's configured memory root is never hardcoded. Packs cannot execute
code or weaken core gates. See the
[experience-pack authoring guide](../docs/references/guides/experience-pack-authoring.md).

Agent-facing commands live in [scripts](../scripts/README.md). The
[context operation runbook](../docs/references/guides/context-operation.md)
connects restrictive policy and revision-bound packets to external task
execution and independent integration. [Schedule advice](../docs/references/context-schedules.md)
is optional and does not install or execute a scheduler.

[freshness_impact.py](freshness_impact.py) evaluates actual changed pages and
both historical and current dependencies. Documentary classifications are
per-proposal review inputs, not persistent hash contracts. See
[scoped freshness](../docs/references/freshness-impact.md).

[action_contribution.py](action_contribution.py) writes one reviewed action body
and its existing memory-log annotation, protected by immutable-parent policy,
CAS, exact-head review and Git readback. See
[agent contributions](../docs/references/guides/agent-contributions.md).

Snapshot [projection](web/snapshot_projection.py) builds and validates the read
models. [Publication](web/snapshot.py) owns disk revisions, locks, atomic
promotion and recovery. Existing public imports remain available.
