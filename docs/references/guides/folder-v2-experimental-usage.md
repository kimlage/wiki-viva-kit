# Experimental folder context v2: explicit packet, preflight and impact

Field and section selectors limit delivered content; `RepositoryReader` first
loads the entire Git blob. The host must be authorized to read the whole blob.
Selectors do not grant cross-owner access or enforce an ACL.

Historical source reassessment requires the same Git blobs for the current and
historical instruction chain, mandatory references and selected index before
replay. This conservative check rejects even a change outside a selected index
section; it does not assert historical approval or review. Auxiliary historical
content additionally requires matching instruction paths, blobs and ownership
boundaries before old markers are opened.

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

The primary entry points default to folders. Select the context index explicitly;
the request contains the task fields and any exact evidence selectors:

```sh
python3 scripts/wiki_context.py --repo . --approved-revision APPROVED_SHA \
  resolve areas/example --index areas/example/index.md
python3 scripts/wiki_context.py --repo . --approved-revision APPROVED_SHA \
  pack areas/example --index areas/example/index.md --content-revision CONTENT_SHA --request REQUEST.json
python3 scripts/wiki_context_flow.py --repo . --approved-revision APPROVED_SHA \
  preflight --folder areas/example --index areas/example/index.md --base APPROVED_SHA \
  --head PROPOSAL_SHA --branch wiki/example --packet PACKET.json --result RESULT.json
```

`REQUEST.json` is an object with `task_id`, `goal`, `output`, `integrator`,
`max_bytes`, optional `evidence` and optional bounded `queries`. The folder and
index must match the packet at preflight. A v1 packet cannot be relabelled or
silently migrated. Use `--mode v1` explicitly on the same CLIs for their
legacy manifest, IDs and result contracts; see [v1 reading](context-reader.md)
and [v1 impact](context-impact-integration.md). The two modes never fall back
to each other. Read-only folder entry is not a native-session or ACL proof.

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
requires a reported change to the packet's declared output (other authorized
changes still require review),
and requires an exact whole prior read for every changed or deleted existing
output. It blocks changes to instructions, skills, indexes and controls for
separate review. This limited candidate only accepts Markdown explicitly marked
`page_type: claim`; other or ambiguous types fail closed. A new claim may declare
simple current requirements only when each pins the approved Git revision and
matches exactly one explicitly reported packet input, including its selector,
use and classification. An existing claim may retain unchanged requirements
under the same matching rule; changing their values or value types, or deleting
those declarations, is blocked.
Historical, query, normative and unsupported selectors remain blocked. Omitted
use/classification follow `interpret`/`internal`, and declared revision pins must
match the selected current evidence. Any covered result explicitly reports that
freshness was not assessed and legacy receipt migration was not performed.

The preflight reports independent review required, not review performed. A
reported read does not establish execution or factual freshness; it cannot
establish semantic completeness or actual tool isolation.

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

## Prepare a consolidation proposal from explicit recorded results

The default `wiki_consolidate.py --max-age-days N` accepts one JSON object
on standard input containing `request`, ordered `results` and explicit
`page_metadata` (page ID, context, visibility, page date, stale threshold,
source/gate/privacy policies, owner and selected parent). The current authorized
packet must include the page-type registry and claim template as mandatory
references; the preview derives the source ID from the selected canonical source
page and validates the output against that registry. It does not renew a source
date or invent an owner. It does not prove page-ID uniqueness or resolve every
relation outside the selected context; repository audit and review remain
required. The host must
set `WIKI_FOLDER_INGEST_HOST_ROOT` and `WIKI_FOLDER_INGEST_HOST_FOLDERS`; add
`--folder-candidate` for each exact current wiki page that may be inspected.
The preview revalidates the folder packet and reported chunk results, reads only
those authorized pages, and returns Markdown for the exact output plus its
current-source requirement. It does not use the global catalogue or FTS,
write the output, record an observed read, perform preflight, merge or establish
execution. The host needs authority for complete selected blobs. Source age is
an explicit caller input and is not evaluated as factual freshness. The source
guard rechecks the current source hash and authorization; for staged RAW, the
approved source-page association is caller-selected and external origin and
freshness remain unverified. Such a claim carries only capture metadata, not
the RAW text. A selected Git repository contributes only identity/path/revision
and digests to the claim, not its full contents. Preflight requires the exact
recorded contextual request via `wiki_context_flow.py ... preflight
--source-request REQUEST.json` under the trusted host binding, including for
Git-only ingestion. The packet binds the authorization digest and preflight
requires the matching recorded request and every applicable claim projection.
Older folder-v2 ingestion requests without this binding must be reissued; v1
is unchanged. Revalidation does not prove execution or authenticate an
external service; an untrusted party able to replace an entire packet and
result can still fabricate a different generic task. Query preflight does not
grant access or attest execution. To retain a bounded query receipt with an
ingestion-bound task, select queries with `--folder-queries QUERIES.json` when
preparing the ingestion request, then repeat that same selection when recording
the result. Extract the already-bound envelope from the request and supply
both to the query preflight. A query attached after reading cannot establish
that the executor received it:

```sh
python3 -c 'import json,sys; json.dump(json.load(open(sys.argv[1]))["folder_query_packet"],sys.stdout)' \
  REQUEST.json > query-packet.json
python3 scripts/wiki_context_flow.py --repo . --approved-revision APPROVED_SHA \
  preflight --folder areas/example --index areas/example/index.md \
  --base APPROVED_SHA --head PROPOSAL_SHA --branch wiki/TASK \
  --packet query-packet.json --result QUERY_RESULT.json --source-request REQUEST.json
```

Keep both files in an authorized local location; they may contain source text.
The host binding must be configured as above. The preflight reproduces the
query envelope, requires the query observations, and runs the existing
host-bound ingestion checks against its original base packet and recorded
request. Missing or mismatched bindings, requests and results fail closed.
Query scope edits still require separate requalification; neither the query
receipt nor the recorded result proves a semantic read or independent review.

When the query envelope and its reported result are provided to folder
consolidation, the proposed claim records versioned query projections in its
existing `information_requirements`. The query preflight rebuilds the envelope
and compares the projections to the reported selection; it requires them for
an ingestion-bound query. Generic query-only proposals may omit them and then
cannot be discovered as durable query consumers. This records the selection,
not proof that the executor read it. The v2 projection retains its own receipt
identity and cannot be reinterpreted as a v1 receipt.

An explicitly authorized host may select consumers and changed paths with
`wiki_folder_reassessment_v2.py --query-changed PATH --candidate CONSUMER`
and a `--reports` file containing the prior query packet, result and integrated
revision for each matching consumer. The host uses the same root and folder
bindings as ingestion. Only the selected owner and paths are inventoried; an
anchor or scope intersection selects a candidate, including a newly added
member. The narrow historical replay supports one query per supplied report.
Without that report the declaration stays `declared_without_report`; with it,
the comparison stays `review_pending`. Neither state asserts completed review,
execution, freshness or exhaustive consumer coverage.

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
The requirement's use and classification must match the report; omission means
`interpret` and `internal`, respectively, as in the existing requirement flow.
An explicitly pinned consumed revision must also match; an omitted pin is not
invented. A mismatched or duplicate report blocks the preview. Treat report files
as potentially sensitive and keep them in authorized storage.

Coverage is limited to selected authorized paths in one owner and the reports
provided; it does not discover receipts, resolve page IDs, evaluate max age,
requalify historical or query requirements, or automatically cover external
repositories. A missing explicitly selected Markdown source is retained only
as a literal declaration; with an authorized matching report, its assessment
is `blocked_missing_source`. Without a report it stays
`declared_without_report`, without asserting source existence or authority.
Git symlinks, unsupported objects and unavailable selections block with a
separate error, rather than being classified as missing. Unrelated unresolved
targets still block inventory. No ACL, completed read, review or integration
is inferred. The command does not modify interpretations.

For a selected independent Git repository, the same command can additionally
compare reported selections using `--independent-root` (absolute local root),
`--independent-identity`, `--independent-revision` (explicitly selected fixed commit) and
`--independent-path`. The selected wiki source must have `page_type: source`,
`platform: repo`, and a `source_locator` matching that configured origin in
both the current node and the whole node reported by the original packet. Each
explicit consumer report adds `repo_read`: the original output from
`wiki_repo_read.py` for the exact path, earlier fixed commit and selected
field/section. The wiki-node requirement must select the whole node. After
checking the wiki reports and current authority, the command verifies each
reported Git selection locally and compares it with the chosen descendant
commit; no fetch is performed and the chosen commit is not asserted to be HEAD.
A changed selection is `review_pending`, while
an unchanged selection remains `verification_pending`. A missing current
selection is blocked. Consumers without reports remain unverified.

The association between a report and a repository read is caller-reported,
not independent proof the consumer actually read or used the source. Origin
configuration is not authentication, a link is not access, and a field/section
reader loads the whole blob. The caller must be authorized for each Git
repository and whole blob; report files can contain source text and must stay
in authorized storage. This does not create a registry, mutate the wiki or
refresh source dates, and coverage is only the explicitly selected reports.

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

## Internal experiments for later integration

- [Host-bound folder coordination](experimental-folder-host-v2.md) uses an
  explicit trusted host binding for a v2 packet and limited preflight. It has
  no endpoint or default activation and does not establish actor or repository
  identity, ACL, execution or integration.
- [Separate collection anchors](experimental-query-anchor-v3.md) keep the
  selected context index distinct from a query anchor. The isolated v3 format
  is not a migration of historical queries or receipts.
- [Multi-owner v1 requalification](experimental-multi-owner-requalification.md)
  is a caller-trust preview for explicitly selected requirements. Its global
  coordinator requires actual host authority to inspect historical manifests;
  results remain review pending and do not establish historical approval.

These experiments do not migrate active v1 coordination or requirements
consumers. The candidate defaults to [folder-bound ingestion](bounded-ingestion.md#folder-bound-ingestion)
and a folder consolidation proposal; recorded interpretations do not migrate
v1 state or integrate memory. The candidate requires aggregate review and gates
before any separate adoption decision.
