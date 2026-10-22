# Inactive mandatory authority candidate

This directory is reviewable source, **not an installed Hermes extension**. It
does not start a worker, create a task, log in, load credentials, alter ACLs or
restart a process. The source bridge still uses the existing single Hermes UI.

`candidate-711.patch` targets Hermes
`71177446eec8d0e2ce107d69f67c4ee4492d81c4`. `source-pins.json` records the exact
source bytes required for generation, as explicit public `sha256` metadata. The builder refuses drift and writes only
an external patch. It has no apply/install mode. Its vendored authority module is
byte-identical to [runtime_authority.py](../../../../wiki_core/runtime_authority.py).

The existing [context bridge](../../../../wiki_core/host_authority.py) still
supplies the versioned [context packet](../../../../wiki_core/coordination.py).
The [native host](../../../../wiki_core/native_host.py) now provides a concrete
native task/run/claim resolver, a host-owned read-only registry interface and a
snapshot compiler feeding the existing projection. The
[local handoff](../../../../wiki_core/native_host_wire.py) connects those checks
to actual native producer/consumer entry bodies. Native task, worker session and
wiki action IDs remain separate explicit bindings, never title/profile guesses.
The plugin, iframe and wiki configuration expose no authority installation API.

## Native host candidate wiring

The existing server lifespan accepts a typed `NativeHostProvider` supplied only
by trusted host startup code. With no provider or invalid registry it holds
protected reads and leaves the native UI running. It never loads policy from a
worker file, environment, prompt, profile name or Managed Scope. No provider,
registry, grant or ACL has been configured on the installed host.

Only the native middleware's **already verified Session** success branches bind
controller identity: provider, organization, user ID and expiry. No token/cookie
field is read or copied by this bridge. Loopback bypass and service-token routes
cannot manufacture this attestation; those paths remain unqualified here.

The actual `_default_spawn` checks this identity and the operator snapshot
before profile/credential preparation, then again immediately before `Popen`.
The existing `_set_worker_pid` validates the database and current claim/run
before writing; conditional native updates refuse a reclaimed run. The native
one-shot environment-registration entry also requires the authenticated channel
before its legacy board write. Env values only corroborate established bindings.

One transient local Unix channel per existing native run lives **inside the
same controller process**. It is not a new HTTP service, scheduler or execution
database. Kernel peer PIDs and native PID/start fingerprint bind both sides;
unsupported platforms, changed parent wrappers and mismatched peers deny. The
constructor and turn entry install/admit the read-only backend before agent
factory/context/model work. Unapproved context files, memory and background
review are skipped; the read worker does not auto-approve startup shell hooks.

The real CLI `_prepare_agent_startup` admits the worker before plugin/MCP/hook
discovery, including the native fast-chat entry. CLI mutable-state setup reuses
that authenticated session. Without native account/transport enforcement, a
protected worker cannot start MCP discovery (inline, background or deferred),
hydrate owner secrets or connect a server. The restriction persists after the
channel hint is consumed. Native administrative startup and its existing
toolset filter remain available; a hint can restrict a process, never admit it.

The [stdlib-only startup restriction](../../../../wiki_core/native_startup_guard.py)
also runs during complete-module import. Native bootstrap hardens its path,
settles the canonical interrupted-update recovery, then admits the protected
process before launch preparation. The main module's own recovery fallback also
precedes the new dependency when bootstrap is missing. The main module and
`model_tools` repeat that barrier before their import-time effects. Missing or
forged channels stop before dotenv or discovery. The restriction is shared by
dotenv, native secret scopes, built-in discovery and plugins, and survives both
consumed hints and reload. Public admission does not qualify account access:
the protected high-level dotenv loader returns no loaded files; lower readers,
hydration and scope getters refuse materialization. Plugin discovery, deferred
startup and secret-source refresh do not scan, reset caches or hydrate secrets.
Native administrative loaders and filters outside the protected worker retain
their behavior. No account/transport exception or worker-controlled enable flag
exists in this cut.

The guard imports no new dependency ahead of native interrupted-update repair.
Recovery still requests a fresh launch after restoring a partial tree; it does
not waive authority. Without a repairable journal, missing/incomplete guard code
continues to fail closed. No recovery is run against the installed checkout.

