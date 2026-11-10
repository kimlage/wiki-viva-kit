# Protected coordination: local host binding

The protected packet route prepares a versioned task packet using an explicitly selected context, approved policy revision, content revision and evidence. It does not dispatch an agent, write a result or merge. The separate in-process source stages can retain a request, result and event under the same host binding, with the limits in [bounded ingestion](bounded-ingestion.md). [Preflight](../../../wiki_core/context_integration.py) remains a read-only check that ends at independent review required. Profiles in the older coordination configuration do not grant access or select a protected context.

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

### One bounded Git evidence selection with owned inputs

For a task that actually consumed a bounded part of one large Git document and
also needs other evidence from the same owner, the protected packet endpoint
accepts `task.range_mode: "owned-evidence/v1"`. Include exactly one evidence
item with `range: {"kind": "utf8-line-bytes/v1", "start": 0, "end": 42}`
and its required `expected_document_sha256`, plus the other explicit evidence
items. All explicit items must belong to the acting owner. The ordinary
authorization, historical policy and deny rules still apply. The range uses
inclusive start and exclusive end at UTF-8 line boundaries and is limited to
65,536 bytes; the caller independently selects the bytes it actually read
from the approved Git revision. Instructions and context indexes remain full
inputs. Queries, additional readers, cross-owner evidence, composite preflight
and range-based information requirements are not supported in this mode.

The endpoint emits `wiki.task-context/v3`; the matching
`wiki.task-result/v3` must report every delivered input, including the exact
range. The preflight reconstructs the packet and checks the complete document
digest against the current approved base, as well as the selected bytes. If
the proposal changes the ranged document, it may only append to its approved
bytes; other changed paths must still satisfy the ordinary same-owner write,
policy and review gates. A changed base document requires a fresh selection.
The 1,000,000-byte packet limit and HTTP request limit remain in force; the
packet is not silently truncated. The reader loads the bounded whole Git blob
internally even though the packet delivers only the selected range. These
checks do not prove comprehension, external authorization, execution or merge.
The separate local `wiki.task-context/v2` owned-log append contract remains
unchanged; see [bounded reads](context-reader.md).

`POST /api/coordination/protected/preflight` uses the same transport and session controls. Its body fields are `context_id`, `approved_revision`, `base`, `head`, `branch`, `packet` and `result`, plus optional `additional_readers` that must belong to the fixed host allowlist and match the packet's retained selection. The packet must have no browser-supplied capability evidence or required external capabilities. Success returns `{ok: true, mode: "approved", preflight: ...}` with state `independent_review_required`; it is not permission to merge. The packet/result, exact head, base, requirements and current policy are checked again. The protected POSTs are bounded read-only calculations: they do not store or replay packet bodies under attempt keys. Every retry rechecks session, current policy and binding.

The operator index `/api/coordination` remains a broad caller-trust projection, marked `policy_enforced: false` and `trust_boundary: caller_trust`. Its profiles, fronts and actions are navigation and historical attribution. It is not an owner-scoped protected read. GET `/api/coordination/profiles/<id>` now returns a constant `coordination_context_required` migration response without snapshot, catalogue, page bodies or profile existence disclosure. There is no fallback from an unavailable protected binding to a legacy packet.

## Context-bound secrets-only check

An independently configured folder-mode binding can run a qualified
secrets-only selection under one context without claiming a global audit:

```sh
python3 scripts/wiki_audit.py --only secrets --context-guard CONTEXT \
  --context-policy-revision APPROVED_SHA --context-selection-sha256 SELECTION_SHA256
```

