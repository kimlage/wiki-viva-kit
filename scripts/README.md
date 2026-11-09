# Wiki command-line tools

The tools provide deterministic orchestration; contextual reading is delegated
to the operating agent. Effect scope is command-specific: local lookup and
inspection differ from source refresh and artifact publication, which can
contact external services. Use the [existing task entry points](#task-entry-points)
to choose a read or write route, and `--help` for exact flags. A command name
does not grant account access or permission to apply its effects.

## Task entry points

Choose the existing entry point by the intended task. The labels below are
not new commands or services. Read the checkout instructions and configured
memory index first; retain any stronger consumer context requirement.

**Drive artifact publication is suspended.** `wiki_drive_publish.py` refuses
all publication and manifest writes before authentication or network access;
its `--dry-run` only inspects local files and cannot verify remote state. This
also affects consumers after C1 sync. Existing Drive objects and manifests are
not migrated or reconciled by the sync. The concurrency and interrupted-effect
work remains open in [issue #234](https://github.com/kimlage/wiki-viva-kit/issues/234).

| Task | Existing entry | Scope and next step |
| --- | --- | --- |
| Find | [wiki_find.py](wiki_find.py) | Search the existing lexical index, or use `--path` for explicit local selections. Read origin and coverage gaps before treating results as evidence. No index or model is started. |
| Context | Use [wiki_read.py](wiki_read.py) for a scoped Git read, [wiki_context.py](wiki_context.py) or the approved mode of [wiki_coordination.py](wiki_coordination.py) for an explicit task packet. | Choose explicit paths and revisions; follow original evidence. Local folder preparation is a separate route described in [bounded ingestion](../docs/references/guides/bounded-ingestion.md), not an approved packet. The profile packet path is retired; the operator index remains `caller_trust`. See [context operation](../docs/references/guides/context-operation.md). |
| Source | Use the existing source workspace, `GET /api/sources` for identity/location and `GET /api/sources/{source_id}/operations` for receipts, described in [source access](../docs/references/guides/source-access-and-ingestion.md). | Inspect retained identity, location and receipts first. [Refresh preview/run](../docs/references/guides/source-refresh-cadence.md) may contact external systems and requires the existing account and authorized scope; an unavailable original is an explicit gap. |
| Action | Open the same [board card](../docs/references/guides/native-action-board.md). Use its existing transition/dialogue writer for allowed local changes; reconcile retained agent results through [contributions](../docs/references/guides/agent-contributions.md). | Keep the same action and origin run/effect references; revalidate its current revision before writing. A received-result comment has its own event identity, does not consume the contribution effect, and does not incorporate its factual proposal. Other documents, rules or required generators use the existing normal multipage proposal with review and gates. |

A lookup reports candidates, not current truth or absence. Claims about current
state need relevant source verification; absence and totals need explicit
coverage. Local writers retain authorization, live admission where applicable,
revision checks, STOP/terminal rules, idempotency and review. A local change is
not an integrated or served result. See [coordination](../docs/references/guides/context-coordinators.md)
for handoff and recovery; inspecting a result does not require redispatch.

## Primary lifecycle

For direct local lookup, use [wiki_find.py](wiki_find.py):

```sh
python3 scripts/wiki_find.py "release review" --context system --limit 10
```

It reads the existing FTS index and reports provenance for each hit. It
distinguishes no matches from a missing or invalid index. Context is filtered
before the result limit, using current local metadata; unresolved identities
remain explicit gaps. Legacy index coverage/revision and factual freshness
remain unknown. This command creates no index, request, cache or model call.
Context selects retrieval results; account and session controls govern access.
An index configured for WAL is reported as unsupported instead of creating
SQLite sidecars or silently ignoring uncheckpointed data. Its journal mode is
never changed by lookup.

For a task with explicit local selections, repeat `--path` for each folder or
file, for example `python3 scripts/wiki_find.py "release review" --path memories/project`.
This reads selected UTF-8 Markdown/text files directly, using case-insensitive
substring AND matching; it does not open the global catalog or SQLite index.
Nested Git repositories and symbolic links are excluded; an explicitly selected
path across either boundary is refused. Results report partial coverage and do
not establish freshness, authorization or that any agent read a source. A path
selection is subject to the host process's actual permissions. Up to 16 paths,
1,000 files, 1 MB per file and 8 MB in total are accepted; traversal is also
bounded. The full selected set and sizes are checked before reading bodies;
reading stops at the hit limit and reports the number of unread files. Errors
in their contents cannot be detected without reading them. Select an independent
repository through its own explicit read flow.
Use [wiki_build_index.py](wiki_build_index.py) explicitly when a rebuild is
needed. The `--context` option on [wiki_llm_context_pass.py](wiki_llm_context_pass.py)
describes a delegated reading request; it does not filter that command's query.

```text
wiki_ingest.py -> wiki_llm_context_pass.py -> wiki_consolidate.py
  -> wiki_operation_compile.py / wiki_input_stage.py
  -> wiki_semantic_inventory.py / wiki_web_snapshot.py -> wiki_audit.py
```

## Revision-bound context

[wiki_read.py](wiki_read.py) requires `--revision`, `--mode` and exact
`--allow-path` values; reads require `--section`, `--field` or explicit
`--whole-body`. [wiki_context.py](wiki_context.py) resolves a physical context
or builds a bounded packet under the approved `wiki.config.yaml` access policy
with `--approved-revision` and a separate `--content-revision`. A `resolve`
result does not qualify the context. The caller supplies the trust boundary; selecting a
revision does not grant access. [wiki_coordination.py](wiki_coordination.py)
has separate approved packet flags (`--context-id`, `--approved-revision`,
`--revision`, `--packet-request`) while profile reads return a migration response without content.
The protected local API additionally requires a host binding and an authenticated
operator session. See [protected coordination](../docs/references/guides/context-coordination-protected.md).
The [context reader guide](../docs/references/guides/context-reader.md)
explains historical evidence, current policy bodies, ingestion flags and
unsupported selections. Optional owner-only `queries` bind dynamic sets to an
existing collection contract, with explicit read/enumeration/match limits; see
[dynamic selection](../docs/references/guides/context-dynamic-selection.md).

## Bounded canonical ingestion

[wiki_ingest.py](wiki_ingest.py) and [wiki_llm_context_pass.py](wiki_llm_context_pass.py)
retain the working-tree compatibility route. Their approved-v1 flags are refused
for new operations, including recording and checks; existing artifacts are
preserved. For an approved folder-policy source use the existing
[wiki_coordination.py](wiki_coordination.py) `--source-stage` interface or the
in-process host-bound stages. Those stages use v5, include context with the
source chunks and check the full canonical request budget before persistence.
Approved failures do not fall back to compatibility. See [bounded ingestion](../docs/references/guides/bounded-ingestion.md)
for payloads, trusted caller boundary, formats and coverage.

For a separately authorized local entry, `--folder` selects the physical
instructions and index instead of an approved-policy packet. The guide documents
the distinct recording and consolidation selectors, explicit independent Git
reads and partial coverage. The two routes cannot be combined; an approved-route
failure never silently falls back to local preparation.

[wiki_context_flow.py](wiki_context_flow.py) reads canonical requirements for
impact by selected content/revision and independently preflights proposals.
Its `revalidate --context OWNER --consumer PATH` reports current dynamic-set and
selected-byte equivalence under approved authority, separately from fact freshness.
See [context impact and integration](../docs/references/guides/context-impact-integration.md):
requirements stay on the canonical page; no additional graph/queue, approval or
merge is performed automatically.

[wiki_template_sections.py](wiki_template_sections.py) previews an opt-in modular
section contract on a trusted working tree; it does not prove approval or access.
[wiki_context_schedule.py](wiki_context_schedule.py) currently blocks folder-policy
requests before opening them because trusted binding and requalification are not
yet connected. It installs nothing and never admits an effect. See
[modular sections](../docs/references/guides/modular-template-sections.md) and
[context schedule advice](../docs/references/context-schedules.md).

## Source identity and index reconciliation

[Ingestion](wiki_ingest.py) identifies new captures by normalized origin and
content digest. Repository-relative locations survive a checkout move;
external file locations and exact URLs remain distinct. A URL is a locator,
not proof of account identity. Legacy captures keep their original identifiers.
Explicit-source checks and [cache inspection](wiki_cache_inspect.py) discover
them only when the retained manifest proves the same location and digest.

Incremental indexing and [rebuild](wiki_build_index.py) select the latest
complete, timestamped observation of each proven origin. Ties and observations
without ordering evidence remain ambiguous. Observation time is neither a
provider revision nor factual freshness. Incomplete retries cannot overwrite a
complete capture of the same bytes. The ingestion result exposes index gaps;
missing prior artifacts are preserved in the incremental index and reported,
while an explicit rebuild retains its existing orphan-removal policy.

## Downstream kit sync

[wiki_sync_from_kit.py](wiki_sync_from_kit.py) is the supported orchestrator:

```sh
python3 scripts/wiki_sync_from_kit.py \
  --kit /path/to/wiki-viva-kit --consumer /path/to/consumer --dry-run
python3 scripts/wiki_sync_from_kit.py \
  --kit /path/to/wiki-viva-kit --consumer /path/to/consumer \
  --c3-command "python3 scripts/consumer_migration.py"
```

`--dry-run` is B0 and never mutates. Apply performs C1 kit-owned sync, C2
generators, explicit C3 and writes `kit.lock`. It is idempotent and does not
copy consumer memory/configuration or private evidence.

The old lane/capsule/attestation runner and migration receipts are retired and
removed. Frozen `upgrade-package.yaml` is historical documentation only.

## Synthetic hosting preview

[wiki_vercel_preview.py](wiki_vercel_preview.py) prepares an opt-in, read-only
Vercel function bundle from the committed public demo. It accepts no consumer
memory or private-data override and never deploys or changes authentication.
Build the cockpit first, then run `--demo --out tmp/vercel-preview` with a new
directory. See the [deployment template guide](../docs/references/templates/deploy/web-cockpit/README.md)
for the routing contract and separate provider-protection checks.

## Privacy

Private consumer PII is valid. Use `wiki_audit.py --public-export --check` at
public boundaries. Access secrets are blocked everywhere.

The [standalone action board](../docs/references/guides/native-action-board.md)
is served by `wiki_web_server.py --frontend`; it does not require a native host.
The retired Hermes installer is retained in Git history only.

[wiki_coordination.py](wiki_coordination.py) reads the caller-trust operator index, records exact-path dialogue and prepares explicit approved context packets without dispatching agents. See [context coordinators](../docs/references/guides/context-coordinators.md).

[wiki_contribution.py](wiki_contribution.py) prepares and reconciles independently
reviewed action-body proposals with optional local agents. See the
[provider-neutral contribution contract](../docs/references/guides/agent-contributions.md)
for Git policy gates, conflict handling and adoption coverage.

[wiki_page_graph.py](wiki_page_graph.py) reports authored dependencies and
exact-base impact. See [scoped freshness](../docs/references/freshness-impact.md)
for reasoned documentary-only edits and conservative source review.


## Context-bound reading and directory captures

Contextual reading reuses a recorded result only when the chunk bytes, prompt,
model/schema, supplied semantic context and source origin match. The same
validation is used by request generation, checks, recording, audits and
consolidation. A cache file's existence alone is not evidence of reading.
New result packets echo each row's `context_sha256` and `chunk_hash_sha256`;
batch export includes the same contextual envelope. Legacy results stay on disk
as history and do not satisfy a newly bound request. No cache migration, source
refresh or model call happens implicitly. The binding covers the supplied
packet, not source freshness or independently verified account permissions.

Directory source identities hash visible regular-file paths and content, not
file sizes or checkout timestamps. Dotfiles remain excluded; unreadable entries
and symbolic links fail explicitly. New captures can receive a different ID;
existing manifests and references are preserved.

## Optional local operator

The [local operator guide](../docs/references/guides/local-operator.md) describes
read-only discovery, effect-specific sessions, finite proposals and opt-in
execution. External agent adapters and source-review jobs default to disabled;
reader/context/ingestion CLIs do not require a resident process or scheduler.
