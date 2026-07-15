---
title: "Wiki Viva v8 rc37 candidate - exact validation passed"
page_id: release-wiki-viva-v8
page_type: release_note
context: system
visibility: public_candidate
updated_at: 2026-07-15
stale_after_days: 365
sources_policy: release_note
gate: github_pr
sensitive_data_policy: no_personal_data
---

# Wiki Viva v8 rc37 candidate - exact validation passed

## Rc24 exact source — productive evidence passed, certification failed closed

`wiki-viva-v8-rc24` binds exact source
`39d490231c00cbc0cf0374c6b1dd3d16f23a2406`, validation metadata
`e912c095e42ba56b97ec3179fd20cdd71779db87` and candidate metadata
`ef8d930cff11ba4a8f9dc4ccfe6ea58785066c19`. Exact validation passed 1,709
Python tests with 3 declared skips and 2 warnings in 988.84 seconds, 516
frontend tests, 115 Node gates, the static/audit/build stack and 102/102
first-attempt public browser cells in 7.6 minutes with zero skips or retries.
The validation browser run-result, gate-result and report SHA-256 values are
`b6f899f3ed365e4788d48ae7957932292c96d232c96040af00c7b3fc2af4c3b9`,
`eb3c91ade66419375a814b760955d1adf7536a2daa3eceece3a60a01e6930c95`
and `7d63ddc26544b4ac582095fe23b3652fce9b477f6405a93780c7187ab9d688bb`.

The candidate package file SHA-256 was
`9fdcd2985f5ab4fbc98932859a950b9aad52ffea0b7ae643a8a1f8830c5f1976`.
Its canonical package identity for capture/certification was
`46494e1d66d1c7bb3e8efeef9687870808453ea5402bb137366c19dacacdd4be`;
the 521-entry portable tree was
`b001f89c7453177a66439a22524f5bb00e47bacb54216cff3291ed408d332048`.
Keeping the file digest and the canonical package identity distinct is part of
the evidence contract; neither may be substituted for the other.

The one productive visual capture passed all four declared profiles on its
first attempt. Its visual-manifest SHA-256 is
`f6f2df7fd4c5461ca5e8ad9dba369f57938233fb4e7bb84b0b8bab1899615fbe`.
The following first Lane A certification then passed frontend, architecture,
bundle and 102/102 browser cells in 6.5 minutes with zero skips and zero
retries. It still failed closed as a whole: `demo_drift` and
`portable_python` invoked ambient `python3`, which resolved differently from
the probed Python 3.12.4 interpreter and its dependencies. A command-registry
Python alias must resolve to the exact interpreter used by the runner's
toolchain probe; a green sibling gate cannot compensate for that divergence.

No release capsule, attestation, certification receipt, trust, Lane B authority,
public release, push, merge or tag was minted. Rc24 is immutable
`historical_certification_failed` and must never be retried, reused, relabeled,
promoted or imported.

## Rc25 exact validation source — failed closed, immutable

`wiki-viva-v8-rc25` bound exact source
`c741e3d0ad409ac9baea8b136e3819952bb0657b` at validation metadata subject
`f2c7665b451b91cb6095ae136b2b5763df67d458`. Its validation-pending package
file SHA-256 was
`d2a92739fadcb89f774238de93fd0d40d9c9b230c05525616811c29c264e0b42`,
its canonical package identity was
`6988fd4ac7c95990127833cbfbdf5e3d8085c8332fb4a67a3be47d8455cbe23e`,
and its exact 521-entry portable tree was
`16705a38c91395cc51f83fd513f54aa1da639c9f4f4c33d12c026d465355d8a9`.

The first complete Python validation ended with 1,708 passed, 3 declared
skips, 2 warnings and 5 failures in 921.24 seconds. The complete frontend/Node
stack passed 516 frontend checks and 115 Node gates; architecture, assets,
build, bundle, release-matrix and every static/audit gate also passed. The five
Python failures exposed three public synthetic contract defects:

- `temporal_value` used `oneOf` around a format-only instant branch, so an
  environment without the optional `date-time` format checker treated
  year/month/day strings as ambiguous;
- the private inventory target appended `-validation-pending` instead of using
  the canonical `release_id@source_sha_prefix` identity;
- the portable `wiki-viva` skill linked the consumer-owned, nonportable root
  `.skills/README.md`, breaking portable Markdown closure.

The strict 102-cell browser matrix was correctly not started after the Python
subject failed. No candidate, productive capture, capsule, receipt, trust
anchor, attestation or Lane B authority exists. Rc25 is immutable
`historical_validation_failed` and must never be retried, relabeled, promoted,
imported or used to mint missing authority.

## Rc26 exact source — every command passed, certification failed closed

