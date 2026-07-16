# Wiki command-line tools

Every `wiki_*.py` command is deterministic and local. Contextual LLM reading is
performed by the operating agent, never by an embedded client. See the
[command reference](../memories/system/wiki/command-reference.md) and use
`--help` for exact flags.

## Primary lifecycle

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

## Privacy

Private consumer PII is valid. Use `wiki_audit.py --public-export --check` at
public boundaries. Access secrets are blocked everywhere.
