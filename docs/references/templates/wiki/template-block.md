# Template - template_block

A modular BLOCK defined as a wiki page. The kit ships generic blocks in
`wiki.templates.yaml`; a wiki defines or specializes its own blocks here as
pages (PR-gated, versioned, visible in the world). The `block:` mapping is the
contract — the same schema as the registry `blocks:` section — read structurally
by `wiki_core.template_blocks`.

```yaml
---
page_id: {{page_id}}
page_type: template_block
title: "{{title}}"
context: {{context}}
visibility: private_self
updated_at: {{updated_at}}
stale_after_days: {{stale_after_days}}
moc_parent: memories/system/blocks/index.md
block:
  block_id: wiki.block.example.v1
  family: example
  kind: interpretation        # interpretation | interface | gate | skill
  extends: ""                 # optional: a kit block_id to specialize
  scope:
    default_mode: descendants # self | children | descendants | context
  anchors: []                 # page types this block may anchor on
  config: {}                  # config for this specialization
---
```

# {{title}}

## Purpose

What local transformation this block contributes (interpretation, interface,
gate or skill) and to which scope.

## Contract

- Inputs it reads / outputs it emits.
- Config it accepts.
- Gates it requires; privacy it never relaxes.

## Related

- Parent MOC: [memories/index.md](../../../../memories/index.md) (a real block page sets its own blocks index)
