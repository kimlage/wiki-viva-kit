# Context coordinators

See [source access and ingestion previews](source-access-and-ingestion.md) for
declared accounts/scopes, bounded adapter evidence and read-only composition
of explicitly linked events and actions. These projections grant no execution.

The [native board](native-action-board.md) can show an explicitly assigned coordinator for each canonical action. The domain owner and executor remain unchanged. A consumer-owned `wiki.coordination.yaml` defines the routes; the kit supplies a canonical protected task packet route and a receipted conversation on the action itself. It does not create another task queue or scheduler.

## Consumer configuration

```yaml
schema_version: wiki_coordination.v1
profiles:
  research:
    label: Research
    scope: Research evidence; preserve existing owners and STOPs.
    action_ids: [action-review-evidence]
```

Use real action page IDs. Assign one primary coordinator per action; missing routes remain visible instead of assigning an arbitrary bot. A profile may coordinate actions in multiple canonical contexts; never union those contexts' permissions or create tasks to fill a profile. IDs and profile labels supply routing and historical attribution, not access grants.

Where the owner explicitly authorizes an identified integrator under the
consumer's policy, that integrator may read across contexts for audit and
reconciliation within that authority. This does not transfer access to
executors or authorize content or policy writes; those remain with the owner
or authorized executor. Promote only proposals authorized by the responsible
owner and independently reviewed under applicable policy. Classify
existing denies by purpose under the current owner direction; do not retain an
inter-context isolation restriction automatically or relax specific secrecy,
audience, unclassified denies or external-effect limits. The owner's decision
can authorize the policy change without requiring the replaced configuration
to already permit it. Existing enforcement applies until the authorized policy
change is effective and the host binds the resulting authority. A documented
rule does not itself change the protected route or prove host enforcement.

The board's **Fronts** view derives projects and initiatives from canonical
pages, including fronts without an active action. Optional `front_refs` on a
profile selects existing page IDs or paths for differently typed contexts.
These references add navigation, not copied statuses or another task store.
Declared status, documentary date, owner, explicit action links and evidence
stay on the source page. Historical tags, coordinator assignment and open
actions never prove live execution or override a paused front. Missing and
changed references remain visible as projection warnings. Protected single-action
context packets do not expand their authorized readset to this inventory.

Task bodies come exclusively from the [protected coordination route](context-coordination-protected.md), with an explicitly selected canonical context, approved policy revision, content revision and task selection. Mandatory rules belong to canonical context instructions/skills/templates. Evidence is selected explicitly or through authorized queries; cross-context evidence requires matching imports/exports. Legacy `common_context` and `context_pages` no longer prepare task content and are not required entries for a profile.

## Runtime integration

- `GET /api/coordination`: caller-trust operator index with primary coordinator by canonical action ID and revision, and separate owner/executor fields.
- `GET /api/coordination/profiles/<id>` and CLI `--profile` without an event: constant `coordination_context_required` migration response, without bodies or a snapshot.
- [wiki_coordination.py](../../../scripts/wiki_coordination.py) with `--context-id`, `--approved-revision`, `--revision` and `--packet-request`: explicit protected task packet. Read the complete packet's mandatory rules and selected evidence, not a truncated sample.
- Dialogue CLI: `--profile`, `--action-id`, exact configured `--action-path`, `--event-file` and `--expected-sha256`; see the protected coordination guide for migration examples.

Argument errors and expected input failures in these context CLIs avoid echoing
operator-supplied values; successful output and other logs still need their own
privacy boundary. The dialogue adapter reads at most 16,001 bytes from a regular
event file before parsing. Nonblocking open is used where available; without it,
opening a special file may still block before the type check. If a transition
fails after it starts, inspect the action state before retrying: the CLI does not
claim that a failure rolled back every effect.

Packet generation is not evidence of LLM reading, comprehension or execution. Runtime admission separately checks actual capability, authorization, claim/STOP/dedup and permitted operations. Profiles never select a canonical context or bypass a refused admission check. Waiting and terminal states remain canonical; coordinator assignment never changes them. Preserve existing action IDs, executor ownership and conversation history; never import packets as duplicate domain tasks.

The [coordinator role contract](../../../.skills/wiki-viva/reference/coordinator.md)
sets the behavioral boundary for both opening and resumption: the coordinator
maintains direction and the owner's acceptance criteria; existing integrators perform product code,
tests, integration and infrastructure. Before any dispatch, the coordinator
checks current owner direction and pauses; an old queued message does not lift
a later pause. A protected packet may request `task.role: coordinator` to
include the complete role contract from the current approved revision, subject
to ordinary policy and deny checks. A denied or missing contract fails closed.
Role selection and packet composition are not runtime authentication or a
pause barrier: the host must bind the actual role and revalidate current owner
state at execution. The local generic brief composer and editing job runner
refuse the coordinator role. Legacy jobs without a role still default to executor:
the host must identify existing coordinators independently and refuse stale
dispatches when their current pause or role cannot be established. An external
T3 launcher is not implemented or controlled by this kit.

