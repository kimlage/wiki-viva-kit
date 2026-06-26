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
updated_at: 2026-06-26
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
The root entity can also declare a default perspective bundle; input channels
and source configs inherit or refine that bundle before the LLM context package
is emitted.

AQAL quadrant perspectives are only the perspectives that explicitly declare a
`quadrant: q1`, `quadrant: q2`, `quadrant: q3` or `quadrant: q4` contract. Other
topical perspectives, such as stakeholder, technical or financial, may extract
people, artifacts, tools or money across quadrants; they do not redefine the
Wilber/AQAL quadrant map.

## Registry

| Perspective | Use |
| --- | --- |
| [technical.md](technical.md) | Architecture, dependencies, decisions, risks and validation. |
| [project.md](project.md) | Goals, status, deliverables, metrics, risks and next milestones. |
| [stakeholder.md](stakeholder.md) | Cross-quadrant stakeholder facts: people, roles, relationships, commitments and privacy boundaries; not the Q3 AQAL contract. |
| [financial.md](financial.md) | Amounts, counterparties, categories, reconciliation state and evidence. |
| [publication.md](publication.md) | Public/private boundaries, citations and publication readiness. |
| [operations.md](operations.md) | Process state, runbooks, failure modes, validation gates and ownership. |
| [identity-intent.md](identity-intent.md) | Q1 identity, intent, priorities and constraints. |
| [artifacts-evidence.md](artifacts-evidence.md) | Q2 owned artifacts, repositories-as-outputs, documents-as-evidence, outputs and metrics; coordination platforms stay Q4. |
| [roles-relationships.md](roles-relationships.md) | Q3 people only as participants in shared meaning, roles-as-lived, mutual expectations, relationships, rituals and culture; rosters and administered assignments stay Q4. |
| [systems-processes.md](systems-processes.md) | Q4 systems, channels, processes and gates. |
| [privacy-publication.md](privacy-publication.md) | Boundary lens for privacy, redaction and publication. |

## Related

- Ingestion flow: [ingestion-flow.md](../wiki/ingestion-flow.md).
- Root entity: [wiki-viva-kit.md](../wiki-viva-kit.md).
- Input stage: [input-stage.md](../input-stage.md).
- Template: [perspective.md](../../../docs/references/templates/wiki/perspective.md).
