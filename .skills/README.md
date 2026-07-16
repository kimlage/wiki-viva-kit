# Skills

Portable kit skills (`wiki-*`), generic and free of personal names — copyable
to another repo without deep adjustments.

## Start here — the single install (`wiki-viva`)

- **`wiki-viva`** — the **entry skill**: install this one to both *configure*
  and *operate* the whole living wiki. It carries the full lifecycle (adopt →
  configure → input stage → ingest → deep read → consolidate → cockpit → gates → PR) with
  bundled references, and points to the focused skills below when you need the
  full procedure for a single step. You do not need the others installed to
  operate.

## Focused playbooks (`wiki-*`)

Optional depth for individual steps; `wiki-viva` orchestrates them.

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

In the current simple upgrade flow, toolkit-owned
[.skills/wiki-*/**](wiki-viva/SKILL.md) directories are byte-equal C1. The
consumer's root [.skills/README.md](README.md), [AGENTS.md](../AGENTS.md),
routers and non-`wiki-*` skills are reviewed C3 routing policy; the root index
is named literally because [.skills/*/**](wiki-viva/SKILL.md) intentionally
matches only nested skill packages. A changed C3 skill surface is reviewed as a
consumer-owned PR change. Core upgrades use the idempotent
`wiki_sync_from_kit.py` B0/apply flow and `kit.lock`, not the retired
lane/capsule runner.

The portable skills assume hierarchical navigation by default: root MOC ->
context/domain hub -> entity/subdomain hub -> relation/evidence pages ->
execution/event pages. Relation pages must declare `moc_parent` so multiple
repos can reuse the kit without accumulating parallel, disconnected pages.
Repos on v6.8+ also declare a semantic `root_entity` page and compile the
generated input stage before source routing.
