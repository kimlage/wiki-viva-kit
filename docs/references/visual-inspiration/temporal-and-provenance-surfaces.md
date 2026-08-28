# Temporal And Provenance Surfaces

Reviewed on: 2026-07-11

| Reference | Primary source | Target surface | Borrow | Reject | License/evidence |
| --- | --- | --- | --- | --- | --- |
| Observable Plot | [Official Plot documentation](https://observablehq.com/plot/), [accessibility contract](https://observablehq.com/plot/features/accessibility) and [license](https://github.com/observablehq/plot/blob/main/LICENSE) | Accessible 2D Timeline, freshness horizon, period comparisons | Layered marks, facets, transforms, SVG/HTML output and fast exploration of temporal encodings | One generic chart replacing the native semantic views; unexplained auto-chart choices | ISC; primary-source URL analysis only |
| NASA Open MCT Time Conductor | [Official Open MCT overview](https://ammos.nasa.gov/openmct/) | Chronoscope and synchronized view state | One visible time range/cursor driving multiple panels and clearly distinguishing live from historical | Per-widget clocks, silent truncation or playback implying history that was never stored | Open-source project; URL analysis only |
| Mapbox Maki | [Official repository](https://github.com/mapbox/maki) | Source landmarks, event kinds and pack map symbols | Small pixel-aligned cartographic landmarks with a restrained geometry | Using icons as the only carrier of state or stretching 15 px symbols into hero art | CC0-1.0 SVG sources; no asset vendored yet |

## Candidate visual grammar

```text
event point       = one typed event
lane              = entity, context, source, decision, action or pack
line/braid        = typed temporal or provenance relation
band              = validity, freshness, obligation or uncertainty interval
marker shape      = event kind
hue               = context or pack accent
tone/luminance    = current state or freshness
outline/focus     = current selection, never semantic state alone
```

The first temporal implementation should be a 2D, accessible freshness horizon
and page-life/provenance trace. A 3D time tunnel may become an optional theme,
but only after the same cursor, lanes and evidence are usable in the table/SVG
surface. Playback is forbidden until history can be reconstructed from Git or
is persisted as versioned snapshots; animation must never fabricate the past.
