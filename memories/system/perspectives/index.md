---
page_id: system-perspectives-index
page_type: source_catalog
title: "Perspectives"
aliases:
  - Perspective registry
tags:
  - wiki/perspective
  - status/active
status: active
context: system
visibility: private_self
updated_at: 2026-06-11
stale_after_days: 90
sources_policy: perspective_registry
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
purpose: "Registry of reusable extraction viewpoints for perspective-aware ingestion."
moc_parent: memories/system/wiki/index.md
related_pages:
  - memories/system/wiki/ingestion-flow.md
---

# Perspectives

Reusable viewpoints for source ingestion. A source request may declare required
or optional perspectives; the deep-read result records each required perspective
as extracted, not applicable, pending, blocked or skipped with reason.

## Registry

| Perspective | Use |
| --- | --- |
| [technical.md](technical.md) | Architecture, dependencies, decisions, risks and validation. |
| [project.md](project.md) | Goals, status, deliverables, metrics, risks and next milestones. |

## Related

- Ingestion flow: [ingestion-flow.md](../wiki/ingestion-flow.md).
- Template: [perspective.md](../../../docs/references/templates/wiki/perspective.md).
