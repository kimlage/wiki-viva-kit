# Dense Readable Mobile Surfaces

Reviewed on: 2026-07-11

| Reference | Primary source | Target surface | Borrow | Reject | License/evidence |
| --- | --- | --- | --- | --- | --- |
| IBM Plex | [Official repository](https://github.com/IBM/plex) | Body, metadata, tabular numerals, source/code details | A versatile Sans/Mono family designed for UI and broad scripts; strong numeric rhythm | Adding another font without testing Portuguese glyphs, loading cost and long labels | OFL-1.1; no font vendored yet |
| Drei Text / troika-3d-text | [Official Drei Text docs](https://drei.docs.pmnd.rs/abstractions/text) and [official repository](https://github.com/pmndrs/drei) | Selected 3D labels and landmark titles | SDF text with antialiasing and an explicit character preload set | Rendering every paragraph or distant metadata label in WebGL; font-loading flashes | Drei MIT; dependency spike required |
| React Postprocessing | [Official repository](https://github.com/pmndrs/react-postprocessing) and [license](https://github.com/pmndrs/react-postprocessing/blob/master/LICENSE) | Focus ring, verified transition and restrained glow | A small effects chain behind a performance capability toggle | Permanent bloom/noise, effects that hide focus or degrade low-power phones | MIT; dependency spike required |
| Open Props | [Official site](https://open-props.style/) and [license](https://github.com/argyleink/open-props/blob/main/LICENSE) | Token research and prototype ramps | Inspectable CSS custom-property scales and reusable motion/size primitives | Importing a second uncontrolled semantic-token source | MIT; reference/prototype only |
| Palantir Blueprint | [Official repository](https://github.com/palantir/blueprint) | Desktop density comparison | Explicit compact controls and data-heavy desktop hierarchy | Copying desktop density into a phone; the project itself states it is not mobile-first | Apache-2.0; URL analysis only |

## Mobile interpretation rules

- Responsive mobile WebGL and the forced 2D fallback are separate products and
  must be tested separately.
- The phone owns one scroll surface at a time.
- Safe areas, landscape, virtual-keyboard open/closed and 200–400% reflow are
  first-class matrix cells.
- A 44×44 CSS px hit target is the minimum, not proof that its label, focus and
  surrounding density are understandable.
- Distant WebGL microtext is progressively summarized; the complete truth
  remains in an accessible DOM reader/table.
- Effects and custom fonts are optional enhancements with system-font and
  no-effects fallbacks.
- Long PT-BR and EN labels are fixture data, not manual spot checks.
