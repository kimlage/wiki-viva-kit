---
page_id: system-memories-log
page_type: system_log
context: system
visibility: private_self
updated_at: 2026-06-12
stale_after_days: 180
sources_policy: append_only_memory_changes
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
---

# Memory log

Append-only record of changes in the [memories/](..) layer.

## [2026-06-12] System | Source configs feed deep-read perspectives

- [wiki_llm_context_pass.py](../../scripts/wiki_llm_context_pass.py) now applies
  `perspectives_required` and `perspectives_optional` from a repo-local source
  page's matching `source_config`, found through `config_ref` or shared
  `source_refs`.
- New helper [source_config.py](../../wiki_core/source_config.py) centralizes the
  lookup/merge behavior and [test_source_config.py](../../tests/test_source_config.py)
  covers explicit config refs and source-ref fallback.
- [ingestion-flow.md](wiki/ingestion-flow.md) and
  [command-reference.md](wiki/command-reference.md) document the automatic
  perspective application.

## [2026-06-12] System | Source configs validate perspective ids

- [wiki_audit.py](../../scripts/wiki_audit.py) now checks
  `perspectives_required` and `perspectives_optional` on `source_config` pages
  against existing `perspective` pages when perspective coverage is enabled.
- [source-config.md](../../docs/references/templates/wiki/source-config.md)
  documents the perspective fields, and [wiki.page-types.yaml](../../wiki.page-types.yaml)
  types them as lists.
- Changed ingestion event pages keep unlinked entity mentions as warnings, not
  errors, because generated events preserve extracted source text; canonical
  pages remain under the stricter changed-page rule.

## [2026-06-12] System | Durable events drop integration boilerplate

- [consolidate.py](../../wiki_core/consolidate.py) no longer emits the
  repeated integration instruction into generated event pages; the operational
  instruction remains in the integration packet where the agent actually uses
  it.
- [test_consolidate.py](../../tests/test_consolidate.py) now asserts generated
  events do not reintroduce the "cataloging is not ingesting" boilerplate.

## [2026-06-12] System | Canonical perspective set expands

- Added canonical perspective pages for stakeholders, finance, publication and
  operations under [perspectives](perspectives/index.md), complementing the
  existing technical and project lenses.
- The perspective registry now exposes six reusable lenses for deep-read
  extraction and integration: technical, project, stakeholder, financial,
  publication and operations.

## [2026-06-12] System | Ingestion closure report

- New deterministic module [closure.py](../../wiki_core/closure.py) and CLI
  [wiki_ingestion_closure_report.py](../../scripts/wiki_ingestion_closure_report.py)
  report whether normalized ingestion events have `consolidated_into`, how many
  candidate claims/decisions/actions they still carry, and which `ingested`
  source pages lack a matching closed event.
- New synthetic test [test_ingestion_closure_report.py](../../tests/test_ingestion_closure_report.py)
  covers closed events, open events, candidate counts and source gaps.
- [command-reference.md](wiki/command-reference.md) documents the report and its
  temporary source-gap budget for gradual adoption.

## [2026-06-12] System | Critical page types gain real shapes

- [wiki.page-types.yaml](../../wiki.page-types.yaml) now declares concrete
  shapes for critical content types: action, claim, context_note, decision,
  meeting, person, project, source and source_config.
- The source shape now requires typed provenance fields and evidence refs while
  keeping `source_refs` optional for root/source-of-record pages.
- [test_page_types.py](../../tests/test_page_types.py) asserts that the repo
  registry keeps these critical shapes instead of collapsing back to generic
  contracts.

## [2026-06-12] System | Quality ratchet includes low-density pages

- [wiki_quality_report.py](../../scripts/wiki_quality_report.py) now supports
  `--max-low-density` under `--check`, alongside `--max-bad-repetition`, and
  reads defaults from `audit.quality_max_*` when flags are omitted.
- The GitHub workflow runs `wiki_quality_report.py --check`; the open-source
  kit keeps the default zero low-density pages and zero bad repetition blocks.
- [command-reference.md](wiki/command-reference.md) documents both thresholds.

## [2026-06-12] System | Quality sees legacy events and checkout drift

