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

For a host-bound coordinator handoff, `task.role: coordinator` adds the full
[coordinator role contract](../../../.skills/wiki-viva/reference/coordinator.md)
as explicit evidence from the current approved revision. In this mode
`content_revision` must equal `approved_revision`; the role file must exist and
pass the ordinary ownership, connection and deny checks. This does not support a
coordinator packet pinned to historical content. The packet records the added
evidence, not an authenticated role: an executor request could select the same
evidence. The host must independently bind the actual role and its request to
the execution; neither a role string nor the packet digest proves identity. The caller cannot
provide a duplicate role-file evidence entry to replace it. The default role is
`executor`; an untrusted request cannot authenticate either role. At opening and
resumption the host must bind the actual role, independently check current owner
direction and pauses, and refuse stale queued work. A packet does not enforce
that runtime behavior or prove that an external T3 launcher consumed it.

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

The selected task-result schema is a technical dependency of the installed
validator, read from the installed code tree; it is not task evidence declared
in the packet. The authority already applicable to execution and its technical
dependencies may cover that read. A missing task-data selector does not itself
grant or deny it, and existing valid authority does not need to be requested
again. Applicable denies and the actual scope of that authority still matter.
The local session and context binding do not prove bootstrap authority, actor
identity for an external system, filesystem isolation or cleanup. An unavailable
binding or unbound context is refused before this entrypoint reaches the schema;
Python imports and other bootstrap reads have already occurred, so that refusal
does not establish admission of the whole runtime or earlier I/O. For a server,
qualification of its actual startup and technical dependencies belongs to the
authorized host; this route does not supply that proof.

The operator index `/api/coordination` remains a broad caller-trust projection, marked `policy_enforced: false` and `trust_boundary: caller_trust`. Its profiles, fronts and actions are navigation and historical attribution. It is not an owner-scoped protected read. GET `/api/coordination/profiles/<id>` now returns a constant `coordination_context_required` migration response without snapshot, catalogue, page bodies or profile existence disclosure. There is no fallback from an unavailable protected binding to a legacy packet.

## Context-bound secrets-only check

An independently configured folder-mode binding can run a qualified
secrets-only selection under one context without claiming a global audit:

```sh
python3 scripts/wiki_audit.py --only secrets --context-guard CONTEXT \
  --context-policy-revision APPROVED_SHA --context-selection-sha256 SELECTION_SHA256
```

An explicit context-guard request for the global audit, another registered
check or a mixed selection is refused before worktree configuration or Git
inventory is opened; it never falls back to the legacy audit. This is a
fail-closed disposition, not selection or execution of those checks. An
invocation without the context guard remains a caller-trust legacy route.
Python startup, imports, executable code and root-binding metadata precede this
refusal and still require independent host authorization; the refusal is not an
OS-wide I/O observation or a qualified audit bootstrap.

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

## Context-bound methodology check

The existing `wiki_check_methodology_coverage.py --check` can use an R1
worktree selection with an independently configured folder binding. This is the
methodology check only: it does not run or qualify a global audit, other gates,
historical blob/message scans, preflight, review, merge or runtime observation.
The legacy invocation without a context guard remains caller-trust.

Before invoking either planning or execution, the host must independently
admit the Python executable and imports, Git configuration and metadata,
approved policy and instructions, approved and worktree configuration, ignore
rules, complete filesystem metadata and the output channel. The inventory and
context qualifier may read bootstrap bodies that overlap the later selection;
the selection cannot retroactively authorize those reads. The worktree config
must equal the approved config; candidate configuration is never authority.
The host provides the complete applicable list of normative paths (including
`wiki.config.yaml`); new normative changes and index divergence remain refused
by R1. A side branch may inherit an older boundary entry only under the
parent-propagation constraints described below.
The host must exclude concurrent writers, including its admission callback;
these checks are optimistic, not an atomic filesystem snapshot or OS sandbox.

Use `--check --context-guard CONTEXT --context-policy-revision APPROVED_SHA
--context-base BASE_SHA --context-head HEAD_SHA --context-branch wiki/BRANCH`
with `--context-normative PATH` for each normative path and `--context-plan`.
The plan includes path metadata and the selection; authorize the output channel
before displaying or retaining it. A plan is not a check. An authorized host
independently reviews the complete selection and then invokes the same command
without `--context-plan`, adding `--context-inventory-sha256` and
`--context-selection-sha256` from that plan. The digests bind the selected
metadata; they do not authenticate approval, actor, bootstrap or host. An
in-process host can instead call `guarded_methodology` with its admission
callback. A refusal or partial result is never a successful gate.

