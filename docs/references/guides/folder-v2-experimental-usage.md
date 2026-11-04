# Experimental folder context v2: explicit packet, preflight and impact

This is an isolated candidate for review, not an activated replacement for the
existing context contract. A v2 packet and result cannot be used as v1 receipts;
legacy IDs, queries and `information_requirements` require an explicit migration.
None of these commands approves, publishes, merges, transmits or executes a task.
The caller must have authority to inspect the selected Git repository and must
independently enforce access through its environment and tools.

The v2 loader inspects tracked paths and instruction-file metadata throughout the
repository. It does not read the bodies of unrelated instruction files, but even
path metadata requires an appropriately authorized coordinator. The packet reads
only the applicable physical instruction chain, selected context index and exact
authorized evidence. It does not prove native instruction loading, isolation or
that an agent actually read any of those texts.

## Context and controls

A nested context node has tracked `AGENTS.md` or `AGENTS.override.md` and
`index.md` in the same directory. The root is an instruction context, and its
index is selected explicitly from links declared in its AGENTS. No README is
automatically substituted for a canonical wiki index. The
selected override wins; a nonempty whitespace-only override is conservatively
rejected when read. A directory with instructions but no index can contribute to
the instruction chain, but ownership inside that area remains unavailable until
a deeper indexed context; it is not silently promoted to an owner.

The optional `wiki-context-controls.yaml` contains mechanical restrictions and
connections only. It is read from the exact approved revision, which must match
the local `refs/remotes/origin/main` ref. Other approval refs need a future
trusted-host interface and are not supported by this candidate. Its path is fixed
for this interface: a command-line argument cannot replace the authoritative
controls with a caller-selected file. An absent folder entry denies its reads,
writes and effects. It does not stop independent folder navigation. The project
must decide and review its own controls; the following is synthetic:

```yaml
schema_version: wiki.folder-controls/v2
controls:
  ".":
    policy:
      read: [self]
      write: [self]
      capabilities: []
      deny: {}
      publication: []
    imports: []
    exports: []
  "areas/example":
    policy:
      read: [self]
      write: [self]
    imports: []
    exports: []
```

Controls use repository-relative folder paths to attach limits; parentage,
instructions and IDs are derived from the Git tree. Effective child limits
cannot widen a parent. For cross-context evidence, both contexts must carry the
same producer, consumer, path, purpose, classification, exact section or field,
and expiry in their respective exports and imports. A link does not grant access.
IDs depend on path and are versioned; a move is not a silently equivalent owner.

An AGENTS may declare additional whole normative bodies in a flat link list
under `## Wiki v2: mandatory references`; ordinary links are not declarations.
Their Git-tracked owners must be the context declaring them, and the selected
context's denies apply before the bodies are read. An optional flat link list
under `## Wiki v2: indexes` declares index choices; the caller must select one
and possess the relevant access. Nested contexts may select their conventional
local `index.md`. Neither a declaration nor a role label grants access. A root
coordinator can select a declared global index if authorized; an executor receives
only the index or section authorized for its task, not an inherited global index.

## Compose and preflight

Prepare an explicit JSON array of evidence selectors. For a source in the same
context, an example is:

```json
[{"path":"areas/example/source.md","producer_folder":"areas/example",
  "reason":"review the selected field","use":"interpret",
  "classification":"internal","field":"status"}]
```

Select the current approved policy revision and an explicit content revision.
The content revision must be an ancestor of the approved policy. Current and
historical authority are checked before a historical evidence body is read;
instructions and index come from the approved policy revision. Supply the
trusted output location and integrator explicitly:

```sh
python3 scripts/wiki_folder_packet_v2.py --repo . \
  --approved-revision APPROVED_SHA --content-revision CONTENT_SHA \
  --index areas/example/index.md \
  --max-bytes 20000 --task-id TASK_ID --goal 'Review the source' \
  --output areas/example/result.md --integrator 'independent reviewer' \
  --evidence evidence.json areas/example > packet.json
```

To read only a section of the selected index, pass `--index-section SECTION_ID`.
The section selection is not a new access grant and is recorded in the packet.

