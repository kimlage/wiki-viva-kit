# Bounded ingestion requests

[wiki_ingest.py](../../../scripts/wiki_ingest.py) is the canonical source entry
point. It extracts and scans in memory, prepares the complete LLM request and
checks its budgets before writing artifacts, indexing, scoring or advancing a
stream cursor. A blocked attempt preserves prior artifacts and never emits a
partial request or a successful-reading receipt.

```sh
python3 scripts/wiki_ingest.py --root . --source SOURCE --context SOURCE_CONTEXT \
  --approved-revision APPROVED_SHA --policy-context CONTEXT_ID \
  --context-max-bytes 100000 --request-max-bytes 256000
```

Replace the placeholders with the authorized source, source classification,
current trusted approval SHA and explicit policy context. The approval loader
revalidates the configured trusted Git reference. Choosing a SHA or context
name does not grant account access or enforce a harness sandbox. See
[revision-bound context reading](context-reader.md) for that trust boundary.

| Limit | Default | What it measures |
| --- | --- | --- |
| `--context-max-bytes` | 100,000 | Complete canonical JSON of the context package, including mandatory bodies, selected evidence, provenance and its digest. |
| `--request-max-bytes` | 256,000 | Complete canonical UTF-8 request: prompt, context, every chunk, identities, limits, accounting and final newline. |

Both limits must be positive integers. They are byte limits, not a token-window
estimate. Each harness must choose an authorized ceiling compatible with its
actual model window and other instructions. No quota or provider capacity is
queried automatically. The emitted JSON uses the same canonical serialization
as the measured bytes; `byte_accounting.request_bytes` is the actual file size.

Required context appears once per request, shared by all chunk rows. The source
text is delivered intact through its extracted chunks, including intentional
chunk overlap. Mandatory rules, evidence and source chunks are never silently
truncated to fit. An oversized source requires an explicit smaller source or
stage, or a separately authorized budget change. This version does not invent
a minibatch scheduler or claim that a selected subset covers the original
source.

## Source admission and task-local routing

Approved mode authorizes a literal regular repository-local source before stat,
hashing, extraction or source catalog lookup. Symlinks, escapes and excluded
credential paths fail. The current source owner and effective read scope must
permit it; an imported source also needs the exact bilateral connection with
`use: interpretation` and `classification: source`. These values appear in the
request's `source_authorization`; they are not wildcard grants. A URI or file
outside the repository needs previously authorized staging/adapter evidence;
this CLI currently accepts staged local files and returns a blocker for the
unsupported external path instead of copying it or inventing a login need.

The caller revalidates current authority and captured source hash before the
next persistence/delivery boundary and before recording, including captures
with no extracted chunks. A changed or revoked
input cannot create chunks, cache results, score or a cursor update through a
new blocked attempt. Prior complete artifacts remain intact.

Approved routing selects the configured root and explicit `config_ref` and
`input_channel_ref` from pinned, authorized context inputs. Perspective and
channel IDs resolve only inside permitted owned paths. It does not run the
global input-stage compiler, reverse-discover all other fronts or include the
generated input-stage body as a mandatory rule. Routing coverage is explicitly
limited to these references; the coordinator must resolve missing required
routing or connections. The context manifest's selected instruction, skill and
template files are delivered as actual text, alongside the applicable root,
channel, source configuration and required perspective bodies.

`--root-entity-ref PATH` selects an explicitly authorized business-root page
for this context, without inheriting another business root's lens bundle.
Alternatively `--omit-root-entity` explicitly omits only the business root and
records missing coverage in the packet. Neither flag grants access or waives
mandatory instructions, skills or templates from the approved lineage. An
explicit external root, channel or source configuration still needs its exact
current authorization. If the task's objective needs an omitted root, the
caller must return a blocker before making that decision. No omitted packet
claims complete context.

These guards constrain this wrapper's declared reads at its validation fences.
They are not a sandbox for arbitrary process I/O and do not grant permission
to operational caches. The trusted caller/harness must independently authorize
its artifact/cache locations and any external adapter or tool effects.

A coordinator with global authority may route using the full map. A scoped
executor uses the validated packet/local map and selectors it received. Links
do not grant additional scope, and a packet hash does not prove approval or
coverage completeness. See the [router](../../../.skills/wiki-memory-router/SKILL.md).

## Recording and revalidation

Use the same source, policy context, current approval and limits when recording
an approved result:

```sh
python3 scripts/wiki_llm_context_pass.py --root . --source SOURCE \
  --context SOURCE_CONTEXT --approved-revision APPROVED_SHA \
  --policy-context CONTEXT_ID --context-max-bytes 100000 \
  --request-max-bytes 256000 --record-result RESULT.json
```

