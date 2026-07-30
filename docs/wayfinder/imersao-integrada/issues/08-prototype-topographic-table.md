# Prototype the topographic table alternative

Type: prototype
Mode: HITL
Status: ready for HITL
Blocked by: 04, 05, 06
Owner: Codex delegated implementation thread, 2026-07-30

## Question

Does an orthographic 2.5D table preserve enough presence and consequence while
making the 3D-to-2D transition materially simpler and more legible?

Use the same data, task, state machine and route as ticket 07. Only camera,
depth, anchoring and transition treatment may vary, so the human comparison is
about the architecture rather than unrelated art directions.

Kim selects the verdict after using both prototypes.

## Implemented evidence

Variant `table` is available on the shared route. It uses one orthographic
topographic artifact, a contained camera and one screen-space inlay linked to
the selected plate. The inlay stays legible without duplicating the decision
surface or inventing a second session.

Desktop, 390×844 mobile, reduced-motion, semantic 2D parity and session
continuity were verified. The prototype is ready for Kim's verdict; its lower
implementation cost does not by itself make it the winner.