The registry publisher remains solely in the controller process. The worker RPC
has no update/grant operation, does not receive the publisher, and never opens
the native database or policy source. Metadata-only native `get_task/get_run`
branches exclude bodies, titles, results, summaries and errors at SQL selection
time; the controller's connections are read-only and do not migrate schemas.
Each protected call rereads policy/native bindings and checks the approved Wiki
context revision. Lost delivery closes the channel without resend. Native
cancellation crosses it as a fixed control code with no exception payload.

The real commit path obtains an allowlisted native projection. Repeated unchanged
snapshots have the same projection ID. Native `done` alone does not prove a source
effect or ACK: without qualified evidence the projection requires reconciliation
and never authorizes retry. No canonical Wiki/board write or new task is made.
The public result function can query an already-ended run after its effect lease
expires, while the operator mandate and controller identity must remain current.
It validates the original session/task/run/claim/PID/start fingerprint and the
explicit projection audience. It never renews the claim or enables a live
effect/model call. Replaced runs, revocation and lost delivery remain holds.

## Entry coverage

The candidate also extends the existing `config.get` dispatcher with the
`connector_gateway_origin` key. The existing `gateway.capabilities` advertises
it only when the actually registered enforcing handler carries that contract.
The UI withholds this query on an older or unknown build, whose ordinary
`config.get` profile decorator could otherwise hydrate secrets before rejecting
an unknown key. Native result and parameter contracts include the extension.
The query additionally requires the new `metadata_only: true` wire parameter.
An old backend's native strict parameter validation rejects it before its
profile decorator, including a backend replaced between the capability and
configuration calls. The new handler refuses this parameter on every other
getter before entering a scope. This is a proposed native wire extension, not
a currently installed SDK capability or an account grant.

For this one key, the handler validates the exact canonical native launch
profile using directory metadata, before entering any runtime/secret scope.
Another profile, absent profile or failure returns explicit unknown metadata;
it never selects a default profile. It does not activate multiplexing, open a
session, load dotenv/config/credentials or make a network request. Legacy keys
keep their existing profile scope. The pure URL resolver is generated from the
pinned native function bodies and constants, with a snapshot of only its three
URL settings; the authenticated gateway module is never imported for this read.

The result contains only sanitized scheme, host and port, provenance
(`default`, `override`, `derived`), canonical profile and `resolution_scope:
process`. Invalid input is unknown without raw URLs or errors. Userinfo, path,
query and fragment never cross the result boundary. This observes process
settings before account hydration: it does not establish effective account
identity, account enforcement, the endpoint after future secret hydration, or
permission to query a source. Both account proof flags remain false.

The same single UI exposes this as an explicit diagnostic action on an exact
native route. It uses `host.requestProfile` with the existing capability and
configuration RPCs, without a source-binding HTTP read, account/session/tool
discovery, conversation or mission. Route inventory is revalidated between
calls and before disclosure; frame/source/route changes discard old results.
The public boundary projects only documented fields and keeps failures content
free. It never changes the source access state or enables a private read. This
extension remains inactive until the candidate is separately adopted.

The patch includes the native Python wire contracts and their TypeScript and
OpenRPC derivatives. The builder applies only the frozen generator delta to
the pinned public artifacts. The complete native renderer was run in a
disposable public fixture: it first reproduced the base artifacts exactly,
then reproduced the candidate derivatives and validated both native results
with the strict Pydantic contract checks. No installed generator, auth/cache
client or runtime was invoked.

