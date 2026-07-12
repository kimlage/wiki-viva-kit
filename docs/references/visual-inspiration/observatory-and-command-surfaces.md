# Observatory And Command Surfaces

Reviewed on: 2026-07-11

| Reference | Primary source | Target surface | Borrow | Reject | License/evidence |
| --- | --- | --- | --- | --- | --- |
| NASA Open MCT | [Open MCT](https://ammos.nasa.gov/openmct/) and [official Time API/Conductor contract](https://github.com/nasa/openmct/blob/master/API.md#the-time-conductor) | Command density, Timeline, operator health | A shared time conductor, synchronized telemetry, composable layouts and explicit live/historical context | A wall of equally loud widgets or telemetry without an owning question | Open-source project; primary-source URL analysis only, no asset copied |
| Apple Liquid Glass | [Technology overview](https://developer.apple.com/documentation/TechnologyOverviews/liquid-glass) and [WWDC25 session](https://developer.apple.com/videos/play/wwdc2025/219/) | Top bar, transient controls, dock chrome, focus transitions | A distinct adaptive layer for controls/navigation, restrained lensing and motion that explains hierarchy | Glass behind long-form reading, dense tables or low-contrast metadata; decorative refraction on every surface | Reference-only; no Apple asset copied |
| Palantir Blueprint | [Official repository](https://github.com/palantir/blueprint) | Dense desktop tables, inspectors, command palettes | Compact component grammar, predictable desktop controls and explicit density | Importing a full visual identity or treating a desktop-optimized toolkit as the mobile solution | Apache-2.0 code; URL analysis only |

## Synthesis for Wiki Viva

The cockpit should behave like an observatory, not resemble a film prop.

- The world owns orientation and sensemaking.
- The reader and evidence tables own precision.
- The Chronoscope owns shared time across views.
- Chrome may be luminous or glass-like, while content surfaces remain stable,
  opaque enough to read and free of continuous optical noise.
- Every high-density panel declares the question it answers, its data revision,
  freshness and next safe action.

The strongest NASA precedent is not dark color or aerospace styling. It is the
idea that several views can remain coherent because they share an explicit
temporal reference. The strongest Apple precedent is not translucency. It is
the separation of content from a responsive control layer. Blueprint is a
density benchmark and component-behavior reference, not a dependency decision.
