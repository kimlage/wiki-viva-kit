# Wiki command-line tools

Every `wiki_*.py` command is deterministic and local. Contextual LLM reading is
performed by the operating agent, never by an embedded client. See the
[command reference](../memories/system/wiki/command-reference.md) and use
`--help` for exact flags.

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
Use [wiki_build_index.py](wiki_build_index.py) explicitly when a rebuild is
needed. The `--context` option on [wiki_llm_context_pass.py](wiki_llm_context_pass.py)
describes a delegated reading request; it does not filter that command's query.

```text
wiki_ingest.py -> wiki_llm_context_pass.py -> wiki_consolidate.py
  -> wiki_operation_compile.py / wiki_input_stage.py
  -> wiki_semantic_inventory.py / wiki_web_snapshot.py -> wiki_audit.py
```

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

[wiki_coordination.py](wiki_coordination.py) reads configured coordinator routes and composes revision-bound context packets without dispatching agents. See [context coordinators](../docs/references/guides/context-coordinators.md).

[wiki_contribution.py](wiki_contribution.py) prepares and reconciles independently
reviewed action-body proposals with optional local agents. See the
[provider-neutral contribution contract](../docs/references/guides/agent-contributions.md)
for Git policy gates, conflict handling and adoption coverage.

[wiki_page_graph.py](wiki_page_graph.py) also has an explicit `--record-review`
mode for the configured documentary pair, using the projector's own trace.
It emits private authoring context, never inferred bindings or freshness approval.
See [documentary authoring](../docs/references/guides/software-change-records.md#authoring-the-complete-consumption-frontier).