The selection includes configured required pages and templates, Markdown under
the memory root, eligible events and manifests, requests and, conservatively,
all eligible result-cache candidates when requests exist, including ignored
files. It may therefore refuse a denied cache even if a later request would not
use it. After admission, all selected bodies are read, including conservative
candidates; the result lists their paths, byte counts and SHA-256 digests. The
host must authorize this result channel too. Required missing files, missing
eligible inputs present in HEAD or the index but missing from the worktree,
denied candidates, stale selections and unsupported
inventory entries fail closed. A partial result distinguishes bodies fully read
and validated from attempted reads that may have accessed bytes even if validation
failed. Bootstrap reads are reported separately and can overlap the selection.
Individual bodies are limited to 2 MB
and the selection to 8 MB. The R1 inventory rejects symlinks, hard links,
nested repositories and mount crossings even outside this check's inputs.
Selection metadata and denied-path presence must already be authorized to the
operator. Synthetic Python instrumentation is not system-wide I/O observation;
host isolation, live observation, termination and cleanup remain external.
The HEAD/index metadata check is not coverage of historical or index bodies.

## Context-bound input-stage check

The existing `wiki_input_stage.py --check` supports an R1-selected worktree
readset, independently of the methodology check. An invocation without a
context guard keeps the legacy caller-trust behavior. The guarded route does
not run or qualify another check, the global audit, preflight, gate composition,
review or merge.

Before planning or execution the host independently admits the executable and
imports, approved policy and instruction bodies, approved and worktree config,
Git metadata and commit objects, ignore rules, filesystem metadata and the
output channel. Bootstrap bodies can overlap later selected targets. The
worktree config must match approved config. A digest binds selection metadata;
it does not authenticate the actor, external approval or host. The host must
prevent concurrent replacement, including during its admission callback. The
inventory retains its conservative restrictions on normative changes,
symlinks, hardlinks, nested repositories and mounts, and is not an OS sandbox.

Use `--check --context-guard CONTEXT --context-policy-revision APPROVED_SHA
--context-base BASE_SHA --context-head HEAD_SHA --context-branch wiki/BRANCH`
with each `--context-normative PATH` and `--context-plan`. The plan's paths and
metadata require an independently authorized output channel. The selected set
includes Markdown under the configured memory root, the configured root page,
the stage output, a present stage cache (including ignored cache) and any
explicit `--context-extra-path PATH` inputs. Extra paths are an explicit
selection, not a grant; R1's current-policy and deny checks still apply. The
current R1 selector requires each selected body to have the acting owner, so
cross-owner inputs remain unavailable even if another contract permits them.
Missing tracked eligible targets and unavailable or denied selected inputs
refuse before selected bodies. Per-body and total limits are 2 MB and 8 MB.

An authorized host may independently review and admit the plan and invoke the
same command without `--context-plan`, supplying the inventory and selection
digests via `--context-inventory-sha256` and `--context-selection-sha256`.
The check consumes the selected bytes through an in-memory reader. Source
`config_ref` targets may be anywhere inside the repository: an existing target
outside the selected set causes a partial result before its body is read, not
a silent absence. A missing or invalid explicit `config_ref` also makes the
guarded result partial rather than falling back; an unavailable configured root
page is refused during planning. Reconcile the attempted reads, then prepare and admit a new
selection with any needed extra paths; do not combine partial results into a
gate. An in-process host may supply an external admission callback, which the
kit does not authenticate.

`completed` means only that the deterministic input-stage comparison
completed. The result retains `gate_state: blocked_external_qualification`,
external admission/bootstrap/cleanup and live observation not verified, and
both the guarded planning and execution CLI return nonzero: planning prints a
`selection_only` result, not a passed check, and this process cannot independently
attest its own host, observer or cleanup after exit. Worktree and ignored
labels cover selected bodies only; index is metadata only; Git bootstrap may
read commit objects including messages, whose bodies are not audited here.
Partial results count bodies validated and attempts that may have read bytes.
Output readsets and paths can be sensitive. Independently qualified authority,
observation and cleanup, plus any applicable consumer gates and review, remain
necessary; no digest or callback self-approves these requirements.

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