- [quality.py](../../wiki_core/quality.py) now counts real ingestion events by
  the canonical events directory, including legacy pages that still carry a
  source/catalog page type but declare `event_id` or `source_id`.
- The synthetic example event
  [2026-06-09-example.md](ingestion/events/2026-06-09-example.md) now has
  `consolidated_into`, so the kit baseline no longer advertises an unclosed
  event.
- [wiki_toolkit_drift.py](../../scripts/wiki_toolkit_drift.py) accepts
  `--ref-path` for comparing against a real checkout instead of only a branch
  ref, and the active ingestion-flow docs now reference
  `wiki_llm_context_pass.v3`.

## [2026-06-12] System | Impact ack audit works in PR CI

- [wiki_audit.py](../../scripts/wiki_audit.py) now recognizes impact-ack ledger
  lines added through `origin/main...HEAD`, in addition to `main...HEAD`.
- This keeps the `audit_impact` gate deterministic in GitHub Actions PR
  checkouts where a local `main` branch may not exist.

## [2026-06-12] System | Source refresh cadence and Obsidian directory-link warnings

- [wiki_source_registry.py](../../scripts/wiki_source_registry.py) now renders
  next suggested refresh, refresh status and policy for canonical source pages.
- Source and meeting templates document `refresh_policy`,
  `refresh_cadence_days`, optional `next_refresh_at` and `refresh_trigger`.
- New guide [source-refresh-cadence.md](../../docs/references/guides/source-refresh-cadence.md)
  defines cadence choices for recurring sources, event-driven sources,
  archival references and meetings.
- [wiki_audit.py](../../scripts/wiki_audit.py) now warns on Markdown links that
  point to local directories, because Obsidian may interpret them as note
  creation instead of folder navigation; link `README.md` or `index.md`
  instead.
- [wiki-viva skill](../../.skills/wiki-viva/SKILL.md) now tells agents to use
  source refresh metadata and concrete local index-file links.

## [2026-06-12] System | v6.3 quality and cost telemetry

- Runtime bumped to `wiki_core.__version__ = "6.3.0"` in
  [wiki_core](../../wiki_core/__init__.py).
- New deterministic quality module [quality.py](../../wiki_core/quality.py) and
  CLI [wiki_quality_report.py](../../scripts/wiki_quality_report.py) report
  information density, link density, same-context/same-type repetition,
  consolidation gaps, estimated context tokens and cache reuse.
- Cost is now visible as telemetry for control and comparison, but it is not a
  hard budget gate.
- Synthetic fixtures for the open-source pilot live in
  [v63-quality-cost](../../docs/references/fixtures/v63-quality-cost/multiperspective-source.md)
  and are linked from the v6.3 roadmap
  [wiki-viva-v6.3-quality-cost-control-2026-06-12.md](../../docs/references/proposals/wiki-viva-v6.3-quality-cost-control-2026-06-12.md).
- Command reference [command-reference.md](wiki/command-reference.md) now
  documents the quality report CLI.

## [2026-06-11] System | v6.2 page graph reachability baseline

- Root MOC [index.md](../index.md) now links the docs/memory boundary review
  [docs-review.md](docs-review.md), making the operational rule reachable from
  the graph root.
- Ingestion events catalog [README.md](ingestion/events/README.md) now links the
  synthetic normalized event [2026-06-09-example.md](ingestion/events/2026-06-09-example.md),
  so the v6.2 reachability gate has a connected baseline before new events land.
- Page type registry [wiki.page-types.yaml](../../wiki.page-types.yaml) added
  with shapes for the kit's current page types; [wiki_audit.py](../../scripts/wiki_audit.py)
  now validates declared types, minimal frontmatter, field types, directories,
  section contracts and template coverage. The example event gained a stable
  `page_id` to satisfy the new ingestion-event shape.
- Perspective-aware deep reads added: template
  [perspective.md](../../docs/references/templates/wiki/perspective.md), registry
  [perspectives/index.md](perspectives/index.md), baseline perspectives
  [technical.md](perspectives/technical.md) and [project.md](perspectives/project.md),
  prompt [context_deep_read.v3.md](../../wiki_core/llm/prompts/context_deep_read.v3.md)
  and cache/request validation for `perspectives_required`.
