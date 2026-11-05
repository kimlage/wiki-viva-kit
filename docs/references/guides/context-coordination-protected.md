# Protected coordination: local host binding

The protected packet route prepares the existing `wiki.task-context/v1` packet using an explicitly selected context, approved policy revision, content revision and evidence. It does not dispatch an agent, write a result or merge. The separate in-process source stages can retain a request, result and event under the same host binding, with the limits in [bounded ingestion](bounded-ingestion.md). [Preflight](../../../wiki_core/context_integration.py) remains a read-only check that ends at independent review required. Profiles in the older coordination configuration do not grant access or select a protected context.

## Trusted local startup

Protected coordination is disabled by default. A local operator may configure its startup environment with an exact, comma-separated allowlist and, optionally, a trusted Git reference:

```sh
WIKI_COORDINATION_ALLOWED_CONTEXTS=example \
WIKI_COORDINATION_TRUSTED_REF=refs/remotes/origin/main \
WIKI_COORDINATION_CONTEXT_MODE=folder \
python3 scripts/wiki_web_server.py
```

The trusted ref defaults to `refs/remotes/origin/main` when the allowlist is supplied. A configured host defaults to folder mode, binding the approved `wiki.config.yaml` access configuration and exact physical context paths; `.` denotes the root. `WIKI_COORDINATION_CONTEXT_MODE=folder` selects the same mode explicitly. An explicitly selected `v1` binding retains the `context.yaml` reader for historical verification but refuses new packets. The default does not migrate legacy context IDs, grant access or establish historical-receipt mappings; those require explicit consumer migration. A payload cannot select or change the policy file, mode, allowlist or trusted ref. The values are validated and pinned on startup; changes require a controlled restart. The ref tip is resolved and the approved policy is revalidated on every request. The host must maintain that reference through an independent approval process; a Git ref alone does not attest review. Missing or invalid binding fails closed. Do not place this host binding in an untrusted proposed branch or expose the operator to untrusted clients.

Every valid local operator session on the same server receives the same configured allowlist. This is a host-level trust boundary, not a per-person or per-agent identity system. A local session authenticates the operator; it is not proof of external access, business permission or sandbox isolation. Strong confidentiality requires separately qualified host/filesystem/service boundaries. Browser-supplied adapter reports and external capabilities are not accepted as evidence by these routes.

## API contract

`GET /api/coordination/protected-capability` takes `X-Wiki-Admin-Session`. Without a valid session or a usable host binding it returns only `available: false` and `reason: not_available_or_not_authorized`; it does not reveal the binding. With both, it returns `schema_version: wiki.coordination-capability/v1`, `available: true`, the bound context IDs present in the approved policy, and the current `policy_revision` SHA. Polling does not keep a session alive.

`POST /api/coordination/protected/packet` requires the usual operator origin, nonce and attempt-key headers plus the active admin-session header. New packets require a folder binding; a v1 binding returns `coordination_v1_retired`. The body has `context_id`, `approved_revision`, `content_revision`, `task` and `entry_folder`, with optional `entry_index`. The two revisions are full Git SHAs. The approved revision must equal the current trusted tip; the content revision must be that tip or an ancestor. `task` contains `task_id`, `goal`, `output`, `integrator`, integer `max_bytes`, `evidence`, and optional `omissions` and `queries`. Owner-only `queries` follow the
[anchored collection contract](context-dynamic-selection.md); they do not infer
cross-context grants and obey separate enumeration, match and read-byte limits. Evidence requires `ref`, `reason`, `use`, `classification`, and may have `section` or `field`, plus `producer` and `expected_document_sha256`. If `producer` is omitted, the backend derives the owner from approved policy; either way it verifies owner and current bilateral connection before returning content. The optional expected digest is checked only after authorization and cannot grant access. Use/classification must match the actual approved connection; they are not inferred from a legacy profile.

The caller must select the task and evidence explicitly and must not insert protected page titles, body text or source metadata into generic task fields before authorizing that page. For UI handoff, use generic task text until a selected page has been authorized. A request may fail rather than broaden a selection or silently drop it. Success is `{ok: true, mode: "approved", packet: ...}`. The packet's `coverage` is explicit and incomplete; it is not proof of semantic reading or execution. A safe error returns `ok: false`, `error_code`, and a structured blocker with action, generic target, reason, owner, required action, a textual interface location, resume condition and pending/denied state. It does not identify a denied path or invent a deep link.

With a folder-mode host binding, the packet body also requires `entry_folder`
and may select `entry_index`. The host allowlist still matches the exact
canonical context ID; the packet builder verifies the physical selection and
its current policy before reading the context. Owner-only folder queries use
the [anchored query contract](context-dynamic-selection.md); queries with
additional readers require requalification and are currently refused. A folder
path does not grant access. The separate in-process `protected_source_stage`
applies its own bound authorization and revalidation; it is not exposed by
these HTTP packet/preflight endpoints. Existing v1 receipts are not converted
into folder authority.

