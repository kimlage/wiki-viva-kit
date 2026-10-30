# OpenClaw through the action card

The existing Kanban action is the entry point. Its runtime section uses the
[administrative bus](../../../wiki_core/web/admin/commands.py), the current
operator session and the [normal proposal workflow](revocable-documentary-proposals.md).
There is no standalone mission command, shell input, arbitrary RPC selector,
new scheduler or second task queue. OpenClaw retains runs; the wiki retains
action authority and reviewed results.

## Consumer setup

The consumer integrator supplies existing local installation and session
metadata in its reviewed configuration. No credential belongs here. This
synthetic example is deliberately not an account or a working installation:

```yaml
openclaw:
  enabled: true
  node_binary: /opt/example/node
  entrypoint: /opt/example/openclaw/openclaw.mjs
  profile: example
  state_dir: /home/example/.openclaw-example
  gateway: ws://127.0.0.1:19880
  mission_options:
    execution:
      label: Example execution
      model: openai/example-model
      effort: high
  routes:
    research:
      session_key: agent:research:example
      session_id: existing-physical-session-id
      label: Example coordinator
      native_thread_id: existing-native-codex-thread-id
```

`research` must already own the action in the consumer's coordination policy.
Absent configuration means disabled. Only loopback WebSocket destinations are
accepted; the browser cannot choose executables, profile, state directory,
destination or physical session. Installation, account authorization and actual
agent tools/sandbox remain consumer responsibilities. A configured route is not
proof of connection, login, account isolation or effective tool access. A profile
name is not an ACL. Changing operator route or authority configuration requires its normal reviewed
adoption and process restart; a running server refuses stale configuration.
After native proposal preparation/adoption, the server can refresh documentary
audit pointers only when every other configuration field remains unchanged.

The adapter uses the installed official OpenClaw gateway client. It obtains
authentication through that client's existing state, without reading, copying
or returning tokens. The integration requires the native `chat.history` and
`chat.send` contracts, physical session identity, expected-leaf comparison and
idempotency keys. Unsupported versions fail closed; this does not install or
upgrade OpenClaw.

## One action, one retained execution

1. Open the canonical action. Unlock the existing local operator session and
   select **Review dispatch**. The plan shows the exact outgoing message,
   action revision, context digest, profile, session and effect identity.
   Only that message is exported; page bodies are not silently sent.
2. Execution rechecks current authority, checkout, action, blockers, policy,
   configuration and the native session leaf. An atomic intent precedes the
   single native send. Acceptance means started, never action completed.
3. Use **Reconcile existing run**. It only reads the same physical session and
   exact terminal message. A timeout or interrupted response retains the
   intent and bars another mission until the attempt is reconciled. Corruption
   is an explicit hold, not permission to start over. Refresh/restart discovers
   these receipts; it never dispatches on mount.
4. **Prepare receipt proposal** derives a native comment on the same action,
   with a distinct receipt effect and a reference to the retained result.
   **Review wiki incorporation** uses the existing proposal writer. It preserves
   action state, owner, blockers, next step, body and factual timestamps. With
   C3, only proven physical CURRENT guards follow the comment; BASE and authored
   interpretations remain unchanged. Ordinary validation still decides admission.
5. Publish the exact prepared commit and open its draft PR from the card.
   Obtain independent review through the existing diff/gates/PR surface. The
   integrator supplies the existing review artifact and digest for that HEAD;
   the form neither creates a review nor approves as the user. Promotion uses
   the normal gates and provider CAS.
6. **Review refresh of approved content** observes the merged PR and pins the
   remote main commit before fetching. It preserves the proposal branch and
   fast-forwards a clean main, with live admission at each effect. Ref changes,
   divergence, occupied main or pending files stop adoption. After interruption,
   reconcile actual refs; an already adopted target is observed without writes.
   Reload the card and verify the receipt on the served approved version.

