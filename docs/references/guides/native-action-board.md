# Native action board

The cockpit's `/board` route groups canonical `page_type: action` pages by their
existing action state. It does not create a task database. A card opens the page,
its source references and evidence alongside the editable next step, priority,
blocker or result. Context and search filters share the same snapshot.

Action state is distinct from executor activity. This first board does not
claim that an agent is running, refresh external sources, dispatch agents or
copy Hermes tasks. Existing executor ownership and STOP records remain in their
own operational system until an explicit adapter connects them by canonical
page ID. Terminal actions remain terminal and can be shown with the history
filter. Missing or invalid states are visible for review.

## Run locally

```sh
npm --prefix apps/wiki-cockpit ci
npm --prefix apps/wiki-cockpit run build
python3 scripts/wiki_web_server.py --root . \
  --frontend apps/wiki-cockpit/dist --port 8765
```

Open `http://127.0.0.1:8765/board`. The operator serves the built frontend and API
from one loopback origin. It serves only UI assets from the given dist directory;
repository files are read through the existing page API. If the real wiki cannot
be loaded, the board shows an error instead of substituting the demo.
`/demo/board` is an explicit read-only synthetic demo.

Writes use the existing action transition API, operator nonce, attempt key,
expected page hash, transition constraints, atomic persistence and receipt
chain. A stale write is rejected. The board rereads after success; it never
pretends an optimistic movement has been persisted. Saving edits the current
workspace, not approved `main`: the consumer's normal review/promotion policy
still applies.

## Hermes Desktop

The optional extension displays this same board in Hermes. It does not add a
second backlog, agent tool, hook, database or background polling job.

```sh
python3 scripts/wiki_web_server.py --root . \
  --frontend apps/wiki-cockpit/dist --port 8765 --frame-origin file:
python3 scripts/wiki_hermes_board.py --url http://127.0.0.1:8765/board
```

The installer writes `~/.hermes/desktop-plugins/wiki-viva-board/plugin.js` using
the Hermes Desktop SDK. Hermes loads the **Wiki Kanban** sidebar route. An
explicit alternate `--plugins-dir` supports another Hermes home. The URL must
be loopback HTTP with the `/board` path and no credentials or query. Installing
again is idempotent; a different existing plugin is preserved and must be
reviewed before replacement. Keep the local operator process running while
using the view. The plugin does not start a service or alter Hermes runtime.

`--frame-origin file:` is optional and only required for the Electron desktop
host. Without it the UI permits only same-origin embedding. This setting does
not grant cross-origin API access or bypass operator writes' nonce checks.
The browser dashboard is a separate Hermes extension target and is not installed
by this Desktop installer.

SDK: <https://hermes-agent.nousresearch.com/docs/developer-guide/desktop-plugin-sdk/>

## Upgrading

Sync kit-owned files with `wiki_sync_from_kit.py` (B0 dry run, C1 copy, C2 demo
generation). There is no domain migration or action import. Existing action
pages and receipt v1/v2 history remain readable. New edits produce receipt v3,
which includes priority in the audited support fields. Consumers that validate
receipt versions outside the kit must accept v3 before enabling writes. Build
the synced cockpit and run the consumer's normal gates before promotion.
