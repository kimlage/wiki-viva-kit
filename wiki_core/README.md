# wiki_core

Deterministic Python core for the wiki viva kit.

This package owns configuration loading, source manifests, extraction, chunking,
indexes, gates, graph checks, page types, score events, quality telemetry,
Wilber/AQAL quadrant contracts, the local web cockpit read/action model and
portable export/import helpers. [upgrade.py](upgrade.py) owns the deterministic
v8 consumer inventory, portable allowlist/drift, preflight and migration-report
contracts; it never performs the import itself.
[release_receipt.py](release_receipt.py) binds normalized public/downstream
gate results and artifact hashes to one exact Git SHA/tree/worktree fingerprint.
Its v1 contract is closure-only and refuses every local E5 promotion until an
external signed authority exists. The web package also owns safe source triage,
ingestion wizard planning and proposal-branch Git workflow contracts for the
localhost operator API. It intentionally does not embed an LLM client.

[action_state.py](action_state.py) is the shared read/compatibility vocabulary;
[action_transition.py](action_transition.py) is the fail-closed writer. It
enforces the transition table, action contract fields, safe chained receipts,
atomic persistence and PR-base audit diagnostics without disabling legacy
reads. Concurrent writers share a hashed per-action lock below ignored
`data/derived/` with `flock` on macOS/Linux. Action writes fail closed on
Windows until handle-pinned reparse-point traversal exists; static flat
snapshot builds remain supported there. The temporary file is fsynced before
atomic replacement and POSIX also fsyncs the parent directory.

Release receipt evidence reads/validation likewise fail closed on Windows.
On supported POSIX systems, evidence is immutable/create-once, opened through
no-follow descriptor chains, and may not be silently removed or overwritten.

[adapter_manifest.py](adapter_manifest.py) compiles and verifies the
consumer-owned `wiki_downstream_adapter_manifest.v1`: an ordered inventory of
tracked adapter bytes whose canonical aggregate replaces self-asserted
downstream adapter hashes. It excludes runtime config, memory and raw/derived
state and is rechecked by both Node preflight and the downstream receipt.

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

Agent-facing commands live in [scripts](../scripts/README.md).
