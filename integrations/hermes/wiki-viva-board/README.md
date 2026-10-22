# Native Hermes source session bridge

The current inactive candidate requires the [mandatory kernel authority](kernel/README.md)
before any new read. This passive plugin does not install a trusted host backend;
missing admission is displayed as a read hold. Existing receipt recovery and
official configuration remain available. The native flow described below is a
transport contract, not proof of authorization, account isolation or adoption.

This optional integration embeds the existing Wiki source screen beside Kanban.
It saves a reusable source connection reference to an explicitly confirmed native
route/profile and optional named account, independently of a conversation. Existing
source execution bindings keep their original stored owner unchanged. It creates no bot, task queue, agent loop, provider
reader or credential store.

The public SDK supplies `profileRoutes`, `requestProfile`, `retainProfile`,
`onEvent` and `openSession`. Opening the source discovers metadata only; it does not retain or resume a chat.
A deliberate read test claims an intention first. A connection-only source resolves
that profile’s canonical `Bot Chat` with the native exact-title lookup, pins its
acknowledged compression tip once in the intent ledger, and mounts it lazily.
An existing legacy execution uses its original stored id. The bridge submits one
read intention with `prompt.submit`. Tools, schemas, resources and account
semantics are discovered by that native conversation through
`tool_search` → `tool_describe` → `tool_call`. Its existing policies, hooks,
approvals and transport remain in force. No provider name or read-tool schema
is implemented here. Official connector/MCP and browser settings remain the
configuration and recovery surfaces.

## Tracking and uncertain outcomes

Before submission, the profile-scoped API exclusively claims an intention id
under `cache/wiki-native-intents`. This is a receipt ledger, not a scheduler.
Only canonical source bindings are accepted; source/config/profile/session
changes invalidate the operation. The API never executes tools, Git commands
or provider clients. Tracking metadata cannot certify account identity,
permissions or read access; those fields always remain unknown/false.

`prompt.submit` has no idempotency key. After its dispatch boundary, timeout
means UNKNOWN. Repeating an intention reconciles native events/history and
never submits another prompt. The bridge retains the native profile socket,
filters live events by connection/profile/session, and reads `session.events.since`
with epoch/sequence plus `session.history`. A bounded, owner-filtered live metadata journal preserves tool ids, reported failures and persisted-turn correlation without storing provider output. It notifies the source screen and reconciles terminal native events without resubmitting. Truncation or an epoch change requires
history recovery; only a complete native replay or the scoped live journal can anchor a terminal tool trace. History tool references alone cannot establish resource success. The accepted
`user_row_id`, exact source intention and native persisted-turn completion must
match before the tracking record names actual tool ids. Search/skill activity
and model text are not proof that a resource was read. The UI offers the native
conversation and approval surface with `openSession(..., {route,
awaitHydration:true, forceResume:true})`.

The integration reuses the canonical bot context or the exact legacy owner; it
never calls `session.create`. Missing, busy, waiting, approval and profile STOP
states hold submission. Native lazy mounting avoids cold-resume auto-continuation
of a different interrupted human turn. If work starts after the final preflight,
`queued:true` preserves the native queue instead of interrupting or steering; the UI
shows waiting for execution. The preflight is not an atomic idle fence. UNKNOWN records do not expire into permission to retry.
An operator can inspect the native conversation to resolve missing evidence.

## Transport and adoption

The iframe has typed source actions only: routes, inspect, official configuration,
read intention, receipt reconciliation and open native conversation. It cannot
supply arbitrary RPC names, tools, arguments, paths, observed identities or grants.
HTTP embedding checks allowed origin, source window, generation and channel.
Opaque Electron embedding uses a dedicated MessageChannel and one-use challenge,
attested through the existing local operator gate. Pairing is transport trust,
not account consent. Credentials never cross the frame boundary.

Run `python3 -B integrations/hermes/wiki-viva-board/build_plugin.py` to produce
`plugin.js`; React and `@hermes/plugin-sdk` remain external. The normal kit sync
copies these passive source files. Installation, enablement, server rollout and
real native acceptance remain explicit operator steps after review and CI.
`WIKI_SOURCE_ORIGIN` permits only HTTP loopback with no redirects or ambient proxy.
No gateway restart or package/provider upgrade is part of this source change.

The official settings selector also lists native toolsets discovered through
`host.toolsets.list` in the selected executor/profile. Selecting any discovered
name opens the existing SDK `ToolsetConfigPanel`; the bridge rechecks membership
before opening it. MCP/account settings continue through `ConnectorsTab`, and
approvals/recovery remain in the existing native conversation. The bridge never
enables a toolset or changes a provider configuration automatically.

## Connection declarations and daily controls

`access_policy.connection` contains route identifiers and optional native account
references, never credentials, observed identity or grants. Saving it uses the
existing source preview/confirmation and content comparison. One native connection
may be referenced by several sources. Native account auth can be profile-scoped
with global inheritance; this integration does not promise credential isolation.
The source’s validated auth method, scopes and restrictive note remain canonical
and travel unchanged as data in the read intention. A new connection cannot edit
that auth declaration or override native policy.

The daily view shows source, context, expected/selected account and evidenced access
state. It reuses a saved route, offers a human context choice when necessary, and
keeps session ids, toolset catalogues and recipe controls under disclosures. Recipe
counts describe catalogue configuration, not authenticated accounts or verified
access. A queued ACK or native tool trace still certifies none of those.
