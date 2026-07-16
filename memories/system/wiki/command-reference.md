---
page_id: system-wiki-command-reference
page_type: source_catalog
title: "Command reference"
tags: [wiki/meta, status/active]
status: active
context: system
visibility: private_self
updated_at: 2026-07-15
stale_after_days: 90
sources_policy: documentacao_do_proprio_sistema
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
purpose: "Reference of all wiki_* deterministic CLIs."
moc_parent: memories/system/wiki/index.md
related_pages: [memories/system/wiki/index.md]
---

# Command reference

All commands are deterministic and local. Run `python3 scripts/<command>
--help` for exact options.

| Command | Purpose |
| --- | --- |
| [wiki_action_adopt.py](../../../scripts/wiki_action_adopt.py) | Adopt a downstream action baseline |
| [wiki_adapter_manifest.py](../../../scripts/wiki_adapter_manifest.py) | Build/check consumer adapter identity |
| [wiki_archive.py](../../../scripts/wiki_archive.py) | Archive resolved proposals/events |
| [wiki_audit.py](../../../scripts/wiki_audit.py) | Audit contracts, links, secrets and public PII |
| [wiki_build_demo.py](../../../scripts/wiki_build_demo.py) | Regenerate the public synthetic demo |
| [wiki_build_index.py](../../../scripts/wiki_build_index.py) | Build the local source/chunk index |
| [wiki_cache_inspect.py](../../../scripts/wiki_cache_inspect.py) | Inspect derived cache |
| [wiki_check_methodology_coverage.py](../../../scripts/wiki_check_methodology_coverage.py) | Check methodology coverage |
| [wiki_consolidate.py](../../../scripts/wiki_consolidate.py) | Compile a deep read into an integration packet |
| [wiki_drive_publish.py](../../../scripts/wiki_drive_publish.py) | Publish ignored artifacts to configured Drive |
| [wiki_export_batch.py](../../../scripts/wiki_export_batch.py) | Export context requests in batch format |
| [wiki_extract_source_manifest.py](../../../scripts/wiki_extract_source_manifest.py) | Build a deterministic source manifest |
| [wiki_extract_text.py](../../../scripts/wiki_extract_text.py) | Extract and chunk a source |
| [wiki_gate.py](../../../scripts/wiki_gate.py) | Inspect/transition proposal gates |
| [wiki_gc.py](../../../scripts/wiki_gc.py) | Remove orphan derived artifacts |
| [wiki_git_subject.py](../../../scripts/wiki_git_subject.py) | Emit a path-safe Git diagnostic fingerprint |
| [wiki_ingest.py](../../../scripts/wiki_ingest.py) | Run end-to-end ingestion |
| [wiki_ingestion_closure_report.py](../../../scripts/wiki_ingestion_closure_report.py) | Report ingestion closure |
| [wiki_input_stage.py](../../../scripts/wiki_input_stage.py) | Compile the input stage |
| [wiki_insight_job.py](../../../scripts/wiki_insight_job.py) | Gather signals for an insight |
| [wiki_llm_context_pass.py](../../../scripts/wiki_llm_context_pass.py) | Assemble/check delegated LLM context |
| [wiki_migrate_templates.py](../../../scripts/wiki_migrate_templates.py) | Migrate page templates |
| [wiki_migration_inventory.py](../../../scripts/wiki_migration_inventory.py) | Inventory template migration needs |
| [wiki_new.py](../../../scripts/wiki_new.py) | Scaffold a canonical page |
| [wiki_new_ingest.py](../../../scripts/wiki_new_ingest.py) | Scaffold an ingestion proposal |
| [wiki_okf_check.py](../../../scripts/wiki_okf_check.py) | Validate an OKF bundle |
| [wiki_okf_export.py](../../../scripts/wiki_okf_export.py) | Export an OKF bundle |
| [wiki_okf_import.py](../../../scripts/wiki_okf_import.py) | Preview an OKF import |
| [wiki_okf_visualize.py](../../../scripts/wiki_okf_visualize.py) | Build an OKF viewer |
| [wiki_operation_compile.py](../../../scripts/wiki_operation_compile.py) | Compile the daily cockpit |
| [wiki_operational_pass.py](../../../scripts/wiki_operational_pass.py) | Compile sources/actions/contexts |
| [wiki_pack.py](../../../scripts/wiki_pack.py) | Validate/operate experience packs |
| [wiki_page_graph.py](../../../scripts/wiki_page_graph.py) | Check graph reachability and impact |
| [wiki_pr_summary.py](../../../scripts/wiki_pr_summary.py) | Summarize a PR |
| [wiki_quadrant_contract.py](../../../scripts/wiki_quadrant_contract.py) | Print the AQAL quadrant contract |
| [wiki_quadrant_projection_report.py](../../../scripts/wiki_quadrant_projection_report.py) | Review quadrant projections |
| [wiki_quality_report.py](../../../scripts/wiki_quality_report.py) | Report quality/cost telemetry |
| [wiki_score.py](../../../scripts/wiki_score.py) | Record/view karma events |
| [wiki_semantic_inventory.py](../../../scripts/wiki_semantic_inventory.py) | Verify authored semantics/read models |
| [wiki_source_registry.py](../../../scripts/wiki_source_registry.py) | Compile the source registry |
| [wiki_sync_from_kit.py](../../../scripts/wiki_sync_from_kit.py) | Dry-run/apply B0/C1/C2/C3 kit adoption |
| [wiki_web_deploy_bundle.py](../../../scripts/wiki_web_deploy_bundle.py) | Prepare deployment inputs |
| [wiki_web_server.py](../../../scripts/wiki_web_server.py) | Run the localhost operator API |
| [wiki_web_snapshot.py](../../../scripts/wiki_web_snapshot.py) | Generate/check atomic cockpit snapshot |

## Common flows

```sh
python3 scripts/wiki_ingest.py --source data/raw/example.pdf --context system
python3 scripts/wiki_sync_from_kit.py --kit . --consumer /path/to/consumer --dry-run
python3 scripts/wiki_operation_compile.py --check
python3 scripts/wiki_semantic_inventory.py --check
python3 scripts/wiki_audit.py --check
```

`wiki_sync_from_kit.py` apply performs byte/mode-equal C1, deterministic C2,
explicit C3 and writes portable `kit.lock`. The consumer PR is the review and
rollback boundary. The retired lane/capsule/receipt runner is not part of the
catalog.
