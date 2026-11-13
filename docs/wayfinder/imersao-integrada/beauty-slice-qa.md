# QA — Anatta Worlds basin beauty slice

Date: 2026-07-30
Branch: `wiki/anatta-worlds-beauty-slice-20260730`
Route: `/prototype/anatta-worlds?variant=organism`

## Functional readback

- quiet → diff → tension → mission → evidence → proposal → human gate;
- canonical decisions `accept → correct → reject`;
- typed receipt visible before mutation;
- authorized mutation changes only `entity.bed-east`;
- exterior → interior → exterior camera transition preserves the reducer state;
- interior surface remains physically located on the Hydrology House wall;
- exterior camera returns to its authored hero pose after leaving the module.

## Runtime readback

- 10/10 sustained samples at 60 FPS;
- 16.7 ms average frame;
- 95–96 draw calls;
- 1,273,525 triangles;
- 88 geometries and 55 textures on the verified reload;
- first Canvas frame in 234 ms;
- 3,786,441 bytes of declared local assets;
- environmental animation produced 413,458 changed pixels between captures
  separated by five seconds.

The current harness does not calculate a statistically valid 1% low or decoded
GPU memory. Those remain explicit release-measurement gaps.

## Visual gate

Combined comparison:
[reference versus implementation](../../../apps/wiki-cockpit/.visual-qa/reference-vs-beauty-final.png).

The slice passes the semantic, interaction, architecture, provenance and steady
frame-budget gates. It fails the reference-fidelity gate: terrain stratification,
shoreline erosion, hydraulic richness, vegetation hierarchy and architectural
surface finish remain visibly behind the best image.

Verdict: executable evidence, not an accepted final visual direction.
