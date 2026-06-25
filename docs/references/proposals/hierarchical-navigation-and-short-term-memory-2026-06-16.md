---
title: "Proposal - Hierarchical navigation and short-term memory"
page_id: proposal-hierarchical-navigation-short-term-memory-2026-06-16
page_type: methodology_proposal
context: system
visibility: private_self
updated_at: 2026-06-16
stale_after_days: 45
sources_policy: local_audit_and_downstream_structure_review
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
---

# Proposal - Hierarchical navigation and short-term memory

This proposal records the June 16 structural review of the kit and a private
downstream implementation, without carrying downstream private facts into the
public kit.

## Diagnosis

The toolkit already has the right primitives: root MOC, context hubs, typed
pages, source registry, operation cockpit, operational pass, page graph, impact
closure and quality metrics. The weak point is editorial topology at scale.
Once a downstream wiki grows from dozens to hundreds of pages, relation pages
(`claims`, `actions`, `decisions`, `sources`, `meetings`) become a parallel
navigation layer unless the context hubs absorb the synthesis and keep the
relations as supporting evidence.

Passing gates proves the contract minimum. It does not prove that the reader
will find the current truth quickly.

Current failure modes:

| Failure mode | Effect | Needed correction |
| --- | --- | --- |
| Atomic relation pages become the primary path | Facts feel scattered across parallel folders | Context hubs own the narrative; relation folders remain indexes/evidence |
| Every extraction candidate becomes a durable page | Page count grows faster than conceptual clarity | Promote only stable entities, decisions and reusable facts; keep execution detail lower |
| Generated status pages are too long for resumption | Agents must scan a report before acting | A compact daily memory must sit at the top of the generated operational pass |
| `ingested` is read as "done" | Source inventory can hide semantic follow-up | Source state, action state and impact closure must remain visible together |
| Concepts are named but not linked | Context graph gets harder to repair later | Known entity mentions should become links in changed pages |

## Target Topology

Use four levels consistently:

| Level | Owner | Purpose | Examples |
| --- | --- | --- | --- |
| 0. Root MOC | `memories/index.md` | Domain map and loading order | Context list, method, generated status |
| 1. Domain hub | `memories/<context>/index.md` | Current truth for a major domain | Finance, documents, companies, projects |
| 2. Subdomain/entity hub | Context subtree or entity page | Stable reusable concept with synthesis | A company, project, person, monthly summary |
| 3. Relation/evidence page | Typed relation dirs | Source-backed atomic support | Claim, action, decision, source, meeting |
| 4. Execution/event layer | System ingestion/events and docs refs | Audit trail, raw source references, proposals | Ingestion event, closeout, generated artifact |

The reader should normally enter at levels 0-2. Levels 3-4 prove and route the
knowledge, but should not be the main mental map.

## Rule Changes

1. Context hubs absorb first-order synthesis.
   A source consolidation is incomplete when it only creates claims/actions or
   source pages. The relevant context hub must say what changed, what remains
   pending, and where execution detail lives.

2. Relation pages must declare their parent.
   New action/claim/decision/meeting/person/project/source/source-config pages
   should carry a visible parent context or target hub through `moc_parent` or
   an explicit parent-hub field. `source_refs` remains provenance and does not
   count as navigation.

3. Navigation pages are generated where possible.
   Indexes over sources, actions, pending decisions and freshness should be
   generated from frontmatter. Manual editing should focus on synthesis pages,
   not on sortable status tables.

4. Execution detail stays below the concept.
   Ingestion events, closeouts, raw-source notes and derived artifacts are audit
   trail. They should link upward, but the domain hub should contain the
   operational conclusion.

5. Short-term memory is generated daily.
   The top of the operational pass now carries a compact "Short-term memory"
   section with review items, primary actions, pending decisions and latest
   updates. The generated page uses `stale_after_days: 1` so it cannot pretend
   to be current after the daily window.

## Implemented In This Round

- [operational_pass.py](../../../wiki_core/operational_pass.py) now renders a
  compact short-term memory section before the full diagnostic tables.
- [operational-pass.md](../../../memories/system/operational-pass.md) now has
  `stale_after_days: 1` and should be read first during resumption.
- [test_operational_pass.py](../../../tests/test_operational_pass.py) covers the
  new section and the daily freshness contract.
- [quality.py](../../../wiki_core/quality.py) and
  [wiki_quality_report.py](../../../scripts/wiki_quality_report.py) now expose
  `relation_pages_without_parent`, with
  `audit.quality_max_relation_pages_without_parent: 0` in
  [wiki.config.yaml](../../../wiki.config.yaml) for this kit.
- [wiki.page-types.yaml](../../../wiki.page-types.yaml) and the typed templates
  require/generate `moc_parent` for relation pages.
- Portable skills under [.skills/](../../../.skills/README.md) now route agents
  through short-term memory and hierarchical hub-first consolidation.

## Next Backlog

| Priority | Item | Acceptance criteria |
| --- | --- | --- |
| P0 | Add a context compression report | Report pages-per-context, relation-pages-per-hub and candidate-to-hub ratios |
| P1 | Update the operational pass closeout template | Closeout explicitly says which hub absorbed the synthesis |
| P2 | Gradually collapse older parallel pages | Downstream wikis reduce relation-page-first navigation without losing evidence |

## Success Criteria

- A new agent can read the root MOC, operations page and operational pass top
  section and know the current state without scanning the full tree.
- Domain hubs answer "what is true now" before linking to execution pages.
- Atomic relation pages are still useful for audit, but no longer compete with
  domain hubs as the main navigation.
- The full gates still pass: audit, methodology coverage, operational pass,
  source registry, quality report and tests.
