# Context coordinators

See [source access and ingestion previews](source-access-and-ingestion.md) for
declared accounts/scopes, bounded adapter evidence and read-only composition
of explicitly linked events and actions. These projections grant no execution.

The [native board](native-action-board.md) can show an explicitly assigned coordinator for each canonical action. The domain owner and executor remain unchanged. A consumer-owned `wiki.coordination.yaml` defines the routes; the kit supplies a context composer and a receipted conversation on the action itself. It does not create another task queue or scheduler.

## Consumer configuration

```yaml
schema_version: wiki_coordination.v1
common_context:
  - AGENTS.md
  - .skills/wiki-memory-router/SKILL.md
  - memories/index.md
  - memories/system/git-approvals.md
  - memories/system/operational-wiki-contract.md
  - memories/system/ingestion-process.md
profiles:
  research:
    label: Research
    scope: Research evidence; preserve existing owners and STOPs.
    context_pages: [memories/research/index.md]
    action_ids: [action-review-evidence]
```

Use real page IDs and existing memory pages. Common procedures may also reference explicit `.skills/.../SKILL.md` files. Paths outside the repository, symlinks and arbitrary files such as environment credentials are refused. Assign one primary coordinator per action; missing routes remain visible instead of assigning an arbitrary bot. A profile may coordinate a context with no current action; never create tasks to fill it.

`common_context` is the shared entry point for **every** profile. Include the
consumer's current approval policy, operational contract, ingestion process and
router there; replace the example paths with that consumer's existing pages.
Profile-specific `context_pages` add domain context and do not replace these
common rules. The composer reads explicit references, not every link from a
root page: linking a policy only from the index is not a substitute for listing
it here. Keep one canonical policy and reference it rather than copying rules
into each profile. A current policy may explicitly supersede historical wording;
record its scope without discarding technical, privacy or access constraints.

## Runtime integration

- `GET /api/coordination`: primary coordinator by canonical action ID and revision, with separate owner/executor fields.
- `GET /api/coordination/profiles/research`: context packet for that profile.
- Add `?action_id=action-review-evidence` to select one assigned action. Cross-profile action requests fail.
- [wiki_coordination.py](../../../scripts/wiki_coordination.py) provides the same contract through `--root`, `--profile` and optional `--action-id`.

Packets contain the configured common/domain context and the action's direct page/source/role/decision relations, with page content and hashes. Expansion is bounded to one action hop, not a recursive whole-wiki import. Unresolved references are explicit. Live external sources are not fetched. Snapshot IDs and content hashes prevent combining a cached action with newer source bytes. The packet hash binds scope, profile, action revisions and context. Runtime consumers must reread/recompose before admission and reject revision drift.

This release always reports `runtime_connected: false` and `execution_ready: false`: it prepares context and records directions/questions/answers without claiming delivery or execution. Packet generation is not evidence of LLM reading, context comprehension, authorization or execution. An existing runtime must bind the intended profile, canonical chat, native claim/STOP/dedup checks and permitted operations before dispatch. Do not replace a refused runtime review or existing admission boundary with this reader. Waiting and terminal states remain canonical; coordinator assignment never changes them. Preserve existing action IDs and executor ownership; never import these packets as duplicate domain Tasks.

Runtime results must retain provenance and use the existing guarded action-transition contract, with revision checks and evidence for completion. A queued, claimed or settled runtime job is not a completed wiki action. The [standalone board](native-action-board.md) remains usable while execution is unavailable.

## Delegation contract

Use the existing [subagent brief](../templates/wiki/subagent-brief.md) to bind a
delegated slice to the canonical action and the composed context. Before work
that depends on a capability, the executing instance must establish:

| Required information | Existing source or evidence |
| --- | --- |
| Task and base | Canonical repository/action ID, page revision, packet hash and existing owner/executor |
| Current rules | Explicit common policy sources, granted authorization and its limits |
| Work context | Domain pages, source/configuration IDs, evidence and consolidation destinations |
| Effective capabilities | Actual host/session, account/resource and available tool, with a current bounded check for the required operation |
| Completion | Result evidence, applicable validation/review and ingestion/consolidation into the destination pages |
| Recovery | Affected step, exact blocker/receipt, bounded attempts and the changed precondition for resuming the same work |

These are references and execution evidence, not a new configuration schema or
an additional task store. A receiving agent reads the current pages; a packet
hash proves content binding, not comprehension. Runtime admission separately
checks actual capabilities, current authorization and reservations. Missing
context or access holds only dependent work; it does not cancel unrelated
authorized work or require generic confirmation for consent already granted.

