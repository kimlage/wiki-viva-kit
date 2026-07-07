---
title: "Wiki Viva v6.9.2"
page_id: release-wiki-viva-v6-9-2
page_type: release_note
context: system
visibility: public_candidate
updated_at: 2026-07-07
stale_after_days: 365
sources_policy: release_note
gate: github_pr
sensitive_data_policy: no_personal_data
---

# Wiki Viva v6.9.2

Public quadrant terminology patch for the open-source kit. This release keeps
the stable internal facet IDs (`intencao`, `pratica`, `relacoes`, `sistemas`)
and the canonical Wilber/AQAL q1..q4 mapping, but changes the human-facing
labels to avoid weak or misleading terms.

## Canonical Labels

| Quadrant | UI label | Meaning |
| --- | --- | --- |
| Q1 / I / interior individual | Identity & intent | Identity, purpose, priorities, meaning, lived or declared intent. |
| Q2 / It / exterior individual | Outputs & evidence | Observable behavior, actions, artifacts, direct outputs, traces and metrics. |
| Q3 / We / interior collective | Culture & relations | Shared meaning, lived roles, rituals, norms and relationship context. |
| Q4 / Its / exterior collective | Systems & governance | Channels, tools, platforms, workflows, rules, governance and process infrastructure. |

## What Changed

- The cockpit quadrant menu, minimap labels, focus lenses and tutorial copy now
  use `Identity & intent`, `Outputs & evidence`, `Culture & relations` and
  `Systems & governance`.
- The Python quadrant contract now exposes those same labels through
  [wiki_core/quadrants.py](../../../wiki_core/quadrants.py), while preserving
  the semantic keys and perspective IDs.
- The template authoring and modular block guides now describe the four facets
  with this vocabulary.
- The demo snapshot should be regenerated with
  [scripts/wiki_build_demo.py](../../../scripts/wiki_build_demo.py) so static
  demo data carries the same labels.

## Migration Boundary

This is a label and documentation migration, not a data migration. Downstream
private wikis should adopt the labels and regenerated static demo assets after
the public kit version is reviewed; internal IDs and existing frontmatter values
do not need to change.

