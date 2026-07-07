---
visibility: private_self
stale_after_days: 30
page_id: block-library-lens
page_type: template_block
title: Lente de quadrantes para bibliotecas
context: sistema
updated_at: '2026-07-03'
moc_parent: memories/sistema/index.md
parent_projection:
  quadrant: q4
  sub_lens: governanca
  reason: Reusable interpretation blueprint inside the system layer.
block:
  block_id: wiki.block.quadrants_lens_library.v1
  family: quadrants
  kind: interpretation
  extends: wiki.block.quadrants.v1
  scope:
    default_mode: descendants
  anchors:
  - context_hub
  config:
    mode: optional_lens
blocks:
- id: wiki.block.quadrants.v1
  scope: descendants
  config:
    labels:
      q1: Propósito do template
      q2: Exemplos e artefatos
      q3: Revisão compartilhada
      q4: Campos e governança
---

# Lente de quadrantes para bibliotecas

## Purpose

Specializes the kit quadrants block for reference libraries — navigate without forcing ingestion.

## Contract

- Inherits the canonical AQAL lenses; only relabels and softens to optional.