Runtime results must retain provenance and use the existing guarded action-transition contract, with revision checks and evidence for completion. A queued, claimed or settled runtime job is not a completed wiki action. The [standalone board](native-action-board.md) remains usable while execution is unavailable.

## Delegation contract

Use the existing [subagent brief](../templates/wiki/subagent-brief.md) to bind a
delegated slice to the canonical action and the composed context. Before work
that depends on a capability, the executing instance must establish:

Identify the sender and intended recipient of each handoff. A sender's account
of their own limits does not change the recipient's assignment. A role change
requires explicit direction from the coordinator responsible for the scope or
the owner; this behavioral rule does not authenticate the sender.

| Required information | Existing source or evidence |
| --- | --- |
| Task and base | Canonical repository/action ID, page revision, packet hash and existing owner/executor |
| Current rules | Canonical mandatory policy bodies, granted authorization and its limits |
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

For each additional blocker, identify the applicable current instruction or
the reproducible failure, including the affected operation and limit. Distinguish
an actual denial, an unverified capability and a restriction imposed by the
agent itself. An offline execution limit alone does not forbid reading an
authorized source. Reuse authorization that remains valid after checking the
executing instance's identity and access and current STOPs; do not bypass denies
or expand scope. A slice executor need not acquire writer credentials.

Before an external effect, the integrator checks the owner's applicable current
acceptance for that version and operation, including a merge that publishes to
production. Reuse acceptance that remains valid; if required acceptance is
missing, hold only the dependent effect while authorized preparation, tests and
review continue.

Record the blocker on the existing action. If no retry budget is specified,
stop the affected attempt after recording it. Do not enter a repair loop for an
unchanged refusal. Ask a specific question only when a missing decision or new
scope requires it. Reconcile action/event IDs and any existing runtime task/run
or contribution IDs before resuming, preserving STOPs, unresolved questions and
other blockers. After a timeout, check retained evidence before retrying an
operation with external effects; do not create a duplicate action or assume the
previous attempt had no effect.

When a final gate requires a generated artifact, do not require that gate to
have approved the merge before allowing the artifact's preparation. Identify
the responsible owner and isolated workspace, and review the preparation under
the existing independently authorized process. Before any authorized write,
verify the reviewed input bytes and HEAD; generate finitely, then run the complete
applicable gates and independent review on the final SHA. Merge by expected
head and read back the result. A candidate does not approve its own authority
and this sequence waives no gate. If authority is missing, only the dependent
step waits for the specific decision.

Returned results follow the consumer's existing ingestion and consolidation
process. Record sources, events and destination pages, including
`consolidated_into` and `source_refs` where that process requires them. Update
the canonical page through its normal guarded writer or reviewed contribution;
the board projects that page. A runtime completion receipt alone cannot close
the wiki action.

Name the existing authorized integrator responsible for consolidation and
publication in the brief. The coordinator routes and consolidates results; the
integrator performs product changes, tests, integration and readback. Accept a
read-only or patch-only slice on its agreed artifacts and evidence without
requiring that child to acquire writer credentials or perform a merge outside
its scope. The responsible actor completes integration through the same wiki
process. Track the slice's delivery separately from the canonical action's
closure, and keep any pending consolidation visible on that action.

Each delivery uses a short brief in the existing action or thread: expected
result, verifiable acceptance criteria, current state or blocker, and the next
responsible actor. Reference common rules instead of copying them into the
brief. The executor returns evidence and remaining work against those criteria;
an independent reviewer compares each criterion with the evidence and records
findings and their resolution. The integrator checks review, applicable
validations, approved-main readback and wiki reconciliation. The coordinator
correlates the states and evidence across fronts and reconciles discrepancies;
a partial merge or sent message alone does not resolve a dependency.

## Integration by destination

The coordinator maintains direction, priority and convergence to the action's
acceptance criteria, and checks the owner's acceptance; the coordinator does
not integrate or grant the owner's acceptance. Assign an
integrator for each destination repository and target branch. The integrator
receives the executor handoff, verifies the proposal, independent review of the
exact final head, validations and approvals required by the destination policy,
then integrates, reads back the target main, cleans up the branch and worktree
and updates the existing action. Send findings and correction criteria to the
responsible thread; request information or access from other fronts only within
their owners' authority.