After incorporation, normal cleanup of the merged proposal branch does not
erase receipt recognition. Recovery verifies the retained prepared action
bytes, their digest, the append-only canonical history and the immutable result
reference. A missing branch alone never proves that a proposal was adopted.

Prepared, published, integrated, adopted and served are separate observations.
Receiving a result does not incorporate documentary changes suggested in that
result or close the action. Those changes retain their existing proposal and
review requirements. A rejected operation has no alternate writer fallback.

Derived runtime files are recovery evidence under the configured ignored cache,
not a new authoritative backlog. Preserve them until the canonical receipt is
integrated. A retained result is bound to its reviewed digest before preparing
material. Canonical references contain the explicit message and result, subject
to the normal secret/privacy boundary. Do not dispatch secrets or data from an
unqualified account.

## Failed attempts without a result

A native failure can outlive the Gateway's transient terminal-error cache. An
integrator may use **Review resolution without a result** after inspecting the
retained attempt. This requires a preserved terminal error or the strictly
qualified expired-contract evidence described below, and an independent review bound to the original plan/run/physical session, current action revision
and approved HEAD. The review names its author, distinct reviewer, reason and
limits. Its decision is `resolve_without_result`, never success or completion.
A native terminal failure may carry `error: null`; this preserves an absent
diagnostic, without inventing an error message or inferring cancellation.
Cancellation attribution requires its own run-bound request/response evidence.
Evidence digests establish integrity, not RPC provenance; the basis is explicitly
`preserved_observation_independently_reviewed`.

The command verifies current configuration and physical session, no active run,
an empty live queue and all paginated pending-input records. Native `total`
counts history; only cancelled/interrupted historical records are admitted with
an explicit zero `queuedCount`. Unknown states, missing pages, duplicate records,
changes during observation or revoked operator authority refuse the operation.
The evidence and native state are checked again before the atomic local receipt.

Resolution retains the original intent, acceptance and reviewed error. It writes
only a `resolved_without_result` recovery record. Discovery distinguishes
`reconciled=true` from `has_result=false`. There is no incorporation button,
result file, action transition or automatic retry. External effects remain
undetermined by this record and must be reconciled separately where applicable.
The original effect still cannot be sent again. Another mission requires an
explicit new plan, an admissible action and all current dispatch gates.

## Limits and verification

Before the first result capture, the native session must still report this run
as its last completed run; otherwise reconciliation remains held. After capture,
the adapter reads the retained exact message even if the session advanced.
No arbitrary history scan, redispatch or account switch is used for recovery.