`packet.json` can contain private content. Keep it in an authorized local
location and never assume it may be published. The result must use
`wiki.folder-task-result/v2`, bind to the packet digest and report each selected
path, kind, revision, hash and selector in `observed`; those reports do not prove
execution. Once the authorized proposal is on a short `wiki/*` branch, run:

```sh
python3 scripts/wiki_folder_preflight_v2.py --repo . \
  --approved-revision APPROVED_SHA --base APPROVED_SHA --head PROPOSAL_SHA \
  --branch wiki/example --packet packet.json --result result.json
```

The preflight reconstitutes the packet, checks the exact ref and proposed diff,
and requires an exact whole prior read for every changed or deleted existing
output. It blocks changes to instructions, skills, indexes and controls for
separate review. This limited candidate only accepts Markdown explicitly marked
`page_type: claim`; other or ambiguous types and existing/new
`information_requirements` fail closed pending their own integration. It reports
independent review required, not review performed. It cannot establish semantic
completeness or actual tool isolation.

## Bounded current-revision queries

For one to eight finite queries, provide `--queries queries.json` to the packet
command. `--evidence` may also provide exact current-revision inputs, including
the whole prior output needed to modify or delete it. All evidence permissions
are checked before packet replay. The selected index must be read whole, identify
an existing collection contract and be the query anchor. The base packet and
query content must both use the current approved revision. A scope containing
another owner, any intersecting deny, an unsupported Git path or an unqualified
instruction folder is blocked before member bodies are read. Queries whose
packet starts in an auxiliary folder are not yet supported. A synthetic query
array is:

```json
[{"target":"areas/example/index.md","reason":"inspect active entries",
  "use":"interpret","classification":"internal","query":{
    "scope":"areas/example/items","filters":{"status":"active"},
    "field":"status","max_enumerated":100,"max_matches":20,
    "max_scan_bytes":100000}}]
```

The envelope and query receipts use separate v2 schemas and digests, tied to
the base packet. The result must use `wiki.folder-query-task-result/v2`, report
the base inputs, selected query inputs and exact query IDs. Preflight rebuilds
the selection and refuses any proposal touching a query scope or its anchor;
it still returns independent review required. This is conservative: even an
irrelevant in-scope edit requires another review. Selection receipts do not
prove that an agent read the results. The normal selection interface still
blocks historical queries. The separate candidate below covers a narrow,
explicit v2 replay; no v1 digest is relabelled as v2. See the [receipt schema](../schemas/wiki-folder-query-receipt-v2.schema.json),
[packet schema](../schemas/wiki-folder-query-task-context-v2.schema.json),
[result schema](../schemas/wiki-folder-query-task-result-v2.schema.json), and
[preflight schema](../schemas/wiki-folder-query-preflight-v2.schema.json).

## Experimental historical query comparison

This separate, explicitly invoked candidate is under independent review and is
not wired to packet selection, preflight, or automatic consumer discovery:

```sh
python3 scripts/wiki_folder_query_history_v2.py --repo . \
  --approved-revision CURRENT_APPROVED_SHA --integrated-revision OUTPUT_COMMIT_SHA \
  --packet query-packet.json --result query-result.json
```

It accepts one v2 query with a whole index, no auxiliary start, and one reported
output. For modification or deletion the old packet must include the complete
prior output as authorized evidence. Current and historical permissions and
the current instruction chain are checked before replay; changed instructions
or revoked authority block it. The output commit must be an ancestor of the
current approved revision, and matching output bytes or absence must also exist
at that revision. The output is always `review_pending`: this comparison does
not prove who produced the output, that an agent read anything, or that review
or a merge occurred. It does not enumerate consumers, migrate v1 receipts, or
cover more than one query. Other cases remain blocked.

## Selectively inspect consumer declarations

This separate candidate checks paths in one authorized owner before opening
their content. Supply repeated `--candidate` arguments or select a scope:

```sh
python3 scripts/wiki_folder_consumers_v2.py --repo . --approved-revision CURRENT_APPROVED_SHA \
  --folder areas/example --scope areas/example
```