Record the blocker on the existing action. If no retry budget is specified,
stop the affected attempt after recording it. Do not enter a repair loop for an
unchanged refusal. Ask a specific question only when a missing decision or new
scope requires it. Reconcile action/event IDs and any existing runtime task/run
or contribution IDs before resuming, preserving STOPs, unresolved questions and
other blockers. After a timeout, check retained evidence before retrying an
operation with external effects; do not create a duplicate action or assume the
previous attempt had no effect.

Returned results follow the consumer's existing ingestion and consolidation
process. Record sources, events and destination pages, including
`consolidated_into` and `source_refs` where that process requires them. Update
the canonical page through its normal guarded writer or reviewed contribution;
the board projects that page. A runtime completion receipt alone cannot close
the wiki action.

Name the existing actor responsible for consolidation/publication in the brief;
it may be the coordinator or another already authorized executor. Accept a
read-only or patch-only slice on its agreed artifacts and evidence without
requiring that child to acquire writer credentials or perform a merge outside
its scope. The responsible actor completes integration through the same wiki
process. Track the slice's delivery separately from the canonical action's
closure, and keep any pending consolidation visible on that action.

## Card conversation and asynchronous work

The action page stores append-only `action_dialogue` events. A changed next step
in the routed board atomically records a `direction` event and `next_action` in
the same revision-checked write. Priority-only changes do not create a direction.
Each event has `event_id`, `kind`, `text`, `coordinator`, optional `reply_to`, and
server-authored `actor`, timestamp and base revision. Kinds are `direction`,
`question`, `confirmation_request`, `answer`, and `comment`. Events never contain
credentials. Questions remain visible until a specific linked answer is recorded;
other questions and blockers stay pending. An answer is not blanket consent,
proof of execution, or a lifecycle transition. Terminal actions cannot receive
new execution directions or dialogue through this writer.

The guarded `POST /api/actions/transition` accepts `dialogue_event` alongside the
existing state contract. The browser adapter always binds actor `operator` and
validates the configured route. It does not accept a claimed agent identity in
the JSON event. Receipt v4 binds the complete dialogue and retains v1/v2/v3 read
compatibility. CAS, atomic write, append-only history, secrets checks and existing
origin/nonce/attempt guards apply. Unknown routes and stale revisions fail.

A pure `comment` is receipt of a communication, not incorporation of its text
as a factual conclusion. The native writer preserves the action body, state,
owner, next step, blockers and factual `updated_at`; the real arrival time lives
in the event and its `comment` receipt. Other event kinds and mixed changes use
the ordinary documentary lifecycle. Existing v4 `contract_update` receipts
remain readable with their original timestamp semantics.

The ordinary proposal command also accepts this typed dialogue event, using
the same coordinator/action route and fixed operator identity. It preserves
revision checks, live session admission, independent review and publication
gates. A received run ID or effect reference is not a new execution or a claim
that its proposed documents have been integrated. Keep that pending work
explicit in the comment and reuse the existing action.

A trusted local agent adapter can invoke [wiki_coordination.py](../../../scripts/wiki_coordination.py)
with `--profile research --action-id action-review-evidence --event-file event.json
--expected-sha256 REVISION`. It validates the route and records the selected
coordinator as actor. `--as-operator` is for trusted local operator integrations.
This CLI has the filesystem user's authority: profile flags are not credentials
or an isolation boundary. A runtime must bind the actual caller to its allowed
profile before exposing it as a bot tool. No remote agent write endpoint or
shared secret is introduced. Example event:

```json
{"event_id":"question-synthetic-001","kind":"question","text":"Which source confirms the date?","coordinator":"research"}
```

A response uses `kind: answer` and `reply_to: question-synthetic-001`. Duplicate
IDs, answering one's own question, conflicting answers and malformed inputs are
refused. The UI preserves a draft after a failed save. Delivery/claim/retake
receipts remain the responsibility of the existing executor; this release does
not invent them. Consumers must reconcile event ID, action revision and context
before resuming, preserving STOPs, other blockers and existing reservations.

## Account and capability requirements

