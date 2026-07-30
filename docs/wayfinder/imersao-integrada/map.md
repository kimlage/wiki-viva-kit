# Wayfinder map — Integrated 3D + 2D immersion

## Destination

Produce an implementable architecture and specification, validated by a
vertical slice in the real engine, for one spatial experience where 3D provides
presence, orientation and visible consequence while 2D provides legibility,
evidence and action over the same selected entity and the same state.

The destination is reached when the route to implementation is clear, the
critical interaction has survived human review, and explicit performance,
accessibility and provenance budgets exist.

## Notes

- Branch: `wiki/wayfinder-imersao-integrada-20260730`.
- Base: committed consolidation `44913a1d`; no dirty worktree state was copied.
- Upstream Wayfinder source reviewed at
  `mattpocock/skills@2ab958093e83e0ec752e6c1c5932da465bf23e0c`.
- Use the installed `grilling`, `domain-modeling`, `research` and `prototype`
  skills when their ticket type requires them.
- HITL tickets are Kim's decisions. An agent may recommend, but must not
  self-answer a grilling ticket or select a prototype winner.
- Every prototype answers one question, runs with one command, exposes its
  state and lives on a throwaway branch.
- Use public synthetic data only. No downstream personal or client data enters
  this kit.
- Prefer one shared semantic state and one complete vertical loop over new
  metaphors, renderers or asset pipelines.

## Decisions so far

- [Inventory the experimental lineages and untracked WIP](issues/01-inventory-experimental-lineages.md)
  — preserve every lineage; use the committed consolidation as base and import
  visual experiments selectively.
- [Verify Wayfinder and choose a tracker](issues/02-verify-wayfinder-and-tracker.md)
  — use a versioned local Markdown tracker first; no GitHub mutation without
  explicit authorization.
- [Recover the product philosophy and technical seam](issues/03-recover-product-philosophy.md)
  — pursue one spatial gesture with a persistent world and a 2D focus surface,
  not a dashboard reproduced inside a planet.
- [Measure the first prototype budget](issues/06-measure-first-prototype-budget.md)
  — keep the cockpit runtime and use a deliberately smaller walking-skeleton
  envelope; the gallery remains selective visual evidence, not a runtime base.

## Not yet specified

- The exact player fantasy and canonical spatial verb.
- The minimum semantic boundary between world, focus surface and deep evidence.
- Whether the first proof uses perspective camera, orthographic 2.5D or both as
  two parameters of the same scene.
- The device and frame budgets that define the first supported envelope.
- The visual language, materials, sound and environmental metaphor that should
  follow once the interaction works without bespoke art.
- The implementation ticket sequence after the vertical slice is accepted.

## Out of scope

- Building the complete game during Wayfinding.
- Merging all prior visual branches, storyboards, flights, terrain spikes or
  generated assets into the new line.
- Deleting local branches, worktrees or Cloud Code scratchpads.
- Producing more high-fidelity moodboards before the engine proves the core
  interaction.
- Publishing issues, pushing branches, opening a PR or changing `main`.
- Treating engagement time as the north-star metric.