| Boundary | Candidate behavior |
|---|---|
| Complete import, dotenv and plugin refresh | Shared restriction/admission before native launch preparation and main/model module effects; native dotenv, external-source, scope and discovery paths remain closed for protected public workers, including reload. |
| CLI startup before agent construction | Authenticates/admit context before discovery; protected workers hold MCP initialization and secret/transport entry points. Native configuration and filters are preserved outside the worker. |
| Turn admission | Requires principal/claim and approved packet before setup/compaction/model work. Optional hook failure cannot remove the required packet. |
| Context materialization | Authorizes action, procedures and the full one-hop closure before related bodies. Other actions are not read. Unknown required refs and revision drift deny. |
| `handle_function_call`, `_pre_dispatch_guards` | Mandatory check independent of skip-hook flags; the existing catalogue and approvals still apply. |
| Registry dispatch and callbacks | The final invocation wrapper checks every success, error and cancellation. Errors omit exception bodies, preserve uncertain effects, and never authorize retry. Missing callback context denies. |
| Native INLINE/context/memory tools | Checks actual arguments after request/execution middleware, plugin rewrites and coercion. The sequential and concurrent handlers both revalidate immediately before execution and return. |
| Native publication | Observer hooks, transforms, UI callbacks and persistence revalidate before each boundary. Each surface must be explicitly permitted in the operation; read permission alone does not grant publication. |
| Publication continuations | Completion/risk callbacks, sequential/concurrent stdout and quiet formatters recheck after the preceding callback. Guardrail observation requires `tool_observer` independently of `native_store`. Native durability preparation carries the concrete call ref and rechecks before each callback and the final flush. |
| Request/pre-hook errors | Request middleware, pre-call hooks and edit-approval failures revalidate before continuing; logs retain constant failure metadata without exception text or traceback. |
| Inner observation errors | The real `_append_guardrail_observation` receives the concrete task, checks between native callees and sanitizes its own handled error. Output metrics, guardrail marks and their native relay error catches also omit exception bodies/tracebacks and propagate mandatory denial/cancellation. Tests exercise these bodies and their real call chain with synthetic dependencies. |
| Agent loop and special tools | Batch preflight is additional validation, never the final barrier. Direct delegation stays closed; concrete server session/task must match the admitted principal. |
| Connector dispatch/client | Checks at dispatch; managed execute and raw execute requests are closed before header/credential/transport resolution. Existing native metadata/configuration paths keep their official checks. |
| MCP direct handlers, retry and RPC | Closed before lazy server acquisition and again at dispatch. No provider-specific reader. |
| Model middleware continuation | Checks the concrete native agent/task and effective provider/endpoint/model/request again after preflight, before sending. An inherited nonempty context does not authenticate another agent. |
| Bot relay entry | Checks concrete agent/task before deriving sender/home, as well as recipient/content/service disclosure. No relay is executed by this patch generator. |
| Worker surface | Exact operation permits only; shell, arbitrary code, administration, plugin install and unqualified delegation are refused. |

The authority is read-only and fail-closed without a host backend. Native grants
remain necessary and are only restricted. Each check reloads current principal,
claim/lease, policy, resource/account binding, context revisions and destinations.
Revocation between effect and return blocks disclosure. The context packet keeps
`access_verified`, `runtime_connected` and `execution_ready` false: preparing it
does not prove runtime execution or account verification.

`Operation.disclosure_surfaces` is an operator-owned allowlist, empty by default.
It names native result, observer, transform, UI, persistence, relay and model
boundaries independently. It does not grant account access, install a policy or
prove that any real audience/ACL is configured. The patched request, handler,
callback and persistence error paths omit raw exceptions, tracebacks and result
bodies. An unexpected durability exception records `unknown`, sets the existing
persistence-failed flag and stops publication; it does not guess a classified
cause from exception text or retry the operation. Native cancellation stays cancellation; an uncertain
effect remains for reconciliation on the existing task instead of another attempt.

Optional native error handlers rethrow mandatory authority denials. Unexpected
observer/formatter/continuation errors stop with the content-free
`authority_native_failure_unknown_no_retry` hold; they do not trigger another
operation. Keyboard, async and future cancellation keep their native control
flow with empty payloads. Already-handled optional UI failures retain the native
safe metadata behavior. A final completion callback that revokes authority cannot
report publication complete or release a private result to its caller.

The native observer still runs `after_call` and identical-call observation,
preserves legitimate guidance/stubs/halt decisions, and retains a constant debug
record for an optional observation failure under valid authority. A lost mandate
blocks its next observer or return. Sanitizing only the outer commit wrapper
cannot protect a lower callee that has already logged its own caught exception;
the selected metrics/relay catches are therefore part of the pinned candidate.

## Adoption dependencies, not delivered capabilities