Profiles may declare `required_tools` (a list of descriptions) and
`access_requirements` (each with `service`, `expected_identity`, `method` and a
canonical `source_ref`). Source configuration pages enter the context packet.
These are requirements, not access grants: `access_verified` remains false.
The canonical source/configuration page can specify the expected host and
environment without adding credential fields to this policy. The executing
instance checks its own tools, host/session, effective account and resource
permissions separately for each required service and operation. A coordinator's
successful check does not establish the child's capability, and a read does not
prove write access. If missing or mismatched, record the evidence on the card
and hold the affected operation under the bounded recovery contract above.
Do not silently inherit a personal account for a corporate context, copy tokens
into the wiki, or treat a successful login in one service as proof for another
service. Native tool enforcement and account-bound credentials remain with the
runtime that actually executes tools.

## Validation

Synthetic tests cover primary-route uniqueness, wrong-profile rejection, terminal preservation, path boundaries, stale content, unmapped new actions and HTTP origin checks. No private consumer routes are distributed by the public kit.

## Optional answer observation

The shared board can notify an existing local executor after a human answer is
committed. The consumer opts in per coordinator; absent configuration records
the answer without notifying an executor:

```yaml
profiles:
  research:
    label: Research
    scope: Review this project's sources within its existing authority.
    action_ids: [action-review-source]
    answer_observer:
      argv: [project-agent, observe-canonical-answer]
      timeout_seconds: 10
```

The command is selected by trusted consumer policy, never by card text or the
HTTP payload. The kit appends `--event-file` and a private temporary JSON path,
uses no shell, and calls it after the action writer releases its locks.
Activation is an intentional server-startup decision: its policy hash is pinned
at startup. A live edit cannot substitute another command; reactivation stays
with the operator's normal reviewed application adoption. Removing the optional
observer disables delivery without undoing the recorded answer. It
captures only the selected canonical action and receipt chain, without
rebuilding the global wiki snapshot. The timeout is bounded from 1 to 30 seconds;
large-wiki context composition is not part of this callback.

The envelope has `schema_version: wiki_canonical_answer_observation.v1`,
`task_ref: {repo_id, action_id}`, `profile`, the complete **persisted canonical**
`event`, `receipt`, and `source`. The event includes its real normalized text,
actor, timestamp and before hash; it is not relabeled as the untouched HTTP
payload. Immediate delivery carries the actual in-memory append receipt and
`source: {kind: wiki_cockpit_action_transition, route: /api/actions/transition}`.
No nonce, credential, invented principal or blanket authorization is forwarded.

A consumer's JSON acknowledgement contains `ok`, `status`, matching `task_ref`
and `event_id`, `unblocked`, and `model_started: false`. Status is `resumed`
only after the consumer's existing unblock CAS succeeds; `observed` is an
idempotent observation without a new transition; `held` keeps the task waiting
under STOP or another current block; `refused` rejects invalid correlation or
policy. Optional task/run references remain owned by that executor. The kit
checks this acknowledgement binding. Delivery alone is not model execution,
account verification, new authority or complete project integration. The board
shows ready, held or unconfirmed delivery without calling those states running.

The executor must verify the action, canonical operator answer, question
`reply_to`, receipt lineage, profile, pinned scope and current authority before
resuming the **same** task and run lineage. It deduplicates by event ID using its
existing task/event state. The wiki creates no job, poller, scheduler or second
task journal. Other agent applications can implement the same optional CLI
contract; no Hermes or Dot dependency is introduced.

A timeout or missing/invalid acknowledgement preserves the committed answer
and reports delivery unknown. Do not repeat the answer POST or launch a new
model. If the original observation is retained in the executor's existing
history, reuse it exactly. A canonical reconciliation instead carries only
`receipt: {receipt_id}` and
`source: {kind: wiki_canonical_answer_reconciliation, coverage: canonical_event_and_transition_lineage}`.
The [observation helper](../../../wiki_core/answer_observation.py) supports this
explicit variant. It does not invent a lost original after hash or HTTP
provenance. Both variants verify the original payload hash over the complete
dialogue prefix (including the referenced question), and the current governed
support hash. If other support changed with the answer and was overwritten by
a later receipt, its old values are not retained: reconciliation refuses rather
than infer that payload. Consumers can reuse the pure
`validate_canonical_answer_payload(frontmatter, event_id, receipt_id)` helper
from the same module under their existing canonical-source lock. It performs
no I/O or unblock and does not replace profile, authority or STOP validation.
Missing retained proof leaves the work held/unknown; recovery after
a process crash is bounded by actual retained history, not promised as complete.
The kit retains no extra durable delivery queue. The operator owns activation
and reader/service adoption in the project application already in use.
