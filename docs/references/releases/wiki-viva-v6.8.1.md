---
title: "Release notes - Wiki Viva v6.8.1"
page_id: release-wiki-viva-v6-8-1
page_type: release_notes
context: system
visibility: private_self
updated_at: 2026-06-26
stale_after_days: 90
sources_policy: release_notes
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
source_refs:
  - report-aqal-quadrant-alignment-2026-06-25
---

# Release notes - Wiki Viva v6.8.1

Status: implemented in the open-source kit first, with synthetic tests.

Runtime anchor: `wiki_core.__version__ = "6.8.1"`.

## Changed

- The default `WikiConfig().llm.prompt_versions.context_deep_read` is now `v3`.
  This matches the open-source `wiki.config.yaml` and makes the root-holon AQAL
  boundary the default even for integrations that instantiate the core without a
  repo YAML file.
- Fallbacks in the ingestion pipeline, quality report and LLM context-pass CLI
  now use the same default instead of silently returning to the historical `v1`
  prompt.

## Why it matters

`context_deep_read.v3` is the prompt that carries the corrected Wilber/AQAL
boundary: Q2 is owned output/evidence of the root holon, Q3 is shared meaning
or roles-as-lived, and Q4 is systems, channels, processes, governance and
administered role structures. Historical prompts remain in the repository for
cache compatibility, but they are not the default contract of the kit.

## Validation

```sh
python3 -m pytest tests/test_config.py tests/test_wiki_pipeline.py tests/test_aqal_quadrants.py
python3 scripts/wiki_audit.py --check
python3 scripts/wiki_quality_report.py --check
```