The host must independently authorize the bootstrap before invocation: the
Python runtime, executable code and imported dependencies; the approved Git
policy, instructions and index; Git metadata and configuration; ignore files
and external exclude rules; and the path inventory. For example, `git ls-files
--others --exclude-standard` may read ignore rules while producing that
inventory. This route does not itself qualify or enforce those bootstrap
reads. The host must also maintain the trusted ref and configure the fixed
allowlist described above; the binding itself does not create a grant. Do not
invoke this route if any bootstrap read conflicts with an applicable deny or
its authority is unknown. The command rejects a missing or stale binding. It
uses the policy in approved Git, not the candidate working configuration. Before
invoking Git's working-tree inventory, it requires exactly one context, the
root context `.`, with root-wide read permission and no contextual read denies.
The host must additionally approve the exact finite selection independently,
bound to the intended repository and policy revision. The command requires
the externally approved selection digest and compares it before opening any
selected target body. A digest binds the list; it does not authenticate an
approval or grant access. It then requires the entire selected set to be owned
and readable by that context. This deliberately refuses even a deny outside
the text selection; it does not grant or bypass denied reads.
It refuses a denied, unqualified or other-owner selection before opening any
selected target body; it does not silently omit that selection. Instruction
and index bodies used for context qualification are bootstrap inputs whose
own policy is checked before reading. The status is nonzero on incomplete
coverage even if `--check` is omitted.

The candidate list uses tracked and untracked non-ignored Git inventory
entries with the legacy secrets check's supported text suffixes, excluding
`tests/` and `wiki_core/detectors/`. Its Git environment is sanitized: global
Git configuration and ambient Git environment variables are not inherited, and
Git fsmonitor and untracked cache are disabled. The resulting list can differ
from the legacy audit's list, such as when a global `core.excludesFile` hides
an untracked file from the legacy inventory. Do not treat approval of the
legacy selection as approval of this list. Binary files and files ignored under
the sanitized Git inventory are not scanned. This mode does not run the other
global checks, and cannot be combined with
`--public-export`, other checks, queries, additional readers or cross-owner
access. The result identifies a secrets-only check, not a full audit or proof
that other checks passed. A global audit remains an independently authorized
caller-trust operation and must not run where its body reads cross a deny;
`--query-context` restricts query recomputation only.

For an independently authorized metadata inspection, form the candidate list
from the sanitized inventory, retain entries whose lowercase suffix is in
`TEXT_SCAN_SUFFIXES`, remove paths beginning with `tests/` or
`wiki_core/detectors/`, and sort the distinct repository-relative path strings
in Python's standard string order. Construct this object, substituting the
actual context, current approved policy revision, trusted ref and path list:

```json
{"schema_version":"wiki.audit-secrets-selection/v1","context_id":".","policy_revision":"APPROVED_SHA","trusted_ref":"refs/remotes/origin/main","check":"secrets","paths":["example.md"]}
```

Encode exactly `json.dumps(selection, sort_keys=True, ensure_ascii=True,
separators=(',', ':')).encode('utf-8')`; `SELECTION_SHA256` is the lowercase
SHA-256 of those bytes. The approver must review the exact list and bind it to
the intended repository identity, executable code, policy, invocation options and bootstrap
authority externally; those are not established by the digest. A missing,
malformed or mismatched digest stops the check before target body reads. The
result reports the digest and selected path count, not global audit coverage.

Before checking whether an eligible inventoried path currently exists, the
guard conservatively requires its authorization. A missing, inaccessible or
non-regular eligible path makes coverage unavailable, even where the legacy
check would skip a missing file.

The check detects policy-ref and inventory drift and rechecks path boundaries
and file metadata, but it is not an OS sandbox or an atomic filesystem
snapshot. The host must independently prevent concurrent file replacement and
provide filesystem and process isolation appropriate to its threat model.

## Legacy lifecycle history selection

The legacy action-state and source-lifecycle checks enumerate historical Git
tree names first and restrict their historical content search to Markdown
paths under the configured memory root. This prevents their historical grep
from searching unrelated JSON or Markdown outside that root. The candidate
selection still includes every relevant Markdown path under the memory root,
including paths outside action or source subfolders, so lifecycle identity,
renames and malformed action candidates remain checkable.

This narrowing does not qualify that selection against context policy: a deny
inside the memory root still prevents an independently restricted actor from
running the legacy checks. The memory root comes from the working configuration,
which may differ from the approved revision; neither it nor a candidate policy
is an authority for the scan. The host must independently qualify configuration
and every actual read, including changed working-tree files, Git attributes and
action-adoption receipt inputs. If the complete selection cannot be qualified,
the dependent check remains unavailable. Neither an `--only` selector nor
filtering a Git result afterwards is a grant or a successful global audit.

