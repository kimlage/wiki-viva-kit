# Docs

Updated on: 2026-06-02

`docs/` holds only perennial references, snapshots, decisions and templates. The
starting point for persistent context is `memorias/`.

## Contract

- `memorias/`: living wiki, consolidated context and updatable pages.
- `docs/referencias/`: perennial material used as evidence or template.
- `docs/referencias/templates/`: stable models for new records.
- `docs/referencias/templates/wiki/`: models for the operational wiki, including
  ingestion proposal, decision, insight and PR checklist.
- Optional per-repo subfolders (create on demand): `inventarios/` (inventory
  snapshots), `decisoes/` (immutable historical decisions), `avaliacoes/`
  (one-off evaluation snapshots).

## Reading rule

1. Start with `memorias/index.md`.
2. Read the consolidated memory of the context.
3. Open `docs/referencias/` only for evidence, perennial detail, template or
   audit.
4. If a reference has more current information than the memory, update
   the memory and record it in `memorias/sistema/log.md`.

Do not use `docs/` as the primary memory.

## Per-PR gate

Relevant memory changes must go into a `wiki/*` branch and pass
through a PR. The PR must point to consulted sources, changed pages, privacy
risks, validations and pending items. The detailed contract lives in
`memorias/sistema/contrato-wiki-operacional.md`.
