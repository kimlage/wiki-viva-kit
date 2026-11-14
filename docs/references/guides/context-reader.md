# Revision-bound context reading — phase 1

The [repository reader](../../../wiki_core/repository_reader.py) reads regular
UTF-8 Git blobs from one commit, independently of a cockpit snapshot. Use it
for an explicitly scoped local lookup. Use the [context policy CLI](../../../scripts/wiki_context.py)
when preparing a packet for an approved folder context. Both are read-only;
preparing content does not prove that an agent read it or authorize execution.

| Route | Content selection | Authority and limits |
| --- | --- | --- |
| [wiki_read.py](../../../scripts/wiki_read.py) | Required revision, mode and exact allowed paths; section, field or explicit whole document | The local caller supplies scope. The raw reader does not enforce context policy. |
| [wiki_repo_read.py](../../../scripts/wiki_repo_read.py) | Explicit local repository root, configured identity, commit and path | Reads the selected Git revision under the caller's actual permissions; identity and receipt do not grant access. |
| [wiki_context.py](../../../scripts/wiki_context.py) | Approved context, explicit evidence paths and byte budget | Current trusted policy authorizes each selection; inherited mandatory bodies accompany evidence. |
| [wiki_coordination.py](../../../scripts/wiki_coordination.py) with explicit context and approval | Explicit task and selected evidence at approved history | Approved policy and current connection checks apply; see [protected coordination](context-coordination-protected.md). |
| [wiki_coordination.py](../../../scripts/wiki_coordination.py) with a profile | No task bodies | Constant migration response; profile identity supplies no context authority. |

## Local reads and stable sections

From an authorized checkout:

```sh
python3 scripts/wiki_read.py --revision HEAD --mode read \
  --allow-path AGENTS.md --ref AGENTS.md --whole-body
python3 scripts/wiki_read.py --revision HEAD --mode catalog \
  --allow-path memories/index.md
```

Repeat `--allow-path` for additional exact paths. A `page_id` is resolved only
inside those allowed paths. Catalog output contains metadata without body
snippets; filtering precedes delivery. Each invocation resolves its revision
to a commit SHA. Worktree edits do not change the selected Git content.

Use `--section criteria` for a heading-bound marker or `--field title` for an
exact frontmatter field. A marker immediately precedes a top-level Markdown
heading, including its subordinate headings and exceptions:

```md
<!-- wiki:section id=criteria version=1 -->
## Criteria
Apply this condition.
### Exception
Retain this qualifier when selecting criteria.
```

The [CommonMark selector](../../../wiki_core/content_sections.py) ignores fake
markers inside code fences, rejects duplicate IDs and reports missing selectors
without returning the whole document. In this phase, markers inside list or
blockquote containers and documents combining selectors with raw HTML wrapper
blocks fail explicitly. Renaming the heading preserves its ID; editing its
selected content changes the digest. Paths cannot traverse outside the repository,
resolve Git symlinks or select excluded credential paths. These path checks do
not turn a raw reader into an operating-system sandbox.

## Approved packets and historical content

