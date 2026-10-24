# Agent contributions to canonical actions

An optional local agent can use the [native board](native-action-board.md),
[context packets and dialogue](context-coordinators.md), and the same
[contribution CLI](../../../scripts/wiki_contribution.py). No Hermes, Dot,
provider SDK, account, scheduler or second task database is required. The agent
application already open on the project remains the executor; the kit never
launches another agent. Claude, Codex, Hermes or a manual operator can supply
reviewable material through this trusted local interface.

This increment covers **one existing action's body and its deterministic
annotation in the existing memory log**, not arbitrary files or complete
project integration. The request still has exactly one authored file; the
log annotation is generated from its link, material hash and receipt time.
Its exact append-only bytes are revalidated on every use. It is not a second
task database or an additional business claim. Lifecycle, questions, answers and direction still
use the existing canonical transition API. The contribution cannot replace
frontmatter, ownership, tool scope or authority. It preserves legitimate
canonical dialogue suffixes, with receipts checked against a known Git base;
conflicting body edits or unproved metadata changes are refused.

## Request and independent review

A request uses `schema_version: wiki_action_contribution.v1` and contains:

- `task_ref`: `{repo_id, action_id}` from the canonical wiki.
- `run_ref`: `{runtime, task_id, run_id}` with stable, nonempty strings. Runtime
  names are open vocabulary; these are references, not claims of live access.
- `session_ref`: `{session_id, coverage}`; optional `thread_id`, `turn_id`,
  `lineage` and `history_ref` remain the original author's identifiers.
  `coverage` is a nonempty string (maximum 2,000 characters) describing retained
  history and its limitations. A reference grants no transcript access and does
  not imply full history or private reasoning is available.
- `effect_key`: a stable, bounded key assigned before the material hash; reuse
  with different material is an explicit conflict.
- `files`: exactly one `{path, base_sha256, sha256, text}`. Text is the complete
  proposed UTF-8 action document, whose frontmatter must equal the known base.
  `base_commit` (full Git SHA) is recommended on that file; without it the port
  searches at most 200 ancestor changes for the pinned base hash.

`material_sha256` is optional on the request and returned by the port. Compute
it over the entire request **except that field**, using UTF-8 JSON with sorted
keys, `ensure_ascii=False`, `allow_nan=False`, and separators `(',', ':')`.
The file's `sha256` binds its complete text, not only the body. Do not change the
request or replace original run/session references after review.

The separate review object contains `material_sha256`, `reviewer_session_id`,
`evidence_ref`, `report: {criteria, findings}` and `decision: approved`. Criteria
must be a nonempty list of text criteria or structured objects
`{criterion, met: true, evidence_refs: [nonempty references]}`. Findings must be
a list; each retained finding must explicitly state `blocking: false`. Missing,
ambiguous or blocking findings refuse integration. The complete original report
is preserved, without deleting nonblocking findings to obtain approval. The
reviewer session must differ from the author session. These assertions come from the trusted local
adapter and are recorded as **independent agent/operator review**, never as a
fabricated human approval, provider execution, permission grant or CI pass.

Before integration, an independent reviewer must inspect the **generated
proposal commit**, including canonical dialogue, receipt and log annotation.
Supply a separate `head_review` with the same complete review fields plus
`proposal_commit` equal to that full Git SHA. The material review from before
preparation cannot satisfy this check. The head report stays external to the
candidate to avoid a circular commit hash; its original report and hash are
returned with the integration result. Missing/wrong head, self-review or
blocking findings refuse the merge. This is independent agent/operator review,
not human approval. The existing explicit human-review policy still applies
when enabled. A ready draft or null GitHub review decision is never a substitute.

## CLI and Git workflow API

```sh
python3 scripts/wiki_contribution.py prepare --root /path/to/project \
  --request /path/to/request.json --review /path/to/review.json --apply
python3 scripts/wiki_contribution.py publish --root /path/to/project \
  --request /path/to/request.json --apply
python3 scripts/wiki_contribution.py integrate --root /path/to/project \
  --request /path/to/request.json --pr 123 \
  --head-review /path/to/generated-head-review.json --apply
python3 scripts/wiki_contribution.py reconcile --root /path/to/project \
  --request /path/to/request.json --pr 123 --apply
```

