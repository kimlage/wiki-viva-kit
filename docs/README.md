# Docs

Updated on: 2026-07-15

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
  consumer's `AGENTS.md`, `.skills/README.md` plus non-`wiki-*` repo-local
  skills as C3 routing.
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
  `wiki-upgrade-release-capsule-v1.schema.json`,
  `wiki-upgrade-release-capsule-v2.schema.json` and
  `wiki-upgrade-impact-registry-v1.schema.json`: classified package,
  fail-closed Lane A capsule and impact-registry contracts. Consumer
  receipts/evidence remain ignored and untracked in each downstream repository.
  New v3 plans keep a private first-write acceptance-clock anchor and a separate
  first-write real-canary completion anchor; both SHA-256 values are carried out
  of band through resumable CI handoffs. Receipt and state bind the full
  B0/C1/C2/C3 Git chain, and the active runner interpreter is part of toolchain
  authority. A command-registry Python alias must resolve to that same probed
  interpreter; ambient PATH divergence fails certification closed. The
  acceptance-attempt identity also binds the canonical digest
  of the complete preflight object; every resume with an execution plan replays
  C2 from C1 and verifies the full path set, Git modes and blob digests before
  reusing gate results.
  Lane A visual authority is generated from the exact clean source by
  `wiki_visual_evidence.py`, covers every declared profile with record-backed
  PNG/console/network evidence, and is independently reopened by
  `wiki_upgrade.py verify-capsule` before adoption.
  New certifications emit capsule v2 plus `wiki_viva_toolchain_probe.v2`, whose
  five canonical entries are `browser`, `node`, `npm`, `python`, `runner`.
  They bind live Chromium, the resolved Node runtime tree, the resolved npm
  package tree, Python distributions and the exact runner closure. Capsule v1 remains
  a verification-only historical contract and is never relabeled as v2.
  Release-bearing cockpit commands run through `wiki_node_workspace.py`: its
  tracked policy v2 binds only portable package/lock hashes, package manager,
  allowlisted invocations and fixed install policy. Lane A alone captures a
  path-free external authority v1 outside Git after a forced clean install; it
  binds source, platform, resolved Node/npm and the complete dependency tree.
  Clean C1 consumes that sealed authority and digest, and every command emits a
  path-free receipt after post-execution drift verification. Another
  platform/toolchain requires a newly certified Lane A capsule, and a consumer
  never captures a replacement authority.
  Rc21 is historical non-promotional evidence after downstream rehearsal found
  the missing config-bound C3 authority. Rc22 corrected that boundary and
  passed its pre-capture local stack, but productive Chromium capture stopped
  fail-closed when its legacy mobile route normalized to Quadrants instead of
  Timeline. No visual manifest, capsule, attestation or Lane B authority was
  minted; rc22 cannot be retried, relabeled, promoted or imported. Rc23
  corrected the native routes, but complete validation stopped on one stale
  synthetic CLI route helper before any candidate, manifest, capsule or
  adoption authority. Rc24 exact source
  `39d490231c00cbc0cf0374c6b1dd3d16f23a2406` passed exact validation, its
  first-attempt four-profile productive capture and 102/102 Lane A browser
  cells. Certification nevertheless stopped fail-closed when `demo_drift` and
  `portable_python` used ambient `python3` instead of the probed Python 3.12.4
  interpreter. Rc24 is immutable `historical_certification_failed`; no capsule,
  receipt, trust or Lane B authority exists, and the subject must never be
  retried, reused, relabeled or imported. Rc25 exact source
  `c741e3d0ad409ac9baea8b136e3819952bb0657b` then failed its first complete
  validation with 1,708 passed, 3 skips and 5 public synthetic contract
  failures; its strict browser matrix was not started and no candidate,
  capture or capsule exists. Rc25 is immutable
  `historical_validation_failed`. Rc26 exact source
  `da3a9a0495db974e409f5af6413401c31851e071` passed complete local
  deterministic/browser validation, its first productive capture and every
  Lane A command, but strict public-evidence scanning rejected a host-local
  interpreter-library path in the successful Python warning summary before
  attestation. Rc26 is immutable `historical_certification_failed`; no capsule
  or downstream authority exists. Rc27 exact source
  `ba7ee19457436993edc7ff8a838b34c5b864fd98` then failed its first complete
  warnings-as-errors validation with 46 public synthetic resource-lifecycle
  failures; browser and later stages were not started. Rc27 is immutable
  `historical_validation_failed`. Rc28 source
  `31cad3bc8aa9cf45d4842103307baff678ddeeb7` was rejected before validation
  because its portable transition guides were stale. Rc29 source
  `905e377220a409bee6e1977d3c0e6262bdc27914` was also rejected before
  validation because one portable skill remained state-stale and public
  fixtures retained private-lineage labels. Rc30 source
  `bc44255b22d65b8c9869ec45759afd4dac1355b9` was pinned only for validation,
  then rejected before its complete matrix when downstream real-data visual
  QA exposed four distinct root-quadrant family controls with the same visible
  and accessible label. Rc31 exact source
  `6fa9b907d5dfc748e94d182ac3704b226142552e` passed 1,740 Python and 517
  frontend checks, then failed its first complete validation because the
  deterministic operational-pass artifact was stale. Browser and later stages
  were not started; rc31 is immutable `historical_validation_failed`. Rc32 is
  exact source `ed073dee5fbf05343b36db1fdc061a24d0220cb9` closed the
  one-write operational-pass fixed point, then its first full Python
  validation stopped with 2 contract failures after 1,744 passes and 3 skips.
  Frontend, browser and later stages were not started; rc32 is immutable
  `historical_validation_failed`. Rc33 exact source
  `539eb19b958a4159eecb2c5a7afd6ceaabcbb086` passed 1,746 Python checks with
  3 declared skips, all 517 frontend and 115 Node checks, and every applicable
  static gate. Its first strict browser matrix then stopped at 98/102 with four
  failures in 330.49 seconds: three focus-scope accessible-name/breadcrumb
  regressions and one short-phone pointer collision. The extra adapter-manifest
  diagnostic appended outside the Lane A registry was
  `inapplicable_gate/orchestration_invalid`, not an rc33 source failure. Rc33
  is immutable `historical_validation_failed`; no candidate, capture, capsule
  or Lane B authority exists. Rc34 exact source
  `533d286869c478bd157b066d7882388b99fde2f7` passed its wholly new exact
  validation at metadata subject
  `2afd435c7cc955ae7a922b1d46eac355472ca0e6`: 1,746 Python checks with 3
  declared skips in 1,113.61 seconds, all 518 frontend and 115 Node checks,
  every applicable static gate, and first/only strict browser run
  `public-mrlafqnv-689884b2-50ea-4a30-bb21-9eb2c776f861` at 102/102 with no
  failure, skip, retry or flaky cell in 6.5 minutes. Its separately reviewed
  candidate metadata subject was
  `59be853af5416ce84c4ca89e7272bb64eb909b2b`, but read-only downstream QA
  exposed RT-170 before productive capture or certification. Rc34 is immutable
  `historical_precapture_rejected`; no visual manifest, certification, capsule,
  receipt, trust anchor or Lane B authority exists. Rc35 exact source
  `52491dfd6c3a81f0356fb64a9e01e41dd71e07a0` passed its wholly new exact
  validation at metadata subject `55910c379b64060451fb8fb93eb85d47b9245122`:
  1,754 Python checks with 3 declared skips in 1,271.55 seconds, 518 frontend,
  115 Node, every applicable static gate and first/only strict browser run
  `public-mrlderie-ab48db4f-1355-47e9-bdc2-69f96f4bda85` at 102/102 with no
  failure, skip, retry or flaky cell in 386.565 seconds. Its separately
  reviewed but uncommitted local-QA candidate package-file/canonical/tree
  identities were `3cea5015...` / `e7a3c448...` / `1c8e6f69...`, 521 entries;
  no candidate metadata subject was committed. The RT-170 fix
  makes B0 `diff_check`-only, records expected drift as prospective C1
  inventory, keeps final C3 `toolkit_drift` and `semantic_inventory` mandatory,
  roots ignored evidence at the exact plan-path parent, and requires domain
  preparation before a new B0. Pre-capture static review plus focused public
  synthetic tests then exposed RT-171: capture record v1 and canary summary v1
  did not bind the exact native view/runtime/`canary_viewport` contract. Rc35 is
  immutable `historical_precapture_rejected`; its exact validation remains
  historical evidence, but no capture directory, visual manifest, capsule,
  receipt, downstream plan, import or Lane B authority was created.

  Rc36 exact source `8f96e1fd58258df64174229d81ee6a330ba9d2b1`
  passed its first and only complete exact validation at metadata subject
  `3db3f9f43c8e73fe583b93fba4ea6b9f63bdc5bd`: 23/23 recorded gates, 1,782
  Python checks with 3 declared skips in 1,082.23 seconds, 518 frontend checks,
  123 Node checks and browser run
  `public-mrlis0t7-bfd938c4-5799-4c19-b7b0-e7df20d75651` at 102/102. Those
  receipts remain valid historical evidence. Their validation result /
  toolchain / runner-payload identities are `5585819e...` / `6728f464...` /
  `03a75c40...`; validation-subject package-file / canonical-package /
  portable-tree identities are `47c3dc7d...` / `81a3b600...` / `53ffdf8b...`.
  Corrected candidate package-file / canonical-package / portable-tree
  identities are `8343066a...` / `8ee7e597...` / `4dc31eff...`. Candidate metadata
  subject `ac0f49afe28a5bf84003b58c537ac1727dab7008` produced four-profile
  manifest `6199d1001ba98c2c772323069765ddc695cc8971f6d7e03390e496de64551808`,
  then its first/only Lane A run stopped fail-closed at 101/102 browser cells on
  RT-172: camera settlement lagged the released spatial cue after desktop
  dense-stress drill-down and back. Certification stream / browser gate log /
  browser run result / Playwright report are `a95d7085...` / `2d5405db...` /
  `2b1c678a...` / `bb69c7ac...`. Rc36 is immutable
  `historical_certification_failed`; no capsule, receipt, attestation, trust
  anchor, downstream plan, import, adoption or Lane B authority exists. Never
  retry, reuse, relabel, promote or import it.

  Exact source `d87af15b4aa850d1a50dc867f74e07ba09d0e89f`
  passed rc37's first and only complete validation at metadata
  `775fe5bc9437da5ec9311704731f4342d515fc16`: 23/23 gates in 1,652 seconds,
  including 1,782 Python passes plus 3 declared skips, 522 frontend passes, 123
  Node passes and browser 102/102 first-attempt with zero skip or retry.
  `wiki-viva-v8-rc37` / `candidate` had package-file / canonical-package /
  portable-tree identities `6d409da4...` / `1af897ce...` / `77799ece...` (521
  entries), with `package_is_pinned=true`. Its productive manifest
  `3be7599a...`, Lane A 11/11 and capsule/receipt/attestation
  `f5ae8e04...` / `90cd0c27...` / `c7a1a4fe...` remain immutable rc37
  history. RT-173 was then exposed by the first disposable clean C1: the Git
  projection had no `node_modules` and no sealed materialization authority, so
  its Node C2 generator could not resolve TypeScript before an untrusted manual
  `npm ci`. Rc37 remains verifiable historical evidence, not executable Lane B
  authority. The still-unnamed successor owns the only current scoreboard at
  `0/5`: source pin, exact validation and capsule verification are pending;
  private canary and private-main readback are blocked. Draft PR
  #61 is stale and does not represent this local truth; public push/publication
  remains unauthorized. Private PR #211 remains historical v2, and a fresh v3
  adoption starts only after the RT-173 successor capsule verifies fail-closed.
  Standing private-main approval is downstream-only and never weakens gates or
  the generic public PR/human gate.
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
