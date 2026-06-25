# Wiki Viva v6.8 - Root entity and input stage

Date: 2026-06-25

## Summary

v6.8 makes the semantic top entity explicit. A repo now declares `root_entity`
in [wiki.config.yaml](../../../wiki.config.yaml), points it to a `root_entity`
page, and compiles a generated input stage before source routing. The input
stage is deterministic: it reads root entity, input-channel pages, source pages
and source configs, then injects inherited perspectives and target pages into
the LLM context package.

## Added

- [wiki_core/input_stage.py](../../../wiki_core/input_stage.py) and
  [wiki_input_stage.py](../../../scripts/wiki_input_stage.py) for compiling and
  checking the root/channel/source input catalog.
- New typed templates for root entities, root-person/team/company variants,
  input channels, processes and artifacts under
  [docs/references/templates/wiki](../templates/wiki/root-entity.md).
- New page types in [wiki.page-types.yaml](../../../wiki.page-types.yaml):
  `root_entity`, `input_stage`, `input_channel`, `process`, `artifact`, `role`,
  `responsibility` and `holon` shapes aligned with hierarchical navigation.
- Open-source dogfood pages:
  [Wiki Viva Kit](../../../memories/system/wiki-viva-kit.md),
  [input-stage.md](../../../memories/system/input-stage.md),
  [Methodology reference input](../../../memories/system/input-channels/methodology-reference.md)
  and
  [Wiki methodology maintenance](../../../memories/system/processes/wiki-methodology-maintenance.md).

## Changed

- LLM context requests now use schema `wiki_llm_context_pass.v4` and can carry
  `root_entity`, `input_channel`, `quadrant_map`, `target_pages` and
  `input_stage_status`.
- Source-config merge logic now supports root/channel inherited perspectives,
  `input_channel_ref`, `process_refs`, `target_pages`, `quadrants` and explicit
  perspective skip reasons.
- Consolidation packets carry `root_impact` and include inherited target pages
  in the impact closure set.
- CI now checks [wiki_input_stage.py](../../../scripts/wiki_input_stage.py)
  `--check`.

## Validation

- Unit coverage added in [test_input_stage.py](../../../tests/test_input_stage.py)
  and expanded in source-config, config, page-type, pipeline and LLM context
  tests.
- Local release gate must include:

```sh
python3 scripts/wiki_input_stage.py --check
python3 scripts/wiki_audit.py --check
python3 scripts/wiki_check_methodology_coverage.py --check
python3 scripts/wiki_operation_compile.py --check
python3 scripts/wiki_operational_pass.py --check
python3 scripts/wiki_source_registry.py --check
python3 scripts/wiki_consolidate.py --check
python3 scripts/wiki_quality_report.py --check
python3 -m pytest tests/ -q
```
