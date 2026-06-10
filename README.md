# Wiki Viva Kit (Living Wiki Kit)

A Markdown/Git-first **living operational wiki** with a deterministic Python core,
honesty gates in CI, and deep reading delegated to the AI agent that runs the
repo (Claude, Codex, Gemini or any other) — no LLM client embedded in the code.

The official language of this project is **English**. Generated pages and
artifacts (cockpit, ingestion proposals) are rendered in the language configured
in [wiki.config.yaml](wiki.config.yaml) (`language: en|pt`).

## What it does

- **Memory layer** in [memories/](memories/index.md): consolidated, auditable
  Markdown pages with frontmatter contracts (freshness, visibility, gate).
- **Ingestion pipeline**: source → deterministic manifest → stable chunks →
  FTS index → secret pre-scan (blocks BEFORE persisting) → LLM context package
  → normalized event → proposal that enters the human gate (GitHub PR).
- **Honesty gates in CI**: contract audit, methodology coverage, cockpit
  freshness, required LLM pass, freshness budget, doc-code drift — all
  deterministic (zero model tokens).
- **Operational cockpit** ([memories/operations.md](memories/operations.md)):
  compiled daily, self-verifiable (`--check` fails if semantically stale).
- **Karma layer**: 8-dimension operational scoring as a by-product, append-only,
  no toxic leaderboard.

## Quickstart

```sh
pip install -r requirements.txt

# 1. Configure your repo profile
$EDITOR wiki.config.yaml          # language, contexts, gates
$EDITOR wiki.targets.yaml         # context -> pages/entities map

# 2. Ingest a source end to end
python3 scripts/wiki_ingest.py --source path/to/source.md --context example

# 3. Run the gates (same ones CI runs)
python3 scripts/wiki_audit.py --check
python3 scripts/wiki_check_methodology_coverage.py --check
python3 scripts/wiki_operation_compile.py --check

# 4. Compile the daily cockpit
python3 scripts/wiki_operation_compile.py --write
```

The deep reading itself is performed by the agent that runs the repo: the
pipeline emits a `*-llm-context-request.json` package; the agent records results
back with `scripts/wiki_llm_context_pass.py --record-result` (provenance is
enforced). For batch/cheap processing, export pending requests with
`scripts/wiki_export_batch.py` (Anthropic Message Batches format, −50%).

## Official documentation

The **meta-wiki is the official documentation** — the living wiki documenting
itself, kept honest by the same gates:

| Page | Covers |
| --- | --- |
| [Meta-wiki index](memories/system/wiki/index.md) | Map of all documentation |
| [Architecture](memories/system/wiki/architecture.md) | Principles and module map |
| [Daily operation](memories/system/wiki/daily-operation.md) | The daily loop |
| [Ingestion flow](memories/system/wiki/ingestion-flow.md) | Source → consolidation |
| [Gates & audit](memories/system/wiki/gates-and-audit.md) | The honesty gates |
| [Privacy](memories/system/wiki/privacy.md) | PII free in private; secrets always blocked |
| [Costs](memories/system/wiki/operation-costs.md) | Where money goes + levers |
| [Command reference](memories/system/wiki/command-reference.md) | Every `wiki_*` CLI (gated against drift) |

Agent-facing entry point: [AGENTS.md](AGENTS.md).

## Layout

The tree is **English by default**: `memories/` (the wiki, one hub per context),
`memories/system/ingestion/` (proposals, `events/`, `archive/`),
`docs/references/` (templates, references, snapshots), `data/raw/` and
`data/derived/wiki/` (gitignored caches). Every directory and file name is
configurable via `paths.*` in [wiki.config.yaml](wiki.config.yaml) — see
`WikiConfig` in [wiki_core/config.py](wiki_core/config.py) for the full key
list. Localized repos pin their own names there (e.g. a Portuguese repo sets
`paths: {memory_root: memorias}`); the code never hardcodes layout paths.

## Principles

1. **Determinism first** — everything that can be deterministic is (hashing,
   chunking, index, gates). Intelligence lives in the agent, not in the toolkit.
2. **Honesty gates that bite** — claims about freshness/coverage are verified in
   CI, not asserted in prose.
3. **Privacy by boundary** — personal data is welcome on private pages; access
   secrets are blocked everywhere; PII blocks at the public boundary
   (`--public-export`).
4. **Human gate** — memory changes ship via PR (`wiki/<topic>` branches),
   reviewed by the owner.
5. **Language by config** — code and docs in English; generated pages in the
   configured language.

## License & contributing

**MIT** — free for any use, modification and redistribution; see
[LICENSE](LICENSE). Contributions are welcome under the same terms: see
[CONTRIBUTING.md](CONTRIBUTING.md). Personal-context-free by design — this
branch carries no personal data and its git history is clean (orphan).
