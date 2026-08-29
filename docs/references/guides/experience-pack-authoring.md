# Experience pack authoring and compatibility

Experience packs are declarative, versioned bundles that extend the Wiki Viva
kit without forking or weakening the core. The source of truth is `pack.yaml`;
`packs/registry.yaml` pins both the published manifest hash and the canonical
whole-tree hash; `wiki.packs.lock.yaml` repeats that immutable inventory for
the installed bundle. A changed README, fixture, template, locale or asset is
therefore a new supply-chain input even when `pack.yaml` did not change.

## Lifecycle

```text
list -> inspect -> preview synthetic fixtures -> install --dry-run
  -> review branch mutation -> validate -> upgrade | disable | remove
```

Use the CLI from a checked-out `wiki/*` branch:

```sh
python3 scripts/wiki_pack.py list
python3 scripts/wiki_pack.py inspect study-research
python3 scripts/wiki_pack.py preview study-research
python3 scripts/wiki_pack.py compile-fixture study-research fixtures/failure --output .wiki-viva/fixture-output/study-failure
python3 scripts/wiki_pack.py install study-research --dry-run
python3 scripts/wiki_pack.py install study-research --branch wiki/pack-study-research
python3 scripts/wiki_pack.py validate study-research
python3 scripts/wiki_pack.py validate --all
python3 scripts/wiki_pack.py disable study-research --dry-run
python3 scripts/wiki_pack.py remove study-research --dry-run
```

The CLI never checks out or creates a branch. A real mutation is refused on
`main`, `master` or any non-`wiki/*` Git branch. Dry-runs remain read-only and
produce the same conceptual diff and receipt identity used by the mutation.
`validate --all` is the release gate: it resolves every registered source
version through the full privacy/secret/path/asset contract, then verifies the
installed immutable bundles and their active composition. An empty lock is a
valid empty composition; a broken registered pack is not ignored merely
because it is not installed.

Both source validation and installation compare `manifest_sha256` and
`tree_sha256` before accepting a bundle. Authors must repin the registry after
the last pack-file change; hand-editing only the manifest pin is intentionally
insufficient.

## Compatibility rules

- Pack IDs use lowercase hyphenated slugs. Every pack-owned capability is
  namespaced; shared core block packages are referenced explicitly.
- Dependencies are exact semver ranges. Explicit conflicts, duplicate
  capabilities and exclusive-slot collisions fail before any filesystem write.
- Append-mode contributions compose in deterministic pack-ID order. Install
  order never changes the adapter payload.
- Only declarative UTF-8 documents and licensed, hashed local assets are
  accepted. A pack's declared license must be proven by an applicable root or
  pack-local license text; metadata alone is insufficient. Executable pack
  files, remote assets and symlinks are blocked.
- Access secrets are blocked in every pack file. Public fixtures additionally
  block PII and e-mail entities. Pack privacy fields are strict constants and
  cannot weaken core publication rules.
- Install and upgrade migrations are declarative and must state
  `data_policy: preserve_user_content`. Migration v1 files are validation and
  dry-run plans only; they are not an executable data-migration language.
- The mutation boundary is limited to `.wiki-viva/packs`,
  `.wiki-viva/pack-receipts` and `wiki.packs.lock.yaml`. Removal verifies the
  immutable bundle before deleting it and never writes or deletes `memories/`.

## Required pack surface

Each published pack declares page types, templates, block adapters, views,
commands, operations, temporal profiles, EN, ES and PT-BR copy, a hashed asset
manifest, public synthetic fixtures, lifecycle migrations and conformance
contracts. At minimum, fixtures cover minimal, normal, dense and intentional
failure behavior.

