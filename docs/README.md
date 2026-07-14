# Docs

Updated on: 2026-07-14

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
  The current cross-repo release review, temporal-world architecture and
  experience-pack execution contract is
  [wiki-viva-release-truth-temporal-world-experience-packs-plan-2026-07-11.md](references/proposals/wiki-viva-release-truth-temporal-world-experience-packs-plan-2026-07-11.md).
- `docs/references/fixtures/`: synthetic sources used to test methodology
  behavior before applying it to private data.
- `docs/references/visual-inspiration/`: primary-source visual precedents with
  explicit borrow/reject, license and evidence rules, starting at
  [visual-inspiration/index.md](references/visual-inspiration/index.md).
- `docs/references/guides/`: adoption and migration guides, including the
  default open-source process guide in
  [default-open-source-process.md](references/guides/default-open-source-process.md),
  the v6.2 migration guide in
  [wiki-viva-v6.2-migration.md](references/guides/wiki-viva-v6.2-migration.md),
  the canonical entity navigation guide in
  [canonical-entity-navigation.md](references/guides/canonical-entity-navigation.md),
  the source refresh cadence guide in
  [source-refresh-cadence.md](references/guides/source-refresh-cadence.md),
  the template authoring guide in
  [template-authoring.md](references/guides/template-authoring.md), the
  modular template blocks (v2) concept guide in
  [modular-blocks.md](references/guides/modular-blocks.md) and the extension
  checklists (blocks, page types, docks, perspectives) in
  [extending-the-kit.md](references/guides/extending-the-kit.md), plus the
  certify-once/adopt-by-delta contract in
  [downstream-migration-two-lane-strategy.md](references/guides/downstream-migration-two-lane-strategy.md)
  and the executable v8 mechanics in
  [wiki-viva-v8-downstream-upgrade.md](references/guides/wiki-viva-v8-downstream-upgrade.md).
  That contract keeps toolkit `wiki-*` skills byte-equal in C1 and treats each
  consumer's `AGENTS.md` plus non-`wiki-*` repo-local skills as C3 routing.
  Its localized technical-page authority is derived exclusively from the
  committed `consumer_B0:wiki.config.yaml` blob and has exactly three roles:
  `command_reference_page`, `operational_pass_page` and `release_records` under
  the configured `references_root/releases/**` subtree. These are C3-only inert
  UTF-8 Markdown `100644` blobs; C1/C2 placement, executable/binary content or a
  worktree/C3 attempt to widen the authority fails closed. Plan, resumable
  state, receipt and report bind the derived-authority digest.
- `docs/references/upgrades/wiki-viva-v8/`: the package plus its sealed,
  versioned path/contract/gate
  [impact registry](references/upgrades/wiki-viva-v8/impact-registry.yaml).
- `docs/references/schemas/wiki-upgrade-package-v3.schema.json`,
  `wiki-upgrade-release-capsule-v1.schema.json` and
  `wiki-upgrade-impact-registry-v1.schema.json`: classified package,
  fail-closed Lane A capsule and impact-registry contracts. Consumer
  receipts/evidence remain ignored and untracked in each downstream repository.
  New v3 plans keep a private first-write acceptance-clock anchor and a separate
  first-write real-canary completion anchor; both SHA-256 values are carried out
  of band through resumable CI handoffs. Receipt and state bind the full
  B0/C1/C2/C3 Git chain, and the active runner interpreter is part of toolchain
  authority. The acceptance-attempt identity also binds the canonical digest
  of the complete preflight object; every resume with an execution plan replays
  C2 from C1 and verifies the full path set, Git modes and blob digests before
  reusing gate results.
  Lane A visual authority is generated from the exact clean source by
  `wiki_visual_evidence.py`, covers every declared profile with record-backed
  PNG/console/network evidence, and is independently reopened by
  `wiki_upgrade.py verify-capsule` before adoption.
  Rc21 is historical non-promotional evidence after downstream rehearsal found
  the missing config-bound C3 authority. Rc22 corrected that boundary and
  passed its pre-capture local stack, but productive Chromium capture stopped
  fail-closed when its legacy mobile route normalized to Quadrants instead of
  Timeline. No visual manifest, capsule, attestation or Lane B authority was
  minted; rc22 cannot be retried, relabeled, promoted or imported. Rc23
  corrected the native routes, but complete validation stopped on one stale
  synthetic CLI route helper before any candidate, manifest, capsule or
  adoption authority. Rc24 is the prospective unpinned validation subject.
  Existing v2 subjects and receipts remain frozen and are never rewritten into
  v3 proof.
- `docs/references/templates/`: stable models for new records.
- `docs/references/templates/wiki/`: models for the operational wiki, including
  root entities, input channels, processes, artifacts, ingestion proposal,
  decision, insight and PR checklist.
- `docs/references/releases/`: release notes, including the OKF v0.1
  interoperability release in
  [wiki-viva-v6.6.md](references/releases/wiki-viva-v6.6.md), the hierarchy
  / short-term-memory release in
  [wiki-viva-v6.7.md](references/releases/wiki-viva-v6.7.md), the
  root-entity/input-stage release in
  [wiki-viva-v6.8.md](references/releases/wiki-viva-v6.8.md), the visual
  region grouping refactor plan in
  [visual-region-grouping-refactor-2026-07-08.md](references/proposals/visual-region-grouping-refactor-2026-07-08.md),
  plus the modular
  template blocks / spatial cockpit release in
  [wiki-viva-v6.9.md](references/releases/wiki-viva-v6.9.md), the canonical
  quadrant-flight patch in
  [wiki-viva-v6.9.1.md](references/releases/wiki-viva-v6.9.1.md) and the
  quadrant terminology patch in
  [wiki-viva-v6.9.2.md](references/releases/wiki-viva-v6.9.2.md).
- `docs/references/reports/`: verification and evaluation reports, including the
  AQAL quadrant alignment check in
  [aqal-quadrant-alignment-2026-06-25.md](references/reports/aqal-quadrant-alignment-2026-06-25.md).
  The working quadrant contract and Integral/AQAL source links are summarized in
  [modular-blocks.md](references/guides/modular-blocks.md#quadrant-assignments).
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
