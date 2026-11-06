# Wiki Viva v9.2.2

Protected ingestion can select a subset of declared targets while recording
the omitted declarations. It also supports an opt-in artifact namespace per
source and actor pair, with the existing per-path authorization checks. A
selected foreign context is requalified for subsequent inspection and
consolidation candidate checks. The separate repository `compare` stage can
still deny a selected foreign context before that requalification.
Protected writes now check each actual artifact path is ignored and untracked,
including when a Git ignore rule re-includes JSON files.

External sources still require an authorized provider adapter and a local
capture. The protected pipeline validates the local capture; it does not
authenticate a provider or verify a manually stated remote identity.

## Upgrading

Use the reviewed `v9.2.2` tag after publication. Review the B0 dry-run, copy
kit-owned files in C1, run declared C2 generators, and apply consumer-owned C3
changes explicitly. The shared artifact layout remains the default. To use the
new layout, grant the exact required source and cache scopes and configure
`llm.protected_cache_mode: by_source_v1` as described in the
[bounded ingestion guide](../guides/bounded-ingestion.md#host-bound-protected-source-preparation).
Existing artifacts are not migrated or deleted. Run the consumer's gates and
verify an authorized source lifecycle in the installed version.
