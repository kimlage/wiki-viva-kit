# Define the shared 3D and 2D focus session

Type: task
Mode: AFK
Status: resolved
Blocked by: 04
Owner: Codex integration thread, 2026-07-30

## Question

Which state must remain continuous while the player moves from spatial
orientation to precise evidence and action?

## Answer

All variants consume one `AnattaPrototypeSession`:

- `phase`: arrival, focus, lenses, mission, returned evidence, gate or receipt;
- `selectedId`: the same source, tension, mission or receipt ID;
- `activeLens`: provenance, hydrology or comparison;
- `missionChoice`: do, delegate, ask for evidence or compost;
- `proposalStatus` and `gateDecision`;
- immutable observed snapshots and the optional returned synthetic snapshot;
- emitted typed receipts;
- the one authorized localized mutation.

Camera, orbit/tilt, projected anchor position, panel placement, transition
progress and pointer hover are renderer-local. Switching variants must preserve
the complete session. Reloading may reset it because this is a throwaway
prototype with no persistence.
