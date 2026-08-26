# Wiki Viva Kit

Reusable kit for a **living operational wiki** in Markdown/Git, with source
ingestion, a per-PR honesty gate, secret/PII detection, karma gamification
and a perceptive layer. The deterministic code lives in Python; the deep
reading (LLM) is delegated to the **agent that runs the repo** (Claude, Codex, Gemini or
another) via skills — there is no embedded LLM client.

## How the agent should operate

- `main` is the approved wiki. Relevant changes go into a `wiki/<theme>` branch and
  pass through a **PR (human gate)**. The `wiki/` prefix is tool-neutral.
- The consolidated memory lives in [memories/](memories/index.md). [docs/](docs/README.md) holds
  references, templates and snapshots; [data/raw](data/raw) and
  [data/derived](data/derived) are cache (gitignored).
- The configured root entity is [memories/system/wiki-viva-kit.md](memories/system/wiki-viva-kit.md).
  It is the semantic top page of the wiki; [memories/index.md](memories/index.md)
  remains the technical MOC. The generated input stage is
  [memories/system/input-stage.md](memories/system/input-stage.md).
- Every source is declared by a `source` page and a linked `source_config` with
  a reviewed, secret-free recipe. Ingestion uses the orchestrator
  [scripts/wiki_ingest.py](scripts/wiki_ingest.py): manifest, text/chunks,
  index, pre-scan, input-stage-aware LLM context package and score-event. The
  LLM pass is written to the cache by the agent (skill
  [wiki-llm-context-agent](.skills/wiki-llm-context-agent/SKILL.md)); a closed
  ingestion event plus versioned sync receipt proves integration into memory.
- Core/toolkit corrections belong here first. Changes to [wiki_core/](wiki_core/README.md),
  [scripts/](scripts/README.md), [.skills/](.skills/README.md), templates, gates or shared
  ingestion behavior must be implemented in this open-source repo, covered by a
  synthetic fixture or unit test, and pass CI before being applied to private
  downstream repos.
- If a core bug is discovered in a private repo, reproduce the behavior here
  with minimized synthetic data. Do not use private financial, personal or
  client data as the proving ground for shared core behavior.
- Before opening a PR, run the local gates (see below) and review the conceptual diff.

## Privacy (two axes)

- **Personal data (PII)** — names, values, counterparties, dates, CPF/CNPJ: they are
  **welcome on private pages**, without warning (that is the goal of operational
  memory). They only become an error at the **public boundary** (public page/
  `public_candidate` or `--public-export` export).
- **Access secrets** — tokens, passwords, API keys, private keys, cookies:
  **always blocked, in any file** (detectors + auditor).

## Structure

- [wiki_core/](wiki_core/README.md) — deterministic core (config, chunking, detectors,
  extractors, gate, index, ingest, input_stage, insight, llm, paths, score,
  source_manifest).
- [scripts/](scripts/README.md) — `wiki_*` CLIs (ingest, audit, coverage, cockpit, gate,
  score, insight job, LLM pass).
- [.skills/](.skills/README.md) — portable `wiki-*` skills for the agent.
- [docs/references/templates/wiki/](docs/references/templates/wiki/README.md) — page
  contracts and templates.
- [memories/system/](memories/system/wiki/index.md) — method pages (ingestion process,
  contract, approvals, coverage, log, perception).

## Gates (run before the PR)

```sh
python3 scripts/wiki_audit.py --check
python3 scripts/wiki_audit.py --public-export --check
python3 scripts/wiki_check_methodology_coverage.py --check
python3 scripts/wiki_operation_compile.py --check
python3 scripts/wiki_input_stage.py --check
python3 scripts/wiki_source_registry.py --check
python3 scripts/wiki_operational_pass.py --check
python3 scripts/wiki_consolidate.py --check
python3 scripts/wiki_migrate_templates.py --pinned
python3 -m pytest tests/
npm --prefix apps/wiki-cockpit test
npm --prefix apps/wiki-cockpit exec -- tsc -p apps/wiki-cockpit/tsconfig.json --noEmit
npm --prefix apps/wiki-cockpit run build
```

- Audit: frontmatter, clickable links, secrets, PII at the public boundary,
  LLM pass gate, proposal gate_state — [scripts/wiki_audit.py](scripts/wiki_audit.py).
- Coverage: presence AND content of the method, real use of the perceptive layer —
  [scripts/wiki_check_methodology_coverage.py](scripts/wiki_check_methodology_coverage.py).
- Cockpit: [memories/operations.md](memories/operations.md) equal to the one recompiled at
  HEAD — [scripts/wiki_operation_compile.py](scripts/wiki_operation_compile.py).
- Input stage: [memories/system/input-stage.md](memories/system/input-stage.md) equal to the
  root entity/channel/source compilation at HEAD —
  [scripts/wiki_input_stage.py](scripts/wiki_input_stage.py).
- Source registry, operational pass and consolidation: generated source state,
  source/action/context resumption and zero read-but-unintegrated sources —
  [scripts/wiki_source_registry.py](scripts/wiki_source_registry.py),
  [scripts/wiki_operational_pass.py](scripts/wiki_operational_pass.py) and
  [scripts/wiki_consolidate.py](scripts/wiki_consolidate.py).
- Template pin report: every page type has the required fields without
  inventing provenance for generated dashboards or subjective journals —
  [scripts/wiki_migrate_templates.py](scripts/wiki_migrate_templates.py).

## Per-repo configuration

Adjust [wiki.config.yaml](wiki.config.yaml): `repo_id`, `owner_label`,
`root_entity`, `contexts` (one hub per context, in [memories/](memories/index.md)),
privacy policy, gate and LLM parameters. The auditor and the coverage read the
config — no context is hardcoded in the code.
