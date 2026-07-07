# Template - tool

A TOOL the center uses — a platform, app or service. Lives in the systems
quadrant (q4, sub-lens `ferramentas`). Records the owner, the access POINTER
(never a secret — same rule as the source AuthPointer), cost and what depends on
it. Not a source (no ingestion recipe); a tool becomes a source only when it
starts producing evidence you ingest.

```yaml
---
page_id: {{page_id}}
page_type: tool
title: "{{title}}"
context: {{context}}
visibility: private_self
updated_at: {{updated_at}}
stale_after_days: {{stale_after_days}}
moc_parent: memories/tools/index.md
platform: ""                 # vendor/platform name
access_pointer: ""           # WHERE the credential lives, never the value
cost: ""                     # plan / monthly cost, if tracked
status: active               # active | evaluating | retired
used_in: []                  # processes/sources that depend on it
source_refs: []
---
```

# {{title}}

## What it is

One line: what the tool is and why the center uses it.

## Access and cost

- Access pointer (never paste a secret here).
- Cost / plan.

## Depends and dependents

- What this tool depends on; what depends on it.

## Related

- Parent MOC: [memories/index.md](../../../../memories/index.md) (a real tool page sets its own tools index)
