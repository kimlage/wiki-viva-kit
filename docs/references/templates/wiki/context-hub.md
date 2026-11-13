# Template - context_hub

The hub of an AREA (a context). An anchor: it carries the area's identity
(a beacon, the context tint on the void, the horizon label), the area's own
create catalog and intake forms, and the area's vitality loop. Quadrant lenses
are usually inherited from the root; an area re-anchors them only when it needs
its own labels.

When using a hub as a local folder context, place applicable AGENTS instructions
and an `index.md` in that folder; another
index can be selected explicitly. Link relevant source and repository pages from
the map. Keep rules in their canonical instruction files rather than copying
them into the index. The [local entry guide](../../guides/bounded-ingestion.md)
describes selection and its limits; an index or instruction file grants no access.

```yaml
---
page_id: {{page_id}}
page_type: context_hub
title: "{{title}}"
context: {{context}}
visibility: private_self
updated_at: {{updated_at}}
stale_after_days: {{stale_after_days}}
moc_parent: memories/index.md
# identity: { landmark: beacon, motif: rings, horizon_label: context }  # optional override
blocks: [wiki.block.quadrants.v1]  # activate projections for this center
# perspective_bundle_required: []
# perspective_bundle_optional: []
---
```

# {{title}}

## Purpose

What this area is and what belongs in it.

## Integral map

All quadrants are relative to this center; use declared evidence, never invent
interior experience for an organization or project.

### Q1 — Intent and identity

Test: does this describe the center's declared identity, meaning or intent?

<!-- integral-map:q1:start -->
_Empty: `quadrant_absence` mission._
<!-- integral-map:q1:end -->

### Q2 — Outputs and evidence

Test: is this an observable output, behavior or evidence of this center?

<!-- integral-map:q2:start -->
_Empty: `quadrant_absence` mission._
<!-- integral-map:q2:end -->

### Q3 — Culture and relationships

Test: does this express shared meaning, lived expectations or relationships?

<!-- integral-map:q3:start -->
_Empty: `quadrant_absence` mission._
<!-- integral-map:q3:end -->

### Q4 — Systems and governance

Test: does this coordinate the collective through systems, rules or processes?

<!-- integral-map:q4:start -->
_Empty: `quadrant_absence` mission._
<!-- integral-map:q4:end -->

## Perspective bundle

Inherited from the root: `perspective-identity-intent`,
`perspective-artifacts-evidence`, `perspective-roles-relationships` and
`perspective-systems-processes` (all required). Additional thematic perspectives
and local promotions are declared in `perspective_bundle_optional` and
`perspective_bundle_required` in this anchor's frontmatter.

## Related

- Parent MOC: [memories/index.md](../../../../memories/index.md)