`wiki-viva-v8-rc26` carries the public synthetic fixes for the three rc25
failures at exact source
`da3a9a0495db974e409f5af6413401c31851e071`. The complete validation ran on
metadata subject `7afa7ece276197c3e7dc746dfa35c17990687ed4`: 1,728 Python
tests passed with 3 declared skips and 2 warnings in 1,193.34 seconds; 516
frontend tests, 115 Node gates and the complete static/audit/build stack
passed. The first and only strict browser run,
`public-mrkxrlvb-620f3776-799d-4c2e-a748-ae6110e5000d`, passed 102/102 cells
with 0 skips and 0 retries in 6.2 minutes while the subject stayed clean and
exact. Its run-result, gate-result and Playwright-report SHA-256 values are
`e638a1f54e2a2bc6fb46aec053ace9c9601903670784d10826e053257249a84c`,
`59772cbd9ba98f35c507dafd54bd36cd464264085ae1f16fefbbe3f6a7553e0a`
and `12c6e2a0deae9309979241326af203dc1888392aebfc8229a7a7bbf08efb1ddc`.
No green rc25 sibling result was reused.

The validation-pending package file SHA-256 was
`f5e73c17547a477cc9ba1b4303b17af23d7141b697659a177287e5f2fd8cd35c`,
its canonical package identity was
`2266b30d60566b21d49103e7bbb258e12291a7dafe0d4f61b1564d0d9873e33c`,
and its exact 521-entry portable tree was
`24d3f0f79e65d00f4b9fe3b1bec4947044aa32ede7d445033ffb25b5e47c402e`.
The separately reviewed local-QA `candidate` package file SHA-256 was
`f2f384e57992fa94d334d0e87bdd87895a9e1ce0c9937532b58cfb6bb7e824b4`,
its canonical package identity was
`73cbca1b9fc514656603eb5a637e6bb193567cfbd965853c03641a6668333c64`,
and its exact 521-entry portable tree was
`b27fbe273055781bc0171fdb3578c2b24634f2ce33fba91d68439c0d36e52804`.
Candidate metadata commit `cdb20a4e64165623de0b0934f472670aee28dcda`
authorized exactly one productive capture and one Lane A certification.

The first productive capture verified desktop, mobile Timeline, explicit
fallback and two-step quadrant collection. Its visual-manifest SHA-256 is
`6681e1f751ecd157854a4c3d78360a79f981100a4eda97ec377189ea9566614f`.
The following first certification command wave returned success for every
registered upstream gate:

| Gate | Exact observed result |
|---|---|
| `architecture` | passed in 0.831 s |
| `bundle` | passed in 2.380 s |
| `frontend` | passed in 4.975 s |
| `demo_drift` | passed in 17.202 s |
| `browser_synthetic_release` | passed 102/102 in 386.098 s |
| `portable_python` | runner passed in 998.129 s; pytest reported 1,728 passed, 3 declared skips and 2 warnings in 997.71 s |

Lane A is transactional: six successful commands are not a successful
certification. Before attestation, the strict public-evidence scanner found a
host-local interpreter-library path in the Python warning summary and rejected
the run with `private_certification_output`. The retained private raw Python
log is 2,621 bytes with SHA-256
`4fbf2a19cd2633d03464354257d43c229efbfa46f77dbc6cf05a7ad1a26e85b7`;
the path itself is intentionally not published.

No capsule, execution attestation, certification receipt, trust anchor, Lane B
authority, public release, push, merge or tag was emitted. Rc26 is immutable
`historical_certification_failed` and must never be retried, reused, relabeled,
promoted or imported. Its capture and successful command outputs cannot be
carried into rc27.

## Rc27 exact validation source — warnings-as-errors exposed lifecycle defects

Rc27 replaces the real multiprocess `fork` fixture that triggered the warning
with `spawn`, registers `portable_python` as
`python3 -m pytest -q -W error tests/`, broadens public path negatives for
common local and CI roots, and makes every certification-output or attestation
failure instruct the operator to freeze the subject and form a new source.
Passing evidence remains the unmodified captured output; there is no
post-processing redactor or manual summary that could hide a warning.

Package `wiki-viva-v8-rc27` was pinned only for exact validation to source
`ba7ee19457436993edc7ff8a838b34c5b864fd98`; status remains
`validation_pending`, so `package_is_pinned=false` and no plan, import, capture
or certification authority ever existed.

The validation-pending package file SHA-256 is
`e092bd63422899b27fd2850d0965380b4fe91f3068a300aa0d773bcc0ae4983d`,
its canonical package identity is
`29225e6855eeec712c9e97f44a897127bbbc94b2e420d86fd6379082077565e0`,
and its exact 521-entry portable tree is
`0d31d17f3889092ecc68ca4ebdc93a48c9eb6df17c7b22f76ba019feb51e57d3`.
These identities authorize validation only.

The first and only complete Python validation ran
`python3 -m pytest -q -W error tests/` at metadata subject
`b4967e1bb7c1d8a2ecc3440fd253b02be2045d87` and ended with 1,693 passed,
3 declared skips, 0 separate warnings and 46 failures in 1,025.93 seconds.
Warnings were correctly promoted to failures. The failures formed three public
synthetic resource-lifecycle families: 12 Codex-job cases retained subprocess
pipes through daemon helper threads; 33 upgrade/closeout cases left
`git cat-file --batch` streams open; and one snapshot reader-lease case waited
without draining and closing its child pipes. The browser matrix, candidate,
productive capture and certification were correctly not started.

Rc27 is immutable `historical_validation_failed`. No capsule, receipt,
attestation, trust anchor or Lane B authority exists; never retry, relabel,
promote, import or use rc27 to mint missing authority.

