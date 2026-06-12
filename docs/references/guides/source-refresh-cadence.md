# Source Refresh Cadence

Updated on: 2026-06-12

This guide defines how a wiki page declares when a source should be read again.
The goal is to control quality and cost: refresh sources when they are likely to
change or when an open workflow needs readback, without repeating stable context
inside every page.

## Frontmatter

Use these fields on `page_type: source`, `source_catalog` and `artifact` pages:

| Field | Meaning |
| --- | --- |
| `last_ingested_at` | Last date the source was actually read or verified. |
| `refresh_policy` | `recurring`, `event_driven`, `on_demand` or `archival`. |
| `refresh_cadence_days` | Number of days after the last read when review should be suggested. |
| `next_refresh_at` | Optional explicit override when a known event drives the next read. |
| `refresh_trigger` | Short human cue for why/when the source should be refreshed. |
| `refresh_priority` | Optional `high`, `medium` or `low` for operator triage. |

The source registry uses `last_ingested_at` when present, otherwise `updated_at`,
adds `refresh_cadence_days`, and prints `Next refresh` plus `Status`. An explicit
`next_refresh_at` wins over the calculated date.

## Suggested Cadences

| Source shape | Policy | Cadence | Trigger |
| --- | --- | --- | --- |
| Financial live systems, open ledgers, dashboards | `recurring` | 1-7 days | New transactions, open month, or required readback. |
| Active project drives or folders | `recurring` | 7-14 days | New docs, delivery checkpoint, or stakeholder request. |
| Email inbox searches | `recurring` or `event_driven` | 7-30 days | Incremental search window or new topic. |
| Chat exports | `event_driven` | 21-30 days | New official export or known decision thread. |
| Public reference pages | `on_demand` | 30-90 days | Public-facing update, claim validation, or publication. |
| Historical immutable artifacts | `archival` | 180+ days | Only when a conflicting source appears. |

## Meetings

Meeting pages are not canonical source pages by default, but they should use the
same freshness fields. If a meeting created decisions or actions, set
`next_refresh_at` within two days after the meeting. If an action remains open,
use `refresh_cadence_days: 7` until the action is closed or linked to another
tracker.

## Obsidian Links

Markdown links to local directories are fragile in Obsidian. Link a concrete
index file instead, such as `README.md` or `index.md`. The audit warns when it
finds directory links so repos can migrate gradually.
