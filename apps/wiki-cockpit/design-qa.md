# Design QA — Anatta Worlds beauty slice

## Inputs

- Source visual:
  [reference shown in the comparison](.visual-qa/reference-vs-beauty-final.png)
- Implementation:
  [exterior](.visual-qa/beauty-hero-final.png)
- Interior:
  [Hydrology House](.visual-qa/beauty-interior-final.png)
- Combined comparison:
  [reference versus implementation](.visual-qa/reference-vs-beauty-final.png)

## Fixed findings

- P0 composition: moved from whole-basin overview to an authored, closer hero
  camera with river axis and module on the right third.
- P0 atmosphere: removed the blown white horizon, reduced exposure and fog,
  introduced colder fill, warm key, SSAO and constrained bloom.
- P0 raw primitives: replaced tree, rock and cliff placeholders with licensed
  photogrammetric assets and replaced the runtime box house with a reproducible
  first-party GLB shell.
- P1 spatial continuity: added an enterable opening, camera passage and an
  information surface projected on the interior wall.
- P1 budget: reduced the authored house to one asset path and held the exterior
  at 60 FPS, 95–96 calls and about 1.27 M triangles.

## Remaining P0 findings

- The terrain is still a mathematical heightfield instead of an authored,
  eroded landscape with splat and cliff masks.
- Water lacks depth-buffer shoreline interaction, obstacle-aware foam and
  local reflection/refraction comparable to the reference.
- Rock, sediment and wet-margin transitions do not yet form a continuous
  geological system.
- Vegetation has instancing and clustering but lacks sub-bosque and riparian
  species hierarchy.
- The Hydrology House proves entry and continuity but still needs an authored
  PBR atlas and a terrain-cut foundation.

The implementation is intentionally not marked as passed while these visible
reference gaps remain.

final result: failed