The legacy base-discovery helper can still return no base when its candidate
refs are unavailable; these changes do not turn that outcome into a verified
historical baseline. Missing or unverified baseline authority must be handled
by the caller's independent gate. Once a base has been selected, failure or
movement while enumerating and searching it makes coverage unavailable.


## Proposal-only Git secrets check

An independently admitted host can check the changed, same-owner Git text
blobs of a specific proposal without reading unchanged denied files:

```sh
python3 scripts/wiki_audit_proposal.py --context CONTEXT \
  --approved-revision BASE_SHA --base BASE_SHA --head HEAD_SHA \
  --branch wiki/BRANCH --selection-sha256 APPROVED_SELECTION_SHA256
```

The host must independently authorize the bootstrap before invocation: code,
imports, policy and context qualification inputs, Git executable, configuration
and complete base/head tree **metadata**, plus the repository identity and
trusted ref. The host must establish that none of those bootstrap reads
conflicts with an applicable deny; this command does not authenticate that
external admission or provide an OS sandbox. A missing binding, stale trusted
ref, changed branch, different base or invalid selection fails closed.

Only the approved base policy authorizes reads. The candidate policy is never
authority; if `wiki.config.yaml` is a permitted changed input it may be scanned
as content, without approving its change. The command compares Git tree path,
mode, type and blob IDs to identify every added, modified and deleted path;
renames are a deletion and an addition. It qualifies the complete diff against
the acting owner's current read rules before opening any changed target blob.
Any denied, other-owner, unsafe, unsupported or unclassifiable changed path
stops the entire check. It does not omit paths under `tests/` or elsewhere.

For independent metadata review, form an ordered `changes` list with objects
`{"status":"A|M|D","path":"repository-relative/path"}` sorted by path,
from the exact base and head tree metadata. The host must approve the complete
selection and bind it to the independently identified repository, bootstrap and
policy. Construct the following object with actual values:

```json
{"schema_version":"wiki.proposal-secrets-selection/v1","context_id":".","policy_revision":"BASE_SHA","trusted_ref":"refs/remotes/origin/main","base":"BASE_SHA","head":"HEAD_SHA","branch":"wiki/BRANCH","changes":[{"status":"M","path":"example.py"}]}
```

The required SHA-256 is computed over
`json.dumps(selection, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode('utf-8')`.
The digest binds that selection; it does not authenticate approval or grant
access. An empty diff is refused. For every selected A/M blob, the command also
refuses an exact Git blob-ID match with any path that the acting context could
not read under the approved base policy in either tree. This conservative
check may reject legitimate identical bytes; it does not detect derivatives or
establish information-flow confidentiality. Secret detectors are heuristic
and do not prove the absence of every possible secret.
Because the alias check classifies complete tree metadata, any path that cannot
be represented as valid UTF-8 and a safe repository-relative path makes the
check unavailable, even if that path is unchanged.

The subcheck scans each added or modified supported UTF-8 text blob at HEAD,
including tests and configuration. It refuses symlinks, gitlinks, unsupported
suffixes, NUL bytes, invalid UTF-8, LFS pointers, blobs over 2 MB, more than 512
changes or more than 8 MB of selected content. Deleted paths are authorized and
reported as deletions; their prior bodies are not claimed as scanned. Approved
policy and context instruction/index bodies are read for bootstrap even when
they are unchanged or deleted by the proposal, and are not proposal scans.
Suffix and UTF-8 checks do not prove that arbitrary bytes are semantically text.
The output identifies `proposal_changed_git_blobs` and counts, with
`global_audit`, `preflight`, `normative_review`, and `merge` all not performed.
Apart from those bootstrap bodies, whose external authority this command does
not verify, unchanged and prior deleted bodies, intermediate commit history, working-tree proposal bodies,
staged/untracked/ignored files and all other audit checks are not inspected.
Working-tree boundary metadata is inspected. A merge that preserves intermediate commits requires a
separately authorized history gate. Ref and branch
are checked throughout, but the host remains responsible for preventing
concurrent state changes and qualifying code and repository identity.

