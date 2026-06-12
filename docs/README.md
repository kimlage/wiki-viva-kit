# Docs

Updated on: 2026-06-12

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
  [wiki-viva-v6.3-quality-cost-control-2026-06-12.md](references/proposals/wiki-viva-v6.3-quality-cost-control-2026-06-12.md).
- `docs/references/fixtures/`: synthetic sources used to test methodology
  behavior before applying it to private data.
- `docs/references/guides/`: adoption and migration guides, including the v6.2
  migration guide in
  [wiki-viva-v6.2-migration.md](references/guides/wiki-viva-v6.2-migration.md)
  and the canonical entity navigation guide in
  [canonical-entity-navigation.md](references/guides/canonical-entity-navigation.md),
  plus the source refresh cadence guide in
  [source-refresh-cadence.md](references/guides/source-refresh-cadence.md).
- `docs/references/templates/`: stable models for new records.
- `docs/references/templates/wiki/`: models for the operational wiki, including
  ingestion proposal, decision, insight and PR checklist.
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
