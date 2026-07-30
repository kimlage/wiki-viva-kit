# Wayfinder map — Anatta Worlds integrated immersion

## Destination

Produce three functional, implementable and directly comparable prototypes for
Anatta Worlds in the real cockpit stack. Every prototype must let Kim complete
the same synthetic vertical slice from observed diff to human gate, receipt and
one localized world consequence. The alternatives may change spatial grammar,
camera, depth and the way a precise 2D surface joins the world, but not the
fixture, state machine, semantic IDs, copy, rules or budgets.

The destination is reached when all three alternatives run from one command,
can be switched on one shareable route without resetting the session, pass the
agreed desktop/mobile/accessibility checks and are ready for Kim to choose or
combine.

## Notes

- Branch: `wiki/wayfinder-imersao-integrada-20260730`.
- Base: committed consolidation `44913a1d`; no dirty worktree state was copied.
- Canonical product direction:
  [Anatta Worlds GDD 3.0](../../../apps/planetary-prototype-gallery/docs/gdd/GDD-3.0.md).
  “Mundos Vivos” is historical/category language, not the current product name.
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
- This is a throwaway Wayfinder comparison, not a production architecture
  migration. The winner will be rewritten against the production runtime after
  human selection.

## Decisions so far

- [Inventory the experimental lineages and untracked WIP](issues/01-inventory-experimental-lineages.md)
  — preserve every lineage; use the committed consolidation as base and import
  visual experiments selectively.
- [Verify Wayfinder and choose a tracker](issues/02-verify-wayfinder-and-tracker.md)
  — use a versioned local Markdown tracker first; no GitHub mutation without
  explicit authorization.
- [Recover the product philosophy and technical seam](issues/03-recover-product-philosophy.md)
  — Anatta Worlds is the authority; the proof is a truthful loop from diff to
  localized consequence, not a dashboard reproduced inside a planet.
- [Define the player fantasy and spatial verb](issues/04-define-player-fantasy-and-spatial-verb.md)
  — the player is a guardian who traces and tends one real tension from evidence
  to receipt; collecting, conquering and decorating are rejected.
- [Define the shared focus session](issues/05-define-shared-focus-session.md)
  — every renderer consumes one fixture and one explicit state machine.
- [Measure the first prototype budget](issues/06-measure-first-prototype-budget.md)
  — keep the cockpit runtime and use a deliberately smaller walking-skeleton
  envelope; the gallery remains selective visual evidence, not a runtime base.
- [Freeze the comparable vertical slice](prototype-contract.md) — one synthetic
  garden world, two lenses, one tension, one mission, one human gate and one
  receipt are identical in every variant.
- [Prototype QA](prototype-qa.md) — all three variants compile as isolated lab
  chunks, share one tested session and passed desktop/mobile truthfulness,
  architecture, asset and bundle gates.

## Frontier

1. Kim completes the same loop in organism, table and direct-scales variants.
2. Kim records which grammar makes 3D necessary for orientation and consequence
   and which makes 2D necessary for evidence and decision.
3. Resolve ticket 09 with one winner or an explicit combination of exclusive
   roles.
4. Rewrite only the selected grammar against the production `SystemScene` and
   measure sustained frames, memory and real no-WebGL behavior before merge.

## Fog

- Which grammar makes removal of 3D materially harm orientation rather than
  only atmosphere?
- Which transition lets 2D add precision without feeling like another
  application?
- Whether a combined architecture should use direct scales for navigation,
  the topographic table for the district and the organism only for consequence.
- Which visual material and sound language should be explored after the
  architecture wins.
- Whether the selected grammar can sustain the production frame and memory
  budgets on the actual mobile-device matrix. The comparison branch proves
  chunk budgets and interaction semantics, not release performance.

## Out of scope

- Building or claiming the complete Anatta Worlds product during Wayfinding.
- Merging all prior visual branches, storyboards, flights, terrain spikes or
  generated assets into the new line.
- Deleting local branches, worktrees or Cloud Code scratchpads.
- Producing more moodboards before the real engine proves the core interaction.
- Publishing issues, pushing branches, opening a PR or changing `main`.
- Treating engagement time as the north-star metric.
