# Verify Wayfinder and choose a tracker

Type: research
Mode: AFK
Status: resolved
Blocked by: none
Owner: Codex research thread, 2026-07-30

## Question

What does the Wayfinder method actually require, and how should it be applied
without prematurely publishing or executing this effort?

## Answer

The verified video is
[/wayfinder: Nothing is too big to plan anymore](https://www.youtube.com/watch?v=F3lL98Pj90o),
published by Matt Pocock on 2026-07-30. The source of record is the
[Wayfinder skill](https://github.com/mattpocock/skills/blob/2ab958093e83e0ec752e6c1c5932da465bf23e0c/skills/engineering/wayfinder/SKILL.md).

Wayfinder is for work larger than one agent session when the route to the
destination is still obscured. It maintains a map, precise decision tickets,
fog, a frontier and blocking relationships. It plans by default; implementation
tickets come only after the route is clear.

Research is AFK. Grilling and prototypes are HITL. A prototype is throwaway
evidence for one decision and cannot be accepted by the agent that produced it.

This branch uses a versioned local Markdown tracker. GitHub Issues would give
native child and dependency relationships, but creating issues, labels,
assignments and comments is a remote mutation that has not been authorized.
The tracker can be migrated later without changing the decision model.
