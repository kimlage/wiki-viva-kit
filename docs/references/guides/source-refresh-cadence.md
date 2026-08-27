# Source Refresh Cadence

Updated on: 2026-08-27

This guide defines how a wiki page declares when a source should be read again.
The goal is to control quality and cost: refresh sources when they are likely to
change or when an open workflow needs readback, without repeating stable context
inside every page.

## Frontmatter

Use these fields on `page_type: source`, `source_catalog` and `artifact` pages:

| Field | Meaning |
| --- | --- |
| `source_kind` | `item`, `collection`, `account`, `endpoint` or `repository`; defines what an update inventories. |
| `last_ingested_at` | Last date the source was actually read or verified. |
| `refresh_policy` | `recurring`, `event_driven`, `on_demand` or `archival`. |
| `refresh_cadence_days` | Number of days after the last read when review should be suggested. |
| `next_refresh_at` | Optional explicit override when a known event drives the next read. |
| `refresh_trigger` | Short human cue for why/when the source should be refreshed. |
| `refresh_priority` | Optional `high`, `medium` or `low` for operator triage. |

The source registry uses `last_ingested_at` when present, otherwise `updated_at`,
adds `refresh_cadence_days`, and prints `Next refresh` plus `Status`. An explicit
`next_refresh_at` wins over the calculated date.

## Recipe and stream freshness

The current source-entity model adds a machine-readable `recipe:` block to the
source's `source_config` page. The recipe is the primary operational contract
for synchronization and declares:

| Field | Meaning |
| --- | --- |
| `pipelines[].cadence_days` | Default cadence for metadata or content processing. |
| `streams[]` | Selected folders, channels, labels, tabs or repository slices. |
| `streams[].cadence_days` | Optional stream override; `0` inherits the content pipeline cadence. |
| `streams[].filters` | Explicit scope of the next read. |
| `streams[].target_pages` | Memory pages that the stream is responsible for keeping current. |
| `auth` | Pointer to an authorized mechanism; never the credential itself. |
| `schedule` | `one_shot`, `on_demand`, `recurring` or `event_driven`; defines whether time can make work due. |

The cockpit computes stream freshness from the cursor state written after a
successful deterministic source pass. That mutable cursor is a processing
checkpoint, not canonical integration proof. The closed ingestion event and
versioned successful `sync:` receipt provide that proof and survive a clean
clone. For exactly one selected stream, the receipt is also the safe freshness
fallback; multiple selected streams still require individual cursors. A
recurring schedule is the only mode that can mark work as due solely because
time passed. `one_shot`, `on_demand` and `event_driven` keep the last factual
ingestion state without becoming stale on a clock. A schedule never grants
access or fetches a live system without an authorized connector or exported RAW.
The legacy frontmatter remains visible in the source registry so existing
consumers can migrate without losing their previous freshness signal.

## Registration is not ingestion

A source page can exist in the wiki before its content has been ingested. In
that narrow case, the honest state is **registered, not yet ingested**: there is
no `last_ingested_at`, successful sync receipt or closed ingestion event yet.
Once any of that evidence exists, the source must not remain `never_synced` or
`sync.last_status: never`; migration and snapshot compilation derive the
factual successful or partial state instead of presenting contradictory
metadata. The interface uses the same wording so “exists in the catalog” is
never confused with “content was integrated into the wiki.”

## Operating sources in the cockpit

Open a source with `?dock=source&src=<source-id>`. The source workspace has four
tabs and does not mix source operations with the world's navigation controls:

| Tab | Operational purpose |
| --- | --- |
| Records | Select an exact recipe record and inspect its deterministic metadata, processing state, privacy and target pages. |
| Update | Refresh the whole source scope and distinguish new records, content changes, metadata enrichment and an unchanged collection. |
| Configure | Edit source type and lifecycle plus governed record fields, review a content-bound preview, then explicitly confirm it. |
| History | Read immutable source-operation receipts produced by successful interface writes. |

Source-level configuration accepts only `source_kind`, `schedule_mode` and
`schedule_cadence_days`. Record-level configuration accepts only `label`,
`selected`, `privacy`, `cadence_days`, `processing_state`, `skip_reason` and
`target_pages`; it never
accepts credentials, arbitrary YAML, commands or paths. The preview token binds
the current config hash to the proposed result hash, so a changed recipe makes
confirmation fail closed.

The update planner derives the maximum useful deterministic inventory from the
entire source before contextual work. Selecting a record does not narrow an
update to one file. The planner chooses one of four routes:

1. `deterministic_connector`: `refresh.argv` runs a repository-owned Python
   adapter under `scripts/`. It queries the declared collection read-only and
   emits `wiki_source_inventory.v1` JSON with stable `external_id`, label and
   deterministic metadata. The core owns validation, comparison, selection,
   recipe patching and receipts; provider-specific access remains in the
   adapter. Metadata added to an already known record is reported as
   `enriched`, not as a content change, and does not reopen ingestion.
2. `script`: a repository script under `scripts/` receives a hashed RAW file or
   folder under `data/raw/`. Folders are inventoried recursively and
   deterministically before execution; the operator does not invoke a shell.
3. `agent_connector`: the declared `mcp_hint` is delegated through the selected
   Codex or Claude adapter only when that CLI is usable and exposes the named
   connector.
4. `manual_export`: the recipe explains what a human must export when neither a
   deterministic script nor connector is declared.

An available agent is not the same thing as an available connector. The
interface probes connector names without returning raw CLI configuration and
blocks delegation when the declared connector is missing. Successful
configuration, deterministic inventory or script operations write a redacted receipt under
`data/derived/wiki/source-operations/`; connector execution continues through
the existing governed job runner and human review gate.
## Suggested Cadences

| Source shape | Policy | Cadence | Trigger |
| --- | --- | --- | --- |
| Financial live systems, open ledgers, dashboards | `recurring` | 1-7 days | New transactions, open month, or required readback. |
| Active project drives or folders | `recurring` | 7-14 days | New docs, delivery checkpoint, or stakeholder request. |
| Email inbox searches | `recurring` or `event_driven` | 7-30 days | Incremental search window or new topic. |
| Chat exports | `event_driven` | 21-30 days | New official export or known decision thread. |
| Public reference pages | `on_demand` | 30-90 days | Public-facing update, claim validation, or publication. |
| Historical immutable artifacts | `one_shot` in the recipe (`archival` remains a legacy frontmatter value) | none | Only when a conflicting source appears. |

## Source type and lifecycle

Choose both fields explicitly:

| `source_kind` | Update scope |
| --- | --- |
| `item` | One immutable or individually addressed file/document. |
| `collection` | A folder, export bundle or set of records; refresh inventories the whole collection. |
| `account` | An authenticated account whose declared query/scope may yield multiple records. |
| `endpoint` | A URL, API endpoint or feed. |
| `repository` | A Git repository or repository-backed memory set. |

| `schedule.mode` | Time-based stale behavior |
| --- | --- |
| `one_shot` | Never stale by time after capture; use for immutable artifacts. |
| `on_demand` | Never stale by time; refresh only when an operator needs readback. |
| `event_driven` | Never stale by time; refresh when the declared external event occurs. |
| `recurring` | Uses `schedule.cadence_days > 0` and may become due when the cadence is exceeded. |

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