If the established consumer gate requires a global audit, this subcheck does
not satisfy it by itself. Replacing or supplementing that gate requires the
consumer's already authorized, independent policy-review and promotion
process, including its own gates and trusted-ref readback; the candidate cannot
authorize its own installation or redefine its own gate.

## Plan-bound C1 sync

`scripts/wiki_sync_guarded.py` is a separate, conservative route for an
externally admitted C1 selection. It does not change the legacy sync or make
that command protected. The host must independently qualify the code, both
repository identities and roots, execution, Git executable and configuration,
policy/bootstrap reads (including Git refs, index, tree metadata and nested
repository sentinels), selection-file read, and authority to review and apply.
The selection and its digest are not grants, approvals or proof of host
identity. An independently authorized process must review the selection before
the consumer lock or selected target bodies are inspected. A candidate policy
cannot authorize its own installation or normative promotion.

The host supplies a nonempty folder `CoordinationBinding` through
`WIKI_COORDINATION_ALLOWED_CONTEXTS` and `WIKI_COORDINATION_TRUSTED_REF`;
the approved policy revision must equal that ref. For each selected target,
including `kit.lock`, and each deterministic temporary path, the current
policy must permit exact read and write for the same owner and connection;
every listed parent needs read permission for metadata. Denies still apply.
The host must separately qualify bootstrap access; environment variables do
not authenticate it. This route requires existing parent directories and
refuses symlinks, hardlinked selected files, nested repositories, unsafe paths, conflicts, selected staged
changes, and C2. C3 has no supported flag here. It currently refuses Windows
before bootstrap because its filesystem/ACL guarantees are not qualified.

Build a `wiki.guarded-sync-selection/v1` object with the public Python helper
`select_contract(context_id, policy_revision, trusted_ref, source_sha, paths,
manifest_path=...)`. `paths` is the exact complete union of source C1 paths,
previous lock-managed paths and `kit.lock`, independently selected and
approved before lock access. The helper deterministically adds temporary and
parent-metadata paths; the same independent authority must admit those too.
`selection_digest(selection)` hashes canonical UTF-8 JSON (sorted keys,
ASCII escaping, compact separators). The selection includes its schema,
source and policy revisions, trusted ref, context, manifest and all paths.
After reading the admitted lock, the implementation checks that exact union
before inspecting any target; a mismatch fails closed. Selection files must be
regular, non-hardlinked files outside both repositories and remain private where appropriate.

Use the host-qualified Python `prepare_plan(...)` with that same selection,
binding, revisions and digest to obtain the full private reviewable B0. Its
`plan_sha256` binds source and consumer HEAD, selection, authority identifiers,
target and lock content hashes, modes or absence, parent and temporary states,
the exact C1 changes, temporary effects and resulting lock. It explicitly
reports `consumer_dirty: not_inspected`; selected index entries are checked,
but no global status or cleanliness is claimed. The CLI B0 prints counts and
digest only, so that output alone cannot supply full plan review:

```sh
python3 scripts/wiki_sync_guarded.py --kit KIT --consumer CONSUMER \
  --context CONTEXT --approved-revision POLICY_SHA --source-sha KIT_SHA \
  --selection-file PRIVATE_SELECTION --selection-sha256 SELECTION_SHA256 --dry-run
```

After independent review and approval of the full effective plan, use the same
arguments without `--dry-run` and add `--expected-plan-sha256 APPROVED_PLAN_SHA256`.
The digest binds the plan but does not authenticate approval; protect its
delivery independently. Apply rebuilds and compares the plan before effects,
rechecks refs, all selected target states and the index, and checks each path
again before its effect. It reads back C1 and lock plus refs afterward. Ref,
target or policy drift fails closed, but ordinary filesystem operations are
not atomic as a group and checks cannot exclude concurrent writers between
checks and effects. The host must prevent such races. An error after an effect
can leave partial changes; inspect the admitted scope and recover through the
consumer's authorized process. These checks do not qualify C2/C3, a global
audit, a consumer gate, or normative approval.

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