- Consolidation impact closure added: integration packets are now
  `wiki_integration_packet.v2` with `impact.must_update`/`impact.should_review`;
  generated events carry `affected_pages` and `impact_closure`; the auditor
  blocks `must_update` entries that are not closed as updated, no-change with
  reason or blocked with reason.
- Template overlays added: [templates.py](../../wiki_core/templates.py) resolves
  base template plus optional overlay, [wiki_new.py](../../scripts/wiki_new.py)
  instantiates typed pages with `template_id`/`template_version`/`template_ref`,
  and the kit ships generic overlay
  [perspective-example.md](../../docs/references/templates/overlays/perspective-example.md).
- Open-source v6.2 pilot metrics recorded in
  [wiki-viva-v6.2-pilot-metrics-2026-06-11.md](../../docs/references/reports/wiki-viva-v6.2-pilot-metrics-2026-06-11.md):
  synthetic source, 1 chunk, 2 required perspectives, 1 cache result, 0 pending
  calls and 0 perspective coverage errors.

## [2026-06-10] System | v6.1: real consolidation (ingestion that integrates knowledge)

- New [scripts/wiki_consolidate.py](../../scripts/wiki_consolidate.py): generates the normalized event from the llm cache (quadrants filled, `consolidated_into: []` to close) + the integration packet (related pages, overlapping claims, potential conflicts); `--check` in CI while there is a read source without integration.
- `audit_consolidation` gate in [scripts/wiki_audit.py](../../scripts/wiki_audit.py): a new event requires `consolidated_into`, the target's reverse reference to the source (`source_refs`) and claims linked or `sem_claim: <reason>` — not skippable.
- [scripts/wiki_build_index.py](../../scripts/wiki_build_index.py) `--rebuild` now also indexes the wiki's own pages (`page:<page_id>`): retrieval finds the existing knowledge before integrating the new.
- Skills (wiki-viva, llm-context-agent, ingestion-agent, router) and method pages ([ingestion process](ingestion-process.md), [ingestion flow](wiki/ingestion-flow.md), [gates and audit](wiki/gates-and-audit.md), [command reference](wiki/command-reference.md)) with the full "ingesting = integrating" checklist; the cockpit shows "Sources awaiting consolidation".

## [2026-06-10] System | v6 Phase 2: external-tool entities + per-source config

- External-tool entities (item 8): new page_types `meeting`, `external_card`, `calendar_event` in [scripts/wiki_audit.py](../../scripts/wiki_audit.py) (ONTOLOGY_DIRNAME_TYPES, en+pt superset: meetings/reunioes, cards/cartoes, calendar/calendario); templates [meeting.md](../../docs/references/templates/wiki/meeting.md), [external-card.md](../../docs/references/templates/wiki/external-card.md), [calendar-event.md](../../docs/references/templates/wiki/calendar-event.md). Live connectors (Jira/Calendar) stay with the agent/skill, not in the toolkit.
- Per-source config (item 9/6): page_type `source_config` in the sources group; template [source-config.md](../../docs/references/templates/wiki/source-config.md) (ingestion/search/business rules, read by the agent). The [source registry](source-registry.md) gained a Config column (reads `config_ref` from the source page; links only when the file exists).
- "Configure a source" process: new [reference/sources.md](../../.skills/wiki-viva/reference/sources.md) in the wiki-viva skill (create the source page + a config page + register it; model meeting/card/calendar as linked entities).

## [2026-06-10] Source registry + people ontology + enriched person/source templates

