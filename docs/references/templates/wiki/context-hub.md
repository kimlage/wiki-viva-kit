# Template - context_hub

The hub of an AREA (a context). An anchor: it carries the area's identity
(a beacon, the context tint on the void, the horizon label), the area's own
create catalog and intake forms, and the area's vitality loop. Quadrant lenses
are usually inherited from the root; an area re-anchors them only when it needs
its own labels.

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
# blocks: []  # optional per-area blocks
---
```

# {{title}}

## Purpose

What this area is and what belongs in it.

## Map

- The pages, sources and people that live under this area.

## Related

- Parent MOC: [memories/index.md](../../../../memories/index.md)