| Owner / contract | Required before adoption |
|---|---|
| Hermes trusted native host | Adopt the inactive lifespan/middleware/spawn/registration/constructor/turn wiring; supply an approved `NativeHostProvider`, protected registry reader and Wiki context source outside worker control. Qualify native host/kernel integrity and the deployed process transport. Missing providers, lost context and unsupported paths deny. No production registry, permission or ACL is configured here. |
| Hermes Portal connector resolver/transport | Prove and apply an immutable effective account/connection revision, no inherited fallback, exact resource/action and disclosure destinations. The 711 client drops the proposed account pin on execute. A wire field alone cannot enable this candidate. Private calls remain blocked. |
| Native MCP/browser owner | Prove account, controller/environment, grant and binding enforcement through supported native mechanisms. No whoami implementation, browser profile copy or cookie migration. Unqualified paths remain blocked. |
| Native Codex runtime owner | Qualify its separate context, identity, capability, approvals and callback/return contract. Code workers/delegation remain unqualified; a refusal never selects another executor. |
| Native Kanban and wiki operator | Supply fresh `/workflow` columns and task/run/claim/intention/effect evidence to the pure [projection](../../../../wiki_core/native_projection.py). No scheduler, task database or second lifecycle is introduced. |

The public control and the following authenticated source phase remain required
for the full product acceptance. This inactive code proves synthetic refusal
behavior only. It does not claim the real public mission, authenticated read,
question/answer/resumption, storage ACL, native runtime adoption, or full DoD.

## Review and validation

Run the normal kit gates. Additionally, set `WIKI_HERMES_KERNEL_SOURCE` to a
read-only checkout of the pinned public source and run
`tests/test_hermes_kernel_candidate.py` and `tests/test_hermes_authority_boundaries.py`.
These tests extract actual patched entry
bodies without importing Hermes modules/configuration, check denial before
handler/credential work, and apply the patch only to a disposable source copy.
They distinguish synthetic account fixtures from any real authenticated read.
`tests/test_native_host_integration.py` additionally exercises actual native auth,
spawn, registration, constructor and registry-return bodies, a read-only synthetic
SQLite database and kernel peer IDs. Its process/factory/identity-provider and
destinations are explicitly synthetic. This is not a real Hermes mission, real
account authentication, an installed bootstrap or private-source acceptance.
`tests/test_native_cli_startup.py` exercises actual native startup and secret/
connection entry bodies with a nonempty fictitious MCP configuration, the real
toolset filter and fake thread/secret/server boundaries. Terminal projection
tests use the public result function, including expired effect leases, unchanged
idempotent readback, identity changes, revoked policy and continued effect holds.
`tests/test_native_complete_import.py` imports complete pinned modules in fresh
subprocesses, rather than extracting their functions. Native bootstrap, main,
model tools, registry, dotenv, secret scopes, plugins and MCP startup execute
from disposable copies. External configuration, parser/PM/plugin dependencies
and source backends are fictitious. The native loaders and refresh method are
not replaced. An isolated home contains harmless marker files; no account env is
inherited, and network/process launch is refused (apart from the synthetic
process-bound Unix channel). The positive administrative control really loads
the fixture files, applies/reapplies the enabled synthetic source and preserves
the native MCP filter; public and consumed-hint/reload cases do none of these.
`tests/test_native_recovery_import.py` additionally executes the complete native
bootstrap/recovery/ZIP-recovery/checkout-lock modules on temporary partial trees.
It restores a missing or incomplete guard through the real journal and verifies
the native relaunch request, including the main-module fallback without bootstrap.
Only PM dependencies, the OS birth-time command and final external exec are
fictitious. A fresh import preserves administrative startup and refuses an
unqualified worker before loaders. A missing guard without a repairable journal
remains an error, never an import bypass.
`tests/test_gateway_origin_metadata.py` runs sanitization on the complete
committed candidate module even without native source. With the pinned source,
it registers the full native `methods_config` through the real `method_ctx`,
uses the native profile-scoping entry, verifies the old-key control and refuses
all file-open/network/process boundaries during the positive metadata read.
It also checks exact native resolver bodies and actual capability advertisement.
Source bridge and UI fixtures cover route replacement, old builds, malformed
metadata and stale responses without an account, credential or live RPC.
The default portable suite also checks that the patch vendors the exact module.

The source-connection UI displays missing enforcement as a read hold; opening
official settings and recovering existing receipts remain available. Catalogue
metadata, expected-account labels, native traces and local receipts cannot lift
the hold. A historical verified receipt cannot stay green without a current,
available account catalogue and exact route/account/provider/alias match. Missing
or changed discovery becomes unverified/unknown, never inferred expiry or revocation.
No operator promotion or independent approval is implied by these tests.