Copy each row's exact cache key, source/chunk identities and contextual hashes.
The caller rebuilds the current request before accepting an approved recording
and opens only that source's exact origin-qualified capture and request paths.
Compatibility capture discovery and global request inspection remain separate
trusted legacy paths; this does not isolate all operational-cache I/O.
Changed context or limits requires a newly emitted and read request; a retained
request above a smaller current ceiling cannot satisfy it. Approved query mode
and unrequested-result bypass are refused. Absence, revocation and budget
failure never select a compatibility fallback.

Approved ingestion requires the installed `context_deep_read.v4` prompt. Older
v1–v3 prompts retain their historical unbound recording commands and remain
available only in working-tree compatibility mode. A consumer explicitly pinned
to an older prompt must configure v4 as a consumer-owned migration. Re-emit and
read a fresh request: v4 has a distinct prompt version and context identity, so
prior results remain inspectable but cannot satisfy the new request. A missing
v4 prompt or an unknown version blocks approved preparation without fallback.

Without approved-context flags, the existing working-tree adapter remains
explicitly labelled compatibility. Historical envelopes remain inspectable;
new requests bind the explicit limits as well as the delivered interpretation
context. Compatibility is not evidence of approved policy or source freshness.

For a local folder entry, start in the nested directory or select it explicitly
with `--folder FOLDER`; paths are relative to the wiki root. The request includes
the physical ancestor `AGENTS.override.md`/`AGENTS.md` chain and the selected
nearest context's `index.md`, or `README.md` when no `index.md` exists. An implicit context has both its own nonempty
instructions and an index; an auxiliary folder still contributes any physical
instructions along the way. A child with only an index does not become a new
context. Use `--index PATH` to select an index in a qualified context folder;
the root requires an explicit index. Missing instructions or index, symlinks and
nested Git roots block preparation. A selected folder cannot be mixed with
approved-policy arguments. Automatic discovery does not select the root index;
choose it explicitly when the root is the intended context. The physical entry
folder and selected index are retained and revalidated before writes.

### Host-bound protected source preparation

The existing in-process host binding can call
`wiki_core.coordination_context.protected_source_stage` for `prepare`, `record`
and `consolidate`, with an explicitly authorized folder, approved revision,
source and artifact owner. The binding is fixed by the host and is not selected
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

This route supports local Markdown, text, CSV, TSV, XLSX, DOCX, EML and PDF
sources up to 16 MB. Extraction consumes the authorized bytes captured in memory;
the extractor does not reopen or stage the source. CSV and TSV require UTF-8,
and email bodies require their declared encoding; invalid encoding is rejected.
Office archives have bounded expanded size and spreadsheet dimensions. Extracted
content from non-text formats is capped at 2 MB. PDF extraction requires the
local `pdftotext` executable, runs with a 30-second timeout, and does not perform
OCR. The extraction reflects the existing format-specific reader, not a guarantee
that every attachment, image, sheet feature or embedded object was interpreted.
Other formats still require an authorized adapter. The complete serialized
request is also capped at 2 MB, which may require a smaller source, particularly
when text needs JSON escaping. Candidates must be explicitly selected.
It does not yet inspect linked sources, read independent Git repositories, expose
an HTTP transport, or incorporate the event in memory. The existing
`wiki_coordination.py` offers the three `--source-stage` operations to a trusted
local operator, with stage JSON on stdin and an explicit context and approved
revision. Its flags are selected by that operator and are not a security boundary
against the operator; a separately configured host binding is the protected
interface. Regular compatibility
search, audit, GC and result recording do not open the reserved new artifacts;
their coverage does not include them. The older shared caches are not migrated
or classified by this route. Their compatibility readers still require separate
review before treating historical approved material as protected. A reserved
name is a routing convention, not an access grant or a filesystem ACL.
Approved folder ownership recognizes `index.md` and `README.md` as stable
conventions, with `index.md` taking precedence. An explicitly named custom
index is usable within an already recognized context; a folder containing only
a custom index does not define approved ownership and requires requalification.
The selected index is not an access grant.

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

Preparation failures return exit code 2 and structured blockers using the
[task-result blocker contract](../schemas/wiki-task-result-v1.schema.json):
action, target, sanitized reason, owner, required action, interface, status and
resume condition. They contain no denied-path inventory or source excerpts.
A missing context does not establish that a login is required.

The operating agent follows the [context-reading skill](../../../.skills/wiki-llm-context-agent/SKILL.md):
use the harness's real native question or approval interface when available,
return the same blocker to the coordinator, and resume only after the stated
condition is supported. A headless caller without an approval interface leaves
the dependent step pending and continues only independent authorized work.
No response, timeout or configuration declaration fabricates consent.