The result reports only canonical `information_requirements` from selected
authorized Markdown files. Scope enumeration excludes other owners, ambiguous
auxiliary folders, instruction and skill files, and unsupported Git objects;
it does not prove global coverage. Resolution is
limited to exact tracked paths and does not search other page bodies for IDs.
File and byte limits apply before opening candidates. Declarations are neither
v2 query receipts nor proof of a read, and this command creates no registry or
automatic requalification. Actual host access remains the caller's responsibility.

## Compare one reported source and consumer

```sh
python3 scripts/wiki_folder_impact_v2.py --repo . \
  --approved-revision CURRENT_APPROVED_SHA --packet packet.json --result result.json \
  --target areas/example/result.md --source areas/example/source.md --field status
```

Use `--section` instead of `--field` for a section, or neither for the whole
source. The command checks current authority for every packet input before
historical replay and compares only the requested selection. A changed selection
returns a review candidate without modifying the interpretation. Equal bytes do
not prove the reported read or integration: the result stays
`verification_pending`. A missing source produces a blocked candidate. The
coverage is one explicitly reported consumption, not a consumer inventory,
complete propagation, or evidence that the reported task actually ran.

## Join a source update to selected consumers

The experimental [reassessment command](../../../scripts/wiki_folder_reassessment_v2.py)
combines the bounded consumer inventory with explicit v2 packet/result reports:

```sh
python3 scripts/wiki_folder_reassessment_v2.py --repo . --approved-revision CURRENT_APPROVED_SHA \
  --folder areas/example --source areas/example/source.md --scope areas/example --reports reports.json
```

`reports.json` is an array of objects with `target`, `section`, `field`,
`packet` and `result`; exactly one of `section` or `field` may be set, or both
may be null for the whole source. Packets and results are complete JSON objects,
not paths. Omit `--reports` to inventory declarations without reported reads.
An exact declared selector without a matching report is `declared_without_report`.
Changed and unchanged reported slices retain the impact command's pending
states; historical, query and unsupported selectors remain explicitly open.
Declared use, classification and consumed revision, when present, must match the
report. A mismatched or duplicate report blocks the preview. Treat report files
as potentially sensitive and keep them in authorized storage.

Coverage is limited to selected authorized paths in one owner and the reports
provided; it does not discover receipts, resolve page IDs, evaluate max age,
requalify historical or query requirements, or automatically cover external
repositories. Missing source paths block inventory, and no ACL, completed read,
review or integration is inferred. The command does not modify interpretations.

## Propose requalification of an explicit v1 requirement

For one canonical, explicitly selected requirement, the CLI currently reports a
blocking condition rather than reconstructing the historic packet:

```sh
python3 scripts/wiki_folder_requalify_v1.py --repo . \
  --approved-revision CURRENT_APPROVED_SHA --folder areas/example \
  --index areas/example/index.md --consumer areas/example/result.md \
  --requirement-index 0 --packet historical-packet.json --result historical-result.json \
  --proposal-head HISTORICAL_PROPOSAL_SHA
```

The index is zero-based. The caller must be authorized to read the supplied
receipt files. The existing v1 loader opens all context manifests, including
unrelated owners; this CLI has neither a scoped historical loader nor a
verified global-host capability. It stops with
`historical_policy_authority_unavailable` before reading historic policy or
source bodies. It does not issue a byte or normative-equivalence result, change
the consumed revision, or convert a page, receipt, approval or authority.
Once an authorized scoped loader exists, the proposal and output must also be
proven against the integrated commit and current owner, read and write limits;
current normative bodies must be compared before claiming equivalence. A role
label or caller-supplied boolean cannot establish access. A reported read
remains a report.
Historical dynamic queries and v1 `authority_digest` are refused with
`dynamic_query_requalification_required` until predicates, universes and
members can be independently requalified in v2.

No durable consumer inventory is created by this candidate. Existing
`information_requirements` remain canonical, but their v1 receipt and authority
semantics are not automatically migrated to v2. General historical query
requalification, exhaustive consumer inventory, native sessions across
independent-repository boundaries, non-query v2 result/review schemas, product
integration and operational session acceptance remain pending.