For a new approved packet, the CLI selects the existing `wiki.config.yaml`
access configuration and discovers context identity and parentage from the
approved Git tree. A context folder has instructions and `index.md` or
`README.md`; the latter is selected when `index.md` is absent. An auxiliary
folder can add instructions without defining an owner. A different selected
index works only within an already recognized context. An access entry can
specify owner, scopes, denials and exact connections, but a folder, instruction
or index does not grant access. Missing access configuration grants nothing.
Documentary copies can be excluded explicitly from ownership discovery as
[described below](#documentary-trees-and-context-discovery).

Ordinary `read` scope strings are literal path prefixes: `docs/item.md` also
covers descendants if that path becomes a directory. To limit a read ceiling
to one exact repository-relative path, use `file[docs/item.md]` in the `read`
list; `file[self/item.md]` resolves relative to the context root. This is an
explicit policy form, not a filename or filesystem-type inference. Existing
prefix scopes, inherited denies and exact bilateral connections retain their
rules; the exact ceiling does not grant access by itself. It does not authorize
a directory query or make a statement about symlinks. The form is read-only;
write and deny scopes retain their existing prefix syntax. Older policy engines
reject brackets, so install and qualify the supporting kit before independently
reviewing any consumer policy that uses this form. A candidate cannot authorize
its own installation or normative change. A directory query still needs a prefix
covering its scope; an exact ceiling can authorize its anchor separately. The
query authority digest covers that anchor and the selected scope, not unused
descendants outside that scope. In v1, mandatory references explicitly declared
in the consumer lineage follow their own normative authorization and remain
subject to inherited read denies; evidence between contexts requires the
corresponding bilateral connection. Folder qualification has its own checks.

```yaml
read:
  - 'file[docs/item.md]'
```

For a repository and request you are authorized to use, replace the placeholders:

```sh
python3 scripts/wiki_context.py --repo REPO --approved-revision APPROVED_SHA \
  resolve CONTEXT_FOLDER
python3 scripts/wiki_context.py --repo REPO --approved-revision APPROVED_SHA \
  pack CONTEXT_FOLDER --folder ENTRY_FOLDER --index INDEX_PATH \
  --content-revision CONTENT_SHA --request REQUEST.json
```

For selected evidence owned by another context, a trusted local operator
appends `--trusted-context PRODUCER_CONTEXT` to `pack`; repeat it for each
explicitly selected producer. Current path scopes and exact bilateral
connections are still required. The flag records the operator's selection; a
folder, link or packet does not grant access. See the
[preflight and requirements CLI](context-impact-integration.md) for repeating
the selection during validation.

`resolve` reports the discovered structure with `authorized: false`; it does
not qualify the context or read its instruction bodies. `pack` checks the
physical entry, policy and explicit selection and includes the qualified
instructions and index. The [packet schema](../schemas/wiki-task-context-v1.schema.json)
and [result schema](../schemas/wiki-task-result-v1.schema.json) retain their
versioned contracts. The [synthetic v1 manifests](../../../examples/context-hierarchy/README.md)
and [manifest schema](../schemas/wiki-context-v1.schema.json) describe the
older contract, not a valid `--manifest` argument for new `wiki_context.py`
packets. Historical v1 receipts keep their original identities and revision;
where the original manifest cannot be established they require requalification,
not an assumed mapping to a folder.

The older approved ingestion flags and new packet composition under a v1 host
binding are refused. Configured hosts default to folder mode; an explicitly
selected v1 binding cannot create a new packet and historical checks are
separate. The folder-policy and host-bound source routes have separate entry points; see
[bounded ingestion](bounded-ingestion.md) and
[protected coordination](context-coordination-protected.md).

The loader requires the supplied policy SHA to match the current trusted
`refs/remotes/origin/main`. An independent approval process must maintain that
ref; choosing or naming a commit is not a grant. Policy and selected physical
instruction and index bodies come from the current approved revision,
even when evidence comes from an older content revision. A stale policy object
or changed trusted ref fails closed. A byte digest identifies selected bytes;
it establishes neither source freshness nor current external facts.

Policy classes declare read, write, capability and publication boundaries.
The policy code checks those declarations; operating-system and service
enforcement belong to the caller's adapter. Adapter identity, permissions and target verification
remain caller trust boundaries. Packets deliver selected text, provenance,
explicit read sets and incomplete coverage. The complete canonical UTF-8 JSON packet, including metadata and digest, must
fit its maximum byte budget; selected-text bytes are accounted for separately.
Overflow is an error. Owner-only dynamic collections use the explicit
[anchored query contract](context-dynamic-selection.md); caller-supplied query
fingerprints remain refused. The builder computes and binds selection receipts,
including empty sets, and preserves predicates in canonical requirements.
Nested independent Git repositories are excluded from ordinary wiki traversal.
The local reader uses an explicit selection under caller permissions. Protected
folder source stages can also include exact Git evidence pinned by the trusted
host, subject to separate grants; see [protected independent Git](protected-independent-git.md).
The selection does not authorize access, establish remote identity or prove
file consumption.

### Documentary trees and context discovery

By default, every tracked folder with instructions (`AGENTS.override.md` or
`AGENTS.md`) and a stable index (`index.md` or `README.md`) defines a context.
This includes documentary snapshots outside the memory root. Without a
`context_access` entry, such a context has owner `unassigned` and empty allow
lists. Even a root reader with `read: ["."]` cannot import its documents when
the discovered producer has no read permission.

An approved configuration can exclude an explicitly selected documentary tree
from automatic ownership discovery:

```yaml
context_discovery:
  exclude:
    - docs/references/ext-workspace/tree
```

`exclude` is an optional list of unique, literal repository-relative folder
prefixes. Each prefix suppresses discovered context roots at that path and
below it. The prefix need not itself define a context. It does not match a
sibling such as `docs/references/ext-workspace/tree-other`. Omission or an
empty list preserves default discovery. The root `.` cannot be excluded;
absolute paths, traversal, globs, malformed lists and unknown discovery keys
are rejected. Any `context_access` entry at or below an excluded prefix is a
configuration error, even an entry with no grants. Resolve that conflict in
the reviewed configuration; exclusions never silently override explicit access.

Files beneath the excluded tree belong to the nearest remaining context. In
the example, that is `.` unless another real context contains the tree. Its
read and deny rules still apply, and a different consumer still needs the
normal bilateral connection. This is an ownership change that requires policy
review. Exclusion does not skip Git-path safety checks or content auditing.
Physical instruction files remain in the mandatory chain when a packet enters
their folders. To inspect a documentary file as evidence, enter the intended
real context and select that exact evidence path.

Both discovery and exclusions come from `wiki.config.yaml` at the current
trusted approved revision. Worktree edits and an unapproved branch cannot
activate an exclusion. Historical evidence is checked against its historical
ownership and authorization as well; changing current ownership does not
retroactively authorize an older body. Rebuild affected packets under the
approved configuration and an authorized content revision.

### Read ceilings through the physical hierarchy

For folder policy, `read` and `write` are literal path-prefix ceilings. `self`
expands to the declaring context's folder, while `.` covers the repository.
Every child's allow list must fit inside its parent's corresponding list.
`memories/org/eng` with `read: ["."]` under `memories/org` with
`read: [self]` therefore fails with `child widens read`. This restriction is
intentional: a nested context cannot grant itself authority outside its
ancestor's ceiling. Denials accumulate through the lineage and take precedence.
Missing allow lists in folder access configuration are empty, not inherited
grants.

For an approved broad reader nested under `memories/org`, widen the read
ceiling of every necessary ancestor and keep sibling policies explicit:

```yaml
context_access:
  ".":
    owner: Operator
    policy: {read: ["."], write: [self], capabilities: [], deny: {}, publication: []}
  memories/org:
    owner: Operator
    policy: {read: ["."], write: [self], capabilities: [], deny: {}, publication: []}
  memories/org/eng:
    owner: Operator
    policy: {read: ["."], write: [self], capabilities: [], deny: {}, publication: []}
  memories/org/ops:
    owner: Operator
    policy: {read: [self], write: [self], capabilities: [], deny: {}, publication: []}
```

This synthetic example assumes each named folder is already a discovered
context. The parent now also has a repository-wide read ceiling; the sibling
`memories/org/ops` remains limited to its own subtree. Write ceilings,
capabilities and publication permissions are separate and stay as declared.
None of these read ceilings supplies a missing cross-context connection.
Prefer the smallest required path list when repository-wide reading is
unnecessary. If the parent must retain `read: [self]`, the current hierarchy
cannot express a wider child. A separately reviewed physical context directly
under a sufficiently broad ancestor is an alternative; do not silently change
parentage or permission semantics.

### Exact connections for selected foreign bodies

Repository-wide `read: ["."]` passes the path-ceiling check only. For each
selected body owned by another context, the producer must permit reading it
and both sides must declare an identical, unexpired rule. For example, put
this same rule in `context_access["memories/team"].exports` and
`context_access["."].imports`:

```yaml
from_context: memories/team
to_context: "."
selector: memories/team/report.md
use: interpretation
classification: context
expires: '2099-01-01'
```

The selector is one exact file path. `memories/team` does not authorize files
below it, and globs such as `memories/team/*.md` are invalid. A selected
`section` or `field` must also match on both sides; omitting those selects the
whole document. Use, classification and expiry are part of the agreement.
A missing or one-sided connection stays pending even when both contexts have
broad read ceilings or share the same owner label. Read denials still win.
The root context has no special import bypass.

For a protected packet, enumerate the necessary evidence paths, approve the
matching producer exports and consumer imports, and have the trusted operator
select each producer through the existing host binding or `--trusted-context`.
Producer and consumer qualification also need their authorized mandatory
ancestor instructions and indexes; include the exact connections and path
ceilings needed for that chain. The host selection qualifies the chosen
producer; it does not create grants. A packet then returns only the explicitly
selected bodies and mandatory context inputs within its byte budget. Exact
connections and owner-only dynamic queries do not provide an implicit global
read or directory/glob import mechanism.

## Bounded reads of an owned log

The local folder-bound `wiki_context.py pack --owned-range` route accepts one
explicit evidence item for an existing file owned by the acting context. Its
`ref` must equal the task `output`; it cannot be a context instruction or index.
The request supplies the usual producer, reason, use and classification plus:

```json
{"range": {"kind": "utf8-line-bytes/v1", "start": 0, "end": 42}}
```

Offsets identify the approved Git blob's UTF-8 bytes, with an inclusive start
and exclusive end. Both boundaries must be line boundaries (or the beginning
or end of the blob); at most 65,536 bytes may be selected. The end must be
chosen from the approved file, not from a proposed marker or candidate file.
The caller must independently obtain the offsets through an authorized route.
The `wiki.task-context/v2` packet records those offsets, revision and digest;
the `wiki.task-result/v2` reports the same declared reads. Mandatory context
instructions and indexes are separate, full inputs. V1 clients and the web
route cannot consume this contract. Queries, additional readers, cross-owner
evidence, composite preflight and generated requirements are not supported.

Use `--owned-range` with `wiki_context_flow.py preflight` for the same packet
and result. Both commands require the existing folder coordination host binding
in the environment, including its trusted ref and allowed context; a flag,
packet or selected SHA is not a grant. The preflight reconstructs the packet,
rechecks current and historical authority, confirms the selected bytes at the
approved base and candidate, and requires the approved and proposed log to
preserve their respective prior bytes and the proposal to append new bytes.
It produces only a review candidate; independent review, gates and merge still
apply. No semantic quality or comprehension is established. The Git reader
loads the bounded-size whole blob internally, although only the selected bytes
are delivered as this evidence. This is not a physical partial-read guarantee
or an operating-system sandbox.

For an already authorized local host, an operator can prepare and check the
proposal with the existing files containing the full request, packet and result:

```sh
python3 scripts/wiki_context.py --repo /path/to/wiki --approved-revision "$APPROVED_SHA" \
  pack CONTEXT --content-revision "$CONTENT_SHA" --folder CONTEXT \
  --owned-range --request /path/to/request.json > /path/to/packet.json
python3 scripts/wiki_context_flow.py --repo /path/to/wiki --approved-revision "$APPROVED_SHA" \
  preflight --context CONTEXT --base "$APPROVED_SHA" --head "$PROPOSAL_SHA" \
  --branch wiki/example --packet /path/to/packet.json --result /path/to/result.json --owned-range
```

The environment uses the host's established `WIKI_COORDINATION_ALLOWED_CONTEXTS`
and `WIKI_COORDINATION_TRUSTED_REF`; these are configuration, not evidence that
the operator or runtime has been admitted. Treat request, packet and result
files according to the sensitivity of their contents.

## Coordination and ingestion

For a task packet, select the canonical context and complete request:

```sh
python3 scripts/wiki_coordination.py --context-id CONTEXT_ID \
  --approved-revision APPROVED_SHA --revision CONTENT_SHA --packet-request REQUEST.json
```

Profile reads no longer prepare task content. The route index remains a broad
operator caller-trust projection. Dialogue writes use an explicit action path
and the existing writer fence, without a snapshot or task packet. Read the
complete protected packet; profiles, aliases, references and truncated samples
cannot replace canonical authorization or mandatory bodies.

The host-bound folder source stages prepare, record and consolidate with the
same approved physical context; they do not perform a model call, review or
incorporation. The separately authorized working-tree folder route is not an
approved-policy packet, and neither route silently falls back to the other.
The existing [wiki_ingest.py](../../../scripts/wiki_ingest.py) approved-v1
flags are refused for new operations; local working-tree compatibility remains
separate. The [bounded ingestion guide](bounded-ingestion.md) documents the
available routes, their byte limits, partial coverage and blockers.

The synthetic CLI regression in the kit source checkout (`tests/test_coordination.py`) compared
serialized output on the same fixture: 27 snapshot payloads totaling 45,766 bytes
versus one context packet of 2,554 bytes, with zero files written. This measures
that fixture's output only; it makes no token, latency or source-freshness claim.

## Passive reader coverage

The human reader's opt-in information assessment uses the current page's
explicit operational requirements and the evidence already loaded for those
requirements. It does not recursively authorize or open additional transitive
requirements. If an already loaded prerequisite or its loaded evidence declares
a nonempty requirement list or a link with a valid, unambiguous operational role
recognized by the Markdown parser, the reader reports that transitive requirements
were not assessed and does not mark that direct requirement ready. This is a
coverage limit, not a finding that nested information is false or unavailable.
Ordinary citations and navigation are not treated as operational requirements;
stale, conflicting or unrecognized role markers are not proof of an operational
role and remain outside this detection. A role marker does not authenticate its
author. The passive reader never grants permission; execution and the separate
impact audit retain their own authority and coverage rules.