## Rc28 source formation — rejected before validation

Rc28 source `31cad3bc8aa9cf45d4842103307baff678ddeeb7` closed the three
RT-163 families with public synthetic controls: Codex
jobs now kill/reap on exceptional exit, join feeder/watchdog threads and close
both parent pipes; Git batch reads use a managed `Popen` plus `communicate()`
and verify all three streams close; and reader-lease tests drain and close the
child with `communicate()`. The integrated affected set passes 159 checks with
warnings as errors. No warning filter, post-processing redactor or fabricated
manual evidence was added.

The pre-pin audit found that two portable C1 guides still described rc28 as
prospective and unpinned. Pinning metadata around those contradictory portable
bytes would have made the release record false. Rc28 was therefore rejected
before its metadata pin and before complete validation; its draft package
identities below are diagnostic only and never became validation, capsule or
adoption authority:

- draft package file SHA-256:
`d3a71b4653df53ad5ab39da214e3aaf08dc9b823913055a16ab840f5ec1eca60`,
- draft canonical package identity:
`26f8f15e177ec92d7a75d4989ec47b854ca95aa2c6486b45ce802ca2b8c8692e`,
- draft 521-entry portable tree:
`961eb6c4f5a11be29e08b72a07fcb4a3d655e160d7d6fae25c441e46dac849a3`.

No complete validation, browser matrix, candidate, capture, certification,
capsule, receipt, push or publication exists for rc28.

## Rc29 source formation — rejected before validation

Rc29 source `905e377220a409bee6e1977d3c0e6262bdc27914` preserves the
resource-lifecycle corrections and replaces the stale portable transition
claims in both guides. The complete portable audit then found one remaining
state-stale claim inside the portable `wiki-viva` skill and real
private-lineage labels in public fixtures. Rc29 was therefore rejected before
its metadata pin and before complete validation. Its draft identities below
are diagnostic only:

- draft package file SHA-256:
`72ff75f4253435e69d4798049cd2d0dc4c5f10559a0d726c8832d2e69aa5438a`,
- draft canonical package identity:
`a7079189f24a63cd6e12b30f9d8fe9b40ae357f6c1347afc0fd70b2802167202`,
- draft 521-entry portable tree:
`9dd92ec9435659def81be0130926c11f19e8dcd3cbf0f7034845735a117d0277`.

No complete validation, browser matrix, candidate, capture, certification,
capsule, receipt, push or publication exists for rc29.

## Rc30 exact validation source — rejected before complete validation

Rc30 source `bc44255b22d65b8c9869ec45759afd4dac1355b9` keeps the
resource-lifecycle fixes, makes the portable skill and guides state-stable, and
replaces private-lineage fixture labels with neutral public synthetic data. The
cleanup-specific evidence passed 27 Python checks with warnings as errors and
all 516 frontend checks. Before its complete exact validation started,
downstream real-data visual QA exposed RT-164: four distinct root-quadrant
projections of the `hub` family rendered the same visible and accessible label.
The canonical node IDs and drill lenses were distinct; the render-time label
resolver discarded that quadrant context, making the controls look duplicated
and giving assistive technology four identically named actions.

Package `wiki-viva-v8-rc30` was pinned only for exact validation at metadata
subject `14ad7edb547b16c83482959e90dd2e14aecff598` and never became executable
adoption authority. Its validation-pending package file SHA-256
is `a99e04d9b41333778a5bee6fb405a85eb4050229ed354ea0151708b9b7f7323c`,
its canonical package identity is
`adf99371ab5e7ddc6b265cbc3dc73b9b7c66c18ca2c93c5c4db53836cf43083f`,
and its exact 521-entry portable tree is
`af505d83ff9ba2f73c8861c029234e3a844392e079f501cd36aa0ebd37a2da8b`.
These identities are now immutable diagnostic evidence only. No complete
validation, browser matrix, candidate, productive capture, certification,
capsule, receipt, attestation, trust anchor or Lane B authority exists for
rc30. It must never be retried, relabeled, promoted, imported or used to mint
missing authority.

## Rc31 exact validation source — deterministic freshness failed closed

Rc31 reproduced RT-164 with public synthetic root-quadrant family
nodes and qualifies each visible and accessible group name with its canonical
`Q1`–`Q4` context. It preserves all four real groups, member counts, semantic
family target and facet-specific drill lens; no entity is hidden, merged or
invented. Unknown or malformed region IDs fail closed to the existing base
label instead of fabricating a quadrant.

Focused public proof passes 517 cockpit tests, including the new four-title
uniqueness and malformed-ID regression, plus architecture, asset and Node gate
checks. A disposable downstream QA clone using real data shows the four
controls as `Q1`–`Q4` and confirms a `Q1` click opens the same family under the
`q1_intencao` lens. Raw downstream screenshots, routes and repository details
remain private and untracked; the versioned authority is the public synthetic
fixture.

