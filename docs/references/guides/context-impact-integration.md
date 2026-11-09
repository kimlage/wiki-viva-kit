# Context impact and integration preflight

An approved task packet exposes the selected context's purpose, owner, root and lineage, plus scoped ceilings, currently approved imports and the owner/connection boundary. It does not expose other manifests or unapproved protected paths; it is a policy view, not a sandbox claim.

The [impact module](../../../wiki_core/context_impact.py) consumes the existing relation inventory through its `dependency_edges` normalization; it does not persist a second graph or queue. The caller must be authorized to read the inventory and provide a trustworthy, complete-enough view: the output cannot certify inventory completeness or prove that an agent read a receipt. Navigation and association edges do not trigger review. A legacy dependency without a fixed `consumed_revision` is returned as `blocked_unpinned_dependency` instead of being silently called fresh. A supplied 40- or 64-character Git commit identifies the actual input revision; the selector is resolved at that commit, independently of the transaction's before revision. A digest proves selected bytes/contract, not current observation of an external fact.

An approved consumer page may declare its dependencies in the existing `information_requirements` frontmatter: the four legacy fields `target`, `fields`, `temporal` and `max_age_days`, plus optional fixed `consumed_revision`, `use` and `classification`. Missing revisions remain unpinned. The `impact --consumer PATH` form reads the consumer from the approved Git revision and derives these edges through the existing parser, without returning the raw graph. It resolves explicit repository paths only; page-ID lookup is not performed. Folder impact requires `after` to be the current approved revision. Before opening older content, it checks approved ancestry and the historical and current authority; a missing authorization remains a coverage limit. Review also rechecks historical authority and the selected input digest before a reported disposition may seed further impact. The `requirements` command checks a completed packet/result, the reported reads and selected digests, current grants, and that the exact proposal commit is incorporated with the same output bytes in the approved revision. It proposes `information_requirements` for the page but writes nothing; a reported read is not proof of comprehension. When a proposal adds or changes such declarations, preflight checks each new selector and fixed revision against evidence the task reported reading; an unpinned new declaration is not eligible for ordinary preflight. Existing legacy declarations remain unpinned until explicitly updated.

For dynamic queries, the data revision and the policy revision under which it
was read can differ. Review uses the policy recorded by the approved consumer;
historical and current read restrictions still apply before opening members.
Older folder candidates whose impact policy differs from their `after` revision
must be requalified; retaining their history does not make them current reviews.

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

### Joint proposals with multiple owners

The in-process `preflight_composite` accepts one exact `base`, `head` and
`branch`, a host-provided `CoordinationBinding`, and a list of participant
objects. Each contains `context_id`, its original `packet` and `result`, and
optionally the exact `additional_readers` retained by that packet. Every
participant result reports only that owner's changes. The function derives
ownership from the current approved policy and partitions the actual Git diff;
missing, duplicate or extra participants and incomplete or overlapping change
reports fail closed. It reuses the per-context packet, query, read and write
checks against the **complete** proposal tree, and returns a bounded summary and
digest of the complete path/action list. It does not combine previously issued
preflight results. Existing single-context `preflight` still covers the whole
diff. The operation permits at most 64 participants and 4,096 changed paths.
Before copying its JSON-like inputs, it applies a conservative 8 MB aggregate
serialization estimate, a 100,000-node limit and a maximum depth of 64; the
estimate may reject some smaller payloads. Errors are opaque and do not report
the path or owner that caused a subcheck to fail.
The returned summary follows the [composite preflight schema](../schemas/wiki-context-integration-composite-v1.schema.json).

The local operator can call the API or use the CLI. The operator-selected
`participants.json` is a JSON array of objects; each object has the keys
`context_id`, `packet` and `result`, with an optional `additional_readers`
array. The packet and result are the complete original JSON objects, not paths,
digests alone or previously returned preflights. Protect this input according to
the data it contains. With an independently established folder coordination
binding in the host environment, a local invocation is:

```sh
python3 scripts/wiki_context_flow.py --repo /path/to/wiki \
  --approved-revision "$WIKI_COMPOSITE_APPROVED_SHA" preflight-composite \
  --base "$WIKI_COMPOSITE_APPROVED_SHA" --head "$WIKI_COMPOSITE_HEAD_SHA" \
  --branch wiki/example-proposal --participants /path/to/participants.json
```

There is no new HTTP route. The caller must independently authorize the
integrator to receive metadata for every context; the binding is only a
configuration ceiling and grants no cross-context access. The output does not
prove actor identity, a signed result, semantic consistency, consumer log rules,
or that any participant performed the work. It is not an approval: independent
review, gates and merge remain outstanding. A split into multiple proposals is
appropriate only when each intermediate state and the consumer's log rules are
independently valid.

### Policy and normative changes

The separate policy-review path can use the consumer's existing, authorized
Git/PR process; the kit has no dedicated command that approves a policy change.
For an intended scope or normative change:

1. Identify the current trusted policy revision, affected owners and scopes,
   and the authority already permitted to propose, review and integrate the
   change. Keep the proposed diff minimal and reviewable.
2. Have an independent reviewer assess the exact diff, authority and impact;
   run the consumer's applicable gates and follow its own PR and promotion
   policy. The proposed policy must not authorize its own review or merge.
3. After an authorized integrator merges the change, read back the integrated
   revision and the host's trusted ref. A PR, Git ref or SHA alone is not proof
   that the required approval or host authorization occurred.
4. Reconstruct affected packets under the approved resulting policy and
   revalidate current scopes and any required connections. Separately establish
   the host binding and actual caller identity, capabilities and effect
   admission; the binding is a ceiling, not a grant. Preserve any applicable
   claim, STOP and consumer review requirements.

Neither the ordinary nor composite preflight approves the candidate policy,
and the impact `review` command reports a disposition rather than approving a
policy. If the authorized external process, current trusted ref or required
authority cannot be established, keep that operation pending. This guidance
does not create a new CLI, attestation, grant or provider-enforced review.

### Integrating a preflight proposal

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


## Historical synthetic pilot

The scripts `tests/context_pilot_setup.py`, `tests/context_pilot_checks.py` and
`tests/context_pilot_verify.py` document an earlier synthetic v1 pilot. They do
not demonstrate the current folder-based flow: its verification step attempts
to create new v1 requirements, which the migrated interface refuses. Preserve
the scripts as historical context, not as an executable acceptance procedure.
For current operation use the folder-based packet and requirement flow described
above and in [context reader](context-reader.md) and
[dynamic collections](context-dynamic-selection.md). A synthetic packet or
event alone does not establish independent review or incorporation.

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
