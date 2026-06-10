---
page_id: system-memories-log
page_type: system_log
context: system
visibility: private_self
updated_at: 2026-06-09
stale_after_days: 180
sources_policy: append_only_memory_changes
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
---

# Memory log

Append-only record of changes in the [memories/](..) layer.

## [2026-06-10] Rich representation by default + meta-wiki integrated as first-class

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
