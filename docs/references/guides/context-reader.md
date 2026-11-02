# Revision-bound context reading — phase 1

The [repository reader](../../../wiki_core/repository_reader.py) reads regular
UTF-8 Git blobs from one commit, independently of a cockpit snapshot. Use it
for an explicitly scoped local lookup. Use the [context policy CLI](../../../scripts/wiki_context.py)
when preparing a packet under an approved context manifest. Both are read-only;
preparing content does not prove that an agent read it or authorize execution.

| Route | Content selection | Authority and limits |
| --- | --- | --- |
| [wiki_read.py](../../../scripts/wiki_read.py) | Required revision, mode and exact allowed paths; section, field or explicit whole document | The local caller supplies scope. The raw reader does not enforce context policy. |
| [wiki_context.py](../../../scripts/wiki_context.py) | Approved context, explicit evidence paths and byte budget | Current trusted policy authorizes each selection; inherited mandatory bodies accompany evidence. |
| [wiki_coordination.py](../../../scripts/wiki_coordination.py) with a profile | Assigned action and its configured context at the selected revision | Legacy coordinator mapping remains a compatibility adapter without context-policy enforcement. |

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

See the [synthetic hierarchy](../../../examples/context-hierarchy/README.md) for
the directory manifests and inheritance rules. The [manifest schema](../schemas/wiki-context-v1.schema.json),
[packet schema](../schemas/wiki-task-context-v1.schema.json) and
[result schema](../schemas/wiki-task-result-v1.schema.json) define the v1 contracts.
The example manifests are inert `context.example.yaml` templates. To run the example, copy them into a separate synthetic Git repository at their documented paths, rename them to `context.yaml`, and commit them there. Never activate them as a second root within a production root; adopting any production policy requires normal review.

In that isolated synthetic repository, after setting its test-only trusted reference, replace the kit path, revision and request placeholders below with your values:

```sh
python3 /path/to/wiki-viva-kit/scripts/wiki_context.py --repo . --approved-revision APPROVED_SHA \
  --manifest examples/context-hierarchy/context.yaml resolve finance/tax
python3 /path/to/wiki-viva-kit/scripts/wiki_context.py --repo . --approved-revision APPROVED_SHA \
  --manifest examples/context-hierarchy/context.yaml pack finance/tax \
  --content-revision CONTENT_SHA --request REQUEST.json
```

The loader requires the supplied policy SHA to match the current trusted
`refs/remotes/origin/main`. An independent approval process must maintain that
ref; choosing or naming a commit is not a grant. Policy and inherited mandatory
instruction, skill and template bodies come from the current approved revision,
even when evidence comes from an older content revision. A stale policy object
or changed trusted ref fails closed. A byte digest identifies selected bytes;
it establishes neither source freshness nor current external facts.

Policy classes declare read, write, capability and publication boundaries.
The policy code checks those declarations; operating-system and service
enforcement belong to the caller's adapter. Adapter identity, permissions and target verification
remain caller trust boundaries. Packets deliver selected text, provenance,
explicit read sets and incomplete coverage. The complete canonical UTF-8 JSON packet, including metadata and digest, must
fit its maximum byte budget; selected-text bytes are accounted for separately.
Overflow is an error. Dynamic query fingerprints are refused by the
approved packet builder in this phase, even though the raw reader can enumerate
an explicitly scoped catalog.

## Coordination and ingestion

For a configured coordinator, replace the profile and action placeholders:

```sh
python3 scripts/wiki_coordination.py --profile PROFILE --action-id ACTION_ID \
  --revision CONTENT_SHA
python3 scripts/wiki_llm_context_pass.py --source SOURCE --context SOURCE_CONTEXT \
  --approved-revision APPROVED_SHA --policy-context CONTEXT_ID --emit-request
```

Profile context reads use the pinned Git reader without building a global
snapshot. The existing coordinator map remains current local configuration;
`--revision` selects content and does not make that map an approved manifest.
The legacy web reader, route index and dialogue-write flow still use snapshots.

LLM request construction includes actual mandatory policy and required perspective
bodies, so changed content under the same ID changes interpretation identity.
Without `--approved-revision`, it uses the explicitly labelled working-tree
compatibility package. With that flag, `--policy-context` is required; missing,
invalid or revoked policy fails without falling back to compatibility. Required
perspective IDs are resolved only among permitted paths owned by the selected
context; imported IDs require explicit connection handling. The Python ingestion
pipeline accepts the matching `approved_revision` and `policy_context` keyword
arguments. The [wiki_ingest.py CLI](../../../scripts/wiki_ingest.py) does not
expose those opt-in flags in this phase.

The [synthetic CLI regression](../../../tests/test_coordination.py) compared
serialized output on the same fixture: 27 snapshot payloads totaling 45,766 bytes
versus one context packet of 2,554 bytes, with zero files written. This measures
that fixture's output only; it makes no token, latency or source-freshness claim.
