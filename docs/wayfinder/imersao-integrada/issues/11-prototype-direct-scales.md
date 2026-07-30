# Prototype direct world → district → interior scales

Type: prototype
Mode: HITL
Status: ready for HITL
Blocked by: 04, 05, 06
Owner: Codex delegated implementation thread, 2026-07-30

## Question

Can three explicit semantic scales preserve spatial orientation while giving
each density level one responsibility: world for diff and consequence, district
for relations and lenses, and interior for mission, gate and receipt?

Use the same data, copy, task, state machine and route as tickets 07 and 08.
Navigation must be direct and reversible; no video, loading corridor, free-flight
maze or bespoke illustrated interior. The selected semantic ID must survive
every scale.

Kim selects the verdict after using all three prototypes.

## Implemented evidence

Variant `scales` is available on the shared route. World, district and interior
are direct reversible camera states over one Canvas; the selected semantic ID
survives every scale, while the interior becomes a precise DOM surface for the
mission, gate and receipt.

Desktop, 390×844 mobile, reduced-motion, semantic 2D parity and session
continuity were verified. The prototype is ready for Kim's verdict; its stronger
game grammar also carries the largest interaction and productization risk.
