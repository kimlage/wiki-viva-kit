---
title: "Wiki Viva v6.9.1"
page_id: release-wiki-viva-v6-9-1
page_type: release_note
context: system
visibility: public_candidate
updated_at: 2026-07-07
stale_after_days: 365
sources_policy: release_note
gate: github_pr
sensitive_data_policy: no_personal_data
---

# Wiki Viva v6.9.1

Canonical quadrant flight + recursive company demo patch for the open-source
kit. This is the versioned bridge for later downstream migration into private
wikis; no private repository is changed by this release.

## What Changed

- **Canonical visual order.**
  [apps/wiki-cockpit/src/scene/facets.ts](../../../apps/wiki-cockpit/src/scene/facets.ts)
  now maps the quadrant scene/minimap coordinates to the Wilber/AQAL screen
  order: Q1 upper-left, Q2 upper-right, Q3 lower-left, Q4 lower-right. The HUD
  compass, scene labels, minimap and quadrant floor planes all derive from the
  same angles.
- **Quadrant camera flight.**
  [CameraDirector](../../../apps/wiki-cockpit/src/scene/parts/camera.tsx)
  now reacts when `layout.cameraTarget` changes, so changing
  `?quadrant=<facet>` animates the camera to the selected region even when the
  perspective itself stays `quadrants`.
- **Richer recursive company example.**
  [scripts/wiki_build_demo.py](../../../scripts/wiki_build_demo.py) expands
  `Clearpath Labs` as a company root under Alex Rivera. The company is Q4 from
  Alex's root, but becomes its own center with Q1 intent, Q2 evidence/metrics,
  Q3 lived roles and meetings, and Q4 process/governance.
- **Methodological pin.**
  The release keeps the Q0/Q2/Q4 classification contract from v6.9: Q0 is only
  the active center, sources/logs/evidence are Q2 when they are observable
  traces, and operational rules/processes/configuration are Q4 coordination.

## Migration Boundary

Use this release as the public, synthetic proving ground before applying the
same quadrant/camera/demo semantics to a private downstream wiki. Do not move
private data into this repo; migrate code and generic templates only.

## Validation

```sh
python3 scripts/wiki_build_demo.py
python3 -m pytest tests/test_build_demo.py tests/test_template_blocks.py
npm --prefix apps/wiki-cockpit test -- --run src/scene/facets.test.ts src/scene/perspectives.test.ts
```