Package `wiki-viva-v8-rc31` was pinned only for exact validation at source
`6fa9b907d5dfc748e94d182ac3704b226142552e`; its status remained
`validation_pending`, so `package_is_pinned=false` and no plan, import, capture
or certification authority ever existed. Its package-file SHA-256 is
`f87ff28b4dd4c43b9c831dc7449888b16898de3a65dc1bafcb408aff80c7074c`,
its canonical package identity is
`3b6df79c764c2c287e26d15c50f74fde3fef12dc1f4ca03fffa48517c84751d4`,
and its exact 521-entry portable tree is
`f03226622e7be9e2668d4d39b8c642bf0a7b52571cbedada70071e656b461037`.
These identities authorized validation only and are not a capsule or adoption
receipt.

Its first complete exact validation passed 1,740 Python tests with 3 declared
skips and 0 separately reported warnings in 1,291.72 seconds, plus all 517
frontend checks. Audit, public audit, methodology, operation cockpit, input
stage, semantic inventory, snapshot, packs and consolidation also passed. The
next blocking gate failed closed: `memories/system/operational-pass.md` was not
equal to the deterministic recompile. Investigation with public repository
data also showed that changing the generated dashboard's date required two
writes because the compiler indexed its own stale page while rendering the
replacement.

The browser matrix and every later release stage were correctly not started.
Rc31 is immutable `historical_validation_failed`; never retry, relabel,
promote, import or use it to mint missing authority. No candidate, productive
capture, certification, capsule, receipt, attestation, trust anchor or Lane B
authority exists.

## Rc32 exact validation source — two truth contracts failed closed

Package `wiki-viva-v8-rc32` was pinned only for exact validation at source
`ed073dee5fbf05343b36db1fdc061a24d0220cb9` and metadata subject
`5848f8f9e5ec059b1c3f880db0d7931a25920af9`. It preserves RT-164, closes
the one-write operational-pass fixed point from RT-165 and aligns local/CI
gate ordering for RT-166. Its formation proof passed 198 focused tests with
warnings as errors, and the regenerated operational-pass dashboard was
immediately check-clean at SHA-256
`b632bf8eb2de2ca84ca84894280e907ff434143cbd822dbe0b62d5abeb8a5dca`.

The validation-pending package-file SHA-256 is
`f88cb5fc625a28e2aff40518d895aa5668110838b2fd4179e53407f06ba2311d`,
its canonical package identity is
`8c07f05a680b1bd47994b3560067c28bcf5416aa2bc3546f1e698466940d2b81`
and its exact 521-entry portable tree is
`7da9d6369550d45f368ee3ddb4f04382949f498fd0c2ff9350389243bd0fb82f`.

Its first and only full Python validation ended with 2 failed, 1,744 passed
and 3 declared skips in 1,201.51 seconds. Both failures were public truth
contracts:

- the exact-base page-graph workflow test still hardcoded the legacy `python`
  alias after the canonical workflow and registry moved to `python3`;
- this release note used only the short label “rc32” and omitted the literal
  `wiki-viva-v8-rc32` identity required by the package/inventory contract.

Frontend, browser and every later stage were correctly not started. Rc32 is
immutable `historical_validation_failed`; never retry, relabel, promote,
import or use it to mint missing authority. No candidate, productive capture,
certification, capsule, receipt, attestation, trust anchor or Lane B authority
exists.

## Rc33 exact validation source — browser matrix failed closed

Package `wiki-viva-v8-rc33` was pinned only for exact validation at source
`539eb19b958a4159eecb2c5a7afd6ceaabcbb086` and metadata subject
`a3aae4b1aa5ef53b5e74983d396a744d22f3b514`. RT-167 derived the
page-graph workflow command and interpreter alias from the versioned impact
registry instead of hardcoding a second command authority. RT-168 kept the
machine truth assertion strict and required every pinned release note to name
the literal package ID.

The validation-pending package-file SHA-256 was
`300a78a6c9005059dfe07c6bbe98c268b34739a0aeed8d9f92eadd21dc1b4cb9`,
its canonical package identity was
`69dd37f9d6ed94b92751f6a83a4f4d15cbb1efe925d9bac9d286976a008e1a15`
and its exact 521-entry portable tree was
`7964e884e019af57cc8d53322039635e66fb0233f407685fb258f3c24d76c847`.
These identities authorized validation only; they are not a capsule, receipt
or downstream adoption authority.

The first and only complete exact Python validation passed 1,746 tests with 3
declared skips and warnings treated as errors. The frontend stack passed 517
tests, the Node gate stack passed 115 tests, and every applicable static,
audit, architecture, asset, build, bundle and release-matrix gate was green.
An additional manual adapter-manifest check was outside the upstream Lane A
selection: it is retained only as `inapplicable_gate/orchestration_invalid`,
not as an rc33 source or validation failure, because adapter identity is a
consumer-owned C3 gate that can never be reused upstream.

The first and only strict public browser matrix then ended in 330.49 seconds
with 98/102 cells passing and four failures. Three failures exposed the same
semantic scoping defect: the `Qn` disambiguator needed by repeated root
quadrant controls had also changed the concise accessible name and breadcrumb
expectation inside an already focused quadrant lens. The fourth failure was
the resulting short-phone pointer collision between the taller focused family
label and the quadrant compass. The subject stayed exact and clean; no retry
or sibling browser evidence was substituted.

Rc33 is therefore immutable `historical_validation_failed`. No candidate,
productive capture, certification, capsule, receipt, attestation, trust
anchor, plan, import or Lane B authority exists. Never retry, relabel, promote,
import or use rc33 to mint missing authority.

