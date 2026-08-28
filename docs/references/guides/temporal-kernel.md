# Temporal kernel contracts

The temporal kernel separates two questions that used to share one partial
feed:

- `timeline.json` (`activity_timeline.v1`) answers **what the repository or
  operator recorded**. Its legacy schema name and event kinds remain readable.
- `temporal_graph.json` (`wiki_temporal_graph.v1`) answers **what happened, when
  it was recorded or valid, what changed, and which source/evidence supports
  it**.

The static snapshot always writes the complete temporal event set. The same
builder supports cursor pages for a future HTTP transport, but a static build
never advertises a `next_cursor` that it cannot resolve.

## Versions

| Contract | Version | Compatibility rule |
| --- | --- | --- |
| Repository activity | `activity_timeline.v1` | `timeline.json.schema_version` remains `wiki_web_timeline.v1`; `contract_version` names the new boundary and old event kinds are unchanged. |
| Canonical event | `wiki_temporal_event.v1` | All non-null temporal values carry an explicit precision. Unknown event kinds fail until registered. |
| Temporal graph | `wiki_temporal_graph.v1` | `event_count`, `total_count`, summary totals and full-range totals must agree; page counts must reconcile exactly. |

Published JSON Schemas:

- [Temporal event v1](../schemas/wiki-temporal-event-v1.schema.json)
- [Temporal graph v1](../schemas/wiki-temporal-graph-v1.schema.json)

The graph schema is an offline, self-contained consumer artifact: its
`$defs.temporal_event` is the exact executable event contract and its event
array uses only an internal `$ref`. A normal Draft 2020-12 validator therefore
does not need network access, a custom URI registry or a resolver pointed at a
placeholder domain. Tests bind the embedded definition to the standalone
event schema so the two published entry points cannot drift silently.

The runtime parser in `wiki_core/temporal.py` remains authoritative for
cross-field rules that JSON Schema cannot express, such as precision agreement,
date conflicts and the public privacy boundary.

## Canonical event

Every event contains stable typed references and these separate clocks:

| Field | Meaning |
| --- | --- |
| `occurred_at` | When the real-world event happened. |
| `recorded_at` | When the wiki or repository learned/recorded it. |
| `valid_from`, `valid_to` | Interval in which a fact or state is considered true. |
| `created_at` | When a tracked object was created. |
| `due_at` | When an obligation is due. |
| `completed_at` | When work ended. |
| `verified_at` | When evidence was checked. |
| `ingested_at` | When a source entered the ingestion flow. |
| `superseded_at` | When a fact/version stopped being current. |

Accepted values are `YYYY`, `YYYY-MM`, `YYYY-MM-DD`, or an ISO-8601 instant
with an explicit timezone. The normalized event mirrors each non-null field in
`precision` as `year`, `month`, `day`, or `instant`; a year is never rewritten
as January 1 and a timezone-less clock is rejected.

The `anchor` is a derived navigation field with `{field, value, precision}`. It
selects one real event clock for sorting without replacing the other clocks.
An event with no temporal value has `anchor: null` and contributes to
`range.undated_count`.

Definite contradictions remain visible instead of being dropped. For example,
`due_at` definitely before `created_at` yields
`temporal_conflicts: ["due_at_before_created_at"]` and
`confidence: conflicting`. Imprecise intervals only conflict when their
possible ranges do not overlap.

## Graph envelope and pagination

The shared graph envelope can represent a future cursor-paginated HTTP result;
the following example demonstrates that transport shape. It is **not** a valid
static snapshot result. A committed `temporal_graph.json` must instead have
`returned_count == total_count`, `truncated: false`, `next_cursor: null` and
`page.remaining_count: 0` because the current cockpit has no temporal paging
endpoint.

The stable envelope is:

```json
{
  "schema_version": "wiki_temporal_graph.v1",
  "event_schema_version": "wiki_temporal_event.v1",
  "revision": "sha256:...",
  "event_count": 581,
  "total_count": 581,
  "returned_count": 160,
  "truncated": true,
  "next_cursor": "...",
  "page": {
    "offset": 0,
    "limit": 160,
    "remaining_count": 421,
    "fingerprint": "..."
  },
  "range": {
    "from": "2020",
    "to": "2026-07-11T15:10:00Z",
    "from_precision": "year",
    "to_precision": "instant",
    "event_count": 581,
    "dated_count": 579,
    "undated_count": 2,
    "basis": "full_result"
  },
  "returned_range": {
    "basis": "returned_page"
  },
  "summary": {
    "scope": "full_result",
    "event_count": 581
  },
  "diagnostics": [],
  "events": []
}
```

The cursor binds its offset to the SHA-256 fingerprint of the complete ordered
event set. Reusing it after that set changes fails as a stale cursor. A result
is never silently capped:

- `event_count == total_count == summary.event_count == range.event_count`;
- `offset + returned_count + remaining_count == total_count`;
- `returned_count == events.length`;
- `truncated == (remaining_count > 0) == (next_cursor != null)`.

For a static snapshot, publication adds the stronger invariant
`returned_count == total_count`, `truncated == false`, and
`next_cursor == null`. Bounded UI windows and filtering therefore operate over
the complete local result. A later server endpoint can call the same paginator
with `limit <= 500` without changing the event or cursor grammar.

## Current adapters

| Input read model | Events emitted when evidence exists |
| --- | --- |
| Page | `page_updated` from `updated_at`/`recorded_at`. |
| Source lifecycle | `source_configured`, `source_ingested`, `source_refreshed`, `source_pipeline_advanced`, and a reviewed-no-change receipt. |
| Ingestion event | `ingestion_recorded` with separate occurred, recorded, verified and ingested fields. |
| Action | Created/due/completed/cancelled events, append-only state transitions and receipt events. |
| Decision | `decision_made` only with an explicit occurrence/decision date; otherwise the honest `decision_recorded`. |
| Activity compatibility | Snapshot and Git events become `snapshot_recorded` and `git_commit_recorded`; unknown legacy kinds become `activity_recorded` with `origin.legacy_kind`. |

Adapters never parse prose dates or infer historical state from current state.
They emit only typed IDs, bounded state maps and date metadata. Invalid adapter
input becomes a code-only diagnostic; values are not echoed.

## Privacy boundary

Event references must follow `type:value` syntax. Free-form or malformed legacy
references are replaced by stable opaque digests before diagnostics or output.
The event parser always blocks access-secret findings. It also blocks PII and
entity findings for `visibility: public` or an explicit public-export parse.
Private events may retain personal identifiers in their private source pages,
but the temporal read model still avoids body text, labels and arbitrary prose.

## Integration boundary

The snapshot manifest advertises `temporal_graph` and pins these versions under
`manifest.versions`: `activity_timeline`, `temporal_event`, and
`temporal_graph`. Consumers must load and integrity-check `temporal_graph.json`
before they expose a Temporal/Chronoscope surface. Consumers that have not yet
adopted it may continue using `timeline.json`; they must not treat that activity
feed as semantic history.

## Chronoscope consumer contract

The bundled cockpit treats Chronoscope as the fifth native view and lazy-loads
the graph only when that view opens. The WebGL host remains mounted but is
suspended and inert while the 2D surface owns the workspace. Three strict modes
answer different questions without clock fallback:

- semantic event anchor — the event's declared navigation/sort clock;
- occurred — only `occurred_at`;
- recorded — only `recorded_at`.

Date ranges, typed lanes and `time_cursor` are shareable URL state. An invalid
range, stale cursor, unsupported version, torn manifest, integrity mismatch or
partial payload has its own visible state; none becomes an apparently healthy
empty history. The inspector preserves every published clock, precision,
before/after state, confidence, actor, cause, supersession and typed reference.
Keyboard events use one roving tab stop and mobile selection moves focus to the
inspector. Static lists expose bounded windows and honest total counts rather
than mounting hundreds of rows at first paint.

Experience packs may contribute temporal-profile descriptors. Composition v1
does not yet carry enough renderer/filter configuration to apply them, so the
generic pack workbench routes to the complete Chronoscope and says explicitly
that the profile is not mounted. Profile-specific visualizations are a future
adapter contract, not inferred behavior.
