---
title: "Wiki Viva v6.9.3"
page_id: release-wiki-viva-v6-9-3
page_type: release_note
context: system
visibility: public_candidate
updated_at: 2026-08-26
stale_after_days: 365
sources_policy: release_note
gate: github_pr
sensitive_data_policy: no_personal_data
---

# Wiki Viva v6.9.3

Source-recipe, provenance and deterministic snapshot correction for the public
Wiki Viva Kit. This is a backward-compatible patch over v6.9.2; it does not
grant access to external systems or migrate any private downstream source.

Runtime anchor: `wiki_core.__version__ = "6.9.3"`.

## What changed

- The kit's canonical methodology source now has a complete,
  secret-free `wiki_source_recipe.v1`, one selected repository stream, explicit
  targets and an on-demand schedule. A real ingestion event records the
  deterministic read, delegated context pass and integration into the
  meta-wiki.
- Source freshness now distinguishes a derived processing cursor from the
  versioned ingestion event and sync receipt. A successful receipt can restore
  clean-clone freshness only when the recipe has exactly one selected stream;
  multi-stream sources still require individual cursors.
- The source, architecture, ingestion flow, process, refresh guide and operator
  instructions now describe the implementation that actually ships, including
  PyYAML strict loading and the boundary between recipes and connectors.
- Generated dashboards and subjective journals no longer require a fabricated
  `source_refs` relationship. Methodology-backed rules and perspectives point
  to the real methodology source.
- Consolidation emits `page_type: ingestion_event`, matching the page-type
  registry and event template.
- Web snapshot freshness uses the snapshot's declared `generated_at`, making
  archived snapshots and tests deterministic. The snapshot CLI can report an
  external `--out` directory without failing after writing the files.

## Upgrading

1. Update the shared core, scripts, page templates and
   [wiki.templates.yaml](../../../wiki.templates.yaml) together; do not copy
   private source pages into the public kit.
2. Run
   [wiki_migrate_templates.py](../../../scripts/wiki_migrate_templates.py)
   with `--apply` in the consumer. Review every scaffolded recipe and replace
   placeholders with the real platform, locator, selected streams, privacy,
   targets, auth pointer and export/ingest procedure.
3. Keep credentials outside Git. A recipe describes access but does not create
   a connector, session or permission.
4. Reingest a changed source, execute the delegated context pass, integrate the
   resulting event and close `consolidated_into`. A date-only metadata edit is
   not an ingestion.
5. Regenerate the source registry, input stage, cockpit and operational pass,
   then run the consumer's privacy, Python and frontend gates before promotion.

No domain migration is required for existing dashboards or journals. Their
`source_refs` remains valid when real provenance exists and may be absent when
the page is purely generated or explicitly subjective.

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
python3 -m pytest tests/
npm --prefix apps/wiki-cockpit test
npm --prefix apps/wiki-cockpit exec -- tsc -p apps/wiki-cockpit/tsconfig.json --noEmit
npm --prefix apps/wiki-cockpit run build
```
