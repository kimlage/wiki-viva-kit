---
title: "Release notes - Wiki Viva v6.7"
page_id: release-wiki-viva-v6-7
page_type: release_notes
context: system
visibility: private_self
updated_at: 2026-06-16
stale_after_days: 90
sources_policy: release_notes
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
---

# Release notes - Wiki Viva v6.7

Status: implemented in the open-source kit first, with synthetic tests.

Runtime anchor: `wiki_core.__version__ = "6.7.0"`.

## Included

- Short-term operational memory in
  [operational_pass.py](../../../wiki_core/operational_pass.py): the generated
  operational pass starts with review-now items, primary actions, pending
  decisions and latest updates, and
  [operational-pass.md](../../../memories/system/operational-pass.md) now uses
  `stale_after_days: 1`.
- Hierarchy quality signal in [quality.py](../../../wiki_core/quality.py) and
  [wiki_quality_report.py](../../../scripts/wiki_quality_report.py):
  `relation_pages_without_parent` flags action, claim, decision, meeting,
  person, project, source and source-config pages that lack `moc_parent` or an
  explicit parent hub.
- The open-source kit sets
  `audit.quality_max_relation_pages_without_parent: 0` in
  [wiki.config.yaml](../../../wiki.config.yaml), so new relation pages cannot
  accumulate beside the conceptual hubs.
- Typed contracts in [wiki.page-types.yaml](../../../wiki.page-types.yaml) and
  relation templates such as
  [action.md](../templates/wiki/action.md) now require/generate `moc_parent`
  for relation pages.
- Portable skills under [.skills/](../../../.skills/README.md) now instruct
  agents to load short-term memory first, consolidate synthesis into hubs, and
  create relation pages only under a declared parent hub.
- Method documentation updated in
  [architecture.md](../../../memories/system/wiki/architecture.md),
  [daily-operation.md](../../../memories/system/wiki/daily-operation.md),
  [gates-and-audit.md](../../../memories/system/wiki/gates-and-audit.md) and
  [command-reference.md](../../../memories/system/wiki/command-reference.md).

## Why it matters

At scale, relation pages can become a second navigation system parallel to the
conceptual wiki. v6.7 keeps the top of the wiki semantic: root MOC -> context or
domain hub -> entity/subdomain hub -> relation/evidence page -> execution/event
layer. `source_refs` still proves provenance, but `moc_parent` proves where the
page belongs.

The short-term memory section gives agents and humans a compact resume surface
without scanning the full operational report.

## Validation

```sh
python3 -m pytest tests/test_operational_pass.py tests/test_quality_report.py tests/test_page_types.py
python3 scripts/wiki_quality_report.py --check
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
