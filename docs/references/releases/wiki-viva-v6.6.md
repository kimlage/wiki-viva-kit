---
title: "Release notes - Wiki Viva v6.6"
page_id: release-wiki-viva-v6-6
page_type: release_notes
context: system
visibility: private_self
updated_at: 2026-06-15
stale_after_days: 90
sources_policy: release_notes
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
---

# Release notes - Wiki Viva v6.6

Status: implemented in the open-source kit first.

Runtime anchor: `wiki_core.__version__ = "6.6.0"`.

External reference: Google's [Open Knowledge Format article](https://cloud.google.com/blog/products/data-analytics/how-the-open-knowledge-format-can-improve-data-sharing/)
and [GoogleCloudPlatform/knowledge-catalog](https://github.com/GoogleCloudPlatform/knowledge-catalog).

## Included

- New deterministic OKF interop core:
  [okf.py](../../../wiki_core/okf.py).
- New CLIs:
  - [wiki_okf_export.py](../../../scripts/wiki_okf_export.py): exports the
    configured memory tree as an Open Knowledge Format v0.1 bundle;
  - [wiki_okf_check.py](../../../scripts/wiki_okf_check.py): validates OKF v0.1
    conformance with permissive broken-link warnings;
  - [wiki_okf_import.py](../../../scripts/wiki_okf_import.py): previews importing
    an OKF bundle back into a Wiki Viva tree, dry-run only;
  - [wiki_okf_visualize.py](../../../scripts/wiki_okf_visualize.py): writes a
    local, dependency-free HTML viewer for an OKF bundle.
- The exporter preserves rich Wiki Viva structure by keeping internal
  `page_type`, `page_id`, context, tags, privacy and source metadata as OKF
  extension fields. Reserved `index.md` and `log.md` source pages are moved to
  `_wiki_viva_reserved/` concept pages while generated OKF indexes satisfy the
  v0.1 reserved-file contract.
- Unit tests in [test_okf.py](../../../tests/test_okf.py) cover reserved-page
  export, conformance checking, import preview and visualization output.

## Why it matters

OKF formalizes the portable Markdown/YAML pattern that Wiki Viva already uses.
v6.6 adds exchange without weakening the richer operational model: the internal
wiki still uses typed pages, perspectives, quadrants, privacy gates, freshness,
impact closure and PR review. OKF sits at the boundary as a producer/consumer
adapter for other agents and tools.

Reference pattern: Andrej Karpathy's
[LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
article describes the persistent Markdown wiki pattern behind the toolkit's
source -> synthesis -> schema workflow.

## Validation

```sh
python3 -m pytest tests/test_okf.py
python3 scripts/wiki_okf_export.py --out tmp/okf-smoke --clean
python3 scripts/wiki_okf_check.py --bundle tmp/okf-smoke --check
python3 scripts/wiki_okf_visualize.py --bundle tmp/okf-smoke --out tmp/okf-smoke/viz.html
python3 scripts/wiki_okf_import.py --bundle tmp/okf-smoke --context system --dry-run
```

The full repo gates remain:

```sh
python3 -m pytest tests/ -q
python3 scripts/wiki_audit.py --check
python3 scripts/wiki_quality_report.py --check
python3 scripts/wiki_check_methodology_coverage.py --check
python3 scripts/wiki_operation_compile.py --check
python3 scripts/wiki_operational_pass.py --check
python3 scripts/wiki_source_registry.py --check
python3 scripts/wiki_consolidate.py --check
git diff --check
```
