---
title: "Roadmap - Typed validation, page templates and perspective-aware ingestion"
page_id: roadmap-ingestion-validation-perspectives-2026-06-11
page_type: methodology_plan
aliases:
  - v6.2 validation and perspectives roadmap
  - Perspective-aware ingestion
  - Typed page templates
tags:
  - wiki/methodology
  - wiki/ingestion
  - wiki/validation
  - status/plan
date: "2026-06-11"
status: plan
context: system
visibility: private_reference
related_pages:
  - memories/system/wiki/ingestion-flow.md
  - memories/system/wiki/gates-and-audit.md
  - memories/system/ingestion-process.md
target_version: "wiki-viva v6.2"
audience: "wiki-viva maintainers and agents"
scope: "implementation plan for the open-source kit and downstream private repos"
---

# Roadmap - Typed Validation, Page Templates and Perspective-Aware Ingestion

Updated on: 2026-06-11.

This roadmap defines the next evolution of Wiki Viva: from a source -> event ->
updated-pages flow into a richer ingestion compiler with **typed page contracts**,
**project-customizable templates**, **first-class perspective pages** and
**impact validation** proving that affected concepts/pages were updated or
explicitly left unchanged.

The implementation target is **v6.2**. Runtime changes must include a coordinated
version bump: perspective-aware deep reads change prompt semantics, result
schema and integration packet semantics.

## Research Inputs

External references support four design choices:

