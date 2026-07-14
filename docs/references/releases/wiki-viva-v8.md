---
title: "Wiki Viva v8 rc22 local validation checkpoint - rc21 historical"
page_id: release-wiki-viva-v8
page_type: release_note
context: system
visibility: public_candidate
updated_at: 2026-07-14
stale_after_days: 365
sources_policy: release_note
gate: github_pr
sensitive_data_policy: no_personal_data
---

# Wiki Viva v8 rc22 local validation checkpoint - rc21 historical

## Rc22 exact local source — capsule not yet minted

Exact source `7e72664fb6871d906addbddb6ed5b2e7f1fec33c` implements the
config-bound three-role C3 authority, productive record-backed Chromium capture,
independent `verify-capsule`, fail-closed impact selection, resumable C1/C2/C3
adoption and fd-pinned evidence reads. Its final local stack passed 1,703 Python
tests with 3 declared skips and 2 known fork warnings, 516 frontend tests, 115
Node gates, both audits with 0 errors, methodology/operation/input/semantic,
26-payload snapshot and pack validation, and the 102-public-plus-2-downstream
matrix contract. The integrated upgrade/security subset passed 375 tests with
3 declared skips.

The `wiki-viva-v8-rc22` `validation_pending` package SHA-256 is
`20a92e19eba537acf411e5d9d01b65adad5f71ca8e7634e81cd6764d8d1e9e0c`;
its 521-entry portable tree is
`7e70e7b3f457374624e4ef2656deb131318336228b848706f2b38ff2954cfb03`.
The command, impact and boundary-operation registry SHA-256 values are
`85993dd5637f90539e9ff7318b7aadfbca3cbced897d651fc42ceae695375ea7`,
`663ab77840d43011856dc79a3c3f718cb3da874e179600a99a668e5e47572315`
and `f8ac0ad44fa0b29c3c0142fa86b8c62d0af060aa7b1b227d44183aadb3de573a`.
The runner identity is
`wiki-upgrade 1.3.0+payload.136b58c2dd34e7f473a59452eb7c1bd1becd0b64667981eb9aad707b493d803f`.

These are local validation identities, not production release authority. No
rc22 Lane A capsule, trusted production attestation, public push, remote CI,
human merge or tag is claimed at this checkpoint. The current private v2
receipts remain unchanged.

## Rc21 historical validation evidence — promotion prohibited

Status on 2026-07-14: **exact public source
`db3bba4957f551cc7c2d261561a45d0c606fdd05`, packaged locally as
`wiki-viva-v8-rc21`, passed its then-declared deterministic and 102/102
first-attempt browser stack. RT-152 later froze that subject as historical
non-promotional evidence. It remains unpublished, has no production Lane A
capsule and must not be promoted, imported, relabeled or used as downstream
adoption authority.**

Rc21 superseded rc20 only at its historical RT-151 validation checkpoint.
Real-data downstream QA had exposed that defect in rc20: at 390 x 844,
filtering, selecting and scrolling the Timeline could visually interleave the
result list and inspector because constrained grid rows collapsed while their
children overflowed. The private pixels, paths, routes and content remain
private. Rc21 reproduces the defect with a public synthetic fixture, uses
normal mobile block flow and one scroll model, and requires DOM/visual order,
containment, readable selected detail and zero horizontal overflow after the
same interaction. Rc20 and rc21 are immutable historical diagnostic evidence;
neither may be promoted or imported.

The exact rc21 local evidence is: both audits at 0 errors / 7 known staleness
warnings; methodology, operation, input-stage, semantic-inventory, 26-payload
snapshot and pack contracts green; 1,632 Python passes with 3 declared skips
and 2 known fork warnings; 516 frontend passes; 115 Node gate passes; zero
architecture debt; licensed assets with 0 external entries; 163.32 kB initial
JavaScript gzip; a 102-public-plus-2-downstream matrix contract; and 102/102
public browser cells on the first attempt with 0 skips / 0 retries in 6.3
minutes. The run-result, gate-result and Playwright-report SHA-256 values are
`70d79029853da8e8ca9a3df8469db39a7668a41b87954736d55826bf64b270c7`,
`d6fbba509bdb236c32af5c9724bfee4a8cbbadc16ec466463dcc13947f66941c`
and `85a1770378364999eb0eb8c0963d4679daa155e5a87adea4b775a97c068b3a18`.
The canonical package SHA-256 is
`65c4e679a43f40c3c91bd38b7d6fa283ba2f329e39731115384a2fa83b527891`;
the 520-entry portable tree is
`1039a8d4ef641a7e9ec9a30283df6914dbc4157aeeb45b26bae16badd9965472`.
The command, impact and boundary-operation registry SHA-256 values are
`e3ae2e664637ca87fd08d2a1db169245594153b68badba9694cfcde3bff3a7c0`,
`ccd3f53eee8ccf3328a820dfe9e2a6c73f1056a9e54a0d88b3380d0224e70629`
and `23c970d79b731280c4a0e9d775cc37017335e453dc36b69f318d66b8659fc308`.
These are historical local identities only; no production capsule was sealed.