[Product tests](https://github.com/kimlage/wiki-viva-kit/blob/c46568234f8d16d81f1e38140246a31d4faff9c8/tests/test_openclaw_product.py) exercise actual HTTP,
session admission, native writers and Git with a synthetic Gateway. They cover
revocation, C3 preservation and server restart. [Adoption tests](https://github.com/kimlage/wiki-viva-kit/blob/c46568234f8d16d81f1e38140246a31d4faff9c8/tests/test_openclaw_adoption.py)
use actual local Git with a synthetic provider, including interrupted adoption
and no-effect replay. [Card tests](https://github.com/kimlage/wiki-viva-kit/blob/9c65f032572d4e5e2e2b3a6f3a4f53685481f9e3/apps/wiki-cockpit/src/components/ActionRuntime.test.tsx)
verify typed review and recovery controls. These fixtures do not prove a live
account, real model response, hosted wiki or autonomous operation. A consumer
must qualify those through its adopted product entry and approved sources.

## Explicit mission selection and native inference guard

New dispatches require an operator-selected `mission_id` from the consumer's
reviewed `openclaw.mission_options` mapping (`label`, `model`, `effort`). Effort
is `high` or `max`; the consumer supplies its approved OpenAI model names. Each
route also pins an independently observed `native_thread_id`. Existing results
remain inspectable after adding these fields, but an unconfigured dispatch is
refused. The browser cannot supply a model, executable or native thread.

The plan includes this selection. An immutable mission contract and exclusive
active lock precede the session-selection patch and send. `sessions.patch` uses
physical-session CAS; it is not itself an atomic model lock. `chat.send` carries
the effort, physical session and contract digest, with command interpretation
disabled. The version-bound guard checks the actual turn and each inference
body immediately before the installed native boundaries. A mismatch refuses
execution instead of substituting a different model or effort.

The optional [loader](../../../scripts/openclaw/mission-loader.mjs) applies the
[explicit overlay](../../../scripts/openclaw/mission-overlay.json) in memory to
OpenClaw and Codex plugin 2026.10.9. Installed package bytes are untouched;
matched modules must have the exact upstream hashes. Enable it explicitly in
the reviewed Gateway process arguments with Node's `--import`, setting
`WIKI_OPENCLAW_MISSION_DIR` to the existing derived OpenClaw directory. The
[guard](../../../scripts/openclaw/mission-guard.mjs) contains no credentials. An
unmodified Gateway rejects the new send field rather than running unguarded.
No automatic package update, installation, privilege grant or runtime activation
is performed by the kit. Verify the selected plugin actually loads the guarded
modules and perform a real native readback before claiming deployment.

Only the pinned existing thread and one native turn are admitted. A durable
claim blocks replay, live-switch retries and a restarted executor; recovery is
inspection, not resending. Readback checks native result model and guard records
before releasing the active lock. A reviewed native terminal failure may also
release that exact lock. Guard records contain IDs, model, effort and hashes,
never prompts, credentials or request bodies. Selection admission is not proof
of network completion or billed usage.

This deliberately narrow mode refuses auxiliary/child/guardian inference and
requests that omit or conflict with the mission's exact selection. It does not
disable native authorization, guardian, sandbox or approval checks: a required
unsupported route fails instead of receiving an exemption. Compact requests
are accepted only with the same exact thread, model and explicit effort. Broader
autonomy and other runtime versions remain outside this qualified contract.

The guarded gateway starts Node with `--import /absolute/path/mission-loader.mjs`.
Set `WIKI_OPENCLAW_GUARD_BOOTSTRAP=1`, `WIKI_OPENCLAW_CORE_ROOT` and
`WIKI_OPENCLAW_PLUGIN_ROOT` to the two real package roots, and
`WIKI_OPENCLAW_MISSION_DIR` to the real consumer derived OpenClaw directory.
These are local service settings, never credentials. The bootstrap validates
package identity, version and the complete JS/MJS/JSON tree (excluding nested
node_modules), then validates each hook again when loaded. All seven hooks must
execute before chat admission. A renamed or partial package is refused. Dependency
resolution and absence of startup side effects need a local smoke for each
qualified installation; this is not a generic compatibility claim.

The returned native turn ID is persisted before releasing native custody to
inference. Inference waits for that existing custody, then checks the exact ID;
no first-event binding is allowed. Terminal notification and inference receipts
must agree on the same ID before a result can be incorporated. A crash or missing
response remains uncertain and blocks replay. Creating and releasing the mission
lock share a filesystem mutex; reading an older result preserves any newer lock.

Native plugin captures are qualified through the native artifact's exact original
path, inverse mapping and module root, followed by full package and SDK-root
validation. The guard does not trust a capture-directory name. Each participating hook must load from its own qualified capture. A capability
binds the current native invocation to its plugin instance. The native client
can retain a route across distinct plugin instances: the turn and inference
owners need not be identical. The guard registers the exact inference function,
client object and asynchronous proxy handle, then admits a turn only against
that same client and route. Each function can belong to only one route; metadata
or matching provider strings cannot establish this association. Every
execution assertion rechecks native revocation, retirement and disposal. Shared
artifacts keep separate owner associations, so disposing a catalog instance
does not revoke a different active runtime instance. Native custody, resolver,
authorization and model-source release remain in force.

### Native mission transport and unaccepted recovery

The mission transport uses the version-bound native CLI facade with the existing
configured identity and authentication resolver. Command-suppressed `chat.send`
requires `operator.admin`; the generic CLI's least-privilege write scope is
insufficient. Only that mission call requests the required scope. Read/selection
calls retain native scope selection. No grants, credentials, exec attribution,
authentication or native permission checks are changed; a denied scope stays denied.
Requests travel over stdin. Safe structured error enums are retained with the
selection/send stage; arbitrary provider messages, details and stderr are omitted.

An intent without acceptance is not proof of non-execution. Recovery never
replays it or manufactures a terminal error. The existing explicit, independently
reviewed `agents.openclaw.resolve_failed` also accepts an `expired_unaccepted`
evidence record containing the exact run, contract digest and original expiry.
It requires an actually expired guarded contract, no acceptance/result/guard-turn
or inference artifacts, the same physical session and original leaf, and no
active run or pending input for that run. Inputs and complete queue observations
are checked again before the receipt. The expired contract cannot admit a later
turn; releasing its exact lock does not release another mission. Original intent,
contract and diagnostics remain intact. The receipt says resolved without result,
not successful execution, a reconstructed rejection, or absence of external effects.
Only a separately reviewed new mission can follow; recovery never dispatches it.

### Shared guard through the native SDK

The pinned loader exposes a frozen, ten-function mission facade through
`openclaw/plugin-sdk/process-runtime`. Captured plugin modules import that existing
native SDK entry point; the SDK and core hooks retain the same host guard and
native owner registry. Direct absolute imports from a captured plugin would be
captured again, producing an unconfigured second guard. Package and hook hashes,
native capture custody, instance identity and revocation checks remain mandatory.
The SDK and native shared-client route factory are required hooks; an SDK loaded before the overlay is refused.
The facade exposes no runtime configuration or artifact registration function.

The ordinary guard tests cover facade identity and fail-closed selection. With the
pinned OpenClaw package available, the optional offline integration additionally
uses the real native capture resolver and `PluginInstance`, a synthetic plugin
and isolated temporary configuration. It reproduces the absolute-import failure,
checks the shared bridge and native revocation, and refuses altered package bytes
and a preloaded unguarded SDK. It does not start a Gateway or call a model:

```sh
WIKI_TEST_OPENCLAW_CORE_ROOT=/absolute/path/to/pinned/openclaw \
WIKI_TEST_OPENCLAW_NODE=/absolute/path/to/compatible/node \
python3 -m pytest tests/test_openclaw_guard_runtime.py
```

This offline proof does not replace the consumer's real mission, terminal return
and reviewed incorporation into its Wiki.

Native route/catalog setup can construct the inference binding before the turn
module loads. Capturing that binding requires the caller's own guarded module,
qualified artifact and live native owner. It grants no execution admission.
Execution requires the turn hook in the turn owner's capture, and the inference
and shared-client hooks in the route owner's capture. All participating owners
must be live trusted runtime owners. A retained execution callback rechecks both
owners, the client, proxy and exact native thread-to-route association. The native
request callback repeats this check immediately before sending `turn/start`,
after any queue or custody wait. Failed route registration closes the newly
created proxy. Revocation cannot be undone by late module loading.

With `WIKI_TEST_OPENCLAW_PLUGIN_ROOT` also set to the pinned plugin package, the
optional native route test uses two actual `PluginInstance` captures, the actual
async proxy and inference factory, and the exact transformed route callback body.
Its client/account context and mission remain synthetic. It checks distinct
captures, wrong client, changed route, client closure and native owner revocation;
it performs admission checks without sending an inference request. This does not
prove the complete live Gateway workflow or a useful model result.


### Managed app-server identity

The pinned plugin only owns the inference route when its native resolver selects
a managed stdio app-server. An explicit `appServer.command` is an external command
even when its bytes came from the official npm package; it must not be relabeled
as managed. The qualified installation uses the plugin's own Codex 0.160.0
package. Remove custom command/environment overrides only as a reviewed consumer
configuration change, preserving the previous installation and native home.

The overlay pins the official launcher and platform binary by package version,
resolution and SHA256. Its startup hook checks the native `resolved-managed`
selection and stdio arguments before each candidate starts, and rechecks bytes.
The sole additional argument form admitted is the native auth bridge's exact
`cli_auth_credentials_store="ephemeral"` override; file storage and other overrides
remain refused.
A desktop fallback, external command, changed package or unsupported platform is
refused before startup. It neither fabricates native ownership nor opens a custom
inference proxy path. This additional qualification is currently Darwin ARM64;
another platform requires its own reviewed pin. The live session and mission
acceptance remain separate from installation and offline tests.

### First mission on an empty native home

A new OpenClaw session can exist before its Codex thread exists. Configure that
one-time route with `native_thread_binding: first_turn` instead of
`native_thread_id`. This is an explicit bootstrap mode, not a fallback for a
missing or incompatible existing thread. Preserve an older native home rather
than opening its newer databases with an older pinned client.

The planner and executor require an empty transcript, no prior run, no pending
input and the exact physical session. The native final admission transaction
also requires an exact empty active path; its usual allowance for an empty
ancestor cannot admit concurrent activity. Before lifecycle preparation, the
captured native owner must observe no saved binding. Only the canonical fresh
`thread/start` branch can register its returned ID, under the same client and
live owner. Resumes, rotations, replacements and auxiliary branches cannot
satisfy bootstrap admission.

The selected model and effort remain immutable in `mission.json`. Exclusive
admission, creation and turn records bind the observed thread ID to that contract
before `turn/start`; inference and terminal receipts must agree on that ID and
the returned turn. A restart after a claim cannot restart bootstrap. Reconcile
the preserved attempt, never resend it. After a successful result is collected,
pin its independently verified native thread ID in a reviewed consumer update
before another mission. The bootstrap route refuses subsequent activity.

An already collected bootstrap result remains readable after that exact pin.
The reader revalidates the native message and complete guard chain, and ignores
only the binding-mode-to-observed-ID change. A different physical session,
policy, runtime, thread or result is not accepted as the same route.

## Opt-in native restart continuation and recurring observation

The default remains inspect-only recovery. A consumer may opt in with
`recovery: {mode: read_only, max_continuations: 1}` under its OpenClaw config.
The mission records the approved Git revision, action bytes and configuration.
The version-qualified native recovery admission links its new native run to the
original mission, physical session and original bound turn. It sets the original
model and effort explicitly and narrows the native recovery tools. The fresh
native client, owner and inference route must qualify normally; disk receipts
cannot reconstruct those capabilities.

Only the configured read/ls/session_status tool surface and Docker read-only,
network-disabled workspace qualify. The app-server bootstrap exec setting may
remain ask; this does not admit the exec tool to the model. No child, auxiliary
inference, new account or external writer is granted. Changed Git/action/config,
expired original validity, completed original turn, another recovery UUID or a
second continuation refuse admission. A crash after claiming continuation but
before its turn starts consumes that allowance and requires reconciliation.
Neither the original message nor chat.send is replayed. Original and continuation
turn/terminal/inference records remain separate; the collector reports the actual
native recovery run while retaining the original canonical effect identity.

A consumer may declare a finite `recurring` rule mapping with profile, action_id,
mission_id, message, interval_minutes and watch_paths. Each wake invokes the fixed
administrative command `agents.openclaw.tick` with only rule_id. The existing live
session capabilities, plan confirmation and single-writer admission still apply.
The command does not install a scheduler or persist administrative credentials.
An authorized scheduler wakes the existing coordinator; it does not own tasks.
The action remains canonical and the coordinator prepares only its approved
technical context package, using `{approved_head}` in the configured message.

UTC slots derived by the backend give stable occurrence identity. A consumed slot
is not reset by retries, restart or a changed HEAD. Uncertain retained work is
inspected first; completed material waits for reviewed incorporation through the
normal proposal port. A receipt comment alone is not factual consolidation.
Subsequent unchanged watched Git content causes no mission/model dispatch. The
watch list selects tracked repository content, never external sources or ignored
caches. A proposal/config change invalidates a prepared plan; absence of a native
result does not imply permission to try another occurrence.

Qualification requires native Gateway interruption, one bounded continuation,
useful reviewed incorporation and served readback, plus repeated wake-up without
duplicate dispatch. Passing synthetic tests or installing a wake-up schedule does
not establish those operational outcomes. Updating core/plugin/client/overlay is
still a reviewed, separately installed candidate with the previous release and
state preserved for compatible rollback; do not enable blind native auto-update.

### Receipt and incorporated content are separate

`received_in_main` proves the normal receipt comment, not useful incorporation.
The derived `content_incorporated_in_main` flag additionally requires a real
committed action-body change from the canonical writer on approved main (published for the GitHub PR gate), associated with the
original effect's run_id (flat contribution metadata or run_ref). The proof uses
the actual before/after body bytes and validated Git transitions, not a formatted
material hash or a caller-provided flag. A separate later editorial consolidation
is checked as its own committed segment; the mixed-change refusal is preserved.
The recurring command returns `incorporation_required` until this proof exists.
Independent PR review still assesses usefulness and factual accuracy; byte and
writer provenance cannot determine whether arbitrary prose is true.


### Interrupted admitted turn without a preserved native terminal

A Gateway restart can leave an admitted original turn `interrupted` while
`agent.wait` reports `timeout`. Neither observation is a terminal error or a
successful result. The failure resolver accepts a separate `expired_interrupted`
evidence mode only after the immutable original contract expires, with no result,
terminal guard or recovery artifact, intact accepted/turn/bound/inference lineage,
and a fresh idle physical session whose current leaf belongs to that original run.
A native queue, another leaf, a partial continuation, an unexpired contract or a
changed mission lock refuses this route.
Exact messageId reads use a native physical-snapshot projection which can leave
activeLeafEntryId unset. The exact message must still match its physical session,
id and original run; complete live observations before and after bind current
leaf, status, last run and queue. An explicit foreign snapshot leaf is refused.

Independent review still binds the exact approved head, action, contract/evidence
and original run. Resolution rechecks native state and retained bytes under the
same cross-process mission mutex used by creation, immediately before recording
`resolved_without_result` and releasing only that mission's lock. It preserves
original evidence, records external effects as undetermined, creates no final
answer and never dispatches. Repeated reads of the resolution are separate from a
new mission. Recurrence keeps its consumed occurrence and requires a genuinely
changed watched condition before a future eligible occurrence.

### Reviewed expiry with a retained native recovery claim

An expired, admitted original can lack both a terminal result and an admitted
continuation. `expired_interrupted` reconciles that exact observation after
independent incident review; it does not assert model completion or external
success. The original occurrence stays consumed and its timestamps stay intact.

The version-qualified native startup adapter can then retire the matching native
claim without replay. This narrow path supports an approved, clean `main` equal
to its fetched remote ref. It reconstructs the original contract from its plan
and approved Git base, checks the immutable reviewed resolution and original
turn/inference lineage, and refuses any result or partial continuation. A
changed claim, session, cycle, revision, writer, pending input, admission or
delivery custody prevents retirement. It does not clear a queue or interrupt
another run to satisfy those conditions.

Settlement uses the native exclusive lifecycle mutation and atomic local
interruption notice/claim cleanup. The writer compares the complete native entry
at commit, including inside the native SQLite worker. Unknown captured worker
generations are refused rather than running without this check. The live guard rechecks the receipt, native owners and the pure
pending-input query. The ordinary history API is deliberately not used for this
precondition because it may reconcile orphaned queued inputs. A lost response
after commit cannot retire another claim: the native source fences and cleanup
commit together. The local notice explicitly records no result, unknown external
effects and retirement time; that time is not a fabricated model completion.
New missions still need separate normal admission and their own immutable
model, effort, context and expiry. No new RPC or scheduler is introduced.