- **Shapes before loose heuristics.** SHACL validates graph data against shapes,
  and shape descriptions can also support UI building, code generation and data
  integration. Wiki Viva should keep Markdown/YAML, but use the same operating
  idea: page type as shape, page as graph node, auditor as validator. Source:
  [W3C SHACL](https://www.w3.org/TR/shacl/).
- **Semantic wiki as queryable memory.** Semantic MediaWiki shows the value of
  semantic annotations: wiki pages become searchable, browsable and easier to
  aggregate without hand-maintained lists. Source:
  [Semantic MediaWiki introduction](https://www.semantic-mediawiki.org/wiki/Help:Introduction_to_Semantic_MediaWiki).
- **Simple frontmatter, rich body.** Obsidian stores properties as YAML and
  treats them as small machine-readable values; Templates provide reusable
  snippets and variables. That points to simple frontmatter plus rich Markdown
  sections, not deeply nested YAML. Sources:
  [Obsidian Properties](https://obsidian.md/help/properties) and
  [Obsidian Templates](https://obsidian.md/help/plugins/templates).
- **Docs-as-code should fail early.** Docusaurus throws on broken links by
  default in production builds; MkDocs strict mode turns warnings into errors;
  Vale treats prose as lintable. Wiki Viva should do the same: warnings for
  legacy discovery, errors for regressions introduced by the current change.
  Sources: [Docusaurus config](https://docusaurus.io/docs/api/docusaurus-config),
  [MkDocs configuration](https://www.mkdocs.org/user-guide/configuration/) and
  [Vale CLI](https://vale.sh/docs).

## Current Baseline

The kit already has strong foundations:

- `wiki_ingest.py` produces manifests, text, chunks, index entries, pre-scan
  findings, LLM context requests and score events.
- `wiki_llm_context_pass.py` delegates deep reading to the repo agent and writes
  validated cache results.
- `wiki_consolidate.py` closes the missing half: aggregate cache results, emit
  normalized events and build integration packets.
- `wiki_audit.py` validates frontmatter, local links, secrets, PII boundaries,
  quadrants, gate state, LLM pass, consolidation and log updates.
- The source registry and operation cockpit make source state and pending work
  visible.

Remaining gaps:

- consolidation proves that **some** integration happened, not that every
  affected page was updated or explicitly skipped;
- page types exist as vocabulary, but there is no declarative shape registry
  listing required fields, sections, relations and templates by type;
- known concepts/entities can still be mentioned without links;
- the deep read is generic instead of perspective-specific;
- project customization is split across config, templates, skills and
  convention instead of one declarative overlay.

## Core Model

v6.2 should treat ingestion as incremental graph compilation:

```text
new source
  -> manifest and chunks
  -> perspective-aware deep read
  -> normalized event
  -> impact graph
  -> integration packet by affected pages
  -> target page updates
  -> closure validation
  -> PR
```

The agent still owns judgment and synthesis. The deterministic core provides the
map, obligations and gates.

## Typed Pages and Shapes

Add a declarative page type registry inspired by SHACL, but implemented with
portable YAML/Markdown.

Proposed file:

```text
wiki.page-types.yaml
```

Conceptual example:

```yaml
schema_version: wiki_page_types.v1
page_types:
  claim:
    template: docs/references/templates/wiki/claim.md
    allowed_dirs:
      - memories/claims
      - memorias/claims
    required_frontmatter:
      - page_id
      - page_type
      - title
      - context
      - visibility
      - updated_at
      - source_refs
    required_sections:
      - Statement
      - Related
      - Conflicts and ambiguities
    relation_rules:
      source_refs:
        min_count: 1
      conflicts_with:
        reciprocal_field: conflicts_with
      supersedes:
        reciprocal_field: superseded_by
    stale_after_days_default: 45
```

Each shape can declare:

- required frontmatter fields;
- simple field types: string, date, list, enum, bool;
- required Markdown sections;
- relation rules and reciprocal fields;
- allowed directories;
- default template;
- freshness policy;
- privacy/publication policy;
- minimum real-content rules.

New audit functions:

- `audit_page_type_registry`
- `audit_page_shape`
- `audit_template_coverage`
- `audit_template_version`
- `audit_section_contract`

## Project-Customizable Templates

Split template resolution into three layers:

1. **Core template**: ships with the open-source kit, no personal context.
2. **Project overlay**: adds local fields, examples, sections and perspectives.
3. **Page instance**: records `template_id`, `template_version` and optional
   `template_customizations`.

Config concept:

```yaml
templates:
  overlays_root: docs/references/templates/overlays
  page_type_overrides:
    project:
      template: docs/references/templates/wiki/project.md
      overlay: docs/references/templates/overlays/project-local.md
    source:
      template: docs/references/templates/wiki/source.md
```

The open-source kit should ship only generic overlays. Private downstream repos
can add domain overlays such as finance, career, companies or document
management.

## Perspective Pages

A perspective is a canonical page defining a lens of extraction and integration.
It is not a tag; it governs what the deep read extracts, which pages it can
update, which metrics matter and what absence means.

New template:

```text
docs/references/templates/wiki/perspective.md
```

Conceptual frontmatter:

```yaml
---
page_id: perspective-technical
page_type: perspective
title: "Technical perspective"
context: system
visibility: private_self
status: active
updated_at: 2026-06-11
stale_after_days: 90
applies_to_source_types:
  - meeting
  - transcript
  - code_change
extracts:
  - architecture
  - dependencies
  - decisions
  - risks
  - action_items
target_page_types:
  - project
  - initiative
  - claim
  - decision
  - action
metric_contract:
  required_metrics:
    - risk_count
    - decision_count
prompt_profile: perspective_technical
template_ref: docs/references/templates/wiki/perspective.md
---
```

Useful core perspectives:

| Perspective | Extracts | Updates |
| --- | --- | --- |
| Technical | Architecture, stack, technical decisions, dependencies, risks, tests | Project pages, technical claims, decisions, runbooks |
| Project/initiative | Goal, status, deliverables, metrics, risks, next milestones, stakeholders | Project/initiative pages, cockpit, actions |
| Person/stakeholder | Positions, preferences, tensions, responsibilities, commitments | Person pages, roles, relationships |
| Publication | Public-safe facts, PII risks, redaction requirements, current-source needs | `public_candidate` pages and publication checklists |
| Operation | Commands, recurrence, failure modes, playbooks, pending work | Cockpit, runbooks, actions |

Source config concept:

```yaml
required_perspectives:
  - perspective-technical
  - perspective-project
optional_perspectives:
  - perspective-publication
perspective_overrides:
  perspective-technical:
    focus:
      - architecture
      - integration points
      - validation strategy
```

Deep-read result concept:

```json
{
  "perspectives": {
    "perspective-technical": {
      "status": "extracted",
      "summary": "...",
      "facts": [],
      "decisions": [],
      "actions": [],
      "metrics": {},
      "target_pages": [],
      "confidence": "medium"
    },
    "perspective-project": {
      "status": "not_applicable",
      "absence_reason": "source has no project-management signal"
    }
  }
}
```

Events should gain a `## Perspectives` section. Every required perspective must
appear with explicit status: `extracted`, `not_applicable`, `pending`, `blocked`
or `skipped_with_reason`.

## Impact Graph and Affected Pages

The system should not rely on the agent remembering every page to touch.

New derived artifacts:

```text
data/derived/wiki/page-graph/page-graph.json
data/derived/wiki/page-graph/impact-<source_id>.json
```

The graph should index:

- `page_id`, path, page type, title and aliases;
- outgoing and incoming Markdown links;
- frontmatter refs: `source_refs`, `claims`, `decisions`, `actions`,
  `related_pages`, `backlinks_expected`;
- textual mentions of known aliases;
- sources linked to each page;
- templates and perspectives applied;
- freshness and status.

Impact computation:

```text
impact_set =
  pages directly named by the packet
  + pages matched by entity/alias
  + overlapping claims
  + pages referencing prior versions of the same source
  + context hubs
  + pages required by perspectives
  + backlinks_expected of changed pages
```

Each candidate gets a severity:

- `must_update`: strong evidence and a shape rule require an update.
- `should_review`: medium evidence or indirect relationship.
- `may_ignore`: low confidence; record a skip if it appears in the packet.
- `blocked`: requires live source access, credentials or human decision.

Event closure concept:

```yaml
affected_pages:
  must_update:
    - memories/projects/example.md
  should_review:
    - memories/claims/example.md
impact_closure:
  updated:
    - memories/projects/example.md
  no_change:
    - page: memories/claims/example.md
      reason: "claim candidate duplicated an existing statement"
  blocked: []
```

New validations:

- `audit_impact_closure`: every `must_update` is either updated, skipped with
  reason or blocked.
- `audit_reverse_source_refs`: every updated target references the source/event
  back.
- `audit_reviewed_pages`: `should_review` needs reviewed/no-change status or
  remains a warning; if the page is touched by the PR, the warning becomes an
  error.

## Concept Linking

Add a "known concept, linked mention" flow.

Alias catalog concept:

```json
{
  "ana souza": {
    "page_id": "person-ana-souza",
    "path": "memories/people/ana-souza.md",
    "confidence": "high",
    "type": "person"
  }
}
```

Severity policy:

- high-confidence alias mention in a changed page without a link: error;
- high-confidence alias mention in legacy pages: warning until cleanup;
- ambiguous alias: warning with candidates;
- short/common term: ignore unless `canonical_alias: true`.

New validations:

- `audit_unlinked_entity_mentions`
- `audit_orphan_pages`
- `audit_expected_backlinks`
- `audit_relation_links`

## Incremental Concept Updates

For pages receiving repeated consolidations, standardize:

```yaml
source_updates:
  - source_id: source-example-abc123
    event: memories/system/ingestion/events/2026-06-11-example.md
    updated_sections:
      - Status
      - Metrics
    perspective_ids:
      - perspective-project
    update_mode: merged
    date: 2026-06-11
```

This supports auditability, targeted refresh, concept changelogs and cheaper
incremental compilation.

## Cost and Performance Optimization

1. Run deterministic triage first: manifest, chunks, aliases, links, source
   registry and page graph.
2. Run only required perspectives from source config; optional perspectives run
   when triage detects a signal.
3. Cache by perspective: include `perspective_id`, `perspective_version`,
   `prompt_version`, `schema_version`, `chunk_hash` and `model_profile`.
4. Keep integration packets small: candidate pages and relevant snippets only.
5. Reuse batch export for low-urgency perspective/chunk work.
6. Make CI incremental: full graph fast checks, expensive checks scoped to diff
   and impact set.
7. Use severity escalation: warning for legacy stock, error for PR regressions.

## Required Version Bump

Implementation must bump:

- `context_deep_read.v2.md` -> `context_deep_read.v3.md` when the result schema
  gains `perspectives`.
- `CONTEXT_PASS_SCHEMA_VERSION`: `wiki_llm_context_pass.v2` ->
  `wiki_llm_context_pass.v3`.
- `PACKET_SCHEMA_VERSION`: `wiki_integration_packet.v1` ->
  `wiki_integration_packet.v2`.
- New `PAGE_GRAPH_SCHEMA_VERSION`: `wiki_page_graph.v1`.
- New `PAGE_TYPES_SCHEMA_VERSION`: `wiki_page_types.v1`.
- New `PERSPECTIVE_SCHEMA_VERSION`: `wiki_perspective.v1`.
- `wiki.config.yaml`: `llm.prompt_versions.context_deep_read: v3`.
- Prompt checksums.
- Release note: `docs/references/releases/wiki-viva-v6.2.md`.

## Implementation Roadmap

### Delivery Status

Updated on: 2026-06-11.

| Phase | Status | Evidence |
| --- | --- | --- |
| PR 1 - Plan and conceptual registry | Delivered as roadmap only | This roadmap and the private PT plan exist; runtime registry files are intentionally deferred until the loader exists. |
| PR 2 - Page graph and concept links | Implemented and tested on branch `opensource/wiki-viva-kit` | `wiki_core/graph/`, `scripts/wiki_page_graph.py`, audit knobs, impact acknowledgements, command docs, release notes and tests. Validation: `tmp/wiki-viva-venv/bin/python -m pytest` (`315 passed, 4 skipped`), `scripts/wiki_page_graph.py --check --impact`, `scripts/wiki_audit.py --check` (`0 error(s)`, 3 legacy warnings). |
| PR 3 - Shapes/page type registry | Implemented and tested on branch `opensource/wiki-viva-kit` | `wiki.page-types.yaml`, `wiki_core/page_types.py`, audit integration and tests; existing event baseline migrated with `page_id`. |
| PR 4 - Perspective-aware deep read | Implemented and tested on branch `opensource/wiki-viva-kit` | `perspective` page type/template/pages, `context_deep_read.v3`, `wiki_llm_context_pass.v3`, request/result perspective fields and `audit_perspective_coverage`. |
| PR 5 - Impact closure in consolidation | Implemented and tested on branch `opensource/wiki-viva-kit` | `wiki_integration_packet.v2`, packet `impact`, event `affected_pages`/`impact_closure`, and `audit_impact_closure`. |
| PR 6 - Template overlays | Implemented and tested on branch `opensource/wiki-viva-kit` | `wiki_core/templates.py`, `scripts/wiki_new.py`, template provenance and generic open-source overlay example. |
| PR 7 - Pilots | Complete locally | Open-source and private downstream synthetic pilots each produced 1 chunk, 2 required perspectives, 1 cache result and 0 pending calls. |
| PR 8 - v6.2 release | Implemented locally; publication pending | Open-source kit gates green; private downstream implementation synced with warnings cataloged for page cleanup; repo and local skills updated. |

### PR 1 - Plan and conceptual registry

- Add this roadmap.
- Add a minimal `wiki.page-types.yaml` for existing page types.
- Add `perspective.md`.
- Document perspectives in the meta-wiki.
- Avoid runtime changes except tiny config-loading tests if needed.

### PR 2 - Page graph and concept links

- Implement `wiki_core/graph/page_graph.py`.
- Add `scripts/wiki_page_graph.py --write --check --impact-source`.
- Index page IDs, aliases, links, source refs, related pages and backlinks.
- Escalate entity mention without link to error in changed files.
- Test aliases, reciprocal links, ambiguity and orphan pages.

### PR 3 - Shapes/page type registry

- Implement registry loader.
- Add `audit_page_type_registry`, `audit_page_shape`,
  `audit_template_coverage` and `audit_section_contract`.
- Migrate existing page types to shapes.
- Preserve English/Portuguese layout compatibility through config.

### PR 4 - Perspective-aware deep read

- Create the `perspective` page type and templates.
- Create prompt `context_deep_read.v3.md`.
- Bump `CONTEXT_PASS_SCHEMA_VERSION`.
- Include `perspectives` in validated results.
- Add `audit_perspective_coverage`.
- Add E2E tests with a synthetic source requiring two perspectives.

### PR 5 - Impact closure in consolidation

- Bump `PACKET_SCHEMA_VERSION`.
- Include impact set by severity in `wiki_consolidate.py --packet`.
- Add `affected_pages` and `impact_closure` to generated events.
- Block open `must_update` items with `audit_impact_closure`.
- Show pending impact in the cockpit.

### PR 6 - Template overlays

- Resolve templates by `base + overlay`.
- Add `template_id`, `template_version` and `template_customizations` to new
  pages.
- Ship generic open-source overlays only.
- Let downstream private repos add local overlays.

### PR 7 - Pilots

- Open-source pilot: synthetic technical + project source.
- Private downstream pilot: low-risk system/wiki source, no credentials.
- Measure affected pages, updated pages, justified no-change pages, unlinked
  mentions before/after, tokens by perspective and audit time.

### PR 8 - v6.2 release

- Update meta-wiki docs.
- Regenerate cockpit/source registry.
- Run:
  - `python3 scripts/wiki_audit.py --check`
  - `python3 scripts/wiki_check_methodology_coverage.py --check`
  - `python3 scripts/wiki_operation_compile.py --check`
  - `python3 scripts/wiki_consolidate.py --check`
  - `python3 scripts/wiki_page_graph.py --check`
  - `pytest`
- Publish to the open-source kit and downstream private repo.

## Acceptance Criteria

- No used `page_type` lacks a shape.
- No canonical page type lacks a template or explicit `template: none`.
- A complete deep-read source cannot remain merely cataloged.
- An event closes only when `consolidated_into` and `impact_closure` are coherent.
- Updated pages reference the source/event back.
- New high-confidence concept mentions become links or carry a justification.
- Required perspectives appear in the deep-read result and event, even when
  marked `not_applicable`.
- Open-source and downstream private repos pass the same core tests with only
  overlays and paths differing.

## Recommended Sequence

Start with the page graph. It unlocks link coverage, orphan detection and impact
sets without relying on model behavior. Then add shapes/templates. Add
perspective-aware deep reading after those deterministic contracts exist, because
the prompt/schema bump should land only when the deterministic gates can prove
the new information was integrated.