When the complete packet exceeds `max_bytes`, API and CLI return `coordination_budget_exceeded`: reduce the authorized selection or revise the limit and retry. The packet is never truncated, and the blocker exposes no selected path or size. Other unavailable or unauthorized inputs remain opaque.

`POST /api/coordination/protected/preflight` uses the same transport and session controls. Its body fields are `context_id`, `approved_revision`, `base`, `head`, `branch`, `packet` and `result`, plus optional `additional_readers` that must belong to the fixed host allowlist and match the packet's retained selection. The packet must have no browser-supplied capability evidence or required external capabilities. Success returns `{ok: true, mode: "approved", preflight: ...}` with state `independent_review_required`; it is not permission to merge. The packet/result, exact head, base, requirements and current policy are checked again. The protected POSTs are bounded read-only calculations: they do not store or replay packet bodies under attempt keys. Every retry rechecks session, current policy and binding.

The operator index `/api/coordination` remains a broad caller-trust projection, marked `policy_enforced: false` and `trust_boundary: caller_trust`. Its profiles, fronts and actions are navigation and historical attribution. It is not an owner-scoped protected read. GET `/api/coordination/profiles/<id>` now returns a constant `coordination_context_required` migration response without snapshot, catalogue, page bodies or profile existence disclosure. There is no fallback from an unavailable protected binding to a legacy packet.


## Trusted CLI

The existing coordinator CLI selects folder authority for a trusted local caller:

```sh
python3 scripts/wiki_coordination.py --root REPO --context-id CONTEXT_FOLDER \
  --approved-revision APPROVED_SHA --revision CONTENT_SHA --packet-request REQUEST.json \
  --folder ENTRY_FOLDER --index INDEX_PATH
```

`REQUEST.json` is the same `task` object used by the API. The CLI uses the local trusted `refs/remotes/origin/main`, requires a full content SHA in approved history, and does not use profile routes or a global snapshot. If omitted, the folder is the current nested directory when inside the selected repository, otherwise the selected context. The operator chooses the local CLI arguments, so they do not create a security boundary against that operator or an operating-system ACL. Reading with `--profile` returns the same constant migration response without task bodies. A separately configured host binding remains necessary for protected host calls.

For evidence from another owner, append `--trusted-context PRODUCER_CONTEXT`
to the packet command; repeat it for each explicitly selected producer. The
approved policy must also permit the selected paths and the exact bilateral
connections. With no configured binding, this CLI builds its selection from
the trusted local operator's arguments; when a host binding is configured,
its fixed allowlist applies and the flag cannot enlarge it. Neither the flag,
a link nor the packet itself is an access grant.

For source preparation, recording and consolidation by that trusted local
operator, `--source-stage prepare|record|consolidate|compare|inspect` reads stage JSON from
stdin. It uses the same context and approval flags and can select an explicitly
authorized ancestor with `--integrator-context`; the [source guide](bounded-ingestion.md)
documents its scope and limitations. For a selected producer in another owner,
the local operator may also repeat `--trusted-context PRODUCER_CONTEXT`;
the fixed host allowlist, where configured, still governs the selection. Exact independent Git evidence requires
host-pinned grants and separate authorization for a derived event; see
[protected independent Git](protected-independent-git.md). These operations do
not dispatch a model, perform independent review or incorporate an event.

## Upgrading profile consumers

Keep existing profile IDs, `action_ids`, `front_refs`, action page IDs and dialogue history. Do not infer a context or grant from a profile name, alias, account requirement or union of its actions. For each task, select the actual canonical context and an approved evidence selection, then use the CLI above or the protected POST. In folder mode, instructions and the context index follow the physical entry; contextual evidence uses explicit evidence/queries. Cross-context evidence requires matching current import/export rules, including purpose, classification, selector and expiry. Do not copy `common_context` or `context_pages` wholesale into mandatory rules; those legacy fields no longer supply task bodies. Consumer migration must resolve ambiguous ownership explicitly.

The trusted local dialogue writer still uses profile attribution and the existing transition/CAS/idempotency boundary. It now requires the exact repository-relative action path inside the configured actions directory, in addition to the canonical action ID and expected document SHA:

```sh
python3 scripts/wiki_coordination.py --root REPO --profile PROFILE \
  --action-id ACTION_ID --action-path memories/actions/ACTION.md \
  --event-file EVENT.json --expected-sha256 DOCUMENT_SHA256
```

Use the consumer's configured actions directory instead of the example path. The path must be a regular Markdown file without traversal or symlinks, and its page ID and coordinator assignment must match. The writer reads only that action plus configuration and the routing policy; it does not prepare a task packet. `--as-operator` retains its existing actor semantics. These are trusted local writes, not context-policy enforcement or execution admission.
