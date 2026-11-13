# Design QA — Planeta de Areia

## Comparison target

- Source visual truth: `.visual-qa/source-tidewright-v2.png`, captured from
  `https://winchxyz.github.io/tidewright/` with the source test muted.
- Implementation: `.visual-qa/implementation-sand-planet-final.png`, rendered
  from `/prototype/anatta-worlds?variant=sand`.
- Normalized comparison: `.visual-qa/comparison-final.png`.
- Comparison viewport: 727 × 784 CSS px, device density 1.
- Source pixels: 727 × 784.
- Implementation comparison pixels: 727 × 784.
- Desktop implementation evidence: 1280 × 720 CSS/pixels at density 1.
- State: initial world state, Salt & Light source look, sand planet in read mode,
  Aurora Leste at 16%, no authorized world mutation.

The goal is an intentional translation, not a scene clone: preserve the source's
material cues, sparse HUD, low-angle light and direct manipulation while moving
from a beach heightfield to a navigable planet with Anatta's semantic state.

## Full-view comparison evidence

The final paired image in `.visual-qa/comparison-final.png` shows both complete
views at the same pixel size. The planet preserves the dominant sand surface,
high-contrast material lighting, small uppercase telemetry, serif display voice,
three-part tool rack and localized material reading. The planetary silhouette,
amber palette and Anatta copy are intentional product changes.

## Focused-region evidence

A separate crop was not needed. At 727 × 784 the material surface, title,
moisture card, primary action, three tools and prototype switcher are all legible
in the full paired comparison. The 1280 × 720 desktop capture was additionally
inspected for the smaller coordinate, caveat and dataRef labels.

## Required fidelity surfaces

- Fonts and typography: the source's editorial serif plus small tracked uppercase
  system is preserved with local platform fallbacks. Weight, hierarchy and line
  wrapping are stable at both inspected viewports.
- Spacing and layout rhythm: the planet remains the dominant visual mass. HUD
  panels stay on the perimeter, persistent controls do not cover the tension
  marker, and browser checks report zero horizontal or vertical overflow.
- Colors and visual tokens: dark void, warm raking light, muted sand neutrals and
  amber focus states form one coherent palette. The warmer planet is intentional;
  it separates the experiment from the source's dynamic night state.
- Image quality and asset fidelity: no source raster assets were replaced or
  approximated. Both scenes are procedural. The planet uses continuous spherical
  geometry, deterministic micro-bump, rough dry sand, darker wet sand and sparse
  mica glints.
- Copy and content: all labels describe the actual spike. The UI explicitly says
  that it has no granular solver or volume conservation, preventing the visual
  experiment from being mistaken for validated sand physics.

## Comparison history

1. Initial comparison found a P2 responsive issue: the persistent action was
   covered by the stacked prototype switcher and the narrow viewport had 132 px
   of vertical overflow. The action became a separate floating control, the
   sand route removed generic mobile bottom padding, and the final browser check
   reported `{x: 0, y: 0}`.
2. Initial comparison found a P2 material issue: the macro dunes read as smooth
   sculpted clay at close range. A deterministic repeated bump texture was added
   to the sand material. The final paired comparison shows visible fine grain
   without losing the authored dune bands.
3. The final pass found no remaining P0, P1 or P2 issue. Browser console warnings
   and errors were empty.

## Primary interactions tested

- Orbit the planet in read mode.
- Select Modelar and apply a localized radial heightfield change.
- Select Umedecer and confirm the local wetness state increments.
- Advance `quiet → diff_available → tension_focused`.
- Open and close the decision drawer.
- Open the dataRef control.
- Confirm the equivalent 2D control remains present.

## Findings

No actionable P0, P1 or P2 mismatch remains.

P3 follow-up: extreme close orbit may reveal the spherical UV seam in the
procedural bump texture. It was not visible in the inspected hero and interaction
states.

## Implementation checklist

- [x] Procedural spherical sand heightfield.
- [x] Dry/wet material response and mica microdetail.
- [x] Localized sculpt and moisture gestures.
- [x] Typed Anatta session, dataRef and decision drawer preserved.
- [x] Desktop and narrow browser inspection with zero overflow.
- [x] No browser console errors or warnings.

final result: passed
