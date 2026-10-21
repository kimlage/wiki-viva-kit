# Native Hermes source session bridge

This optional integration embeds the existing Wiki source screen beside Kanban.
It binds a source to an explicitly selected native route/profile and **existing
stored context conversation**. It creates no bot, task queue, agent loop, provider
reader or credential store.

The public SDK supplies `profileRoutes`, `requestProfile`, `retainProfile`,
`onEvent` and `openSession`. The bridge lists stored conversations and optional
native account constraints, resumes the selected stored id, then submits one
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

The integration uses an existing conversation; it does not create sessions
implicitly. A busy/waiting context is preserved. A race at submission uses the
native queued input path. UNKNOWN records do not expire into permission to retry.
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