Dense and intentional-failure fixtures may carry the closed
`wiki_experience_pack_fixture_compiler.v1` block. The trusted core compiler can
only materialize declared page-type counts, apply the three bounded mutations
(`clone_page`, `remove_page`, `set_field`) and run the five registered checks.
The compiled diagnostic set must equal `expected_diagnostic_codes` exactly.
Packs cannot contribute a compiler, expression, import or script. See the
[fixture compiler schema](../schemas/wiki-experience-pack-fixture-compiler-v1.schema.json).
Materialization is allowed only in a dedicated
`.wiki-viva/fixture-output/<fixture-id>` child. An existing non-empty target
must carry the matching managed-output marker; the repository root, configured
memory root and an output owned by another fixture are refused without delete
or overwrite.

The first reference implementation is
`packs/study-research/pack.yaml`. It composes existing `quadrant_lenses` and
`gamification` block packages while keeping its domain capabilities isolated.

## Runtime boundary

`wiki_core.experience_packs.compose_active_packs()` emits the stable backend
adapter payload (`wiki_experience_pack_composition.v1`). The current builder
always publishes it as the integrity-covered `experience_packs.json` file and
advertises both the `experience_packs` capability and the
`experience_pack_composition` contract version in `manifest.json`. Once either
signal is advertised, capability, version, declared file and payload are one
required fail-closed unit. Earlier v2 snapshots that predate the feature and
advertise none of those signals remain valid. The published schema is
[experience pack composition v1](../schemas/wiki-experience-pack-composition-v1.schema.json).

A repository with no lock or an empty lock publishes one exact empty
composition: no packs, block packages or slot contributions, plus the
deterministic hash of those empty structures. This is a healthy first-class
state, not a missing feature. A malformed lock, drifted installed bundle,
unsatisfied dependency, capability conflict or exclusive-slot collision blocks
snapshot construction and publication. The snapshot builder never catches
these failures and substitutes an apparently healthy empty payload.

Snapshot and cockpit registries consume this adapter; pack code must not import
or patch frontend modules directly. Slot consumers must preserve the declared
`views`, `commands`, `operations` and `timelines` namespaces and use
`composition_sha256` to distinguish compositions, rather than inferring pack
state from the presence of copied assets.

The base cockpit mounts a generic lazy `pack_view` fallback for every verified
view contribution. It selects only canonical pages whose registered
`page_type` belongs to that pack namespace, supports search/keyboard/mobile,
opens the real reader and can route to the full Chronoscope. It deliberately
does not execute a declared command/operation or claim that a temporal profile
was applied. A richer renderer or operator adapter is a separate versioned
capability, not a side effect of installing declarative YAML.

## Declarative execution boundary

The `views`, `commands`, `operations` and temporal-profile artifacts are
closed, schema-versioned documents. Pack validation binds every artifact ID to
the matching manifest capability and every contribution to its declared slot.
Commands and operations must remain `proposal_only`, `dry_run: true` and
`human_gate: required`; validation mounts metadata but never executes an
operation.

Published temporal artifacts use
`wiki_experience_pack_temporal_profiles.v2`. Each adapter binds one namespaced
event kind to a declared page type, an existing page-type field inventory, an
explicit core lane, canonical semantic clocks, bounded before/after state and
field-level source/evidence provenance. Typos in time, state or provenance
fields fail source validation; missing required provenance rejects only that
event with a safe diagnostic. The snapshot preserves authored year/month/day/
instant precision and never fabricates a clock. The v1 profiles schema remains
a historical metadata contract and is not executable. See the
[temporal adapter schema](../schemas/wiki-experience-pack-temporal-profiles-v2.schema.json).

Likewise, `wiki_experience_pack_migration.v1` only describes
content-preserving install/upgrade plans for conceptual diffs and review. Any
future executor that transforms user data must ship as a new, explicitly
versioned capability with its own contract, rollback proof and human Git/PR
gate. It cannot be introduced by broadening migration v1 semantics.

The public, navigable fixture workflow and its explicit runtime limitations are
documented in the
[experience-pack showcase demo guide](experience-pack-showcase-demos.md).
