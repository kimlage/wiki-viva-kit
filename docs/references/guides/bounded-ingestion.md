# Bounded ingestion requests

Use the [host-bound source stages](#host-bound-protected-source-preparation) for
new approved folder-policy ingestion. They validate the selected source,
context, policy and budget before retaining a request. An authorized agent
must read the request, record its own results and arrange review and
incorporation; those outcomes are not produced automatically.

[wiki_ingest.py](../../../scripts/wiki_ingest.py) remains available for the
separately authorized working-tree compatibility route. Its old
`--approved-revision` and `--policy-context` flags, and the matching flags on
[wiki_llm_context_pass.py](../../../scripts/wiki_llm_context_pass.py), are
refused for new v1 operations, including recording and checking results. They do
not fall back to compatibility. Historical v1 artifacts and their prompt remain
preserved; reading a mixed historical cache under current authority needs a
separately qualified route, not a new use of the retired flags.

The context and full-request budgets measure canonical UTF-8 bytes, not model
tokens. They bound the complete selection without truncating mandatory content
or chunks. When a source is too large, select a smaller authorized scope or
change the budget under the task's policy. A failure before persistence does not
imply that a later failed write was atomic: the host-bound route reports
possible partial effects that require inspection.

## Folder selection

Without approved-context flags, the existing working-tree adapter remains
explicitly labelled compatibility. Previously retained envelopes are preserved;
their availability depends on current authorization. New requests bind the explicit limits as well as the delivered interpretation
context. Compatibility is not evidence of approved policy or source freshness.

For a local folder entry, start in the nested directory or select it explicitly
with `--folder FOLDER`; paths are relative to the wiki root. The request includes
the physical ancestor `AGENTS.override.md`/`AGENTS.md` chain and the selected
nearest context's `index.md`, or `README.md` when no `index.md` exists. An implicit context has both its own nonempty
instructions and an index; an auxiliary folder still contributes any physical
instructions along the way. A child with only an index does not become a new
context. Use `--index PATH` to select an index in a qualified context folder;
the root requires an explicit index. Missing instructions or index, symlinks and
nested Git roots block local preparation. In `wiki_ingest.py`, `--folder`
cannot be mixed with approved-policy arguments. Automatic discovery does not select the root index;
choose it explicitly when the root is the intended context. The physical entry
folder and selected index are retained and revalidated before writes.

Approved folder ownership recognizes `index.md` and `README.md` as stable
conventions, with `index.md` taking precedence. An explicitly named custom
index is usable within an already recognized context; a folder containing only
a custom index does not define approved ownership and requires requalification.
The selected index is not an access grant.

## Host-bound protected source preparation

The existing in-process host binding can call
`wiki_core.coordination_context.protected_source_stage` for `prepare`, `record`,
`consolidate` and read-only `compare`, with an explicitly authorized folder,
approved revision, source and artifact owner. The binding is fixed by the host and is not selected
by the payload. Result objects arrive from that host; these operations do not
call a model. They use the existing `WikiPaths` layout under the reserved
`.wiki-viva-protected` component within the configured Git-ignored derived root.
The selected source, every retained artifact and event destination must satisfy
the current policy. A context cannot write an artifact belonging to a different
owner. An explicitly selected ancestor integrator may do so only when both
contexts are in the host binding and exact bilateral connections authorize the
integrator to read the selected source and every applicable instruction/index.
Source pages and candidates also require the relevant read connections. Each
stage revalidates the source, selected context and revision. A failed write may
leave partial effects and explicitly reports that inspection is needed before
retry.
Before retaining protected JSON, the stage checks the actual artifact paths
against Git's ignore rules and refuses tracked or unignored paths. It repeats
that check at each write. A later ignore change or a forced Git add can still
expose files; the application boundary does not replace filesystem controls.

An installation can opt into source-scoped artifact locations with
`llm.protected_cache_mode: by_source_v1` in its approved configuration. For
the exact executor, integrator and local source selector, an operator can obtain
the relative component before approving the corresponding policy scopes:

```sh
python3 -c "from wiki_core.ingest.cache_partition import partition_component; print(partition_component('.', '.', 'data/raw/example.pdf'))"
```

The component is below the configured derived root and
`.wiki-viva-protected`. Grant the artifact owner only the required read and
write scopes there, and independently authorize the source and any selected
context. The hash is a stable routing name, not a secret, a grant or an OS ACL;
each operation still checks current policy and the physical boundaries. The
default `shared` mode retains the previous layout. Changing modes does not
migrate or erase existing artifacts. Requests remain pinned to their approved
policy revision: restoring the old layout in a later revision does not make an
old request current. Reprepare and review against the current policy, or use a
separately reviewed migration if the installation provides one.

For a source in an external provider, an authorized operator or existing
provider adapter first captures the original bytes in an explicitly authorized,
Git-ignored local source path. Retain the provider identity, file identifier,
version or modification time, observation time, byte size and provider checksum
when available in the private source record, and compare the provider checksum
with the downloaded bytes. Record a SHA-256 of those bytes as well. Recheck the
provider metadata after download if the provider can change the file in place.
If the provider does not supply a comparable checksum or stable revision,
record that limit instead of claiming verified provenance. The protected stage
checks the local bytes and their digest on every stage; it does not itself
authenticate the provider or verify an operator's external-source assertion.
Never store credentials or authenticated links in the record. The external
original remains canonical; a local capture or source-page association is not
proof of a complete reading or incorporation.

### Provider messages with prohibited links

If a provider message contains an individualized tracking or access-bearing
link which policy forbids retaining, keep the protected ingestion **pending**.
The current stage has no qualified representation contract for a sanitized
projection of a message. It cannot bind the omitted or transformed material to
the request, reconstruction, event and reviewer readback. Do not submit a
projection as though it were an intact original, or omit its representation
from the request to make the current stage accept it. A `.txt` file created
from a message is treated as the selected local source; its digest verifies only
that file, not the provider message or the transformation.

Do not persist the prohibited link in source bytes, extracted text, request,
logs, temporary files, metadata or an event. Scanning for common secrets does
not establish that every individualized URL has been removed. Until a reviewed
projection and provenance contract is implemented, report the omission and the
unavailable source-bound verification without creating a protected event or
claiming completed ingestion. An intact provider original may remain available
at its own provider, subject to the provider's access and retention policy.

Each stage must receive the same `context_selection`, with either an explicit
`root_entity` path or `omit_root_entity: true`. It may also select exact
`source_page`, `source_config`, `input_channel`, `templates` and `target_pages`
paths. The packet authorizes each selected body for both actors before source
capture, checks declared config and channel links, and retains omission coverage.
Declared path links from the source to its configuration/channel and their
`target_pages` are resolved through that same authorized packet builder; they
do not have to be copied into the stage payload. Unresolved page IDs still need
an exact selected path; they never trigger an unrestricted catalog scan.
To restrict the selected targets, pass `"target_selection":"explicit"` with
an explicit `target_pages` list on every stage. Declared but unselected targets
remain visible as omissions and are not selected merely by that declaration.
Independent, authorized hub discovery may still identify them as candidates;
the mode grants no access. Without it, declared targets continue to be selected
and checked. Here, declared targets are those in the selected source page,
configuration and channel. `target_pages` in the captured source's own
frontmatter is not automatically included in this coverage; assess it
separately when relevant.
References containing `/` or ending in `.md` (case-insensitively) are treated
as literal paths, not page IDs, even if another page uses that string as its ID.
Other references are treated as page IDs, including names without an extension.
Noncanonical paths, including backslashes, repeated separators or whitespace at
their ends, are rejected. Target declarations with whitespace at their ends are
also rejected rather than silently trimmed, and declarations must be text.
The frontmatter parser does not detect duplicate YAML keys; review malformed
source metadata separately before relying on its coverage.
The source-page association is operator-selected and is not proved by the link.
A nested executor does not automatically receive a global business root or
its bundle. Required perspectives from the selected context require an exact
`perspective_refs` ID-to-path map, repeated at each stage. Each page must have
the matching ID and type and pass current policy; the paths grant no access.
Skipped perspectives, unselected optional perspectives, linked sources and
other gaps remain visible in packet coverage. Source frontmatter declaring a
configuration or channel must match the selected context.
Protected consolidation includes declared targets, subjects linked by connected
hubs and declared consumers found inside selected hub directories, alongside
explicit candidates. The bounded discovery checks current authority for both
actors before each body read; missing access or a scan limit is reported as
incomplete coverage. Consumers outside those directories are not assessed. All selected candidates are read from the approved
commit, with each path, commit, Git blob and SHA-256 recorded in the integration
packet. Unapproved working-tree edits do not influence candidate matching.
Selected candidate boundaries and current authority are rechecked before
effects and after readback; a late failure can leave partial artifacts.
Retained packets created under an earlier candidate selection can fail current
requalification; their bytes remain in place and are not silently accepted.
Hub navigation discovers candidates, not factual dependencies. A sibling
subject without a matching source reference or semantic relevance is not made
an update obligation merely because it appears in the same hub.
Current `information_requirements` targeting the selected source are review
suggestions. A proposed event is not an approved change: after incorporation,
use the existing context impact and review operations with approved before/after
revisions to evaluate downstream requirements, owner by owner. Discovery alone
does not establish a completed review or authorize propagation.
For `wiki_context_flow.py impact`, omitting `--consumer` discovers current
requirements in the working directory for the selected `--context`. Run it
inside an authorized folder below the wiki root; `--before` must be an approved
ancestor and `--after` the current approved revision. The result remains a
one-hop review proposal with incomplete coverage outside that folder and owner.
To record one returned `event_id` on an existing action, pass `--event-id`,
`--action-id`, `--action-path`, `--profile` and the action's current
`--expected-sha256` to the same impact command. The current binding, owner,
write policy and approved coordinator route are checked again; missing access
or a stale action is refused. New events require either approved action bytes
or an exact, receipt-validated chain of review comments for current candidates;
other working-tree changes are preserved and block the write. An identical retained event is reconciled without
duplication. This comment requests review; it does not dispatch an executor,
alter existing blockers or prove incorporation. Continue through the normal
review, integration and readback gates.
Among those candidates, a declared `source_refs` ID in the `source-v2` format
with the same origin and a different content-hash prefix is suggested in
`should_review`. If the source page was selected in the request, a candidate's
reference to its `page_id` is also suggested. This reference does not identify the
consumed revision and can suggest review even when the source has not changed.
The operator-selected association between that page and the source remains unverified. These are review suggestions,
not proof of capture, consumption, a factual change or a mandatory update. They
do not search unselected pages or grant access. A source page selected only
later during consolidation cannot supply this matching input. Legacy IDs and IDs
ending in `unobserved` are not inferred from names or content; their coverage
remains unknown.
For independent Git evidence, `repository_source_pages` may explicitly map
each host selection ID to its own authorized source page; the page locator
must match the sanitized configured identity. This association does not grant
access or prove remote identity or file consumption.

An authorized host may pin up to 32 exact independent Git grants, each binding
a local root, sanitized configured identity, commit, literal path, executor,
integrator and byte limit. A stage selects one ID or a list of up to eight IDs
using `repository_selection`; every selected grant is checked before opening
any selected repository, and the same selection must be repeated on later
stages. Both actors need the current `independent_git.read` capability.
The separately authorized `independent_git.derived_proposal` publication
capability and an exact host-pinned `event_target` are required to consolidate
a Git-derived event. A selected path, configured origin, receipt or source-page
association is not a grant or proof of remote identity. The primary
`source_ref` remains a separately authorized wiki-local source.

The trusted local operator can inspect the configured IDs and actors, without
displaying roots or identities, using `wiki_coordination.py --show-host-binding`.
The `compare` source stage compares an originally selected file to a separately
host-pinned current selection for the same repository identity and path. It
examines only explicitly selected authorized candidates, returning a manual
review suggestion and unknown file consumption; it does not write a page or
perform a review. See [protected independent Git](protected-independent-git.md)
for configuration, filesystem limits, exact stage inputs and provenance.

Protected folder ingestion requires the v5 prompt, which points to
`wiki_coordination.py --source-stage`. A configuration explicitly selecting
v4 must be updated through its approved policy process before preparing a new
folder request. When no version is configured, this route defaults to v5.
Version and prompt text participate in the request fingerprint: requests using
v4 must be prepared and read again, while retained historical artifacts and the
v4 prompt remain unchanged.

The legacy `wiki_ingest.py` and `wiki_llm_context_pass.py` approved-v1 flags
are retired for new operations, including result recording and checks through
those flags; they refuse before opening the selected source or result. Local
working-tree compatibility without those flags remains available. Existing
v1 and mixed-cache artifacts are preserved, but examining the mixed artifacts
under current authority requires a separately qualified historical route.
The protected host also refuses new v1 task packets; existing historical
preflight remains a separate operation.

This route supports local Markdown, text, CSV, TSV, XLSX, DOCX, EML and PDF
sources up to 16 MB. Extraction consumes the authorized bytes captured in memory;
the extractor does not reopen or stage the source. CSV and TSV require UTF-8,
and email bodies require their declared encoding; invalid encoding is rejected.
Office archives have bounded expanded size and spreadsheet dimensions. Extracted
content from non-text formats is capped at 2 MB. PDF extraction requires the
local `pdftotext` executable, runs with a 30-second timeout, and does not perform
OCR. PDF chunks do not retain page numbers; consult the original PDF to locate
an extracted passage. DOCX extraction includes body paragraphs and simple table rows in their
document order. Each table row is a JSON line with table/row identifiers and
escaped cells, and remains whole in its chunk; merged or nested tables require
separate review. Footnote/endnote references, inline revisions and wrappers
that the reader cannot preserve also require review. Headers, footers, images,
embedded objects, hyperlink destinations and comments are not
interpreted. CSV and TSV are represented as JSON lines with logical record
ordinals, not physical line numbers; a record can span multiple physical lines.
The protected reader defaults to Python's comma-delimited `excel` dialect for CSV
and tab-delimited `excel-tab` for TSV, including doubled quotes. For a `.csv`, the
operator can supply `"csv_delimiter": "comma"`, `"semicolon"` or `"tab"` in the
source-stage payload; repeat the same selection for prepare, record, inspect,
compare and consolidate. The selected delimiter is bound to the request and
recorded in the manifest and event. No delimiter is inferred or independently
verified; confirm the source's quoting and format before relying on columns.
Without a selection, a semicolon-delimited CSV can be misread as one column; the
unverified comma default is recorded in that source's manifest, request and event.
An existing capture using a different selection is preserved and requires review
or migration; it is never silently overwritten. The legacy reader is unchanged.
The newly explicit dialect uncertainty for existing CSV/TSV captures and the
page-location limitation for existing PDF captures also change their retained
coverage and request fingerprint, even when source bytes are unchanged. A prior
protected request cannot be reused as current evidence without requalification;
preparation preserves any conflicting earlier capture and requires a controlled
review or migration rather than replacing its artifacts.
XLSX rows are JSON lines with sheet names and row numbers. Cell boundaries, line
breaks and separators are preserved; XLSX numbers, booleans and strings retain
their types, while dates, times, durations, decimals and errors are tagged.
Nonempty XLSX cells include their stored number format; this is not a rendering
of conditional formatting, locale-dependent display or other styles.
Each tabular row remains whole in its chunk: a row above 32,000 bytes or 1.5
times the estimated word target (minimum 80) is blocked and needs a smaller
source scope. The estimate uses the larger of the space-split word count and
UTF-8 bytes divided by five, rounded up; it is not a hard model token limit.
XLSX formulas are retained with their cached values where present;
the extractor does not recalculate them and explicitly marks missing caches.
Workbook dimensions are limited to 100,000 rows, 1,024 columns and 2,000,000
cells per sheet. EML text and HTML bodies are included; attachments or other
non-text MIME parts require separate explicit review, and an absent body blocks
the capture. This is not a guarantee that every sheet feature or embedded object
was interpreted. An older capture of the same source whose extracted content
differs is retained; it requires explicit review or migration before reuse.
Other formats still require an authorized adapter. The complete serialized
request is also capped at 2 MB, which may require a smaller source, particularly
when text needs JSON escaping. Candidates must be explicitly selected.
The default `context_max_bytes` is 100,000 and `request_max_bytes` is 1,000,000;
both are configurable and must be repeated consistently for the same request.
It does not automatically inspect linked sources, expose an HTTP transport,
or incorporate the event in memory. Explicitly selected independent Git
evidence has the separate [host binding](protected-independent-git.md). The existing
`wiki_coordination.py` offers `--source-stage` operations to a trusted
local operator, with stage JSON on stdin and an approved revision. When the
folder is omitted, each stage selects it from the current working directory
inside the wiki; it does not cross a nested Git repository. When invoking the
script from an external kit, pass `--root WIKI_ROOT` unless the installed operator
already binds the content root. When the index is
omitted, the approved context uses `index.md` or falls back to `README.md`;
select another context index explicitly when necessary. If `--context-id` is omitted, an existing
host binding must already include the discovered context. The working directory
never grants access. Explicit context, folder and index selections still work.
The CLI's flags are not a security boundary against its trusted local operator;
a separately configured host binding is the protected interface. Regular compatibility
search, audit, GC and result recording do not open the reserved new artifacts;
their coverage does not include them. The older shared caches are not migrated
or classified by this route. Their compatibility readers still require separate
review before treating historical approved material as protected. A reserved
name is a routing convention, not an access grant or a filesystem ACL.

For example, a trusted local operator can prepare a selected root-context source
using the existing CLI (replace all placeholders with authorized values):

```sh
python3 scripts/wiki_coordination.py --root REPO --context-id . \
  --approved-revision APPROVED_SHA --source-stage prepare <<'JSON'
{"entry_folder":".","entry_index":"index.md","source_ref":"source.txt","source_context":"example","context_selection":{"omit_root_entity":true}}
JSON
```

The selected context, source, index, artifact paths and event destination must
already be permitted under the current policy; the example does not create
those grants. It explicitly omits the business root; the resulting coverage
gap must be resolved before a task that needs that context can be decided.
`prepare` returns a request plus `source_id` and `request_id`.
The returned request is a point-in-time projection: each selected cache key is
read under the current binding and checked against the source and request.
`result_exists`, source/chunk provenance and call counts reflect that readback;
the retained request is unchanged and has the same request ID. A malformed or
inaccessible result stops readback instead of being reported as a cache miss.
If that happens, previously written artifacts may remain. Cache availability
is not a review or an incorporation, and can change after the response.
Read the complete request and supply the results explicitly. For `record`,
the JSON supplies `source_ref`, `source_id` and `request_id`, and adds a `results`
array bound to the request. For `consolidate`, repeat those selectors and add
`source_page`, `event_target`, ISO `date` and optional `candidates`. Each stage
must resolve the same folder and index as the retained request, either from cwd
or explicitly. The event path must use the configured ingestion-events
directory and the canonical name `<date>-<sha256(source_id)>-<request_id>.md`.
The source page must exist, be authorized and have `page_type: source`. Its
association with the selected file is operator-supplied, not verified by the
route. Both `record` and `consolidate` must use the same limits and authorized
integrator and `context_selection` as `prepare`. Repeat any selected
`perspective_refs` and `repository_selection` as well. See the [stage dispatch](../../../wiki_core/coordination_context.py)
and [synthetic tests](../../../tests/test_protected_ingestion.py) for the exact
JSON fields. A result, event or integration packet is not a reviewed or
incorporated memory update.

For a `record` batch, the request and source are fully reconstructed before
and after the batch. Each result write and its readback are surrounded by
checks of the binding, physical boundaries, selected repository grants, and
the source and request identities. Existing differing results are preserved.
These checks are not an atomic filesystem transaction: if a change is detected
after a write, the operation reports possible partial effects for inspection.

`prepare` reports `result_budget`, including the 2 MB combined review limit and
the bytes of the exact selected cached results observed in its readback. A
`within_limit` status covers only those existing results; missing and future
results are not counted and can later exceed the limit. An `exceeded` status
warns that the observed results already exceed it. The route rechecks each selected result or absence
before returning, but the cache can change after that check; it is not an atomic
snapshot or filesystem access control.
After every `record` batch, `result_budget` reports the bytes in that submitted
batch and explicitly marks the aggregate as unchecked. This count is not a net
increase: an identical result might already have been recorded. `record` checks
the written batch without scanning previous results. To check the current
aggregate on demand, repeat `prepare` with the same selectors and limits, then
compare **both** returned `source_id` and `request_id` to the original IDs. Use
the reported aggregate for the original request only when both match. Identical
selectors do not guarantee identical IDs: a changed source can produce a new
capture and request. `prepare` is not a read-only check; it can retain new
capture and request artifacts, and a failure can leave partial effects requiring
reconciliation. It reads selected cache entries and can be expensive for many
chunks or repositories. Consolidation enforces the combined limit before
writing a packet or event; the separate inspection output limit also applies.

Results previously stored with `protected_historical_review` are preserved but
cannot be inspected or reused through this route. Preparation reports the
affected chunk as unavailable; other results remain available. An existing
annotated result also prevents recording a replacement under the same cache key.
No historical request or result is removed or overwritten, and this route provides
no recovery or migration for the affected result.

To review retained data, use `--source-stage inspect` with the same selectors,
limits, context selection, repository selection and integrator as the original
request. Supply `view: "results"` and an explicit `chunk_ids` array of one to
32 IDs from that request to retrieve matching recorded results. To inspect the
retained proposal, supply `view: "integration"` and the exact `candidates` array
used at consolidation, including `[]` when none were selected. The operation
revalidates the binding, current policy, source and selected data, reconstructs
the packet from authorized results and approved candidate revisions, and refuses
a mismatch. It does not check whether an event was written or a proposal was
reviewed or incorporated. The combined results are limited to 2 MB during both
consolidation and inspection. An older retained packet remains preserved but is
refused by inspection if any reconstructed field differs, including warnings or
impact classification; this route does not automatically replace or migrate it.
Consolidation checks this and the size of the
inspection result before writing an event or packet. Older packets above either
limit remain preserved and cannot be
reconstructed by this inspection route. The canonical serialized `result`
object, excluding the surrounding stage and CLI envelope, is limited by
`max_output_bytes` (default 1 MB, at most 2 MB).
An unavailable, invalid or over-budget selection fails without partial output.
These checks bind the result to the request but do not authenticate its author
or protect its semantic contents against an actor able to edit protected files.
Inspection requires the original approved revision to remain the current trusted
ref; it does not requalify an older request against a newer policy. Reading an
integrated wiki page is a separate operation.

## Working-tree folder entry

The commands and selectors below apply to the separate working-tree
compatibility route, not to the host-bound protected stages above.

For example, from the wiki root, enter the chosen context and prepare a source
using paths anchored to that root (replace the example paths and context):

```sh
wiki_root="$(git rev-parse --show-toplevel)"
cd "$wiki_root/path/to/context"
python3 "$wiki_root/scripts/wiki_ingest.py" --root "$wiki_root" \
  --source "$wiki_root/path/to/source.md" --context SOURCE_CONTEXT
```

The source must exist and be authorized, and the context must have the required
instructions and index. This command prepares a local request; it does not prove
native session instruction loading or grant access.

This is local context preparation, not proof of native instruction discovery,
an ACL or a sandbox. The selected entry reads its instructions and index without
opening the global source catalog or block world. Source configuration, linked
sources and other context remain unresolved; links do not grant access. The
source must be an explicitly selected regular file inside the wiki or a URL;
access-bearing URLs are refused. Folder ingestion does not
update the global search index or score event. Filesystem checks do not prevent
concurrent replacement. Multiple folders may retain distinct requests for the
same source. A complete, matching source capture is reused; a partial or
different capture blocks and is preserved. Re-emitting an identical request
preserves its original bytes. Local requests have a 2,000,000-byte retention
limit even when a larger request budget is supplied; an oversized request is
blocked before capture or request files are written, without truncation.
If local persistence fails, `written: false`
means persistence did not complete; `partial_effects: unknown` warns that
partial effects may exist and require inspection before retrying. Folder entry
does not provide scoped query search.

To include an independently authorized Git file with this source, append
`--repo ROOT IDENTITY REVISION PATH` to both ingestion and result recording;
repeat it for each selected file. `ROOT` is its local Git root, `IDENTITY` is
the credential-free host/path of its configured origin, `REVISION` is a full
commit SHA, and `PATH` is an exact tracked file. The request retains the root,
origin, commit, path, blob and hashes with the selected text. The caller must
provide the same authorized selections again when recording; each is checked
again before the result is written. When recording, also pass `--request`
with the exact retained request; repeat `--repo` for local consolidation. For
`--check`, repeat the same source, context, folder, index, limits, profile and
every repository selection used for the result, as applicable. The check uses
the recomposed request; it does not select a retained `--request`.
The configured origin and the receipt are
not authorization or proof of remote identity. Reads use the chosen Git commit,
without fetching or including working-tree edits; reading an old commit does
not establish that it is current.

An integrator can compare a previously recorded independent Git selection with
an explicitly chosen newer revision without editing the wiki:

```sh
python3 scripts/wiki_consolidate.py --source SOURCE_ID --request REQUEST_PATH \
  --source-file SOURCE_FILE --folder CONTEXT_FOLDER --source-page SOURCE_PAGE --candidate CANDIDATE_PAGE \
  --repo-compare REPOSITORY_ROOT IDENTITY NEW_REVISION FILE_PATH
```

Repeat `--candidate` for the pages the integrator explicitly selects; use
`--index` when the folder used a non-default index. The retained request,
recorded result, local instructions, selected source file, source locator and the
selected file's Git receipt are revalidated. Other repository selections in the
request are not revalidated by this comparison. A changed file and a candidate's current requirement on the
selected source page can produce `review_pending`. Whether that interpretation
actually consumed the Git file remains `unknown`; unselected pages are not
inspected, coverage is partial, and no review or fact verification is claimed.
These are nonblocking suggestions for manual triage; they do not change a gate
or assert that a factual update is necessary.
The caller supplies the repository selection under the host's actual permissions;
the configured origin is not an access grant. Source files exceeding 16 MB
cannot be revalidated by this diagnostic.

Local-folder results use the existing cache under a `local-folder` subdirectory;
recording them requires the current source and folder to be revalidated. Results
written through the legacy unrequested bypass stay in the legacy cache and do
not satisfy a local-folder request. Earlier results in the shared legacy cache
remain intact but are not evidence for the new local entry; re-record after the
selected inputs are checked. Existing legacy and approved v1 caches retain their
previous paths. This separation is not an ACL against a process with filesystem
access. The existing cache-summary command reports the legacy root only; its
file count does not include `local-folder` results.

The ingestion response names the retained request. Record each result with the
same explicit source, folder, index and limits; the CLI selects the matching
request and revalidates the inputs. Git-bound recording additionally requires
the exact `--request`. For consolidation, select that request with
`wiki_consolidate.py --source SOURCE_ID --request REQUEST_PATH --emit-event
--source-ref SOURCE_PAGE_ID` (add `--packet` when needed). Each interpretation
has its own event and gate state. For local requests, pass `--candidate PATH`
for each candidate page to inspect; an empty list is allowed. The packet marks
that its coverage includes only those candidates and performs no global catalog
or FTS search. Legacy consolidation keeps its global catalog and search, and
requires corresponding host access. Neither a folder selection nor a request
identifier grants access. GC
preserves contextual requests, their packets and matching source captures for
explicit review. The request and result formats used by approved v1 remain
unchanged. Earlier prototype local requests and results remain on disk; their
folder binding is not silently upgraded to the new identity, so consolidation
reports them as requiring re-emission. Re-prepare and re-read a new request
when adopting the new binding.

Local events and packets retain each selected Git file's configured identity,
commit, path, blob and content hashes. The configured identity is not remote
authentication. They also retain the complete source SHA-256 from the request;
the source capture manifest link is a local, potentially gitignored reference for
authorized consultation. Local events omit capture and verification dates when
those dates are not bound to the selected request; the event update date is not
evidence that the source was captured or verified on that date. The local gate
checks canonical event names for a request and rejects duplicates among those
names; it does not scan other owners for renamed copies. The separately
authorized global audit checks for duplicate page IDs.

The shared source manifest retains the context recorded for its first capture.
A global catalog filtered by that field can therefore omit another interpretation
of the same source; it does not establish complete coverage for that context.
Quality telemetry reports physical chunks once and interpretation calls separately.

## Recoverable blockers

For the host-bound CLI, a handled `--source-stage` preparation failure returns
exit code 1 and a JSON blocker; argument parsing errors can return exit code 2
without that JSON. The separate working-tree `wiki_ingest.py` returns exit code
2 when it reports a blocked preparation. When present, structured blockers use
the [task-result contract](../schemas/wiki-task-result-v1.schema.json): action,
target, sanitized reason, owner, required action, interface, status and resume
condition. They do not establish that a login is required.

The operating agent follows the [context-reading skill](../../../.skills/wiki-llm-context-agent/SKILL.md):
use the harness's real native question or approval interface when available,
return the same blocker to the coordinator, and resume only after the stated
condition is supported. A headless caller without an approval interface leaves
the dependent step pending and continues only independent authorized work.
No response, timeout or configuration declaration fabricates consent.
