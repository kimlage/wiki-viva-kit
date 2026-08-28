---
title: "Wiki Viva v6.10.0"
page_id: release-wiki-viva-v6-10-0
page_type: release_note
context: system
visibility: public_candidate
updated_at: 2026-08-28
stale_after_days: 365
sources_policy: release_note
gate: github_pr
sensitive_data_policy: no_personal_data
---

# Wiki Viva v6.10.0

> Superseded for downstream migration by
> [Wiki Viva v6.10.1](wiki-viva-v6.10.1.md), which includes the public
> synchronization command and manifest referenced below.

Source operations release for the public Wiki Viva Kit. It adds a complete,
self-contained two-dimensional workspace for registering, inspecting,
configuring and updating sources without mixing source operations with the
world or quadrant perspectives.

Runtime anchor: `wiki_core.__version__ = "6.10.0"`.

## What changed

- Source management now has a persistent workspace with an overview, resizable
  grouped registry, record inspection, update planning, configuration previews,
  operation history and run monitoring.
- Source scope (`item`, `collection`, `account`, `endpoint`, `repository`) is
  independent from lifecycle (`one_shot`, `on_demand`, `event_driven`,
  `recurring`). Only recurring sources can become due from elapsed time.
- A source refresh inventories the whole declared source or authorized RAW
  collection and detects new, changed, removed and inaccessible records before
  execution. Selecting one record does not narrow a folder refresh to one file.
- The initial source view identifies sources requiring attention and builds a
  governed `Update all` batch. Every source is previewed independently and a
  missing recipe, authorization or RAW input stops that source without writing
  false freshness.
- Source groups can be created, renamed, reordered and persisted in the
  consumer-owned `wiki.source-groups.yaml` file.
- Portable platform identities cover common source systems through bundled
  assets and semantic fallbacks. Consumer-specific identities remain
  declarative and are not hardcoded into the kit.
- Codex and Claude are supported through capability probes and non-interactive
  job adapters. Authentication stays outside Git and capability failures are
  shown before execution.
- Existing ingestion events, sync receipts, cursors and `last_ingested_at`
  evidence are reconciled before presenting a source as never synchronized.

## Upgrading

1. Create a clean consumer proposal branch and preserve unrelated local work.
2. From the `v6.10.0` kit checkout, preview the managed-file update:

   ```sh
   python3 scripts/wiki_sync_from_kit.py \
     --kit . --consumer /path/to/consumer --dry-run
   ```

3. Review the C1 file list and the generated C2/C3 instructions. Apply C1 only
   through the same command. Use an explicit consumer-owned C3 migration when
   existing source pages must receive source-kind, lifecycle, authorization or
   deterministic-route fields.
4. Keep source records, source groups, RAW paths, account identities and
   authorization pointers in the consumer. Never copy private source data into
   the public kit and never version credentials.
5. Recompile the consumer input stage, source registry, operational pass and
   cockpit. A stable second dry-run must show no remaining C1 delta.
6. Run the consumer's audits, Python tests, frontend tests, TypeScript, build,
   secret scan and rendered-cockpit readback before promotion.
7. Promote the public kit first, pin `kit.lock` to `v6.10.0`, then promote the
   consumer migration through its own PR.

Existing sources do not become fresh merely because the UI or recipe changed.
Only successful deterministic collection evidence, a closed ingestion event and
the appropriate cursor or versioned receipt may advance freshness.

## Validation

```sh
python3 scripts/wiki_audit.py --check
python3 scripts/wiki_audit.py --public-export --check
python3 scripts/wiki_check_methodology_coverage.py --check
python3 scripts/wiki_operation_compile.py --check
python3 scripts/wiki_input_stage.py --check
python3 scripts/wiki_source_registry.py --check
python3 scripts/wiki_operational_pass.py --check
python3 scripts/wiki_consolidate.py --check
python3 scripts/wiki_migrate_templates.py --pinned
python3 scripts/wiki_page_graph.py --check --impact --base origin/main
python3 -m pytest tests/
npm --prefix apps/wiki-cockpit test
npm --prefix apps/wiki-cockpit exec -- tsc -p apps/wiki-cockpit/tsconfig.json --noEmit
npm --prefix apps/wiki-cockpit run build
gitleaks git --log-opts='origin/main..HEAD' --redact --no-banner
```
