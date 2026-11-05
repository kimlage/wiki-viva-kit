# Context impact and integration preflight

An approved task packet exposes the selected context's purpose, owner, root and lineage, plus scoped ceilings, currently approved imports and the owner/connection boundary. It does not expose other manifests or unapproved protected paths; it is a policy view, not a sandbox claim.

The [impact module](../../../wiki_core/context_impact.py) consumes the existing relation inventory through its `dependency_edges` normalization; it does not persist a second graph or queue. The caller must be authorized to read the inventory and provide a trustworthy, complete-enough view: the output cannot certify inventory completeness or prove that an agent read a receipt. Navigation and association edges do not trigger review. A legacy dependency without a fixed `consumed_revision` is returned as `blocked_unpinned_dependency` instead of being silently called fresh. A supplied 40- or 64-character Git commit identifies the actual input revision; the selector is resolved at that commit, independently of the transaction's before revision. A digest proves selected bytes/contract, not current observation of an external fact.

An approved consumer page may declare its dependencies in the existing `information_requirements` frontmatter: the four legacy fields `target`, `fields`, `temporal` and `max_age_days`, plus optional fixed `consumed_revision`, `use` and `classification`. Missing revisions remain unpinned. The `impact --consumer PATH` form reads the consumer from the approved Git revision and derives these edges through the existing parser, without returning the raw graph. It resolves explicit repository paths only; page-ID lookup is not performed. The `requirements` command checks a completed packet/result, the reported reads and selected digests, current grants, and that the exact proposal commit is incorporated with the same output bytes in the approved revision. It proposes `information_requirements` for the page but writes nothing; a reported read is not proof of comprehension. When a proposal adds or changes such declarations, preflight checks each new selector and fixed revision against evidence the task reported reading; an unpinned new declaration is not eligible for ordinary preflight. Existing legacy declarations remain unpinned until explicitly updated.

Existing inventory edges supply `source`, `target`, `type`, and optionally `consumed_fields`, `consumed_revision`, `owner_context`, `producer_context`, `use` and `classification`. A consumed selector is `section:<stable-id>`, `field:<name>`, `body`, `*`, or a legacy bare frontmatter field. For `source_ref` edges the existing inventory treats `target` as the prerequisite and `source` as the consumer. Preserve the actual source relationship in the canonical page or its existing task receipt; do not make a separate persistent edge file solely for this command. A consumer must retain the revision it actually consumed, not claim the latest revision. If a selector was removed, the result reports a missing digest; malformed or duplicate section markers fail closed. Section content compares its stable ID and version and body, excluding the heading label; use a field or whole document when the title itself is consumed.

`assess_impact` reads one destination context at a time. It derives the actual owner from the approved context hierarchy, checks both destination read scope and exact bilateral import/export permissions, then compares only the authorized selected content. Unauthorized edges are not returned, counted, or described; the result always says authorized-only coverage, not complete coverage. For a proposed new connection, an already authorized person must use the existing [connection proposal contract](../../../wiki_core/context_packet.py), with exact producer, destination, selector, use, classification and expiry, in a channel authorized for that metadata. A proposal is pending and cannot grant access. A folder or branch is not confidentiality isolation.

The folder impact route currently qualifies one destination owner at a time.
Even when an exact cross-owner connection is declared, an edge whose producer
has not been separately qualified stops with `cross-context folder authority
requires requalification`; it is not an absent impact or a completed review.
The connection alone does not authorize the caller to act as the producer.

Each result is an immediate candidate for **independent interpretation** by the destination; it neither copies a source conclusion nor recursively updates the next context. The `review` command can prepare an `updated`, `still_valid`, `superseded`, or `blocked` disposition with reason and current approved evidence, for recording in the existing task result. It is explicitly `reported_not_verified`. `updated` requires the target digest to have changed since the candidate was generated, and the source slice to remain unchanged; only then is a subsequent impact run indicated. This is not proof of who performed the review or of fact freshness. For a chain of such invocations, carry the returned `trace`; a repeated event or generation limit becomes `blocked_cycle_limit`, never an endless loop. Trace is caller-supplied continuity evidence, not a global lock. Fan-out is bounded: `authorized_remaining` and `next_offset` expose unprocessed authorized candidates. A continuation passes the prior `selection_digest`; a changed candidate set is rejected instead of skipping or duplicating work. These are finite read-only calculations, not a daemon or scheduler.

`policy.permits` is only an upper bound for path permissions. Adapters must not use it as a complete authorization decision: every cross-context evidence read, including a parent reading a child's artifact, also needs the current exact producer export and consumer import; writes also require the target's canonical owner to equal the acting context. The parent having `read: [self]` or `write: [self]` does not bypass those rules.

The [preflight module](../../../wiki_core/context_integration.py) revalidates the current trusted approval reference, exact short branch head and ancestor base; reconstructs the packet with current policy; compares each selected input at the approved base; and checks reported changes against the actual Git diff and the context's current write scope. It refuses policy edits, changes to any active instruction, skill or template (which require the separate policy-review path), unsafe or unsupported files and detected secrets. The result explicitly says independent review, gates and merge were not performed. It does not execute proposed code or certify semantic compatibility, freshness of facts, actor identity, review, or external effects.