The rc21 package names the following exact portable contracts:

| Surface | Contract |
|---|---|
| Route / snapshot / envelope | `wiki_world_route.v8` / `wiki_web_snapshot.v2` / `wiki_web_snapshot.v2` |
| Blocks / visual grammar / semantic visual tokens | `wiki_templates.v2+wiki_web_block_stacks.v1` / `wiki_visual_grammar.v8` / `wiki_semantic_visual_tokens.v1` |
| Appearance / runtime / source lifecycle / freshness / server | `wiki_cockpit_appearance.v1` / `wiki_world_runtime.v8` / `wiki_source_lifecycle.v2` / `wiki_web_freshness.v1` / `wiki_web_server.v6` |
| Timeline / temporal event / temporal graph | `activity_timeline.v1` / `wiki_temporal_event.v1` / `wiki_temporal_graph.v1` |
| Experience pack / registry / lock / composition | `wiki_experience_pack.v1` / `wiki_experience_pack_registry.v1` / `wiki_experience_pack_lock.v1` / `wiki_experience_pack_composition.v1` |
| Asset / downstream adapter manifests | `wiki_cockpit_asset_manifest.v1` / `wiki_downstream_adapter_manifest.v1` |

The new `wiki_viva_upgrade_consumer_c3_authority.v1` contract belongs to rc22,
never rc21. Exact rc22 source
`7e72664fb6871d906addbddb6ed5b2e7f1fec33c` binds that contract to public
synthetic fixtures and the complete local stack, but remains
`validation_pending` without a capsule; it inherits no rc21 status or receipt.

Any future rc22 publication still requires explicit authorization, remote
public CI, human conceptual/privacy/VoiceOver review and merge, followed by a
separately reviewed promotion boundary that can mint Lane A release authority.
External E5 and a release tag remain separate. The in-flight private v2
migration keeps its original full blocking matrix and receipts; neither rc20,
rc21 nor the local rc22 checkpoint reclassifies, reduces or rewrites that
evidence.

## Historical rc8-era evidence — preserved without current authority

Status on 2026-07-12: **metadata envelope rc8 pins an exact public S9 payload
whose full automated public and redacted private stacks pass. Release remains
blocked by the remaining consumer-semantic evidence, human review/merge,
VoiceOver, tag authority and external E5**.

Historical payload `S` remains pinned to
`b781882a11e8bbac3ae9684d199979a1f4ee1bf7`. The first clean-subject browser
attempt exposed 18 genuine and test-contract regressions (**84/102 passed**).
After the route-authority, browser-contract and mobile-geometry corrections
were committed, the exact public wrapper passed **102/102 on the first attempt,
with 0 skips and 0 retries in 5.8 minutes**. The retained run result is
`public-mrha530b-79ce7ec4-2880-4244-a30e-6e9b429627fd/run-result.json` under the
local release-run evidence directory.

The previous downstream-pressure payload is
`S2=f0936539ca44c34ff5eacf5817b22ff9451b9cef`, pinned by package
`wiki-viva-v8-rc3`. It adds portable/config-driven docs and skills, acyclic
source consolidation rules, a one-time content-bound adoption receipt for
pre-gate action history, exact rollback execution/report parity and a resolved
demo person link. Exact `S2` passed **1,355/1,355 Python tests**, **489/489
frontend tests**, **106/106 Node gates** and **102/102 first-attempt browser
cells with 0 skips / 0 retries in 6.4 minutes**. The retained browser result is
`public-mrhf7c6i-d57c7e0c-dfde-43bf-925c-576ce411ff9a/run-result.json`.

Real downstream pressure then exposed a final parser and navigation boundary.
`S3=8904d69daab1803043a89e553d78b95b57d2022f` made action YAML readable by
both the structured and flat frontmatter parsers and passed 1,356 Python tests,
but its exact browser run was rejected at **101/102**: a real operator manifest
could finish between a direct `popstate` and React's later demo-render cleanup.
The then-current historical payload was
`S4=f7c9d0ad837b303e388b3b1c1dbaaeff9df3b1bb`, pinned by package
`wiki-viva-v8-rc4`. It aborts the live read on the navigation notification
itself and requires same-turn abort for external history writers. Exact `S4`
passed **1,356/1,356 Python**, **489/489 frontend**, **106/106 Node** and
**102/102 first-attempt browser cells with 0 skips / 0 retries in 5.9
minutes**. Its retained browser result is
`public-mrhi2oel-b9899085-eb90-4b27-b9fd-4f265fee8fcd/run-result.json`.