## Rc34 exact source — historical pre-capture rejection

Package `wiki-viva-v8-rc34` binds exact source
`533d286869c478bd157b066d7882388b99fde2f7` and validation metadata subject
`2afd435c7cc955ae7a922b1d46eac355472ca0e6`. Its public synthetic correction
scopes the `Q1`–`Q4` prefix to the root quadrant overview, where repeated
family labels need disambiguation, while a focused quadrant lens keeps the
concise family name used by navigation, breadcrumbs and assistive technology.
The semantic scope correction removes the excess focused-label height instead
of masking the mobile collision with a broad positional override.

Before validation, the `validation_pending` package-file SHA-256 was
`f5a0ef463b56d3b35a918bb163108ba01e39eb68eefd8ef8b35f3a933507bb33`, its
canonical package identity was
`dc7cc755a69b33a8aaf994f52b12d38307a7153bde9942d1eac9b310cb0ebac7` and its
exact 521-entry portable tree was
`257140ba318e4ee269d026f58f0e02bc6056e593dc9b25750e7f81af4c8834f9`.
These validation-only identities remain historical evidence of that state and
are not substituted for the candidate identities below.

The first and only complete exact validation passed 1,746 Python tests with 3
declared skips and warnings treated as errors in 1,113.61 seconds, all 518
frontend tests, all 115 Node gate tests and every applicable static, audit,
architecture, asset, build, bundle and release-matrix gate. The first and only
strict public browser run,
`public-mrlafqnv-689884b2-50ea-4a30-bb21-9eb2c776f861`, then passed 102/102
cells in 6.5 minutes with zero failures, skips, retries or flaky cells. Its
run-result, Playwright-report, release-build-manifest and gate-result SHA-256
values are
`02f3d2bb5d7acea26313944978cc620cd92e024945f55f87f3d4bfb1f5fd09fe`,
`3353646ccf808c586b285007c835566a6928fdfe430a64b044f5fdf5c9bd3d53`,
`6578f59c80add285cea103795618ec8c3a0537906cd723cd178350332dc657aa`
and `d0dca2712e831c953d76b58ff373bcb550a659e601596415134d2bd078b9ea9c`.

The separately reviewed local-QA `candidate` metadata subject was
`59be853af5416ce84c4ca89e7272bb64eb909b2b`. Its package-file SHA-256 was
`a62594490177830b24d7a65b70f5acbd7f033235e0a26ed4f6e4b84d4af7cac8`, its
canonical package identity was
`b076019c6b890a0a54f2c5b4f6362bbe025f490d53eb588fdbd119bd74e7e5ea`, and its
exact portable tree was
`59fa6d660f0d0e43b880e34d72fb1b9c00485ec72828051c0d8eeb56a881671c`
with 521 entries.

Before any productive capture or certification attempt, read-only downstream
QA exposed RT-170. The B0 preflight required toolkit CLIs whose bytes would
arrive only in C1, treated the expected pre-C1 portable delta as failed
equality instead of prospective import inventory, and allowed a reviewable
semantic repair even though C3 forbids domain content. The runner also
hardcoded its mutation/evidence root instead of deriving it from the parent of
the exact plan path. A legitimate older consumer therefore could not produce
an honest plan, while the exception path could mix consumer preparation into
the technical migration boundary.

Rc34 is immutable `historical_precapture_rejected`. No productive capture or
`certify` command was attempted, and no visual manifest, certification result,
capsule, receipt, attestation, trust anchor, downstream plan, import or Lane B
authority exists. Never retry, reuse, relabel, promote, import or mint missing
authority for rc34.

## Rc35 exact validation — RT-171 pre-capture rejection

`wiki-viva-v8-rc35` exact source
`52491dfd6c3a81f0356fb64a9e01e41dd71e07a0` passed its wholly new exact
validation at metadata subject `55910c379b64060451fb8fb93eb85d47b9245122`:
1,754 Python checks with 3 declared skips in 1,271.55 seconds, all 518 frontend
and 115 Node checks, every applicable static gate, and first/only strict
browser run `public-mrlderie-ab48db4f-1355-47e9-bdc2-69f96f4bda85` at
102/102 with no failure, skip, retry or flaky cell in 386.565 seconds. The
browser subject stayed clean and byte-identical before/after the run.

The browser run-result, report, build-manifest and gate-result SHA-256 values
were
`f4dd1c23ce1512a3a944d867709c51f84b6356368cbe651b9b2e359bc841acc8`,
`64c94f15a4aa7980f4fe13bfe10a0301264789fca93bab530a5677927ebf5add`,
`d39fc981d2ff687a297f72cc6da5410fe159ddb2adddd79db00c0dec03a9646a`
and `079278e90ac01631783a18c92e69245aa3a89bd264db48a5995c47b4ebc7e6bd`.
The exact validation toolchain and matrix-contract SHA-256 values were
`322a224362397a29f53b22862e33d8dfae207ce027bf5727a6338d2e15c76a85`
and `f5c9a48b7325efaa4ffb48f1d99aaf4201489060bfa0294ea1aaa93a21300432`.

