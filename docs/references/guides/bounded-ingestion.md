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

## Experimental folder-bound ingestion

A trusted local coordinator configures the host root and allowed folders at
startup, then explicitly selects a folder, its index and intended output:

```sh
WIKI_FOLDER_INGEST_HOST_ROOT="$(pwd)" WIKI_FOLDER_INGEST_HOST_FOLDERS="FOLDER" \\
  python3 scripts/wiki_ingest.py --root . --source SOURCE --context SOURCE_CONTEXT \\
  --approved-revision APPROVED_SHA --folder-context FOLDER \\
  --folder-index INDEX --folder-output OUTPUT --dry-run
```

All four folder-mode selections are required and cannot be combined with the v1
`--policy-context`. The trusted host supplies the root and folder allowlist
separately from the request; a flag or environment variable is not an access
grant or actor authentication. The host needs actual permission to
read the complete source and context files. The source must be a staged local
file; files inside independent Git repositories require explicit repository
selection, not this wiki ingestion path. The approved Git context is pinned to
the current trusted revision, and the source is rechecked before persistence.
The dry run returns its summary without writing an inspectable request file;
omitting `--dry-run` prepares the normal local capture and request artifacts.
The local caller must maintain cooperative custody of the staged source and
repository configuration during preparation; path checks and hash fences do
not provide a filesystem compare-and-swap against concurrent writers.

This experimental route prepares a folder-v2 request without running a model.
For a Git-tracked UTF-8 source, staged bytes must match the approved revision;
the request binds origin, path, revision, hash and whole-source evidence.
For a staged Gitignored RAW file, add `--folder-source-ref SOURCE_PAGE`, an
authorized, approved `source` page with a platform and source locator. The
request binds the approved source page to the local path, hash, origin ID and
chunks as a **caller-selected, unverified association**. It records no Git
revision for the RAW, and external origin and freshness remain `not_verified`;
this does not prove that the local copy matches the provider's object. A RAW
source without that explicit page is blocked. Non-UTF-8 tracked Git sources
need a separately qualified provenance adapter.
Its distinct binding version cannot consume existing v1 cache results.
Existing v1 and working-tree compatibility paths remain unchanged. A known
context omission blocks preparation rather than silently dropping v1 coverage
obligations.
Only a new, currently absent Markdown output in the selected context is
accepted; existing or untracked work, indexes and instruction files are not
valid destinations in this preview. Existing outputs require a prior complete
read and a separately supported result contract.
Required perspectives must currently be explicit authorized paths; unqualified
page IDs require a separate authorized resolution. The selection does not prove
a native session was started in that folder or provide filesystem isolation.

After a human or authorized agent actually performs the reading, record its
result with `scripts/wiki_llm_context_pass.py` using the same source, approved
revision, folder/index/output, byte limits and trusted host binding, plus
`--record-result RESULT.json`. The command rebuilds the current request and
checks source hash and authority again and recomputes the deterministic
extraction and chunks before writing to a separate `folder-v2`
cache namespace. A legacy unrequested entry cannot satisfy that namespace. A matching recorded
result remains a report, not proof that a reading occurred. It does not create
a v2 task-result receipt, integrate canonical memory or bypass a PR gate.

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
