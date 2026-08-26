---
event_id: evt-2026-08-26-wiki-viva-methodology-v5-md
page_id: event-2026-08-26-wiki-viva-methodology-v5-md
page_type: ingestion_event
context: system
visibility: private_self
updated_at: 2026-08-26
stale_after_days: 30
sources_policy: evento_normalizado_com_quadrantes
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
source_id: source-wiki-viva-methodology-v5-md-3551b009f242
source_ref: sources-wiki-viva-methodology
source_type: repo
captured_at: 2026-08-26
verified_at: 2026-08-26
status_epistemologico: fato
sem_claim: "The three candidate claims restate the integrated source contract and are maintained in the five target pages; separate claim pages would duplicate the meta-wiki."
risk_level: low
requires_gate: true
target_pages:
  - memories/system/ingestion-process.md
  - memories/system/wiki-viva-kit.md
  - memories/system/wiki/architecture.md
  - memories/system/wiki/index.md
  - memories/system/wiki/ingestion-flow.md
consolidated_into:
  - memories/system/ingestion-process.md
  - memories/system/wiki-viva-kit.md
  - memories/system/wiki/architecture.md
  - memories/system/wiki/index.md
  - memories/system/wiki/ingestion-flow.md
affected_pages:
  must_update:
    - memories/system/ingestion-process.md
    - memories/system/wiki-viva-kit.md
    - memories/system/wiki/architecture.md
    - memories/system/wiki/index.md
    - memories/system/wiki/ingestion-flow.md
  should_review:
    - memories/operations.md
    - memories/system/operational-pass.md
impact_closure:
  updated:
    - memories/system/ingestion-process.md
    - memories/system/wiki-viva-kit.md
    - memories/system/wiki/architecture.md
    - memories/system/wiki/index.md
    - memories/system/wiki/ingestion-flow.md
  no_change:
    - page: memories/operations.md
      reason: Deterministic dashboard is regenerated after source integration; it carries operational state rather than the durable methodology synthesis.
    - page: memories/system/operational-pass.md
      reason: Deterministic dashboard is regenerated after source integration; it carries operational state rather than the durable methodology synthesis.
  blocked: []
---

# Event - wiki-viva-methodology-v5-md

## Source

- Canonical source: [memories/sources/wiki-viva-methodology-v5.md](../../../sources/wiki-viva-methodology-v5.md).
- source_id: `source-wiki-viva-methodology-v5-md-3551b009f242`.
- Event generated from the recorded deep read (llm-cache) by [scripts/wiki_consolidate.py](../../../../scripts/wiki_consolidate.py); review and INTEGRATE before consolidating.

## Quadrants

| Quadrant | Extracted content | Absence/limit |
| --- | --- | --- |
| Interior individual | The Wiki Viva Kit declares an intent to remain a portable, auditable Markdown/Git operational wiki whose canonical truth is approved by human review. (confidence: high) |  |
| Exterior individual | The methodology source is a versioned repository artifact that now records source identity, recipe-backed synchronization scope and the deterministic ingestion pipeline as observable outputs of the kit. (confidence: high) |  |
| Interior collective | The shared operating norm is that agents prepare deterministic evidence and contextual synthesis while the wiki owner reviews the conceptual change through a pull request. (confidence: high) |  |
| Exterior collective | The coordinating system is source page plus source_config recipe plus input channel plus ingestion event, followed by manifest, chunks, index, deep-read cache, integration and PR gates; credentials are excluded from recipes. (confidence: high) |  |

## Candidate claims

- Canonical memory is versioned Markdown and becomes approved truth only through the human PR gate.
- A source recipe declares platform, locator, streams, filters, cadence, targets and authorization pointers without storing credentials or automatically granting external access.
- The public kit currently has one canonical repository-local methodology source; downstream repositories must declare their own real sources.

## Candidate decisions

- (none)

## Candidate actions

- (none)

## Risks

- Treating a recipe as an automatic connector would overstate access and synchronization behavior.

## Conflicts and ambiguities

Uncertainties from the deep read; complete with the integration packet's conflicts and record the resolution.

- (none)

## Extracted relationships

| From | To | Relationship |
| --- | --- | --- |
| source | source_config | configured_by |
| source_config | ingestion_event | grounds_ingestion |
| ingestion_event | canonical memory | integrated_into |

## Integration

The recipe/source contract was integrated into the five target pages declared
in the event frontmatter. No conflicting claim or unresolved ambiguity was
found in the integration packet. The versioned source page records this event
as its latest successful ingestion; generated operational dashboards are
refreshed separately from the durable synthesis.
