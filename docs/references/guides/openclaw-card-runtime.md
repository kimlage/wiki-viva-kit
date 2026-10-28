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
  routes:
    research:
      session_key: agent:research:example
      session_id: existing-physical-session-id
      label: Example coordinator
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
   intent and bars another mission until the result is reconciled. Corruption
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

## Limits and verification

Before the first result capture, the native session must still report this run
as its last completed run; otherwise reconciliation remains held. After capture,
the adapter reads the retained exact message even if the session advanced.
No arbitrary history scan, redispatch or account switch is used for recovery.

[Product tests](../../../tests/test_openclaw_product.py) exercise actual HTTP,
session admission, native writers and Git with a synthetic Gateway. They cover
revocation, C3 preservation and server restart. [Adoption tests](../../../tests/test_openclaw_adoption.py)
use actual local Git with a synthetic provider, including interrupted adoption
and no-effect replay. [Card tests](../../../apps/wiki-cockpit/src/components/ActionRuntime.test.tsx)
verify typed review and recovery controls. These fixtures do not prove a live
account, real model response, hosted wiki or autonomous operation. A consumer
must qualify those through its adopted product entry and approved sources.
