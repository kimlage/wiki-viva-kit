# Skills

Portable kit skills (`wiki-*`), generic and free of personal names — copyable
to another repo without deep adjustments.

## Reusable kit (`wiki-*`)

- `wiki-memory-router` — loads the wiki and routes context.
- `wiki-ingestion-agent` — source -> normalized event -> proposal.
- `wiki-llm-context-agent` — performs the contextual LLM pass (delegated to the
  agent that runs the repo) and records the result in the cache.
- `wiki-operation-compiler` — maintains the cockpit [memories/operations.md](../memories/operations.md).
- `wiki-source-auditor` — source traceability.
- `wiki-privacy-publication` — separates private from public.
- `wiki-raw-drive` — fetches/downloads raw sources from a single Drive folder
  (raw is never versioned).

## Per-repo local profile

Each repo adopting the kit can add its own specific skills (local profile, e.g.
a `repo-*` or `<name>-*` prefix) alongside the `wiki-*` ones. Keep the local
profile separate so the kit stays copyable.
