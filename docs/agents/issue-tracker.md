# Issue tracker: versioned local Wayfinder maps

Wayfinder maps for this repository live in
[docs/wayfinder/](../wayfinder/README.md). This keeps discovery local,
reviewable and branch-scoped until a human explicitly authorizes publishing
issues or other remote changes.

## Conventions

- One effort per directory: `docs/wayfinder/<effort>/`.
- The map is `docs/wayfinder/<effort>/map.md`.
- Child tickets are one Markdown file each under
  `docs/wayfinder/<effort>/issues/`, numbered from `01`.
- Each ticket records `Type`, `Mode`, `Status`, `Blocked by` and `Owner`.
- Ticket types are `research`, `prototype`, `grilling` and `task`.
- Status is `open`, `claimed` or `resolved`.
- A HITL ticket remains open until the human has reacted and made the decision;
  an agent must not choose a prototype winner on the human's behalf.

## Wayfinding operations

- **Create map:** write `map.md` with `Destination`, `Notes`,
  `Decisions so far`, `Not yet specified` and `Out of scope`.
- **Create child:** add one numbered file under `issues/` containing one
  decision question sized for a single fresh agent session.
- **Blocking:** use `Blocked by: NN, NN`; a ticket is unblocked only when every
  referenced ticket is `resolved`.
- **Frontier:** scan for tickets with `Status: open`, no unresolved blocker and
  no owner. Lowest number wins unless the map explicitly states otherwise.
- **Claim:** set `Status: claimed` and `Owner` before starting work.
- **Resolve:** append the answer under `## Answer`, set `Status: resolved`, then
  add a one-line pointer to the map's `Decisions so far`.
- **Prototype evidence:** keep throwaway code on its own branch and link the
  branch and verdict from the ticket. Do not merge the prototype wholesale.

Remote GitHub issues, labels, assignments, comments and closures are out of
scope until Kim authorizes that publication surface explicitly.