The existing audit entrypoint also offers a **partial base-history search** for
one transition check under an independently admitted folder binding. For example,
the host may request a plan with `--check --only action_state_transitions`,
`--context-guard CONTEXT`, `--context-policy-revision BASE_SHA`,
`--context-base BASE_SHA`, `--context-head HEAD_SHA`, `--context-branch BRANCH`,
one or more `--context-normative PATH` options and `--context-plan`. The host
must supply its complete independently qualified normative scope, including
`wiki.config.yaml`. The alternative check name is `source_lifecycle_transitions`.
The approved Git configuration selects the memory root; a candidate worktree
configuration is not used as authority. A denied candidate or denied object
alias refuses the entire search before grep, not just the denied path.

After independent approval of the full plan and its output audience, the host
can repeat the command without `--context-plan`, passing the returned inventory
digest as `--context-inventory-sha256` and the plan digest as
`--context-selection-sha256`. Digests bind bytes but do not authenticate actor
or admission. Git/runtime startup, policy and context bodies, Git attributes
(including ignored or external sources), metadata, historical authority and
concurrency isolation must be independently qualified before invocation.
Bootstrap reads may overlap the later selection. Plan output includes path and
object metadata; do not emit it to an unqualified audience.

Both planning and execution deliberately return nonzero, even when the selected
grep completes. The result is partial and does not execute the transition check,
read its action-adoption receipt or changed worktree bodies, audit intermediate
history or messages, qualify the host, or pass the global or consumer gate.
Failures after search starts report partial attempts; a missing or denied input
is never a pass. This route does not replace the legacy check or make any R1
gate optional.


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
For a proposal whose only changed Git blob is `AGENTS.md`, this same scoped
secrets check can scan that one candidate when the acting context is permitted
to read it under the approved policy and the host independently admits the
selection and bootstrap. If the approved policy denies that read, the candidate
cannot grant it and the check refuses before opening the candidate body. This
does not authorize normative review or replace any other required gate; an
independently authorized reviewer and applicable process remain necessary.
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

## R1 inventory and selected secrets scan

The in-process `wiki_core.audit_r1_inventory` module provides a bounded
inventory, explicit selection and secrets-only scan. It is not a global audit,
an installation authority, an observer or a substitute for consumer gates.
Before calling it, an independently trusted host must authorize the code and
Git executable/configuration; repository identity and refs; approved policy,
instructions and index; all commit objects needed for traversal, including
their messages; filesystem names and metadata; ignore files and exclude rules;
and the audience receiving the inventory. Git may read commit messages and
ignore bodies during this bootstrap, before selected target bodies are scanned.
Bootstrap files may also be among the later selected targets. A digest never
authenticates the host or grants any read.

`inventory(...)` records the `base..head` commit interval and boundary parents,
tree OIDs and modes, index stages, physical metadata, untracked and ignored
files, missing tracked files, current-policy denials and denied-OID aliases.
The host supplies an explicit `normative_paths` list including
`wiki.config.yaml`; the inventory also includes `AGENTS.md` and
`AGENTS.override.md` found in the trees or index. The host must independently
establish that its list covers all other applicable normative paths; that
completeness is not verified by this module.
It requires the selected branch to be the actual worktree HEAD, rechecks refs,
index, physical metadata and ignore classification, and refuses unsupported
symlinks, hardlinks, nested repositories, different-device directories, sparse
entries, new changes to those normative paths in Git history or index, new untracked
context instructions, shallow repositories, grafts, object alternates,
limits and Windows. Content
relation for worktree files remains `unknown`; unstaged normative bodies are
not inspected. Historical policy and live observation are not qualified. Paths,
OIDs and metadata in the result may be sensitive: the host must admit the
output channel independently.

An older normative entry inherited unchanged from a boundary parent that is an
ancestor of the approved base can appear on a side branch. All candidate
single-parent commits must preserve their parent's normative entries. A merge
must preserve the base entry wherever a parent contains it; otherwise its
parents must agree on that entry. Its complete normative snapshot must match
one parent, and HEAD and index must match the base. The inventory retains all
commits, boundary parents and trees. This checks propagation of presence, mode
and object ID only: ancestry does not prove historical review or authorize an
older policy or any body read. The approved base policy and the host's
independent bootstrap, historical-access and selection admission remain
required; a consumer may impose a stricter rule.

`select(inventory, requested)` binds explicitly requested Git blobs, index
stages, worktree files and commit messages to the inventory digest; it refuses
current-policy denials and OID aliases shared with denied paths. It opens no
selected target bodies. The host must independently establish that the request
contains every input required by the actual gate, review the full selection,
qualify historical and current authorization and admit the selection digest.
Neither a caller-provided list nor a digest proves completeness or approval.