After preflight, an authorized integrator must independently review the exact proposal HEAD and semantic relationships, run applicable gates tied to that HEAD and configuration, revalidate the approved base, and follow the repository's existing PR/merge policy. If the base or branch advances, rebuild the packet against the current approved base, reconcile every actual read (including an existing output read while editing), rerun preflight and review the new HEAD. Plan work in progress so one context does not repeatedly rebase while other changes land; an undeclared read makes that attempt ineligible rather than being silently omitted. Use one integrator per target until a provider-enforced current-base queue is qualified; worktrees alone are not a merge lock. The external integrator performs any authorized merge and readback; these commands never do so. A self-reported completed result or this preflight alone is not approval.

The [CLI](../../../scripts/wiki_context_flow.py) offers finite `impact`, `requirements`, `review`, `revalidate` and `preflight` commands.
For a packet containing evidence from another owner, the trusted local
operator repeats `--trusted-context PRODUCER_CONTEXT` after `preflight` or
`requirements`; repeat it for each selected producer. `requirements` also
needs `--context EXECUTOR_CONTEXT` when `--trusted-context` is used. If the
packet has retained additional readers, repeat each with
`--additional-reader READER_CONTEXT` in the same subcommand. These local
selections do not grant access: the current policy's path scopes and exact
bilateral connections still apply, and a separately bound host retains its
own fixed allowlist.
[Dynamic collections](context-dynamic-selection.md) retain their predicate and
digests on the same canonical requirement/edge; authorized `revalidate` compares
sets and selected bytes without asserting factual verification. Its `--graph` argument is an already authorized JSON representation of the existing relation inventory, not a new canonical graph. Its `--packet` and `--result` inputs are the existing task contracts. The current CLI uses the approved `wiki.config.yaml` folder policy; pass the trusted approved revision and use `--help` for arguments. Historical v1 receipts without a verifiable original manifest require requalification. This guide and the synthetic tests do not authorize new credentials, a public export, an external transmission or a scheduler.


## Synthetic pilot preparation

Run `python3 tests/context_pilot_setup.py` from this checkout to create a fresh local-only synthetic Git repository and two short branches in a temporary directory. It writes packets, candidates, task results and preflights as synthetic proof files; it does not perform independent review or merge. Run `python3 tests/context_pilot_checks.py PILOT_DIRECTORY` once using the printed temporary pilot directory to test the cycle limit, revoked grant and parent write denial. The new bilateral connection is simulated only in an unbound in-memory policy; the real approved policy stays pending. The setup creates two example draft interpretations in one process; this is not evidence that independent agents or two harness products ran. Separate context threads may replace those drafts after reading their own packets, then the resulting HEADs must be revalidated and independently reviewed. To complete a pilot, a separate reviewer must review the exact branch HEADs; the authorized integrator then serializes merges in the synthetic repository and refreshes packets and preflight after the base advances.

After independently reviewing and serially merging both synthetic proposals, prepare a separate, unmerged source-change preview commit. Run `python3 tests/context_pilot_verify.py PILOT_DIRECTORY REVIEWED_COST_HEAD PREVIEW_HEAD` to rederive the requirement from the approved output, read that page through the existing inventory, and compare its consumed selector with the preview. The command does not merge, alter a branch, or verify an external fact.

## Explicit inherited normative consumption

When an output actually depends on a whole mandatory lineage instruction, skill
or template, its author may explicitly declare an `information_requirements`
entry with that exact path, `fields: ['*']`, `temporal: current`, a chosen
`max_age_days`, `use: normative`, `source_kind: mandatory`, `classification`, and `consumed_revision`
equal to the packet's **policy revision**. This is a policy dependency, not a
claim that an external fact is fresh. The normal requirements helper does not
implicitly attach all mandatory inputs to every output. Preflight requires the
whole mandatory input and reported read from the packet; a normative label on
ordinary evidence is not an authorization. Evidence with `use: normative` and no `source_kind` remains subject to the usual bilateral connection and may use authorized selectors.

The authorized impact check requires the input to be declared by the current
lineage and permitted by all applicable denies, and to have been declared in
the approved ancestral policy revision at which it was consumed. Folder
receipts must retain their authority format and physical entry/index; v1
receipts lacking a verifiable binding require requalification. It checks
that authority before opening historical content. A changed whole body produces
a review candidate; a revoked, removed or otherwise unprovable authority stops
with an opaque pending-review error. The global caller-trust audit cannot certify
policy authority and conservatively reports a requalification obligation when
relevant context authority changes. A policy or normative edit itself still requires its
separate review; no parenthood or this declaration grants access to ordinary
cross-context evidence.

The global inventory resolves an exact mandatory path outside the memory root
from tracked regular-file Git metadata only. This creates a declared edge; it
is not a grant, and the inventory does not open that external rule body. An
untracked or unsafe target remains an inventory error. Generic information-use
readiness reports `information_normative_authority_required`, not factual
claim/evidence/verification blockers. The existing scoped freshness audit
binding (`--query-context`, `--query-policy-revision`, `--query-head`) also
qualifies normative requirements for the selected owner only. It compares the
approved declaration and historical/current authority and whole bytes, and
requires the proposed rule to be unchanged. Git tree/index and worktree stat
metadata are compared without opening a proposed rule body; unknown or changed
metadata fails closed. The comparison detects ambiguity; it does not certify
worktree bytes. Qualification is for approved Git blobs on a stable host. On
Windows, worktree ctime may mean creation time, so unchanged-rule qualification
remains pending rather than trusting insufficient metadata. This does not protect
against a hostile concurrent host.
Equivalent bytes qualify that
normative requirement without asserting factual freshness; changed, denied or
unprovable authority remains pending. It does not prove semantic reading,
independent review, or authorize an effect. Other contexts are not qualified. The
surrounding global audit and its output remain caller-trust, not a context ACL.
