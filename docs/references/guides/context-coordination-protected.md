# Protected coordination: local host binding

The protected route prepares the existing `wiki.task-context/v1` packet using an explicitly selected context, approved policy revision, content revision and evidence. It does not dispatch an agent, write a result or merge. [Preflight](../../../wiki_core/context_integration.py) remains a read-only check that ends at independent review required. Profiles in the older coordination configuration do not grant access or select a protected context.

## Trusted local startup

Protected coordination is disabled by default. A local operator may configure its startup environment with an exact, comma-separated allowlist and, optionally, a trusted Git reference:

```sh
WIKI_COORDINATION_ALLOWED_CONTEXTS=example \
WIKI_COORDINATION_TRUSTED_REF=refs/remotes/origin/main \
python3 scripts/wiki_web_server.py
```

The trusted ref defaults to `refs/remotes/origin/main` when the allowlist is supplied. The manifest is the approved repository-root `context.yaml`; payloads and environment cannot choose another manifest. The values are validated and pinned on startup; changes require a controlled restart. The ref tip is resolved and the approved policy is revalidated on every request. The host must maintain that reference through an independent approval process; a Git ref alone does not attest review. Missing or invalid binding fails closed. Do not place this host binding in an untrusted proposed branch or expose the operator to untrusted clients.

Every valid local operator session on the same server receives the same configured allowlist. This is a host-level trust boundary, not a per-person or per-agent identity system. A local session authenticates the operator; it is not proof of external access, business permission or sandbox isolation. Strong confidentiality requires separately qualified host/filesystem/service boundaries. Browser-supplied adapter reports and external capabilities are not accepted as evidence by these routes.

## API contract

`GET /api/coordination/protected-capability` takes `X-Wiki-Admin-Session`. Without a valid session or a usable host binding it returns only `available: false` and `reason: not_available_or_not_authorized`; it does not reveal the binding. With both, it returns `schema_version: wiki.coordination-capability/v1`, `available: true`, the bound context IDs present in the approved policy, and the current `policy_revision` SHA. Polling does not keep a session alive.

`POST /api/coordination/protected/packet` requires the usual operator origin, nonce and attempt-key headers plus the active admin-session header. The body is an object with exactly `context_id`, `approved_revision`, `content_revision` and `task`. The two revisions are full Git SHAs. The approved revision must equal the current trusted tip; the content revision must be that tip or an ancestor. `task` contains `task_id`, `goal`, `output`, `integrator`, integer `max_bytes`, `evidence`, and optional `omissions`. Evidence requires `ref`, `reason`, `use`, `classification`, and may have `section` or `field`, plus `producer` and `expected_document_sha256`. If `producer` is omitted, the backend derives the owner from approved policy; either way it verifies owner and current bilateral connection before returning content. The optional expected digest is checked only after authorization and cannot grant access. Use/classification must match the actual approved connection; they are not inferred from a legacy profile.

The caller must select the task and evidence explicitly and must not insert protected page titles, body text or source metadata into generic task fields before authorizing that page. For UI handoff, use generic task text until a selected page has been authorized. A request may fail rather than broaden a selection or silently drop it. Success is `{ok: true, mode: "approved", packet: ...}`. The packet's `coverage` is explicit and incomplete; it is not proof of semantic reading or execution. A safe error returns `ok: false`, `error_code`, and a structured blocker with action, generic target, reason, owner, required action, a textual interface location, resume condition and pending/denied state. It does not identify a denied path or invent a deep link.

When the complete packet exceeds `max_bytes`, API and CLI return `coordination_budget_exceeded`: reduce the authorized selection or revise the limit and retry. The packet is never truncated, and the blocker exposes no selected path or size. Other unavailable or unauthorized inputs remain opaque.

`POST /api/coordination/protected/preflight` uses the same transport and session controls. Its exact body fields are `context_id`, `approved_revision`, `base`, `head`, `branch`, `packet` and `result`. The packet must have no browser-supplied capability evidence or required external capabilities. Success returns `{ok: true, mode: "approved", preflight: ...}` with state `independent_review_required`; it is not permission to merge. The packet/result, exact head, base, requirements and current policy are checked again. The protected POSTs are bounded read-only calculations: they do not store or replay packet bodies under attempt keys. Every retry rechecks session, current policy and binding.

The legacy `/api/coordination` and profile APIs remain available under their previous local trusted-caller behavior, marked `policy_mode: legacy_coordination_compatibility`, `policy_enforced: false`, `trust_boundary: caller_trust` and legacy coverage. They may build a broad snapshot; they are not protected owner-scoped reads. Choose the protected route explicitly; there is no fallback from an unavailable protected binding to the legacy route.

## Trusted CLI

The existing coordinator CLI also supports explicit approved mode for a trusted local caller:

```sh
python3 scripts/wiki_coordination.py --root REPO --context-id CONTEXT \
  --approved-revision APPROVED_SHA --revision CONTENT_SHA --packet-request REQUEST.json
```

`REQUEST.json` is the same `task` object used by the API. The CLI uses the local trusted `refs/remotes/origin/main`, requires a full content SHA in approved history, and does not use profile routes or a global snapshot. It does not provide an operating-system ACL; callers who can read the repository retain their host permissions. The legacy `--profile` mode remains separate and explicitly labelled as caller-trust compatibility.
