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

- Pages, child contexts, relevant sources, people and connected repositories.
- For a connected repository, retain its canonical location, purpose and links
  to revision/path-specific evidence so this map remains useful without a clone.
- Follow [context entry](context-entry.md) for the folder instructions; the
  index is a map, not proof that linked bodies were read or access was granted.

## Related

- Parent MOC: link to the actual parent index chosen by the project.
