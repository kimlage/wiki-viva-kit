# Prototype QA — Anatta Worlds integrated immersion

Date: 2026-07-30

## Comparable runtime

All variants run at `/prototype/anatta-worlds`:

- `?variant=organism`
- `?variant=table`
- `?variant=scales`
- append `&renderer=2d` for the first-class semantic equivalent.

They share one reducer, fixture, semantic IDs, mission, gate and receipt. The
switcher changes only the spatial grammar and preserves the active session.

Prototype code lives in the
[Anatta Worlds laboratory](../../../apps/wiki-cockpit/labs/anatta-worlds/README.md).
Each variant owns one experimental Canvas, but the laboratory is isolated from
production `src/` and loaded only by the explicit prototype route. The main
Wiki Viva runtime retains its zero-debt single-`SystemScene` contract.

## Automated readback

From `apps/wiki-cockpit`:

| Check | Result |
| --- | --- |
| `npx tsc --noEmit` | passed |
| `npm test` | 85 files, 807 tests passed |
| prototype Playwright spec | 3 scenarios passed |
| `npm run check:architecture` | zero violations |
| `npm run check:assets` | passed |
| `npm run check:bundle` | passed |
| `npm run test:gates` | 60 passed, 62 intentionally skipped |
| production build | passed |

The E2E slice verifies session continuity across variants, one Canvas per
variant, receipt-before-mutation ordering, East-only authorized change, no
mutation for blocked/compost choices, keyboard switching, reduced motion,
390×844 layout and the 2D equivalent without horizontal overflow.

The build keeps the normal initial bundle under its existing limits. Prototype
hosts and variants remain lazy chunks; their JavaScript gzip sizes are about
1.13 kB for the host and 2.46–3.76 kB per grammar, excluding shared Three
runtime chunks already split by the build.

The comparison is intentionally small in bytes but not in presentation code:
the laboratory contains about 5,491 lines, including roughly 2,025 shared
lines, 797 for organism, 1,042 for table and 1,627 for direct scales. Most of
the difference is interaction-specific JSX and CSS. This is strong evidence
against productizing all three grammars: direct scales is the richest and most
expensive; organism is the narrowest; table sits between them.

## Visual readback

The three 3D variants were inspected at 1920×929 and 390×844. Mobile content
scrolls instead of being clipped, touch targets remain at least 44×44 and the
fixed switcher keeps the 2D alternative visible. Organism no longer collides
with the fixed brand; table uses one readable inlay; direct scales preserves a
visible world → district → interior path.

## What this does not prove

This branch is decision evidence, not release evidence. Sustained FPS, decoded
texture memory, low-end physical-device behavior, screen-reader audit and real
no-WebGL fallback still need measurement after Kim chooses a grammar. No
prototype is allowed to enter production merely because it passes the bundle
gate or looks convincing in the comparison.

`npm audit --omit=dev` also reports one existing low-severity DOMPurify
advisory. The prototype introduced no dependency or lockfile change, so this
branch records the finding instead of applying an unrelated automatic upgrade.