A separately reviewed but uncommitted local-QA candidate projection had
package-file SHA-256
`3cea5015b2be7bfc34b951553c5d2ab0a4d45098f6360699b5a66c36d929e636`,
canonical package identity
`e7a3c44876ed8265db0123cce6cfd23ce8cb9d1d6579a4fb89ba27ea29eef0e8`,
and package-bound portable tree
`1c8e6f696ce705a3a5be04633051d793785bea9a2933b6f103c236c401d0255c`
with 521 entries. No candidate metadata commit was created, so this projection
is review evidence only: it is not a durable candidate boundary and minted no
capture, certification, capsule, receipt, attestation, trust anchor,
downstream plan, import or Lane B authority.

Pre-capture review then exposed RT-171. The downstream real-canary exporter
entered positional `/w/quadrants` routes, including its mobile profile, and
neither its v1 summary nor the upstream v1 capture record bound the rendered
`data-runtime-mode`. A route that normalized to a compatibility or wrong view
could therefore retain correctly sized PNG evidence without proving native v8
runtime semantics. Rc35 is immutable `historical_precapture_rejected`: no
productive capture or `certify` command was attempted, and none of its
validation or uncommitted candidate evidence can be retried, relabeled,
promoted, imported or used to mint missing authority.

RT-170 remains valid historical source behavior:

- B0 preflight runs only `diff_check`; it cannot depend on a CLI imported by C1;
- expected pre-C1 portable drift is a prospective, package-bound C1 inventory,
  while final-C3 `toolkit_drift` and `semantic_inventory` remain mandatory,
  blocking and never reusable;
- the parent of the exact `plan --out` path owns the one ignored/untracked
  evidence root for state, screenshots, receipts and reports;
- domain-content debt is repaired and merged before freezing a new B0, never
  admitted to C1, C2 or C3; and
- standing approval for incremental private-main merges removes only the
  downstream human-authorization blocker. It does not waive privacy, secrets,
  exact-subject gates, real canary, report or rollback verification.

Pre-pin source-formation review passed 126 upgrade/package checks, 153 Lane A/B
authority checks and 90 resumable-CLI checks with 3 declared skips. Audit and
public-audit each returned 0 errors with the 6 already-known freshness warnings;
package and consumer inventory validation passed while
`package_is_pinned=false`. That remains source-formation evidence only; it is
not relabeled as the exact validation above.

## Rc36 exact validation — first Lane A certification failed closed

`wiki-viva-v8-rc36` bound exact source
`8f96e1fd58258df64174229d81ee6a330ba9d2b1`. Its first and only complete exact
validation ran against metadata subject
`3db3f9f43c8e73fe583b93fba4ea6b9f63bdc5bd` and remains valid historical
evidence. It passed 23/23 recorded gates:

- 1,782 Python checks passed with 3 declared skips in 1,082.23 seconds;
- all 518 frontend checks passed;
- 123 Node gate checks passed; and
- first/only exact-validation browser run
  `public-mrlis0t7-bfd938c4-5799-4c19-b7b0-e7df20d75651` passed 102/102 with
  zero failure, skip, retry or flaky cell.

The exact-validation result and identity SHA-256 values are
`5585819e60c5f7550f06e9990c4de23b42e5eb3113f2bdf5036cac563465a267`
and `4eef33dd7b6ede28a324cfb2addf583f7fbed1a06fff611d5f62b81b09e82aa6`.
The browser run-result/Playwright-report/release-build-manifest/gate-result
identities are
`451399635d7d441dca9a9fd31c5fc2476651f878633b7684ed10f97e0f5062ae`
/ `293e7b4878985c0e98a645b98e490ed7b0e7b5ba067d7adf0fabffdce4933803`
/ `78dfb9786a2785f282af88e210525aba4df0712f768adf305b5128108dfd400d`
/ `68b6dec6bb83fad11001a2fc3a2b8792075ff6867358e485cf676112d973929b`.
The release-matrix contract SHA-256 is
`f5c9a48b7325efaa4ffb48f1d99aaf4201489060bfa0294ea1aaa93a21300432`.
The toolchain SHA-256 is
`6728f4644bc18da8602f1c3ea982f6b5584c7e949716e2e3c2bb58110fba7083`;
runner identity is
`1.4.0+payload.03a75c4072048b8150e95737bb7c458562bd29da184286c09a3cea7699955424`.

The exact-validation subject measured package-file / canonical-package /
portable-tree SHA-256
`47c3dc7dff8336c7707a4c43cc37275aef3721e2b1a54109b94e64cbed6992f1` /
`81a3b600f4cd6cd0f0d3abac0b886e9db15fdd3ad0120c9442ce7fc76cc07832` /
`53ffdf8bc0a2c61f1bf7f426ba12e7e9a0c4995e92703a7264596b9f9a81594c`
with 521 entries. Those identities remain exact-validation history and are not
candidate or adoption authority.

