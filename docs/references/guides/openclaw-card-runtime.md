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
retained attempt. This requires a preserved terminal error and an independent
review bound to the original plan/run/physical session, current action revision
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
A desktop fallback, external command, changed package or unsupported platform is
refused before startup. It neither fabricates native ownership nor opens a custom
inference proxy path. This additional qualification is currently Darwin ARM64;
another platform requires its own reviewed pin. The live session and mission
acceptance remain separate from installation and offline tests.