- Canonical source registry wired into the docs: root MOC [index.md](../index.md) now links [system/source-registry.md](source-registry.md) (ingestion state + last update, generated by [scripts/wiki_source_registry.py](../../scripts/wiki_source_registry.py)); command reference [command-reference.md](wiki/command-reference.md) registers the CLI (quick-map row + `--write`/`--check` subsection).
- New people ontology hub [people/index.md](../people/index.md) (`ontology_index`): the people registry — one page per person with contacts + a sourced perspective; mentions of a person link here.
- Person template enriched: `contacts:` frontmatter, a Contacts table, a Perspective section (sourced viewpoint over time, each position linking its claim/decision), the "mention becomes a link" rule, and the optional `config_ref:` for single-purpose pages.
- Source template enriched: `source_type`/`ingestion_state`/`last_ingested_at` frontmatter (fed to the registry) plus an Ingestion log table — the page is the hierarchical node holding that source's log, indexed by the registry.
- Obsidian conventions: "bring information WITH links" (named entity becomes a link; auditor warns on unlinked known-entity mentions; a person mention becomes a link) and a new *Single purpose and rules on a separate page* section (`config_ref:` for heavy rules; the source registry indexes sources with state + last update).

- Rich representation made method, not afterthought: new *Rich representation by default* guideline in [obsidian-conventions.md](../../docs/references/templates/wiki/obsidian-conventions.md) — pages SHOULD illustrate with Mermaid + tables, architecture/flow/relationship/process pages MUST carry a diagram, with a "which diagram for what" mapping (flowchart/stateDiagram/sequenceDiagram/er-classDiagram/mindmap/timeline) and diagram authoring rules. Referenced from the methodology source ([wiki-viva-methodology-v5.md](../sources/wiki-viva-methodology-v5.md)) and the [operational-wiki-contract.md](operational-wiki-contract.md).
- Methodology source page enriched: principles as a table, a Mermaid flowchart of ingestion-as-compilation, and a rich-representation section linking the convention.
- Meta-wiki integrated as a first-class context rather than a separate manual: [README.md](../../README.md) "Official documentation" reframed around dogfooding ("open the root map of content and you are already inside the living wiki"); root MOC [index.md](../index.md) gained a Mermaid mindmap of the wiki's own structure (contexts + method + meta-wiki), a dedicated meta-wiki section and a method/operation table; meta-wiki [index.md](wiki/index.md) gained a Mermaid map of its pages and a "where to start" table.

## [2026-06-10] Debts resolved | karma display i18n, gate hardening, index pruning, CLI robustness

- Badge names/criteria and journey levels now render in the configured language (BADGE_DISPLAY/LEVEL_DISPLAY pt+en); persisted ids untouched. Generator i18n leftovers closed; NEW tests/test_i18n_tables.py enforces pt/en key+placeholder parity across every string table.
- Gates hardened: orphan context-pass requests no longer jam the gate; prompt checksums pinned (wiki_core/llm/prompts/.checksums — editing a prompt without a conscious bump fails the audit); provenance check never silently disabled; cache_key validated (hex64); auditor faster.
- index_source prunes previous versions of a re-ingested source; 'blocked' is a legitimate gate state; tables/CSV keep their shape through chunking; CLI edge cases fixed (archive, gc, export, drive_links, publisher, drift).

## [2026-06-10] License | MIT + contributing guide

- [LICENSE](../../LICENSE): MIT — free for any use, modification and redistribution.
- [CONTRIBUTING.md](../../CONTRIBUTING.md): ground rules (English official, per-language output tables with key parity, determinism, gates green, no personal data, persisted identifiers frozen) and the wiki/<topic> PR workflow.
- README license section updated; runtime-path references in the command reference made audit-compliant.

## [2026-06-10] English as the official language | core + README + Drive rule

- Toolkit core fully in English (docstrings, comments, CLI/error messages, deep-read prompt — same v1, cache keys unaffected). Generated OUTPUT stays in the configured language; the insight proposal generator gained its per-language string table (was hardcoded Portuguese).
- New root [README.md](../../README.md): the meta-wiki is the official documentation; quickstart, principles, doc map. Last two templates and the E2E fixtures translated.
- Drive rule completed in the kit: [scripts/wiki_drive_publish.py](../../scripts/wiki_drive_publish.py) + `wiki_core/drive_links.py` + [.env.example](../../.env.example) (non-versioned artifacts live in a personal Drive folder; wiki pages point to the Drive link via the versioned manifest).
- Personal-only tests excluded; per-repo test skipif'd. 216 tests green, gates green.

## [2026-06-10] P1/P2 closure | Physical archiving + freshness budget + doc-code gate