`scan_selected(...)` reconstructs the inventory and selection, requires the
trusted host's live `admit(selection)` callback before selected object sizes
or bodies, rechecks admission and refs, and reports only a bounded secrets
count for explicitly selected UTF-8 text. NUL, invalid UTF-8, LFS pointers and
C0/C1 control characters other than tab, LF and CR result in partial coverage;
accepted text is not proof that every secret was detected. It rechecks the
inventory afterward and reports partial coverage on handled errors. Abrupt termination may produce
no result; the host must record that outcome as uncertain. The host
must prevent concurrent writers, including mutations by the admission callback,
and independently qualify historical grants,
the callback, the output and any required live observer or interruption/cleanup
barrier. The function cannot authenticate those properties. It does not run
the rest of the wiki auditor, prove the gate's input coverage, establish an
atomic snapshot or claim a global PASS. Same-device mounts, ignore-configuration,
object-store and runtime isolation require a host-qualified boundary; a denied
or unsupported required input blocks the dependent gate rather than being
silently excluded.

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
approved before B0 target access. The helper deterministically adds temporary and
parent-metadata paths; the same independent authority must admit those too.
`selection_digest(selection)` hashes canonical UTF-8 JSON (sorted keys,
ASCII escaping, compact separators). The selection includes its schema,
source and policy revisions, trusted ref, context, manifest and all paths.
After reading the admitted lock, the implementation checks that exact union
before inspecting consumer worktree target bodies; a mismatch fails closed.
Selection files must be
regular, non-hardlinked files outside both repositories and remain private where appropriate.

For assisted discovery, first run:

```sh
python3 scripts/wiki_sync_guarded.py --kit KIT --consumer CONSUMER \
  --context CONTEXT --approved-revision POLICY_SHA --source-sha KIT_SHA \
  --bootstrap-selection
```

It emits a proposed lock-only selection and digest without reading either
repository. Independently review and admit it, the code and context bootstrap,
reading `kit.lock`, source Git and its manifest, and an output channel allowed
to receive every name in the lock and manifest. Pass the admitted selection
file and digest using this separate command:

```sh
python3 scripts/wiki_sync_guarded.py --kit KIT --consumer CONSUMER \
  --context CONTEXT --approved-revision POLICY_SHA --source-sha KIT_SHA \
  --selection-file BOOTSTRAP_SELECTION --selection-sha256 BOOTSTRAP_SHA256 \
  --propose-selection
```

The command verifies binding and
policy for that lock selection before opening the lock, then prints a proposed
complete selection and its digest. It reads C1 blobs from the source kit and
the separately admitted approved Git policy, instructions and context index;
these approved bootstrap bodies may overlap C1 targets. The output reports
that overlap as `approved_bootstrap_c1_overlap`; it does not read consumer
worktree target bodies or admit the proposal. The host must authorize the
bootstrap even for any overlapping path before invoking discovery. Review
and separately admit the entire returned selection,
including every temporary and parent path, before using it for B0. A denied
lock fails before its body is opened; a denied target may be named in this
proposal and causes B0 to refuse. Do not use this output channel unless the
host independently permits that disclosure.

Use the host-qualified Python `prepare_plan(...)` with that same selection,
binding, revisions and digest to obtain the full private reviewable B0. Its
`plan_sha256` binds source and consumer HEAD, selection, authority identifiers,
target and lock content hashes, modes or absence, the desired hash, size and
mode for each C1 file (or absence for a removal), parent and temporary states,
the exact C1 changes, temporary effects and resulting lock. It explicitly
reports `consumer_dirty: not_inspected`; selected index entries are checked,
but no global status or cleanliness is claimed. The CLI B0 prints counts and
digest by default. Add `--full-plan` to emit the complete plan as JSON to
stdout for independent review on an admitted channel:

```sh
python3 scripts/wiki_sync_guarded.py --kit KIT --consumer CONSUMER \
  --context CONTEXT --approved-revision POLICY_SHA --source-sha KIT_SHA \
  --selection-file PRIVATE_SELECTION --selection-sha256 SELECTION_SHA256 --dry-run --full-plan
```

These explicit outputs contain names and metadata that may be sensitive. The
command itself does not create a report or cache, but stdout, terminals, logs,
swap or crash handling can persist data; the host must qualify the transport.
The selection-file read is also an independently authorized bootstrap input.

After independent review and approval of the full effective plan, use the same
arguments without `--dry-run --full-plan` and add `--expected-plan-sha256 APPROVED_PLAN_SHA256`.
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
