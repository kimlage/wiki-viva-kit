# Sources — configure, register, and model external tools

Sources are first-class. Onboarding one is a small, repeatable process; external
tools (meetings, Jira cards, calendar events) become linked entity pages during
ingestion. Repo-path examples below use the kit's English defaults; in a
localized repo the paths differ — [AGENTS.md](../../../AGENTS.md) routes to them.

## Configure a source (the process)

1. **Create the source page** (page_type `source`) under the sources dir, with
   `source_type`, `ingestion_state` (`unread | partial | ingested | stale`) and
   `last_ingested_at`. This page is the hierarchical node that holds the source's
   ingestion log.
2. **Create its config page** (page_type `source_config`) under the sources
   `config/` subdir, holding that source's **ingestion rules** (how to fetch/
   extract, formats, frequency, what never to copy), **search rules** (how to find
   the relevant chunks), and **business rules** (domain logic — e.g. ledger
   append-only, readback required, dedup key). Point the source page's
   `config_ref:` at it (and the config page's `source_refs` back at the source).
3. **Register it.** Run `wiki_source_registry.py --write` so the source appears in
   the registry with its state, last update and a link to its config.
4. **Ingest.** Run the pipeline (see [operating.md](operating.md)). The deep-read
   **reads the source's config rules** and applies them — the rules live in the
   page (agent-consumed), not hardcoded in the toolkit.

The config page keeps the content/source page single-purpose: rules live in the
sidecar, linked, not inline.

## Model external tools as linked entities

When a source is a meeting, a Jira/board card, or a calendar event, create the
matching entity page so the wiki stays connected:

| Tool | page_type | Lives in (en / pt) | Links |
| --- | --- | --- | --- |
| Meeting | `meeting` | `meetings/` · `reunioes/` | participants (people), decisions, actions, source |
| Jira / ticket / board card | `external_card` | `cards/` · `cartoes/` | owner (person), decision/action, source |
| Calendar event | `calendar_event` | `calendar/` · `calendario/` | attendees (people), the meeting, source |

Templates for all of these ship under the templates dir (`meeting`,
`external-card`, `calendar-event`, `source-config`). Every participant/attendee/
owner named in the body becomes a **link to that person's page** — a name with no
link is a defect (the auditor warns).

**Connectors stay yours.** Pulling cards from Jira or events from a calendar is
the agent/skill's job (there is no external client in the Python toolkit). The
toolkit only models, links and audits the resulting entity pages.
