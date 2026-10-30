# Revocable documentary proposals

The existing [admin command bus](../../../wiki_core/web/admin/plans.py) can prepare
an ordinary documentary PR through `wiki.proposal.prepare`,
`wiki.proposal.publish` and `wiki.proposal.promote`, then return to approved
content through `wiki.proposal.adopt`. A context packet or successful
freshness check does not authorize these operations. The live local session,
existing capabilities, operator nonce/attempt checks, repository policy,
independent review and applicable gates remain separate requirements.

## Material and preparation

The [documentary adapter](../../../wiki_core/web/normal_proposal.py) accepts a
bounded regular JSON file under the configured derived root and its SHA-256.
The closed material binds the proposal branch, exact HEAD, canonical action,
revision, run/effect IDs, document preimages, returned text and fixed C2 IDs.
It accepts no client commands, scripts, imports, executable code, credentials,
roles or security changes. Action bodies and lifecycle changes use the
[canonical writers](../../../wiki_core/action_transition.py); other action pages
cannot be smuggled through documentary replacements. Log changes are append-only.
The optional configuration change is limited to the two existing audit pointers
for the authored documentary contract and its base.

Preparation captures every reviewed input hash, including absence and C2 output
preimages. It stages native writer/C2 results in an isolated temporary tree,
then checks the planned inputs and output hashes before installation. C2 uses
the explicit material capture instant; the result separately records actual
preparation time. Neither timestamp revalidates external facts. Only the three
existing producers `input_stage`, `operation` and `operational_pass` are allowed,
in that dependency order. Unchanged outputs are not staged; exact new files in
an untracked directory remain selectable through the native Git workflow.
They retain their documented readsets; a consumer must qualify any additional
input/generator before extending this catalog.

Actual installation, stage and local commit each pass through the live effect
guard. Index bytes/modes and HEAD/branch are checked before commit. Preparation
never updates canonical main or publishes a PR. Later failure may leave a local
proposal with explicit affected/uncertain paths; it does not promise rollback.

## Revocation and effects

[Local sessions](../../../wiki_core/web/admin/sessions.py) register each admitted
effect while keeping their mutex available. Native lock immediately bars new
admissions and acknowledges `locked` only when the admitted effects finish.
A long operation returns `admin_revocation_pending`, rather than a premature
confirmation. A reported uncertain Git/provider outcome remains uncertain and
blocks further writes in that session; readback is required before retry.
A process restart revokes tokens, but is not evidence that an uncertain remote
operation did not happen. Preserve its receipt and reconcile the same PR/effect.

The cockpit removes ordinary command access immediately on lock or local expiry.
It keeps a separate private RAM-only credential for confirmation on the same lock
endpoint. Pending, uncertain and failed responses cannot announce completion or
discard that credential. Strip, reopened Dock and the off command use the same
confirmation result. Late lock, renewal, unlock, discovery and countdown responses
cannot restore access or overwrite a newer session lifecycle. Only positive native
lock readback for the current credential confirms that session's drain. Reload
loses the local credential; anonymous discovery reports aggregate instance activity
without session identities or grants, and cannot certify a lost session's lock.
The client refuses discovery without the activity metadata; an older operator
must be restarted with the adopted code before this interface is available.

This defines an admission and completion barrier, not cancellation or rollback.
An already admitted operation can finish before lock is acknowledged. Separate
publication and promotion steps revalidate authority after long gates and before
each provider write. Promotion binds `approved_base` to the approved main ref,
permits only a documentary delta and reads policy from committed configuration.
It checks the independent final-head review and runs the existing policy gates
one command at a time in a detached temporary checkout of that immutable head.
Caller worktree scripts, uncommitted policy and gate receipts cannot replace
those inputs. Remote failed checks or requested changes still refuse promotion
in local validation mode. Promotion uses the provider's exact-head CAS. A local artifact is
review evidence; its hash is not a grant or proof of the reviewer's identity.
The trusted operator must obtain the actual independent review and run all
additional checks required by its repository instructions. Consumers requiring
human review need their own supported human-review adapter; this command does
not infer that approval from a local assertion.
The same exact-head review may include `freshness_reviews`, a mapping of exact
memory paths to `disposition`, `evidence`, `rationale` and `limits`. These are
the existing [individual age reviews](../freshness-impact.md), not gate results
or a permanent registry. Promotion passes them to the full auditor with the
reviewed `approved_base` inside the immutable candidate checkout. The auditor
rechecks the evidence, changed-page dependency closure and unchanged source
dates; other failures still stop promotion. Malformed declarations, arbitrary
CLI arguments and changed review bytes are refused. Omit the field when no age
findings need review. No command can infer that a source was reread.
An absent `approval.require_human_review` keeps the existing false default;
explicit true refuses promotion without that adapter, and non-boolean policy
values are invalid. Independent review remains required when the policy is false.

The synchronous action create/transition/run and Git workflow routes require
the same current session and appropriate capabilities. Proposal listing remains
read-only. Provider writes require the exact prepared head, effective push
destination and PR identity. PR publication also reads back the requested
title/body. A completed ready effect remains in the receipt if merge is later
refused; unavailable or malformed post-effect observations remain uncertain.
Provider readback is an observation, not a remote lock or evidence of served
consumer adoption. The older HTTP
contribution prepare/publish/integrate dispatch is refused because wrapping its
whole gate/provider batch would not guard each effect. The contribution library
retains its documented one-action/log scope; it is not a multi-page bypass.

This capability does not qualify asynchronous jobs, ingestion dispatchers,
arbitrary host CLIs, an OS ACL, runtime source-account access, or autonomous
scheduling. The controlled integrator must use these fixed operations for its
actual effects and must not fall back to another writer after refusal. Tokens
and startup codes stay in the operator's RAM and never enter model context,
material, source control or receipts. Operator v10 advertises
`revocable_documentary_proposals_v1`; restart an older selected process before
claiming this boundary is active.

## Verification

[Admission tests](https://github.com/kimlage/wiki-viva-kit/blob/c46568234f8d16d81f1e38140246a31d4faff9c8/tests/test_normal_proposal_admission.py) use real native
challenge/unlock/lock HTTP endpoints, a real Git fixture, the action writer,
deterministic C2 and a real local commit. They compare domain bytes, index, refs
and state after revocation, then prepare the same material with a new session
and plan. [Session effect tests](https://github.com/kimlage/wiki-viva-kit/blob/c46568234f8d16d81f1e38140246a31d4faff9c8/tests/test_admin_effect_authority.py)
cover live expiry, capability refusal and ordering. Controlled provider tests
can verify dispatch/CAS/uncertainty semantics, but do not demonstrate an actual
provider account, remote merge or consumer adoption. Each consumer still needs
its own reviewed SHA adoption, full gates and served readback.

## Editorial action consolidation

A body contribution may additionally declare `consolidations`: up to eight
objects with `paragraph`, `canonical_ref`, `canonical_sha256` and `label`.
The native writer verifies the exact complete prose paragraph still exists in a
distinct sibling action at the pinned hash, then replaces only that paragraph
with the supplied label linking to that sibling. All remaining body bytes,
factual dates, lifecycle and support fields remain unchanged. Terminal actions
remain immutable; they may be the canonical destination. The real operation
time is recorded in an append-only `body_consolidation` receipt.

The submitted body must equal these replacements exactly. The audit replays
them against the approved body, rejecting extra facts and date renewal. Mixing
factual body rewrites and editorial consolidation in one reviewed base delta is
unsupported; use separate reviewed changes. Normal proposal preview pins the
canonical source as a real read input. This is not a generic freshness waiver
and does not relax any quality, source or independent-review gate.
