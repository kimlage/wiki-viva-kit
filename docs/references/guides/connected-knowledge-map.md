---
title: "Connected knowledge map"
page_id: guide-connected-knowledge-map
page_type: reference_guide
context: system
visibility: public_candidate
updated_at: 2026-10-07
stale_after_days: 90
sources_policy: implementation_and_synthetic_browser_evidence
gate: github_pr
sensitive_data_policy: no_personal_data
---

# Connected knowledge map

Open **Connected knowledge · 2D** from the cockpit, or use
`/w?projection=2d`. The public synthetic equivalent is
`/demo/w?projection=2d&tour=0`. This optional projection reads the same
integrity-checked revision and canonical PageReader as the existing world.
It does not write pages, refresh sources, approve work or invoke the operator.

## Everyday navigation

1. Start with the connected overview. Search uses the complete page index,
   including pages outside a bounded drawing. Selecting a result opens its
   summary and preserves the current map focus.
2. Switch between **Connections**, **Areas**, **Sources** and **Work**. They
   rearrange the same recorded graph by connection/context or page type.
   Positions do not represent evidence strength, urgency or an inferred
   dependency. Selection, revision, explicit focus and canonical reading
   survive perspective changes, reload and browser history.
3. Choose **Focus on this page** for its recorded neighborhood. **Expand
   connections** adds adjacency of a reachable selected page. **Overview**
   restores the global drawing and retains selection.
4. Use **Sources** in the inspector to follow declared source references.
   An unavailable reference stays visibly unresolved. **Read page** opens the
   canonical Markdown in the same inspector; its expand control provides
   comfortable reading. Source references are declared links, not a claim
   that every statement has a quotation-level citation.
5. Select a connection to read its human label, recorded endpoints,
   direction and provenance. **Original record** exposes its complete graph
   record, including raw type, ID, weight and metadata. Parallel and reciprocal
   records stay distinct. Only explicitly directed edges receive arrows or
   directional signals; missing direction is never inferred.

The color legend explains area, category or the selected existing state
metric. Connection chips emphasize a type without deleting other records.
Relation colors and stroke patterns match the connection legend; arrows
appear only for recorded direction. Hover or keyboard focus previews a page
and its drawn neighbors, or a connection and its two endpoints, while dimming
the rest. The human preview's action opens the summary or exact provenance;
hover alone keeps the selection, reader, focus and URL. A brief pointer corridor
keeps the same record while moving into its preview, even across another band.
A short canvas places the preview at the viewport's
bottom so it does not block the page that opened it. Click or touch pins the
selection across perspectives.
Click an empty part of the drawing or press Escape in the map to clear it while
preserving the map focus. Dragging the background pans without clearing the pin.
Use the wheel or zoom controls, and choose **Fit map** to recover the overview.
Camera coordinates and previews remain ephemeral.

Keyboard access uses `/` for search, Arrow Down for the first result, Enter to
select, and arrow keys to move among map nodes. `E` reaches a node's first drawn
connection; arrow keys move among connections and Enter or Space pins one.
Tab enters the preview controls and Shift+Tab returns to its trigger. There is
one tab entry for nodes and one for connections, rather than one per record.
`+`/`−` zoom and Home fits. Escape in the map clears its highlight and selection;
search and the canonical reader retain their own Escape behavior.
The embedded reader keeps its existing `F` expansion and dialog focus behavior.
The list offers the same drawn pages without requiring spatial selection.

## Bounded drawing and movement

The renderer draws at most 180 overview pages, 64 focus pages and 900
connections. True snapshot totals and omitted/unresolved counts remain
visible. Selected pages and connection endpoints are pinned in large
overviews. The complete index and selected page's incident records remain
available; long relation lists reveal another 100 records at a time.

Layout is deterministic and finite. A perspective change interpolates
positions for 420 ms and camera fitting for 320 ms; there is no force
simulation running while idle. At most eight directional signals animate
on explicitly directed selected relations. **Direction signals** can be
paused. `prefers-reduced-motion` and a hidden document disable movement.
These signals indicate recorded orientation, not live data processing or
traffic. Labels are placed without overlap where they fit; full titles stay
available through accessible node names, search and the inspector.

