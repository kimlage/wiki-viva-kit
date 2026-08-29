# Contributing

Contributions are welcome — bug fixes, portability improvements, new gates,
docs. The kit is MIT-licensed: by contributing you agree your contribution is
licensed under the same terms (see [LICENSE](LICENSE)).

## Ground rules

1. **English is the official language** for code, comments, messages and docs.
   Generated output (cockpit, proposals) is rendered per `language` in
   [wiki.config.yaml](wiki.config.yaml) via per-language string tables — when
   you add a generated string, add it to the `en`, `es` and `pt` tables (a
   parity test enforces matching keys and placeholders across all three).
2. **Determinism first** — the toolkit never calls a language model. Deep
   reading is delegated to the agent that runs the repo. Don't add LLM clients.
3. **Honesty gates must stay green** — before opening a PR, run:
   ```sh
   python -m pytest tests/ -q
   python3 scripts/wiki_audit.py --check
   python3 scripts/wiki_check_methodology_coverage.py --check
   python3 scripts/wiki_operation_compile.py --check
   ```
4. **No personal data** — this branch carries zero personal context by design.
   Test data must be synthetic and neutral. Secrets are blocked everywhere by
   the auditor.
5. **Persisted values are frozen** — badge ids, event types, gate states,
   dimension keys and generated frontmatter values are identifiers written to
   ledgers and pages; never rename them (add display-string tables instead).
6. **Layout comes from config** — directory and file names are read from
   `paths.*` in [wiki.config.yaml](wiki.config.yaml) (`WikiConfig` in
   [wiki_core/config.py](wiki_core/config.py)). Defaults are English; localized
   repos pin their own names in config. Never hardcode layout paths in code.

## Workflow

- Branch from `opensource/wiki-viva-kit` using the `wiki/<topic>` convention
  (tool-neutral — any agent or human follows the same flow).
- One topic per PR, with tests. CI runs the same gates listed above.
- Document any new `wiki_*.py` CLI in
  [memories/system/wiki/command-reference.md](memories/system/wiki/command-reference.md)
  — the doc-code gate fails otherwise (both directions).

## Where things live

- Deterministic core: [wiki_core/](wiki_core/) · CLIs: [scripts/](scripts/)
- Official docs (the meta-wiki): [memories/system/wiki/](memories/system/wiki/index.md)
- Agent entry point: [AGENTS.md](AGENTS.md)
