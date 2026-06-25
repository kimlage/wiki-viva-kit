# Docs

Updated on: 2026-06-25

`docs/` holds only perennial references, snapshots, decisions and templates. The
starting point for persistent context is `memories/`.

## Contract

- `memories/`: living wiki, consolidated context and updatable pages.
- `docs/references/`: perennial material used as evidence or template.
- `docs/references/proposals/`: methodological plans and proposals preserved as
  reference material, including the v6.2 roadmap for typed validation,
  templates and perspectives in
  [ingestion-validation-perspectives-roadmap-2026-06-11.md](references/proposals/ingestion-validation-perspectives-roadmap-2026-06-11.md)
  and the v6.3 quality/cost roadmap in
  [wiki-viva-v6.3-quality-cost-control-2026-06-12.md](references/proposals/wiki-viva-v6.3-quality-cost-control-2026-06-12.md),
  plus the v6.8 root-entity/input-stage refactor in
  [integral-root-entity-and-input-stage-refactor-2026-06-25.md](references/proposals/integral-root-entity-and-input-stage-refactor-2026-06-25.md).
- `docs/references/fixtures/`: synthetic sources used to test methodology
  behavior before applying it to private data.
- `docs/references/guides/`: adoption and migration guides, including the
  default open-source process guide in
  [default-open-source-process.md](references/guides/default-open-source-process.md),
  the v6.2 migration guide in
  [wiki-viva-v6.2-migration.md](references/guides/wiki-viva-v6.2-migration.md),
  the canonical entity navigation guide in
  [canonical-entity-navigation.md](references/guides/canonical-entity-navigation.md)
  and the source refresh cadence guide in
  [source-refresh-cadence.md](references/guides/source-refresh-cadence.md).
- `docs/references/templates/`: stable models for new records.
- `docs/references/templates/wiki/`: models for the operational wiki, including
  root entities, input channels, processes, artifacts, ingestion proposal,
  decision, insight and PR checklist.
- `docs/references/releases/`: release notes, including the OKF v0.1
  interoperability release in
  [wiki-viva-v6.6.md](references/releases/wiki-viva-v6.6.md) and the hierarchy
  / short-term-memory release in
  [wiki-viva-v6.7.md](references/releases/wiki-viva-v6.7.md), plus the
  root-entity/input-stage release in
  [wiki-viva-v6.8.md](references/releases/wiki-viva-v6.8.md).
- Optional per-repo subfolders (create on demand): `inventories/` (inventory
  snapshots), `decisions/` (immutable historical decisions), `evaluations/`
  (one-off evaluation snapshots).

## Reading rule

1. Start with `memories/index.md`.
2. Read the consolidated memory of the context.
3. Open `docs/references/` only for evidence, perennial detail, template or
   audit.
4. If a reference has more current information than the memory, update
   the memory and record it in `memories/system/log.md`.

Do not use `docs/` as the primary memory.

## Per-PR gate

Relevant memory changes must go into a `wiki/*` branch and pass
through a PR. The PR must point to consulted sources, changed pages, privacy
risks, validations and pending items. The detailed contract lives in
`memories/system/operational-wiki-contract.md`.