Omitting `--apply` validates operation-specific prerequisites and performs no
effect or Git object/ref import. Preparation checks the required material
review, approved base, source reconciliation and policy/log overlap; it does
not run gates or create a proposal. Publication requires a validated retained
candidate and origin. Integration checks the PR, applicable gates, sources and
exact-head report before returning ready; pending gates remain explicit waits.
Reconciliation may query remote identities but only validates objects already
retained locally. Missing required objects are unknown, never a successful
readiness result. A successful dry run does not promise future network success
or replace the real gates. The corresponding
`run_git_workflow` operations are `prepare_contribution`,
`publish_contribution`, `integrate_contribution` and `reconcile_contribution`,
with `request`, optional `review`, `head_review`, and `pr` in the payload. Existing operator
HTTP authorization applies to this API; it is not an unauthenticated bot route.

Preparation starts from the approved Git base, creates an isolated proposal,
and invokes the real auditor, input-stage check, PR summary and diff check.
Consumer-owned `approval.contribution_gates` can add argv arrays of normal
project gates. Model work and auditing hold no application checkout lock.
Ref installation then revalidates HEAD, policy and source bytes under the
canonical writer's cross-process guards and Git ref CAS. It never switches the
application's branch, stages its files or overwrites disjoint WIP. The existing
memory log is a shared overlapping resource: uncommitted log changes are a
conflict, and its source bytes are revalidated under its own cross-process
guard before proposal installation and again against canonical Git before
integration. An intervening append requires reconciliation of the existing
proposal under normal project review/CI, without repeating the model/body
work, inventing a new review or granting another authority. The existing memory log receives only the generated annotation. The action's
existing history receives a body-integration receipt binding material, review,
references, effect key and before/after body hashes (plus base-comparable revisions insensitive only to terminal
newlines, matching the auditor's Git wrapper). Exact requested body bytes are
still enforced at proposal use and readback. Generated receipt time is
not a refresh of the business evidence or a waiver of freshness checks.

Publication/integration currently implements the consumer's `github_pr`
policy. Other policies return `waiting_policy_adapter`; no GitHub account is
created. Publication opens a draft. Mark it ready through the project's normal
review process. Integration checks the exact proposal head, target branch,
the configured validation policy, outstanding review/draft status and current
committed policy before an exact-head merge. An explicitly configured
`approval.require_human_review: true` additionally requires a real GitHub user
approval of that commit. The local review JSON cannot satisfy that human gate.
No access or a pending required gate is a refusal/wait, never successful adoption.
GitHub PR remains the promotion mechanism; another integration policy requires
its own explicit adapter.

### Validation when a consumer does not use remote CI

`approval.contribution_validation` defaults to `github_checks`: integration
requires a nonempty set of successful GitHub checks, preserving the public
kit's CI policy. A consumer that deliberately uses local verification can
commit this explicit policy through its normal independent review:

```yaml
approval:
  gate: github_pr
  contribution_validation: local_gates
  contribution_gates:
    - [python3, scripts/project_checks.py, --check]
```

The additional command above is illustrative; each consumer lists its real
applicable gates. Missing policy retains `github_checks`; unknown values refuse.
The request and review cannot select this policy, supply commands or substitute
successful gate receipts. An uncommitted policy change cannot enable it.

In `local_gates` mode, real integration reruns the existing mandatory gates,
documentary-support gates when applicable, and configured `contribution_gates`
in a temporary detached clone of the exact reviewed `proposal_commit`. The clone
uses retained local Git objects. Policy and gate code come from that commit's
approved parent, never uncommitted application files. Diff hygiene compares the
commit with its parent. A failure, unavailable command, changed HEAD, changed
tracked file/index or unexpected untracked output refuses promotion; normal
ignored caches remain allowed. The application checkout stays untouched.

The result identifies `validation_policy: local_gates`, `validation_commit`,
`validation_policy_sha256` and the existing `gate_receipts` with actual command,
exit code and output hash. `remote_check_receipts` reports GitHub observations
separately, including an honest empty list. No GitHub check or human approval is
created. Any observed remote check that is not successful still blocks, as do
drafts, requested changes and an explicitly required human review. Local gates
never replace independent review of the exact generated head.

After the local gates, integration rereads canonical policy and overlapping
action/log/support bytes, the PR and proposal head before the normal
`--match-head-commit` merge. GitHub branch protections remain authoritative; no
administrative bypass is requested. An uncertain merge still requires
reconciliation without repeating the effect. A local-mode dry run performs no
gates and returns `validation_status: local_validation_required` with
`gates_not_run: true`, rather than claiming integration readiness. Selecting
local validation does not waive the documentary-support contract below.

## Exact documentary support (optional)

An exact `audit.freshness_records` contract binds the entire BASE and CURRENT
document maps. A normal contribution changes the action and log, so leaving
that contract unchanged makes the real auditor refuse the proposal. Merely
configuring an audit input does not authorize the port to write it.

A project operator may opt in through the approved parent policy:

```yaml
approval:
  contribution_record_support: true
```

The default is `false`. The model request still contains exactly one action.
The port derives only the one existing tracked, regular JSON contract named by
the parent's `audit.freshness_records`, outside memory/raw/cache/secret paths.
It validates the actual configured BASE and parent CURRENT using the existing
projector (this bounded option requires `audit.freshness_base` to be a full
commit SHA), then updates only the final action/log CURRENT hashes. An existing
last H2 record in the log may acquire only the exact blank separator from the
canonical append. Every other declaration field, BASE hash, artifact, date,
role, evidence, rationale and context remains unchanged. Duplicate JSON keys,
unsupported selectors and changed semantic record content cause refusal.

Affected occurrence guards and consumed-record bindings require explicit
project migration (C3). The port never infers eligibility from `navigation`,
`change_target`, a phrase or an empty evidence list. A capture proving an
earlier log update does not prove a future update.

A reviewed `document_record.v2` parent contract can explicitly qualify an
individual CURRENT `change_target` occurrence with
`"contribution_effect": "canonical_log_annotation"`. This narrow qualification
requires the exact configured log, a canonical `prerequisite_document_sha256`,
no `evidence` field (including an empty list), and unchanged consumer document
and occurrence context. BASE, other roles, legacy hash aliases and unknown
values are invalid. Ordinary projection still checks the exact hash; the
qualification itself proves no completed write.

Only support derivation can advance that one CURRENT guard, after proving the
actual new canonical body receipt/history and matching material, effect,
task/run/session and independent review, plus the exact canonical log append.
Preparation, immutable candidate validation and merged canonical readback use
the same proof. Valid earlier dialogue suffixes remain preserved. An unmarked
or evidence-bearing guard still refuses: initial C3 must separately preserve
and justify the dated old proof, never silently remove it or turn it into proof
of the new transaction. The helper cannot add a qualification, change a role,
edit evidence/rationale/contexts or renew BASE/artifacts.

`record_support_c3_required` identifies other binding or declaration fields to
review. This mechanism does not author the complete initial five-view C3. In
particular, the real body writer sets `updated_at` to the receipt's UTC date;
if that changes a producer's content or ordering, normal checks still refuse.
Do not anticipate or renew a date to make those checks pass.

The opted-in transaction also runs the real source-registry, operation and
operational-pass checks alongside the existing auditor/input-stage gates.
Other authored pages, including the action index, remain byte-identical.
If an H1 or other producer input requires a generated view update, preparation
refuses instead of adding another output file. Failed checks install no ref.

The generated proposal and exact-head review bind all three files. Reuse,
publication, reconciliation and merged readback recompute the exact support
from the immutable parent and validated canonical action/log delta. Local
support/input drift fails the late CAS. Publication and OPEN integration
require freshly observed canonical HEAD to equal the proposal parent; a main
advance is a conflict, without automatic rebase or hash renewal. The remote
base may still race that observation: post-merge readback detects an unexpected
parent or support, retains `remote_merged`, and reports unknown rather than
replaying or rolling back. Canonical readback also validates the complete
document pair and retained artifact bytes. Readback covers the support file as well as the
action/log; selected checkout and served adoption remain separate observations.

A dry-run preparation does not derive support or run these gates and therefore
does not establish contract eligibility. With the flag off, the original
two-path flow and its exact-contract refusal remain unchanged.

Retained and merged proposal validation reads support eligibility, modes and
artifact bytes from immutable Git. A missing, aliased or executable local
support file reports `waiting_worktree_adoption` after canonical validation;
recovery does not follow or replace it. Preparation, its late CAS and integration
still require a safe regular local support file with the expected preimage,
using the existing bounded file reader. Working-tree audits retain their normal
filesystem guards for evidence. Git-only artifact validation checks the entry
types in both frozen cuts instead of resolving aliases in the selected checkout.

Successful repeated preparation and reconciliation reconstruct the same
`generated_paths` and `receipt_id` from the validated commit and frozen parent
policy. They do not depend on retaining the first response. The list contains
the verified canonical log and, when opted in, the exact derived contract; a
model-supplied path list never determines it. A dry run or an unvalidated
candidate does not establish this prepared receipt.

## Recovery and adoption coverage

A prepared proposal is identified by its Git branch and recorded effect, so a
repeated identical preparation reuses it. Source changes during preparation or
after its freeze cause an explicit conflict. Reprepare only after inspecting
that conflict; do not silently discard dialogue, replace the request, reopen a
question or rerun a model. No exclusion of all history is used as a shortcut.

After a timeout or `unknown`, call **reconcile only**. It queries the PR and
reads actual Git objects and bytes; it never repeats the merge. A failed
readback stays unknown/refused. The PR number is optional during recovery:

```sh
python3 scripts/wiki_contribution.py reconcile --root /path/to/project \
  --request /path/to/original-request.json --apply
```

The unchanged request/effect key locates its deterministic proposal branch.
Discovery queries only that branch in the origin repository and at most 100
matching PRs. Multiple results (including a full 100-result window) are
ambiguous. Both supplied and discovered PRs must match the complete origin,
head repository/owner, branch, target branch and exact commit identity. Every
present local or remote proposal ref must agree. A deleted branch after merge
can be read through the origin's exact PR head ref. Candidate bytes still pass
the full material, body, log, history, independent-review and reference checks
against freshly observed canonical ancestry. A second PR read detects changed
identity. No title, branch name or stored material hash alone proves the effect.

Recovery imports Git objects through unique temporary refs, then deletes only
its own refs with CAS. It updates no permanent ref, FETCH_HEAD, tag, worktree or
index; it never prepares, pushes, creates, reopens or merges. Valid retained
proposals without a visible PR return `prepared_ref_no_pr_observed` or
`published_ref_no_pr_observed`; an open PR returns `waiting_pr`, and an observed
unmerged closure returns `closed_unmerged_pr`. None authorizes repetition.
No retained ref/PR is `unknown` (`contribution_effect_not_observed`), not proof
of absence. Query and fetch failures remain unknown; conflicting identities or
bytes are refused. Coverage is the current configured proposal namespace: a
changed proposal prefix may make older evidence undiscoverable. Do not broaden
the scan or change the frozen request to force a match. No durable recovery
ledger or additional task store is introduced.

Even a successful remote merge is not proof of
local application adoption: `remote_merged` and `source_commit` report Git
facts, while `canonical_body_adopted` requires the selected checkout to contain
the merged source and matching action and generated-log bytes. Otherwise the result is
`waiting_worktree_adoption`. The operator owns that adoption; the port does not
reset, stash or update the active checkout. `served_adoption_verified` remains
false: reader/service adoption is a separate operator readback, not implied by
this receipt. Completion of one card body does not prove complete project or
runtime integration.

Tests distinguish synthetic adapter reports and mocked GitHub CI from real
local Git/CLI execution. Neither proves a model or provider was called. Public
fixtures contain only fictional content; personal configuration and material
remain in each private consumer.