Downstream attestation then exposed two more public P1 boundaries. Immediate
predecessor
`S5=605ad66b9d9a011505704c72be506e03e680583a` replaces the non-portable
`../../LICENSE` asset reference with the shipped
`assets/FIRST_PARTY_ASSET_LICENSE.md` license artifact (RT-138) and makes the
downstream E2E recompute pack composition with the `presentation` contract
included (RT-139). Exact `S5` passed **1,356/1,356 Python**, **489/489
frontend** and **106/106 Node** controls together with the deterministic
non-browser gates. The then-current historical browser-closure payload was
`S6=b852a992afa3eae64e220c461c2eff052572377c`, pinned by package
`wiki-viva-v8-rc5`. It closes RT-140 by classifying requests against their
route at both start and finish, and by forcing a live-to-demo transition in the
observer test instead of counting legitimate pre-transition traffic as a demo
leak. Exact `S6` passed **102/102 browser cells on the first attempt, with 0
skips and 0 retries in 6.0 minutes**. Its retained browser result is
`public-mrhjnxhu-0b3e0e14-d9d3-430c-9b11-8c03b3bb3fed/run-result.json`.
Exact `S6` also passed **1,356/1,356 Python tests in 346.27 seconds**, with
the two known multiprocessing-fork deprecation warnings. The `S5`
deterministic counts remain preserved on their original subject even though
the unchanged Python surface was repeated successfully on `S6`.

Two downstream proof-contract corrections follow rc5. Exact
`S7=fa83a70500b3b1d27074c54e70893405d61d9b87` closes RT-142: the verifier no
longer invents `pages.snapshot_id`, attests `pages.json` through manifest
integrity, and accepts `action_state_canonicalized` plus
`action_contract_updated` in the temporal vocabulary. Exact
`S8=d0a6168cf8aa291d79047c28a0c61eb274b973f9` closes RT-143 by observing the
atomic `/api/snapshot/boot` envelope the cockpit actually consumes instead of
waiting for a deprecated manifest/pages/experience-pack fan-out. Exact S8
passed **102/102 public browser cells on the first attempt in 5.9 minutes with
0 skips/retries**; the paired adopted private S8 subject passed **2/2 mandatory
downstream cells on the first attempt with 0 skips/retries**. Those receipts
remain evidence for S8 only.

The then-current historical payload was
`S9=b45378d37e96eed04fb355392d10bd8471c5fda7`, pinned by package
`wiki-viva-v8-rc8`. It closes the implementation side of RT-144 after real
390x844 inspection found that all five view controls stayed inside the
document but their labels overflowed their own 60 px buttons. Mobile CSS now
hides view icons and tightens gap/padding; the Timeline geometry regression
requires exactly five controls and zero inner-label overflow. Exact S9 passed
**102/102 public browser cells on the first attempt with 0 skips/retries in
6.0 minutes**; retained result
`public-mrhlap2k-c82be0c1-a378-4faf-a558-28d397bdfbad/run-result.json`. It also
passed **1,356/1,356 Python tests in 380.02 seconds** with two known
multiprocessing/fork warnings, **489/489 frontend tests across 62 files in 3.13
seconds**, **106/106 Node gates in 12.46 seconds**, build, zero-debt
architecture, assets with 0 external entries, bundle at 162.38 kB initial
JavaScript gzip, release-matrix inventory 102+2, both audits at 0 errors/6
known warnings, methodology, operation, input, deterministic demo, 26-payload
snapshot contract and pack validation. Its payload tree is
`d39bff5c4b5b9dbe9ee09be2264682cd3ed418bf`; SHA-256 evidence hashes are
`88ea56ac9a57654e0ac57c1e59d8db081d72019e4df9e06a81b8acb3cdfedc28`
(run result),
`7b5fbe0b3e57fdc1191a376c663ba4783ac084c4b2a7018be02d37400a913026`
(gate result) and
`7d1ec18b3d33d353e33657e02e61f5460e5ddcae7e9457b38f4b5a90a4ea398e`
(report). The isolated snapshot API also passed against 49 public pages.

The private S9 subject passes **2/2 mandatory downstream
cells on the first attempt with 0 skips/retries in 7.8 seconds**; redacted
preflight aggregates are 562 pages, 772 temporal events, one active pack and
one adapter file. Manual 390x844 reinspection measured five 62 px controls
with `clientWidth == scrollWidth`, zero inner/document overflow, 44 px minimum
height and hidden icons. The same clean private subject passed **1,117 Python
tests with 1 explicit skip and 0 warnings in 144.62 seconds**, **489/489
frontend across 62 files in 3.74 seconds**, **106/106 Node in 14.398 seconds**,
build, zero-debt architecture, assets, 162.38 kB initial JavaScript gzip,
audit at 0 errors/35 known warnings, methodology, operation, input,
deterministic demo, 26-payload snapshot contract and packs. No S8 result is
promoted across this subject boundary; public and private S9 were executed
independently.

The official read-only downstream upgrade preflight, consuming gate evidence
bound to that clean private subject, is **ready with 0 blockers**, toolkit drift
0, all five required pre-import gates passing, a real snapshot and one expected
`local_overrides` warning. The redacted report remains in the private ignored
evidence cache; its SHA-256 is
`0e38c895350097485f701f8a2285ed604d4744f626b4db34fef3a62bc9614e23`.

