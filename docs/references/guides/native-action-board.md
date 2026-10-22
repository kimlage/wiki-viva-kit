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

## Standalone browser

Serve the built cockpit using the local operator:

```sh
python3 scripts/wiki_web_server.py --root . \
  --frontend apps/wiki-cockpit/dist --port 8765
```

Open `http://127.0.0.1:8765/board`. The operator nonce, revision checks and
canonical Markdown persistence apply unchanged. The cancelled Hermes extension
is no longer distributed; its removal does not remove the action board.
See the [withdrawal record](../releases/hermes-integration-withdrawal-2026-10-22.md).

## Reading completed work

The card distinguishes its recorded state from the current executor connection
and general automation. The latter two are **not verified in this interface**:
no live heartbeat is available. Neither a terminal action nor static coordinator
flags establish live execution. The complete original receipt remains expandable.

Related `artifact` pages that link back to the action appear with their canonical
title and short summary. They open in the existing confined page reader, with a
return-to-card button. This is a relation, not proof that the executor produced
or approved that artifact. Local paths and hashes in messages stay inert text;
there is no arbitrary file endpoint. A consumer may version a readable artifact
copy with provenance, assisted execution and retained failures stated explicitly.

Conversation display resolves known page IDs to human titles, while expandable
original records preserve literal questions, answers, identities and hashes.
Reply submission and revision checks continue to use the original protocol.

## Creating and editing a task page

In local operator mode, **New task** asks for title, text, context, responsible
and next step. Contexts come from the repository configuration. Creation uses
the registered action template and its configured output directory, through the
same safe creation writer as `scripts/wiki_new.py`. It validates the final
page and creates it without overwriting an existing destination. A repeated
operator attempt returns its original result. A title collision is shown to the
operator; it never silently produces a differently named task. If the response
is lost, refresh and inspect the board before submitting a different title.

Open a card to edit the page. **Move to column** selects the canonical action
state in the same save. Blocking requires a reason, completion requires result
evidence, and cancellation requires its reason. Completed and cancelled tasks
retain the existing read-only rule. Assignment records responsibility only;
it does not grant accounts, permissions or tools, select an executor profile,
or start a bot.

The operator uses the page's exact content SHA for optimistic concurrency.
A stale save is rejected without overwriting the file. The draft remains in
the form; copy it before refreshing and reconcile against the current page.
Body edits preserve the submitted text, including trailing blank lines. Exact
body hashes decide whether a write is needed; the newline-normalized Git audit
projection does not decide whether text was saved. Existing v5 receipts remain
readable alongside the optional exact-byte witness in new body edits.
The API accepts a small `page_edit` allowlist, never a frontmatter patch. Other
frontmatter values, prior history and dialogue are preserved structurally;
YAML comments and formatting can change during the existing serialization.
Demo and static readers do not offer writes.

## API and compatibility

- `GET /api/actions/create`: configured creation contexts and default context.
- `POST /api/actions/create`: title, context, next_action, body, owner_kind and
  owner_ref. It returns the created page identity and file SHA.
- `POST /api/actions/transition`: existing state/support/dialogue operation,
  optionally with `page_edit` containing title, body, and a responsible pair
  (`owner_kind`, `owner_ref`). Unassigned responsibility has an empty reference;
  the canonical file omits that optional reference.

Both writes use the existing loopback/origin, nonce, bounded JSON and attempt
key protections. Edits use the same action lock, CAS, atomic replacement and
append-only receipt chain. Existing writes and reviewed contributions keep
receipt v4; effective page edits emit v5 with hashes of the edited projection.
Audit accepts v1–v4 and verifies interleaved edits, dialogue and contributions
without treating an operator edit as an independently reviewed contribution.
The operator advertises `wiki_web_server.v9` and `action_page_authoring_v1`;
the browser handshake detects an old running process before a mutation.

## Upgrading

Use the existing kit sync; do not copy private pages into the public kit or
introduce another task store. From a clean consumer proposal branch, first run
B0 (`wiki_sync_from_kit.py --dry-run`) against the approved kit commit. Review
C1 managed code changes and C2 generated artifacts; run the consumer's explicit
C3 migration only if its own policy requires one. This increment needs no
rewriting of existing task pages and no automatic model or bot activation.

Apply the sync in that proposal, validate the consumer's own gates and review
policy, and merge it normally. The serving owner then builds the frontend,
updates the served checkout and restarts the existing operator. Read back its
v9 capability and verify a synthetic create/edit/move flow on the same page.
A public-kit merge does not establish personal-wiki adoption or served state.
