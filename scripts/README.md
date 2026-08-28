# Scripts

Command-line entry points for operating the wiki viva kit.

The scripts wrap deterministic behavior from [wiki_core](../wiki_core/README.md):
ingestion, audit, source registry, operation cockpit, quality reports, PR
summaries and format conversions. They do not call an LLM directly; model
reading remains delegated to the agent running the repo.

Use [wiki_audit.py](wiki_audit.py), [wiki_input_stage.py](wiki_input_stage.py),
[wiki_operation_compile.py](wiki_operation_compile.py) and
[wiki_pr_summary.py](wiki_pr_summary.py) as the default PR gate surface.

Use [wiki_sync_from_kit.py](wiki_sync_from_kit.py) to preview and apply the
portable kit-owned layer to a downstream consumer:

```sh
python3 scripts/wiki_sync_from_kit.py \
  --kit /path/to/wiki-viva-kit --consumer /path/to/consumer --dry-run
python3 scripts/wiki_sync_from_kit.py \
  --kit /path/to/wiki-viva-kit --consumer /path/to/consumer \
  --c3-command "python3 scripts/consumer_migration.py"
```

The dry run is B0 and never mutates. Apply performs C1 managed-file sync, C2
deterministic generators, explicit consumer-owned C3 commands and then writes a
portable `kit.lock`. It refuses a dirty consumer unless the operator explicitly
supplies `--allow-dirty` after reviewing the plan.

Use [wiki_quadrant_contract.py](wiki_quadrant_contract.py) when an external
consumer needs the canonical Wilber/AQAL `q1/q2/q3/q4` mapping without scraping
templates or historical proposals.

Use [wiki_web_snapshot.py](wiki_web_snapshot.py) to generate the local/static
JSON read model for the web cockpit, and [wiki_web_server.py](wiki_web_server.py)
to run the localhost-only operator API with allowlisted commands.
Use [wiki_web_deploy_bundle.py](wiki_web_deploy_bundle.py) when one
implementation needs portable static deploy inputs plus a deployment proof
without choosing Vercel, GCP or any other host inside the core kit.
