# Hermes source configuration bridge

This optional integration adds **Sources and access** beside the existing Wiki
Kanban. It embeds the same `/w?dock=source` wiki screen and opens the exported
Hermes `ConnectorsTab` with an explicit `ProfileScope`. There is no second source
registry, credential store, task queue or bot.

Every safe source recipe, including one without access metadata, receives an
unverified canonical binding. The operator discovers native routes, selects an
environment/profile, inspects available providers/accounts, opens official
settings, and reviews/confirms the binding through the existing preview/CAS flow.
Catalogue support, configuration and tools/list are not account or read evidence.

| Method | Configuration | Implemented source read |
| --- | --- | --- |
| `local_git` | Explicit eligible wiki repository + profile | Native Git status and stable HEAD; `git.metadata.read` only |
| `managed_connector` | Official connectors + explicit named account | Gmail account profile, exact alias/id, observed email |
| `mcp` | Official Hermes MCP settings | No read adapter yet; tools/list is not a resource read |
| `browser_controller` | Official browser toolset settings in the chosen profile | Requires a real bound native controller contract |

Gmail reads only `GMAIL_GET_PROFILE`, after current account, enabled connector,
read facet and exact schema guards. It never searches tools, reads mail, changes
policy, calls connections/reconnect, or selects a default/other account. The
gateway resolves the explicit alias; account id is rechecked before/after. The
observed email must match the expected source email. A successful profile read
proves `gmail.profile.read`, not all mailbox/OAuth scopes or business authority.
The native gateway may report `CONNECTION_REQUIRED` with an authorization link;
the integration discards the link and records the need for official setup. It
never follows that link or claims a completed OAuth grant.

Local Git reads prove no Google/GitHub identity, remote access, full-text access
or write permission. Identity is not applicable, without a fictional email. A
legacy locator pointing to its own source page stays unchanged: the operator
explicitly chooses `wiki_repository` and sees its actual target. Remote locators,
other repositories, arbitrary files/subdirectories and cross-root paths fail.

The existing deterministic access test remains available without a native
binding. Once native execution is saved, Update directs the operator to native
Configure/read controls. The legacy endpoint refuses that binding before calling
its adapter, so it cannot silently test another executor.

## Packaging and adoption

These files are a proposal, not an automatic installer:

- Run `python3 -B integrations/hermes/wiki-viva-board/build_plugin.py` to generate
  `plugin.js` from `plugin.entry.js` and `source-bridge.mjs`.
- After review, the operator may replace the existing desktop wrapper with
  `plugin.js`. One plugin registers both `/wiki-board` and `/wiki-sources`.
- Adopt `dashboard/` under the selected Hermes profile's normal user-plugin
  directory using its existing discovery/trust/enable gates. The API namespace
  is `/api/plugins/wiki-viva-board/*`; its empty UI entry avoids duplicate tabs.
- The existing native API hot-mount fallback and wrapper runtime loader can
  adopt qualified files without a gateway restart when supported by that host.
- `WIKI_SOURCE_ORIGIN` defaults to `http://127.0.0.1:8765` and accepts only an HTTP
  loopback origin. Redirects and ambient HTTP proxies are refused.
- Native profile credentials stay in Hermes. Private source metadata stays in
  the private consumer. Installing code does not grant organizational access.

Browser recovery opens the exported `ToolsetConfigPanel` with `toolset: browser`
and an explicit profile, without declaring an active browser session/controller.
The desktop wrapper imports only public SDK exports. The API adapter calls the
existing native profile, Git and managed-connector clients, preserving scoped
execution and the gateway's tool policy. No internal frontend imports, parallel
provider connections or copied auth headers/tokens enter the iframe.

## Transport and recovery

The iframe can request only `routes`, `inspect`, `configure`, `read_test` and
`read_receipts`. It cannot supply RPC names, paths, URLs, argv, observed identities
or granted permissions. Every operation rereads canonical source/config hashes.
SDK calls and native HTTP explicitly select connection/profile; no ambient
request fallback exists. Source/config/profile changes invalidate old evidence.

HTTP hosts use a same-origin configured allowlist plus source-window/channel/
request/generation checks. Explicit `file:` Electron embedding uses a dedicated
MessageChannel and short-lived challenge. Raw `origin: null` is never trusted.
Only the challenge/port crosses the exact parent bootstrap with `targetOrigin:
*`, necessary for an opaque origin. Before source requests, the wiki checks its
own server for native-backend pairing through the existing local-operator
host/origin/nonce/attempt gates. The nonce stays only in backend memory. Pairing
is one use, expires after 45 seconds and has bounded storage. It establishes
transport at the existing local-operator trust boundary, not account consent or
protection against an attacker already executing local operator code.

Reads exclusively claim a request id before dispatch and persist receipts under
the selected Hermes home's `cache/wiki-source-access`. Repeating that request
reconciles its receipt, never reruns an unknown result. Interrupted reads remain
pending. Reopening the source requires receipt reload before another read.
An unresolved request id is retained in source/config/route-bound session storage
across iframe reload, without credentials. Empty receipt lists do not clear it;
only the exact terminal receipt does.
Expired receipts remain history; they do not promote the source account badge.
Receipts retain no raw provider content, changed filenames, login URLs or tokens.

## Validation and operational acceptance

Run normal kit PR gates. CI also executes `npm --prefix apps/wiki-cockpit run
test:hermes`. Synthetic tests cover first setup, actual exported ConnectorsTab
props, source/profile/account/schema/policy mismatch, scope, deduplication,
pending recovery, expiration, stale close and opaque-port/origin pairing.

Operational acceptance still requires the installed host: open Sources and
access, choose its actual route, confirm an eligible source binding, reload
receipts, perform the read, reload the iframe and recover that receipt. Verify
the actual PID and exact source/config/profile tuple. Git requires stable HEAD;
Gmail requires the selected account's observed email. Synthetic tests, catalogue
listing or successful preview are not this operational acceptance.
