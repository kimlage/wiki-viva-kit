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
folder's `index.md`. Use `--index PATH` to choose another index inside the folder;
the root requires an explicit index. Missing instructions or index, symlinks and
nested Git roots block preparation. A selected folder cannot be mixed with
approved-policy arguments. Starting inside an auxiliary directory without its
own index requires explicitly selecting the intended context folder.

This is local context preparation, not proof of native instruction discovery,
an ACL or a sandbox. The selected entry reads its instructions and index without
opening the global source catalog or block world. Source configuration, linked
sources and other context remain unresolved; links do not grant access. The
source must be an explicitly selected regular file inside the wiki or a URL;
access-bearing URLs are refused, and independent repositories require a separate
authorized selection not implemented by this entry. Folder ingestion does not
update the global search index or score event. Filesystem checks do not prevent
concurrent replacement. Until contextual
capture reuse is implemented, a folder ingestion refuses to replace an existing
capture or request for the same source; a repeated explicit request emission
also preserves the prior file. If local persistence fails, `written: false`
means persistence did not complete; `partial_effects: unknown` warns that
partial effects may exist and require inspection before retrying. Folder entry
does not provide scoped query search.

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