Pausing movement, enabling reduced motion or hiding the document during a fit
finishes its pending camera destination. A later manual pan or zoom cancels that
destination, so pausing cannot restore an obsolete fit. Connection hit bands
remain 18 screen pixels; parallel curves between distinct pages retain their
spacing when zooming out,
and the visible center of a curve takes precedence over another hit band.
At very low zoom, nodes or overlapping curves can still cover a connection.
Zoom in or use keyboard navigation and the inspector's recorded connection list.
The drawing does not promise a separate pointer region for every dense record.

## Route compatibility

Existing `projection=2d`, `map_focus`, `map_view`, `map_expand`, `map_color`
and `map_edge` bookmarks remain readable. An older explicit-focus bookmark
keeps neighborhood scope. A fresh projection entry starts with overview.
The additive query fields are:

| Field | Values | Meaning |
| --- | --- | --- |
| `map_perspective` | `network`, `areas`, `evidence`, `work` | Geometry perspective |
| `map_scope` | `all`, `focus` | Global drawing or recorded neighborhood |
| `map_relation` | Original relation type, up to 120 characters | Visual emphasis |

The registered world view and real `center` remain independent of map focus.
**3D world** returns the selection/reader to the existing cockpit and clears
projection-specific fields. Crafted docks, trays and pack surfaces are
stripped before the read-only projection is exposed; the router's existing
primary-surface precedence remains authoritative.

## Upgrading

Pin the independently reviewed kit PR head or its approved merge SHA. Use
the [normal downstream runbook](wiki-viva-v8-downstream-upgrade.md): B0 dry-run,
one consumer PR, C1 tracked kit-owned copy and its declared deterministic C2.
This increment adds frontend files and additive URL state. It changes no
snapshot schema, page contract, canonical relation, source lifecycle or
backend endpoint. Existing v8 snapshots need no data migration. There is no
map-specific C3 command; retain any C3 required by an older consumer baseline.

Build the cockpit from the pinned source, run kit and consumer gates, then
read back overview → selected page → sources → canonical reading → focus →
another perspective → Back/Forward on the consumer's own local environment.
Keep private URLs, data and screenshots in the private consumer. Run B0 again
to verify idempotence. Promote only after the consumer's own PR review policy.
Rollback uses its normal revert PR; original 3D routes remain available.

## Implementation and checks

- [Projection/index/layout](../../../apps/wiki-cockpit/src/scene/integratedMap.ts)
  preserves the original graph records and exposes bounded coverage.
- [Map interface](../../../apps/wiki-cockpit/src/components/FocusMapView.tsx)
  uses the existing navigation and canonical-content ports.
- [Canvas](../../../apps/wiki-cockpit/src/components/ConnectedMapCanvas.tsx)
  implements finite movement, pointer/focus previews, keyboard nodes/connections
  and pan/zoom. Its [camera regressions](../../../apps/wiki-cockpit/src/components/ConnectedMapCanvas.test.tsx)
  cover pause, reduced motion, visibility and manual interruption.
- [Model tests](../../../apps/wiki-cockpit/src/scene/integratedMap.test.ts)
  prove record parity, deterministic order, real adjacency, missing endpoints,
  dense parallel/self edges and bounded synthetic 10,000-page input.
- [Browser journeys](../../../apps/wiki-cockpit/e2e-prototypes/focus-map.spec.ts)
  exercise canonical integrity failures, read-only request boundaries,
  perspective/history/source navigation, legends, pointer curves, keyboard,
  mobile geometry and reduced motion.

With a local production preview already running on port 4297:

```sh
cd apps/wiki-cockpit
npx playwright test --config=playwright.focus-map.config.ts
```

`WIKI_MAP_QA_BASE_URL` can select another isolated local preview. The dedicated
journeys supplement the normal project gates; they do not replace or relax
privacy, architecture, snapshot or CI checks. The validation is a targeted
browser/accessibility check, not a claim of complete WCAG conformance.