The preceding candidate metadata subject
`7f1c859d2b666f320b319094d02a551e94542926`, package-file/canonical/tree
`4b3dd32b...` / `bca7d50a...` / `2f03cae7...` and productive visual manifest
`e314296c3105b6c943cd901cc4fc3c38867df69353a0fe37f0713d66838745f5`
are immutable rejected evidence. Its certification preflight rejected an
8,372-character limitation against the schema maximum of 8,192 before any
Lane A gate ran. Failure stream SHA-256 is
`1e81630834bf71da92df2ba125fe7419fab837327b84e25a0c9c33d58f536489`;
no capsule, receipt, attestation or authority was minted, and neither package
nor capture can be reused.

The corrected and separately committed candidate metadata subject was
`ac0f49afe28a5bf84003b58c537ac1727dab7008`. It bound package-file /
canonical-package / portable-tree SHA-256
`8343066af6b1c36e888750d560d71c4a34351fc04565f7d2b735e5053fd7df1b` /
`8ee7e597b495a9f5e4a2357758ccd279306170243f035051191ff9a7714b42b2` /
`4dc31eff8a5aef8b0e6e4f4b630908da889e0ecc1dd1de5f0706ec6d48776cc3`
with 521 portable entries. Its first and only productive four-profile capture
sealed visual manifest
`6199d1001ba98c2c772323069765ddc695cc8971f6d7e03390e496de64551808`.

The first and only Lane A certification for that corrected candidate stopped
fail-closed at 101/102 browser cells. After drill-in and Back navigation in the
reviewed dense desktop profile, the semantic target was visible but the camera
and Drei Html hit tree had not settled to the same navigation sequence, so the
center-point hit test returned no node. The certification stream, failing
browser-gate log, browser run-result and Playwright-report SHA-256 values are
`a95d70853be927ad29a6e98e619f62faad1dffa3dfc60f11299ca803f2e8f545`,
`2d5405db94d8ba9af0d72d3cad564205d5af660513be29c1f7953cf746e77256`,
`2b1c678a7e3bd46d7dc1a27c0e8cbf9a21269c781b8cb1b4bd17fc3bcd1ffa33`
and `bb69c7acb697bbd33619765f30b6dc32851ef16c3675c5f4eaac1c7a29601c05`.
No capsule, receipt, attestation, trust anchor, downstream plan, import or Lane
B authority was minted. Rc36 is immutable
`historical_certification_failed`; its valid exact validation remains
historical evidence, but its candidate, capture and gate results must never be
retried, reused, relabeled, promoted or imported.

## Rc37 candidate — exact validation passed, capture pending

RT-172 requires the single successor source to bind exact layout request,
morph, camera and Html settlement to the same navigation sequence before
declaring spatial settlement. Exact source
`d87af15b4aa850d1a50dc867f74e07ba09d0e89f` now implements that contract and
passed its first and only complete exact validation at metadata subject
`775fe5bc9437da5ec9311704731f4342d515fc16`: 23/23 recorded gates in 1,652
seconds with a stable Git subject; 1,782 Python passes plus 3 declared skips in
1,088.81 seconds; 64 frontend files / 522 passes; 123 Node passes; and browser
run `public-mrlmvik8-6aaf518b-83ce-46b2-8913-2ee9a101f331` at 102/102
first-attempt with zero skip or retry in 6.5 minutes. The critical RT-172
quadrant-overview settlement cell passed on that first attempt.

The immutable validation subject carried package-file/canonical/tree
`5b88cad7e0194a90db014edaa96e044779e9072e51e8e3a9324c49548a8656d7` /
`8c7a107bae1f9410995b9e3ba22af46e64ac3924764c551310afaeaa7c6cf9aa` /
`e40d77b81d5b4cde127d566eb04834b5f6a2bccd569c8a1ffaacb1c3619bb3a9`
(521 entries). Its validation-result / identity / browser-result / browser-gate
SHA-256 values are
`e409a148cf717b09ad18ca772720f20bd0a1e98e3321b06a9ce0c92af9bb5e62` /
`68d11b2a2c74f958c7833c52a0fa24bd22c9f4942bc0229b16a33511e5edff0e` /
`acd03c5b4f9dd0db515a2d87e12f3391fe0826bf4fb02a5e4e45aed8bfdaf6f9` /
`3519fceccf4821df2775de90fe3a99cee72773743152779a2a0461afdfbf945c`.

The separate candidate package-file/canonical-package/portable-tree SHA-256
values are
`6d409da4e58466a4932d3ee2bc089e9151450184e7292cf5513e45e6686f7f95` /
`1af897ce9bf851563521b51048a20d0f2edfef31b72d27c823479022977f03d0` /
`77799ece4d3a61bba2a1c3f8814f2e5ecc3232a6b3b813b65b54931067c35d8e`,
521 entries. Active `wiki-viva-v8-rc37` is now `candidate` and
`package_is_pinned=true`. Rc36 receipts cannot be carried forward. No
productive rc37 capture, visual manifest, certification, capsule, receipt,
attestation, trust anchor or downstream plan exists yet; only one fresh
productive capture and one Lane A certification attempt are authorized. The
canonical scoreboard is `2/5`: source pin and exact validation are complete;
capsule verification, private canary and private-main readback remain pending.
Draft public PR #61 remains
stale and does not represent this local truth; public push, publication, PR
mutation, merge and tag remain unauthorized. Private PR #211 and its v2
receipts remain immutable historical evidence. A fresh v3 adoption may start
from the then-current private `main` only after the successor capsule and
attestation verify fail-closed.