Historical exact `S` passed **1,339/1,339 Python tests, 0 skips, in 355.06
seconds**, with two multiprocessing-fork deprecation warnings. It also passed
**489/489 frontend tests across 62 files**, **106/106 Node gate tests**, the
production build, architecture, asset, snapshot, pack, demo, bundle and matrix
checks. Initial JavaScript is **162.38 kB gzip**. Normal and public-export audits
report **0 errors and 6 freshness warnings** caused by the date crossing
midnight, not privacy or contract failures.

This evidence promotes only the historical subjects named by each receipt.
Browser closure is
not a full-release receipt and does not self-attest Python, private data,
product approval or E5. The allowlisted private S9 adoption and its two
mandatory browser cells plus both complete deterministic stacks are now
proven. [Draft PR #61](https://github.com/kimlage/wiki-viva-kit/pull/61)
still requires human review and merge; no tag is authorized yet.

## Historical rc8 correction lineage — public payload candidate at that checkpoint

The active correction contract at that checkpoint was the
[release truth, temporal world and experience packs plan](../proposals/wiki-viva-release-truth-temporal-world-experience-packs-plan-2026-07-11.md).
It consolidates the independently reproduced parts of the interrupted parallel
Claude review, but not its raw local transcripts, stale task cards or
coordinator label. Nine live process/filesystem checks found no newer
Claude-authored plan,
repository write or completed verifier set; a still-running worker/preview is
not treated as project progress. The eighth check also confirmed that a clean,
detached Claude worktree contained only historical July 1 material, not a
hidden July 11 implementation.

The ninth checkpoint recovered the already-completed structured workflow
behind the visibly rate-limited Claude session. Revalidation produced two real
residuals, both closed in `S2`: canonical rollback must bind and execute exact
reverse-order migration SHAs, and Markdown must expose the same regression
fixtures as JSON. No Claude write was merged mechanically.

The public payload adds an exact public/downstream Playwright collection,
hash-bound toolchain and worktree subjects, a browser-only receipt, fail-closed
demo/transport and atomic snapshot activation controls. Adversarial rereview
reopened asynchronous GET, responsive layout, revision inventory,
cleanup/durability and evidence-ownership boundaries before the final freeze.
The implementation ledger has no unassigned public P0/P1 through RT-144. The
checked-in matrix records 102 public cells and 2 mandatory downstream cells;
exact S9 passed both halves independently on their paired subjects.

### Exact public subject evidence

The rc8 metadata overlay at that checkpoint pins exact `S9`. Its public ledger passed
**1,356 Python**, **489 frontend**, **106 Node**, **102/102 browser** and every
deterministic release gate; its private adoption ledger passed **1,117 Python**,
**489 frontend**, **106 Node**, **2/2 downstream browser** and every private
deterministic gate on a clean subject. Historical rc5/S6 passed **102/102
browser** and **1,356 Python** on its own subject, while S8 passed the complete
102+2 browser split on its paired historical subjects. Historical rc4/S4 and
all earlier counts below remain attached to their original subjects and are not
rewritten.

- Exact S9 frontend unit/component suite: **489/489 passed across 62 files in
  3.13 seconds**.
- Playwright collection: **102 public cells in 17 specs** plus **2 downstream
  cells in 1 spec**. Exact S9 passed 102+2 on paired subjects, first attempt,
  with zero skips/retries; **106/106 Node gates** also pass.
- Executable public demos: **7 isolated base scenarios**, **22 bound claims**
  and **12 canonical `/demo/w` routes**, plus all 9 Genesis stages (0–8).
- Pack showcases: Study/Research has **6 pages, 11 events and 4 pack-owned event
  kinds**; Personal Finance has **11 pages, 19 events and 5 pack-owned event
  kinds**. Both temporal payloads report zero diagnostics.
- Final frozen deterministic evidence: **1,339/1,339 Python tests**, **0 skips**
  in **355.06 s**, with 2 fork deprecation warnings; **489/489 frontend**;
  **70** action lifecycle, **65** action audit, **6** action endpoint and **113**
  snapshot/demo controls; **165** focused RT-133 reviewer controls; **42/42**
  assets; **26** snapshot payloads. Production build and bundle pass with
  initial JS at **162.38 kB gzip**. Normal/public audits report **0 errors / 6
  freshness warnings** after the date crossed midnight.

RT-35 is closed at the P0/P1 implementation-review boundary: external
HEAD/ref/index and dirty/config/wiki/pack fingerprints, linked worktrees,
same-size rewrites, two-client conflicts, focus/demo-return, failure and
removed-page behavior have deterministic controls. Focus/visibility refresh is
implemented; continuous idle polling remains P2. Action state truth is a
closure candidate: receipt v2 binds exact monotonic transitions and terminal
time across tracked moves/deletes, clears incompatible fields, governs
malformed base records and remains compatible with v1. Typed `gate_type`,
`blocker_type`, `unblock_condition` and terminal waivers are future contract
work, not v8 claims. RT-133 is also a closure candidate: rejected history rows
cannot advance causal state, state-preserving receipts use truthful kinds and
canonical receipt IDs, and the regenerated 141-event graph has zero dangling
references and zero false same-state transitions. Causal self/cycle/time-
direction checks and a future paginated API full-graph attestation remain
explicit P2 work.

The rc5 pressure pass additionally closes RT-138, RT-139 and RT-140 at the
public P1 boundary: every first-party asset license now exists inside the
portable asset tree, downstream composition recomputation includes pack
presentation, and the browser observer measures the actual live-to-demo route
boundary. RT-141 remains a non-blocking P2 hygiene item: the runtime
`.wiki-viva/pack-operation.lock` file still needs a portable ignore contract.

S7 closes RT-142 by aligning downstream proof with the actual pages integrity
and canonical action-event contracts. S8 closes RT-143 by observing the atomic
boot envelope actually consumed by the UI; its exact public/downstream browser
receipts remain S8-only. Private S9 repeats both contracts in 2/2 mandatory
cells, and exact public S9 passes 102/102. S9 implements RT-144's 390x844
inner-control overflow repair and regression; public browser plus private
manual geometry are closed.

RT-145 is a non-blocking P2 observability item found during that manual pass:
closing/reloading a client while a large `/api/snapshot/boot` body is being
written can log full `BrokenPipeError`/`ConnectionResetError` tracebacks. It did
not affect UX or gates. A future narrow write/flush guard must quiet only these
expected disconnects and retain visibility for serialization and unexpected
server errors, backed by an aborted-client regression.

The architecture extracted from Claude's interrupted review has been
independently replayed: collection compilation is shared, graph deduplication is
indexed, demo construction no longer monkeypatches private snapshot functions,
and one runtime route writer owns shareable state. The remaining extension
boundary is deliberately honest: `sceneSystems`, `relationTypes`,
`operatorCommands` and `effects` are declarative descriptions, not a supported
plugin ABI. A future versioned `wiki_runtime_extension.v1` contract must bind
ownership, consumers, capabilities, accessible fallbacks and rollback before
those registries can be advertised as installable runtime extensions.

The independently revalidated Claude design material is consolidated as future
kit direction rather than rc8 release evidence: **Setup Studio** for visual
pack/block composition, a pack-extensible **contract interview wizard**, the
calmer **Quiet Reference Library / Knowledge Garden**, and optional **Module
Orbit + bento docks** with a complete accessible 2D counterpart. The pack
roadmap explicitly covers finance, teams, PDLC, notes, studies and references;
each remains a separate versioned pack series with synthetic fixtures, temporal
profiles, operations and rollback.

## Historical candidate checkpoint

The major rendered review payload is `4e4ee631`; `3e5c0867` adds the
downstream preflight safety boundary, `5179dc5c` makes nested centers
relation-aware and `27f3b369` refreshes the deterministic snapshots against
that final portable contract. `206da2ca` keeps the same guide valid in both
demo and real-operator routes; `d2ddcb5f` closes the final downstream review by
scoping every local world to its compiler-owned members, preserving inherited
quadrant projections, fixing Focus center ownership and refining long fallback
labels; `487f7935` closes the last responsive review with one vertical fallback
scrollport and no horizontal/document overflow. `fa65d5f9` closes the final
upgrade audit by honoring wildcard-bearing portable skill allowlists, with
synthetic block-precedence coverage. `3813ff45` through `5b09ca0b` add explicit
collection membership without rewriting hierarchy, canonical action-state
authoring, nested canonical-source discovery, generic collection-capable
anchors and Node 24-backed CI actions. `2da6c73a` closes the final integrity
review: generated artifacts are idempotent, action has one schema declaration,
and scene LOD uses the full scoped-world count before strict performance QA.
`d27bf316` moves the retained browser-evidence upload to the official Node 24
action after the final CI surfaced the last deprecated-action warning.
`cfa32594` closes the P0 rendered-navigation blocker: every Alex quadrant now
contains reachable real pages, technical buckets are translated into semantic
collections with counts/descriptions/examples, group navigation cannot loop to
itself, recenter resets the lens, and the same runtime/canvas survives the
complete journey. The same payload makes the canonical action template and
demo author `action_state`, valid ownership, next action, priority/attention
basis, blockers and terminal receipts under one validated contract. It also
normalizes semantic family target IDs across the 3D and adaptive 2D renderers;
when a measured WebKit session falls back for performance, the same collection
and real-page journey remains touchable without pretending the canvas survived.
`b942735f` closes the real short-mobile hit-collision blocker found during the
final in-app Browser audit. It preserves the five disjoint 44 px semantic
landmarks introduced by `39b28fe8`, and extends the regression to a dense
synthetic center with repeated families across quadrants and multiple families
inside Q2. In both worlds, the visual hit target resolves to the intended
group and every mouse/keyboard activation preserves quadrant, breadcrumb,
collection and the same runtime/canvas. Resolved Markdown links remain proven
by mouse and keyboard without remounting the world.
`1d801f1c` closes the source-hierarchy integrity blocker discovered in the
in-app Browser: generated ingestion events now use their canonical source page
path, or the canonical source ID fallback, as `moc_parent`. The source registry
therefore remains a source-only collection instead of flattening normalized
events into its hierarchy.
`a483ad02` closes the final reader-navigation P0 discovered while traversing
registry -> source -> event: the persistent reader resets its internal
scrollport before each page paints, and wide Markdown tables remain readable in
an accessible, keyboard-focusable horizontal scroll region without creating
document overflow or per-character wrapping.
`d4a3c890` closes the remaining tall-mobile P0 found at `390x844`: semantic
group landmarks keep disjoint 44 px native controls and stable per-quadrant
lanes on both short and tall phones, including repeated families in real
downstream worlds. The regression covers both heights, hit-testing, overflow,
collection progress and canvas continuity.
`f7f95119` closes the WebKit/Linux route race found by remote visual CI: a
query debounce can no longer replay the pre-close Create dock over an
Enter-opened reader. The submitted marker is bounded to the uncommitted query,
stays active for that exact draft until a genuine edit, and is never retained
when the query had already committed, so the same search remains reusable.
`877b586b` closes the desktop counterpart of the semantic-group blocker found
in the final downstream Browser audit. Stable quadrant/family lanes keep every
full explanatory group target disjoint at `1280x900`, including repeated Q2
families and the Q4 area/content pair, while preserving the same phone contract
at `390x664` and `390x844`. The regression waits for the authored spatial
transition to settle, then proves pairwise geometry, native hit ownership,
mouse/keyboard collection progress, breadcrumb/lens truth, no document scroll
and one persistent canvas in the instructional and dense synthetic worlds.
`dbd158a4` closes the final adaptive-fallback blocker surfaced only by the
private Linux/WebKit run. Phone offsets authored for projected 3D labels are
now explicitly disabled for the semantic 2D map, so `family:source` and
`family:event` remain untransformed, scrollable and touchable after the measured
`performance_budget` transition. The strengthened test preserves the scene
shell, accepts only a one-way canvas-to-map change, waits for outgoing
reader/collection surfaces, and revalidates every Q2 target in the active
renderer rather than assuming the session stayed in 3D.

## Product boundary

v8 consolidates the cockpit into one center-relative living world:

- real pages are entities; quadrants, regions, lenses, overlays and UI surfaces
  are projections/controls;
- `WorldRuntime` and a pure reducer own semantic state and transitions;
- registered interactions distinguish inspect, select, read, recenter and
  operator execution;
- an atomic, integrity-checked snapshot envelope prevents mixed revisions;
- runtime registries actively own interactions, views, overlays, surfaces and
  visual primitives; scene-system/effect/command/relation entries remain
  declarative-only descriptors, while renderer modules, injected operator
  ports and the backend relation vocabulary are the current executable owners;
- source lifecycle, freshness and last attempt remain separate;
- collections add typed `collection_member` edges and linked sub-worlds while
  keeping `moc_parent` as the canonical location contract;
- quadrant family handles are density controls only: each explains a semantic
  collection and reaches a reader or real center in at most two steps without
  inventing a page, stale breadcrumb or second canvas;
- action pages expose canonical runtime state, ownership, next action,
  blockers, priority and completion/cancellation receipts without discarding
  useful editorial `status` wording;
- a primary-surface contract keeps quadrant/HUD instruments behind readers and
  docks, while the reader exposes decision-ready action facts before prose;
- one semantic motion grammar drives CSS and WebGL view/lens/travel/retreat
  timing, per-entity overlay resolution, reduced-motion cuts and real surface
  enter/exit presence without remounting the world;
- static demo, localhost operator and private adapter have explicit capability
  and security boundaries.

The architecture contract is documented in
[wiki-viva-v8-runtime-architecture.md](../guides/wiki-viva-v8-runtime-architecture.md).

## Source lifecycle authoring

Source pages author v8 telemetry in the nested `source_lifecycle` block. The
flattened `source_last_attempt_state` and `source_pipeline_stage` fields remain
readable for early-v8 compatibility. When both shapes are present their
normalized values must agree; a conflict is a publication error rather than a
precedence rule that can hide contradictory source truth.

`last_attempt_state` accepts `never`, `ok`, `failed`, `needs_auth`,
`parser_error` and `secret_blocked`. When reused in an authored last-attempt
field, the legacy sync values `partial`, `running` and `queued` normalize to
`failed`, `ok` and `ok`, respectively, and produce a non-blocking authoring
warning. `pipeline_stage` accepts `configured`,
`manifested`, `extracted`, `indexed`, `deep_read`, `proposal_ready`,
`integrating`, `gate_pending` and `complete`.

Unknown values are not translated or replaced with a healthy default. The
frontmatter audit reports the safe field and alternatives without echoing a
secret/PII-shaped value; the snapshot contract repeats the validation and still
refuses atomic publication if the authoring audit was bypassed. Accepted and
reviewed-no-change states require their evidence closures and
`state: ingested`; blocked sources require a failure attempt, pending adoption
and a safe reason. Lifecycle, pipeline and adoption use explicit transition
tables. Existing-source changes remain fail-closed until the next wave adds an
atomic append-only receipt writer; first canonical adoption and new sources
remain valid when the complete declaration passes.

## Versioned contracts

| Contract | v8 version |
| --- | --- |
| Canonical route | `wiki_world_route.v8` |
| Snapshot/envelope | `wiki_web_snapshot.v2` |
| Templates/block vocabulary | `wiki_templates.v2` |
| Resolved block stacks | `wiki_web_block_stacks.v1` |
| Visual grammar | `wiki_visual_grammar.v8` |
| Semantic visual tokens | `wiki_semantic_visual_tokens.v1` |
| Runtime | `wiki_world_runtime.v8` |
| Source lifecycle | `wiki_source_lifecycle.v2` |
| Freshness payload | `wiki_web_freshness.v1` |

The authoritative machine list is
[upgrade-package.yaml](../upgrades/wiki-viva-v8/upgrade-package.yaml).

## Route migration

Every canonical writer emits `/w?view=<view>...` (or `/demo/w?view=<view>...`).
The positional forms below are compatibility inputs only: parsing remains
supported, while the next canonical write normalizes them and records
`runtime=compat` where needed. A positional context that is still required by
the compatibility projection moves to bounded `compat_context=...`; it is not
dropped and native v8 routes do not author it. Malformed percent escapes fail
closed to the nearest safe world/alias instead of throwing. Packet and Missions trays are URL-owned as
`tray=packet|missions`; reader, dock and tray share one primary-surface slot,
with deterministic `dock > reader > tray` precedence for hand-written
conflicts.

| Legacy input | Canonical v8 state | Compatibility |
| --- | --- | --- |
| `/w/quadrants/...` | `view=quadrants` with explicit center/lens/overlay | Read and normalize through v8. |
| `/w/radar/...` | `view=radar&overlay=freshness` | Preserve the freshness question. |
| `/w/districts/...` | `mode=compat&view=districts&lens=type&overlay=actions` | Direct links retain the legacy geometry even when native navigation hides it; no native view is falsely selected. |
| `/w/trails/...` | `mode=compat&view=trails&lens=relations&overlay=evidence` around a real center | Direct links retain the ego-graph identity; a missing page normalizes to root with warning. |
| `quadrant=<id>` | `lens=<quadrant-id>` | `lens` wins when both exist. |
| short `intencao/pratica/relacoes/sistemas` | `q1_intencao/q2_pratica/q3_relacoes/q4_sistemas` | Legacy read, canonical write. |
| `group=region:*` | real `family:*` group or ephemeral visual focus | Never written by v8. |

## Breaking and operational changes

- Components no longer own semantic navigation/transport in the native runtime.
- New docks/interactions are registry modules, not manual branches across the
  router, app shell and command bar.
- Snapshot consumers must validate revision, hashes, capabilities and schema
  versions before committing state.
- Optional reader/diagram/operator/specialized capabilities must be genuinely
  lazy and respect public bundle budgets.
- The current core reader exposes fenced Mermaid as source only. Diagram
  execution/rendering remains an uninstalled experience-pack capability, not a
  release claim.
- Local/private overrides extend public contracts but cannot weaken semantic,
  privacy, secret, operator or sample-fallback invariants.
- Downstream imports require an inventory, read-only preflight, portable
  allowlist, three commit boundaries, migration report, rollback point and
  redacted visual QA.

## Upgrade and rollback

Use the [v8 downstream runbook](../guides/wiki-viva-v8-downstream-upgrade.md).
Its tools validate inventory, compile preflight, enforce allowlist/blocklist and
produce deterministic JSON/Markdown migration reports. First-line rollback is
`runtime=compat`/`legacy`; second-line rollback reverts adaptation, artifact and
import commits while preserving downstream configs and memory roots.

## Compatibility window

Legacy routes, quadrant aliases and block vocabulary remain readable with
warnings through v8. Warnings become errors at the v9 release-candidate boundary
unless completed migration reports prove a blocker. Previous snapshot support
lasts one warning cycle and is removed two release cycles after v8. Legacy local
dock wiring is compat-only and targets removal in v9 stable.

## Required release evidence

The release owner must record one exact source SHA and pass:

```sh
/opt/anaconda3/bin/python scripts/wiki_audit.py --check
/opt/anaconda3/bin/python scripts/wiki_audit.py --public-export --check
/opt/anaconda3/bin/python scripts/wiki_check_methodology_coverage.py --check
/opt/anaconda3/bin/python scripts/wiki_operation_compile.py --check
/opt/anaconda3/bin/python scripts/wiki_input_stage.py --check
/opt/anaconda3/bin/python scripts/wiki_build_demo.py --check
/opt/anaconda3/bin/python scripts/wiki_web_snapshot.py --check-contract
/opt/anaconda3/bin/python scripts/wiki_pack.py validate --all
/opt/anaconda3/bin/python -m pytest tests/
npm --prefix apps/wiki-cockpit run test
npm --prefix apps/wiki-cockpit run test:gates
npm --prefix apps/wiki-cockpit run build
npm --prefix apps/wiki-cockpit run check:architecture
npm --prefix apps/wiki-cockpit run check:assets
npm --prefix apps/wiki-cockpit run check:bundle
npm --prefix apps/wiki-cockpit run check:release-matrix
git diff --check
```

Desktop Chromium, mobile WebKit, forced fallback and Firefox smoke evidence are
also release blockers. A green unit/build stack cannot override a runtime crash,
blank world, center error, overlap, unreadable label or sample fallback.
Conversely, a passed `browser_closure` receipt binds only that browser evidence;
the commands above require their own exact-`S` results and broader manifest.

## Historical rc8 checklist — superseded by rc21 historical status

- Retain the exact historical S6 and S8 ledgers on their original subjects;
  neither can be relabeled as current S9 proof.
- Preserve the completed exact S9 public 102-cell browser, 1,356-test Python,
  489-test frontend, 106-test Node and deterministic-gate evidence.
- Preserve the completed private S9 2/2 first-attempt downstream and full
  deterministic receipts with only redacted real-data aggregates public.
- Commit metadata envelope `M` only after the S9 payload, without asking a
  commit to contain its own SHA; rc8 pins that already-created payload subject.
- Complete the consumer-semantic gates that a green generic suite does not
  replace: real legacy-event equality/compatibility inventory (RT-09/10),
  real-data search acceptance (RT-29), canonical migration report (RT-33),
  downstream relation inventory (RT-36), source authoring replay (RT-47) and
  restart/security documentation replay (RT-48).
- Complete human conceptual/privacy/VoiceOver review, human merge and the
  separate signed E5 promotion authority before creating a release tag.

## Historical final candidate evidence (`dbd158a4`)

Every count in this section belongs to the historical checkpoint introduced at
the top of this note. It is retained as lineage, not current-worktree proof.

- Python: 706 passed, 4 skipped; audit 0 errors with 3 known staleness
  warnings; methodology 22/22. Every command in the remote `audit-and-test`
  workflow passes locally, including operational-pass freshness.
- Snapshot: 24-payload v2 contract, deterministic demo drift and atomic
  sidecar promotion/rollback checks pass.
- Frontend: 395 unit tests across 51 files and 15 gate tests pass; architecture reports
  0 violations and 0 legacy debt.
- Bundle: initial JS 139.11 kB gzip, CSS 1.73 kB gzip and largest lazy/worker
  chunk 53.88 kB gzip, all below the committed budgets.
- Browser matrix: 57 passed with 2 environment-gated real-endpoint skips across
  59 scenarios. A dedicated clean Chromium performance project passes both
  normal and dense windows under the strict 33.33 ms p95 budget. The P0 Alex
  journey also passed three consecutive focused repetitions and exercises all
  visible Q1-Q4 pages/groups, native mouse/keyboard/focus behavior, collection
  explanation, reader/recenter, breadcrumb/lens, no loop and one persistent
  canvas. Mobile WebKit proves the same two-step path and mission foreground at
  `390x664`; the short-mobile regression additionally proves disjoint semantic
  group targets in both the instructional and dense repeated-family worlds,
  correct `elementFromPoint`, focus, route, lens, breadcrumb, collection and
  canvas identity. The final regression also measures both instructional and
  repeated-family dense worlds at `1280x900`: every full explanatory label is
  disjoint, hit-owned by its intended native button and inside the viewport.
  The in-app Browser covered `1280x900`, `390x664` and `390x844` with no
  document/shell overflow.
- Manual public browser QA covered four views, six overlays, four lenses,
  semantic motion, docks, reader, fallback and mobile. It preserved one canvas,
  had no document overflow, measured p95 12.1 ms on the normal world and proved
  atomic 400 ms overlay crossfades plus reader/Guide focus restoration.
- Downstream pilot: portable source `dbd158a4`; the prior private proof at
  `fa65d5f9` had toolkit drift 0 and a real snapshot v2
  with 24 payloads and complete private/redacted-public migration reports with
  zero validation errors. Redacted desktop, mobile and fallback evidence uses
  real operator provenance, no sample fallback, clean console/network state
  and exactly one fallback scroll axis across 560 real pages.
  The controlled private refresh to `dbd158a4` passes the complete local
  desktop/mobile/fallback/Firefox matrix against 561 real pages and remains
  behind the remote and human evidence gates
  in PR #208; no private content is claimed by this public candidate.

## Superseded planning surfaces

v8 is the single release boundary. Earlier v7 living-world drafts, recursive
quadrant-center plans, modular-template implementation notes and visual-region
refactor proposals are historical input absorbed by the v8 execution plan; they
are not separate compatibility lines or independent releases.
