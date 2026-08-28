# Visual Inspiration Register

Updated on: 2026-07-11

This register turns visual inspiration into reviewable product input. It is not
a dependency shortlist and it does not authorize copying external artwork.
Every precedent must identify the product question it helps answer, the pattern
to borrow, the pattern to reject, its license status and the evidence retained.

## Register contract

| Field | Required meaning |
| --- | --- |
| Reference | Stable product, project or design-system name |
| Source | Primary URL or a versioned local artifact |
| Reviewed at | Date on which the source was checked |
| Target surface | Cockpit surface or experience-pack slot informed by it |
| Borrow | Specific interaction, hierarchy or encoding worth prototyping |
| Reject | Attractive but unsuitable pattern that must not leak into the product |
| License | License of reusable code/assets, or `reference-only` |
| Evidence | Screenshot/hash when copied lawfully; otherwise `URL analysis only` |

Production assets remain governed by the cockpit asset manifest. A URL in this
register is never permission to hotlink, vendor or imitate protected artwork.

## Boards

- [Observatory and command surfaces](observatory-and-command-surfaces.md) —
  mission control, clear glass and dense desktop information architecture.
- [Temporal and provenance surfaces](temporal-and-provenance-surfaces.md) —
  synchronized time, temporal lanes, traceability and semantic landmarks.
- [Dense readable mobile surfaces](dense-readable-mobile-surfaces.md) —
  typography, 3D labels, effects and token systems under mobile constraints.

## Selection rule

A candidate becomes an implementation dependency only after a small spike
proves all of the following:

1. it improves a named user task or measurable reading/navigation outcome;
2. it works in the supported browsers and fallback renderer;
3. it passes performance, reduced-motion, keyboard and contrast budgets;
4. its license and attribution fit the public kit;
5. it can be removed or replaced without changing canonical wiki semantics;
6. its exact version and assets are pinned in the dependency/asset manifest.

The visual north star remains **clear futurism with operational truth**:
evidence, time, state and action may look extraordinary, but no graphic earns
space unless it improves interpretation or safe operation.