- [scripts/wiki_archive.py](../../scripts/wiki_archive.py): physically archives resolved proposals (superseded/rejected) and their events into ingestion/archive/ via git mv, transitioning the gate to archived, adding stale_exempt and rewriting inbound links/refs.
- Freshness budget gate: `audit.freshness_budget` in wiki.config.yaml — the audit FAILS when total stale pages exceed the budget (0 disables; off by default in the kit).
- Doc-code gate: every tracked `wiki_*.py` CLI must appear in [command-reference.md](wiki/command-reference.md) and vice versa (errors both ways).

## [2026-06-10] P2 | Robustness: content chunking, deterministic dir-hash, NFKD slugify, drift check

- chunking.py: content-based boundaries (paragraphs/lines) instead of a fixed word window — editing one paragraph only changes that paragraph's chunk (was rebuilding all downstream); structure preserved. cache.py: cache_key no longer includes the whole-source hash — identical chunks dedupe across versions/sources (was invalidating 100% of the cache on any edit). Finding 4.
- source_manifest.py: deterministic sha256_directory_listing (no mtime, no dotfiles) — directory-source source_id now matches between local and clean clone/CI. Finding 3.
- ids.py: slugify normalizes accents (NFKD); accent collisions gone.
- [scripts/wiki_toolkit_drift.py](../../scripts/wiki_toolkit_drift.py): detects toolkit drift between branches (main vs opensource).

## [2026-06-10] P1 | Scale: incremental index + orphan GC + faster auditor

- index/sqlite.py: `index_source` reindexes ONE source incrementally (was a full FTS rebuild per ingestion); `build_index` prunes sources whose chunks file is gone; new `prune_index`. Pipeline uses the incremental path.
- [scripts/wiki_gc.py](../../scripts/wiki_gc.py): garbage-collects orphan derived artifacts (old source versions not referenced by a live proposal) + prunes the index. Dry-run by default; refuses to delete when no live source is found.
- wiki_audit.py: `tracked_files` memoized (was ~8x/run, ~16 git forks per audit).

## [2026-06-09] P0 | Cost: Batches exporter + operating discipline

- [scripts/wiki_export_batch.py](../../scripts/wiki_export_batch.py): exports pending LLM context packets in the Message Batches API format (-50%), deterministically and WITHOUT an LLM client (respects delegating intelligence to the agent). `custom_id` = chunk `cache_key`.
- New meta-wiki page [memories/system/wiki/operation-costs.md](wiki/operation-costs.md): where the cost actually goes (agent session and human time dominate; ingestion is pocket change) and the levers (session discipline, budget alert, Batches, model by profile). Registered in the meta-wiki index.

## [2026-06-09] setup | Open-source kit initialized

- Living wiki initialized from the reusable kit: deterministic core in
  [wiki_core/](../../wiki_core/), `wiki_*` CLIs in [scripts/](../../scripts/),
  portable skills in [.skills/](../../.skills/) and templates in
  [docs/references/templates/wiki/](../../docs/references/templates/wiki/).
- Example context created ([example/index.md](../example/index.md)); contexts
  are configurable in [wiki.config.yaml](../../wiki.config.yaml).
- Active gates: audit, coverage, cockpit and core tests.

## [2026-06-09] i18n | Open-source project fully in English

- `language: en` set in [wiki.config.yaml](../../wiki.config.yaml); the generated
  cockpit ([operations.md](../operations.md)) is now rendered in English via the
  language-keyed string table in [wiki_operation_compile.py](../../scripts/wiki_operation_compile.py).
- All authored content translated to English: [AGENTS.md](../../AGENTS.md), every
  page under [memories/](..) (methodology pages, meta-wiki, perceptive layer,
  example context and event), the `wiki-*` skills, the page templates under
  [docs/references/templates/wiki/](../../docs/references/templates/wiki/),
  [docs/README.md](../../docs/README.md), the PR template and config comments.
- Language-dependent gate checks made bilingual so English content passes: the
  coverage required mentions are language-keyed, and the quadrants section/names
  accept Portuguese or English ([wiki_audit.py](../../scripts/wiki_audit.py),
  [wiki_check_methodology_coverage.py](../../scripts/wiki_check_methodology_coverage.py)).