## Rc23 exact validation source — full matrix failed, promotion prohibited

Exact source `ba42b95c93c3383162bf105703d5d6d4ea688e3e` corrected all four
visual profiles to canonical native routes. The first complete validation of
that source pin at metadata commit `e97371490091416466825bc6c6d79ed984d480ee`
ended with 1,670 passed, 1 declared skip, 2 warnings and 41 setup errors.
Reproduction against the exact source reached the same route-contract
signature. Every error had the same public synthetic root: the CLI authority
helper still fabricated the legacy desktop route, so its capture record
correctly failed the exact route contract. The validation-pending package/tree pair was
`a55126d84551c32feb458607a7f6dfd1e2785c136c6ad789dc4be32365477578` /
`4ec21ffe6221fadf7ea582f14fd83ee89926ca5d2738f7040436b89749de79ad`,
with 521 entries. No candidate, visual manifest, capsule, attestation, receipt
or Lane B authority existed. Rc23 must never be retried, relabeled, promoted,
imported or used as adoption authority.

## Rc22 exact local source — failed capture, promotion prohibited

Exact source `7e72664fb6871d906addbddb6ed5b2e7f1fec33c` implements the
config-bound three-role C3 authority, productive record-backed Chromium capture,
independent `verify-capsule`, fail-closed impact selection, resumable C1/C2/C3
adoption and fd-pinned evidence reads. Its final local stack passed 1,703 Python
tests with 3 declared skips and 2 known fork warnings, 516 frontend tests, 115
Node gates, both audits with 0 errors, methodology/operation/input/semantic,
26-payload snapshot and pack validation, and the 102-public-plus-2-downstream
matrix contract. The integrated upgrade/security subset passed 375 tests with
3 declared skips.

The local-QA `wiki-viva-v8-rc22` candidate package SHA-256 was
`d7a6a005ee7a57658e4d40ebd3d589be5b9151b7d0b95adf0914bafd6b382797`.
Its first productive Chromium capture stopped fail-closed before sealing any
manifest: `/demo/w/timeline?tour=0` normalized to Quadrants instead of the
native Timeline. The validation-pending package/tree pair was
`20a92e19eba537acf411e5d9d01b65adad5f71ca8e7634e81cd6764d8d1e9e0c` /
`7e70e7b3f457374624e4ef2656deb131318336228b848706f2b38ff2954cfb03`;
the attempted candidate pair was
`d7a6a005ee7a57658e4d40ebd3d589be5b9151b7d0b95adf0914bafd6b382797` /
`e27f8efd99fb7eb112a9d08dcc8628f891086f191bf43de084f69b2c40c3593c`,
both with 521 entries. Mixing the package-bound tree digests in the prior prose
was stale documentation, not a verifier failure or reusable evidence. No rc22 visual manifest, capsule,
attestation, receipt or Lane B authority was minted. Rc22 must never be
retried, relabeled, promoted, imported or used as adoption authority. Its
failure does not change the still-valid identity-scoped private v2 receipts.

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

The `wiki_viva_upgrade_consumer_c3_authority.v1` contract was introduced after
rc21 and is preserved in the exact rc24 validation source. Neither rc22's
failed capture nor rc23's failed validation can authorize its adoption. Rc24
inherits no prior status or receipt, and its own failed certification minted no
new authority.

Active rc37 has a separate source pin and candidate boundary. Its first and
only exact validation passed 23/23; it still requires one productive capture,
one Lane A certification and independent capsule/attestation verification
before any downstream plan.
Remote public CI, human conceptual/privacy/VoiceOver review, public merge and
promotion remain separate and unauthorized; stale/conflicting public PR #61
does not represent this local truth. External E5 and a release tag remain
separate. The historical private v2
migration keeps its original full blocking matrix and receipts; neither rc20,
rc21, rc22, rc23, the exact rc24/rc26 failed-certification subjects, the exact
rc25/rc27/rc31/rc32/rc33 failed-validation subjects, rejected
rc28/rc29/rc30/rc34/rc35 nor the exact rc36 failed-certification subject
reclassifies,
reduces or rewrites
that evidence.

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
proven. At that historical checkpoint,
[draft PR #61](https://github.com/kimlage/wiki-viva-kit/pull/61) still required
human review and merge. It is now stale/conflicting and does not represent
the active rc37 candidate truth; no tag or public push is
authorized.

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
python3 scripts/wiki_audit.py --check
python3 scripts/wiki_audit.py --public-export --check
python3 scripts/wiki_check_methodology_coverage.py --check
python3 scripts/wiki_operation_compile.py --check
python3 scripts/wiki_operational_pass.py --check
python3 scripts/wiki_source_registry.py --check
python3 scripts/wiki_input_stage.py --check
python3 scripts/wiki_semantic_inventory.py --check
python3 scripts/wiki_quality_report.py --check
python3 scripts/wiki_build_demo.py --check
python3 scripts/wiki_web_snapshot.py --check-contract
python3 scripts/wiki_pack.py validate --all
python3 scripts/wiki_consolidate.py --check
python3 -m pytest -q -W error tests/
npm --prefix apps/wiki-cockpit test -- --reporter=tap
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