The integrator's runtime thread must be able to follow proposal events through
completion; a delegated child unable to observe those events cannot serve this
role. One proposal integrates at a time per destination; separate destinations
may proceed in parallel. The default preparation limit is two proposals per
destination and the consumer can adjust it. A new proposal must serve the
action's acceptance criteria; record an out-of-scope finding on the action or
in an issue instead of creating a proposal.

Read policy from the destination's `wiki.config.yaml` `approval:` block, or
from its AGENTS or equivalent repository rules if it has no wiki. If
`require_human_review: true`, prepare all other work, wait for human approval
of the exact final SHA and resume when it arrives. GitHub is an adapter, not an
assumption about the destination. The [handoff template](../templates/wiki/subagent-brief.md#integration-handoff)
records the proposal and evidence needed by the integrator.

## Thread continuity and closeout

When taking responsibility for a front, receiving a result and before ending a
turn, the responsible operator checks authorized open threads in their scope and
reconciles delivery in the canonical action, wiki or PR. A completed turn is not
a completed delivery; inactivity alone does not prove a blockage or justify
archiving or settling. Check current state, owner direction, WIP and STOPs before
resuming an authorized, executable next step in the same thread. Send a short
handoff naming the completed point, existing artifact, next step and acceptance;
avoid a second writer or a duplicate effect. Follow the result and decide the next
operation rather than stopping at an acknowledgement.

Use the host's existing read/send/wait interface when available. Where the host
documents `thread send --wait` and `thread show`, exit 1 means failure and exit 2
means waiting for an answer; confirm actual state and do not resend just to wait.
Reconcile a failure or uncertain effect before retrying; the same denial or
blocker without new evidence is not a reason to repeat it. Respect the runtime's
own `next`, delegation and PR-watch instructions. When no progress is possible,
record the exact blocker, evidence, dependency or missing input and responsible
provider on the existing action, route it to the coordinator and continue
independent work. Do not turn a local blocker into a global gate.

Settle a work thread only after its required independent review and gates,
integration into the approved main branch, result readback and reconciliation
with the canonical wiki. A sub-delivery, finished runtime job or merged PR does
not close a front with remaining scope or acceptance. After the turn ends, an
authorized observer, coordinator or host checks the effective settled state
through the existing host interface. A read during the turn does not prove a
later transition. If the state hides pending work, restore visibility and resume
the same thread only under current direction and STOPs. If no observer is
available, report verification pending on the existing action without guessing
its cause. Keep unresolved work and blockers visible on the existing action.
Report actual completion, resumption or an actionable blocker to the existing
coordinator; do not send confirmation-only updates. This is an operator
agreement, not a scheduler, access grant or proof that a runtime integration
exists.

### Post-merge cleanup

For the wiki and each coordinated project, only `main` is permanent. Every other
branch has a PR; push and open a draft no later than the end of the turn in which
it was created. A draft records incomplete or paused work, including STOP, and
does not authorize resumption. A ready PR is awaiting review, a merged PR is
integrated, and a closed PR is discarded with its specific reason in a comment.

Compare content against current `main`: integrate useful work or discard it;
branch name and age do not decide. Commit and push uncommitted worktree changes
before deciding. For squash or rebase, compare the content and later commits;
a merged label alone does not prove that the current head is covered. Preserve
unique work, including untracked or ignored files, without deleting personal or
historical files outside Git. Compare expected heads immediately before mutation.
If anything changed, reconcile it before deleting that item.

On merge or close, remove the local and remote branch and worktree in the same
delivery. Do not create backup branches, bundles or snapshots. On GitHub, PR
commits remain available through `refs/pull/<n>/head`; other adapters have their own
retention behavior. Enable automatic deletion of merged branches
where authorized, and still verify local and remote state. Read back branches,
worktrees and PRs, and record the result with the existing delivery. Retain valid
review and test evidence for unchanged work; new changes or concerns receive the
applicable validation. Keep incomplete work in its PR rather than a new queue.

For a process failure, record its cause and the applicable rule or source on
the existing action, issue, PR or log. If the rule was adequate, fix its
implementation or application; if ambiguous or wrong, edit or remove the
canonical rule, adding one only if that does not resolve it. The coordinator
identifies recurrence; integrators return evidence and the kit owner integrates
the common correction. Validate against the failed case, using synthetic fixtures
where needed, integrate and read back the kit, then qualify consumer adoption and
readback. Check effectiveness on the next eligible delivery in the same process
issue or action. That later check does not circularly block closing an already
accepted lot; if the failure recurs, resume the same occurrence without an agenda.

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
with `--profile research --action-id action-review-evidence
--action-path memories/actions/review-evidence.md --event-file event.json
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
Each requirement may additionally declare `action_ids` belonging to that
profile, plus `operation`, `resource` and `recovery` descriptions. The board
separates action-specific requirements from profile-wide requirements. A
requirement without `action_ids` is not evidence that every action needs that
service. Check the effective account identity, not a browser's numeric account
index; changing `/u/N` can select another signed-in account. Recovery uses the
existing authenticated flow and grants no new permission.
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

## Optional session hooks

The repository may opt in to `scripts/wiki_session_hook.py`. It consumes one
provider event as JSON on stdin. It uses the read-only integration checker and
returns JSON to the host; it does not post, merge, clean, persist a queue or
change action state. `SessionStart` injects a short count summary. `Stop` defaults
to `--mode observe` and warns only. `--mode enforce` may request one continuation
for a verified current-branch-without-PR, uncommitted current worktree or merged
current branch/worktree remaining. It does not block on other findings or an
unavailable observation. A provider `stop_hook_active` event ends that one
attempt; no generic continuation is requested.

`SubagentStop` checks only the explicitly selected executor agent types. Its
final handoff uses separate `Proposal`, `Head`, `Base`, `Review`, `Gates`,
`Pending` and `Responsible-Thread` lines; head and base are nonzero full SHAs,
the proposal is a URL or numbered PR, review is a reference, gates name a
command and result, and the thread has a runtime reference. Pending may say
`none`; placeholders do not count as evidence. An incomplete executor handoff
may cause one focused continuation. This is a shape
check, not proof of review, gates or delivery. Claude's `SubagentHandback` may
carry the report separately from `last_assistant_message`; when the host does
not supply the report in that field, this adapter cannot verify that handback.
Do not enable blocking for that flow without a host adapter that supplies it.

A continuation requires a trusted host-maintained `--stop-state-file` whose
entire content is `running`. A missing, unreadable, stale or unrecognized
state must be represented as `unknown` by that host; `stop`, an explicit
`stop_requested` input, a STOP notice in the response, or an already active
stop hook prevents a continuation. This file is an input owned by the host,
not created by the kit. The hook cannot authenticate its contents or infer a
user STOP from an unavailable transcript. Only enable blocking if the host
can maintain this state for the current session and respect owner STOPs.
The `--executor-type` option can be repeated; absent it, only `executor`
qualifies. `--timeout` is bounded to 1–60 seconds. These are opt-in behavior
and do not grant authority or replace the destination policy.

Codex discovers project hooks in `.codex/hooks.json` (and requires trust for
non-managed hooks); Claude Code reads `.claude/settings.json`. The following
examples use a placeholder for a host-maintained state file. Install only the
provider's configuration in the consumer repository, adjust paths and
executor type, and follow the host's trust and policy requirements. The same
script handles both providers.

Codex `.codex/hooks.json`:

```json
{
  "hooks": {
    "SessionStart": [{"hooks": [{"type": "command", "command": "python3 \"$(git rev-parse --show-toplevel)/scripts/wiki_session_hook.py\"", "timeout": 45}]}],
    "Stop": [{"hooks": [{"type": "command", "command": "python3 \"$(git rev-parse --show-toplevel)/scripts/wiki_session_hook.py\" --mode observe --stop-state-file /path/to/runtime-state", "timeout": 45}]}],
    "SubagentStop": [{"matcher": "^executor$", "hooks": [{"type": "command", "command": "python3 \"$(git rev-parse --show-toplevel)/scripts/wiki_session_hook.py\" --executor-type executor --stop-state-file /path/to/runtime-state", "timeout": 45}]}]
  }
}
```

Claude Code `.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [{"hooks": [{"type": "command", "command": "python3 \"${CLAUDE_PROJECT_DIR}/scripts/wiki_session_hook.py\"", "timeout": 45}]}],
    "Stop": [{"hooks": [{"type": "command", "command": "python3 \"${CLAUDE_PROJECT_DIR}/scripts/wiki_session_hook.py\" --mode observe --stop-state-file /path/to/runtime-state", "timeout": 45}]}],
    "SubagentStop": [{"matcher": "^executor$", "hooks": [{"type": "command", "command": "python3 \"${CLAUDE_PROJECT_DIR}/scripts/wiki_session_hook.py\" --executor-type executor --stop-state-file /path/to/runtime-state", "timeout": 45}]}]
  }
}
```

After observing behavior, an authorized consumer may change the Stop command
from `--mode observe` to `--mode enforce`. Official schemas and lifecycle
semantics: [Codex hooks](https://learn.chatgpt.com/docs/hooks) and
[Claude Code hooks](https://code.claude.com/docs/en/hooks).
