---
title: "Plan - Visual region grouping for the cockpit map"
page_id: plan-visual-region-grouping-2026-07-08
page_type: methodology_plan
aliases:
  - Visual region grouping
  - Regions as navigation groups
  - Region work cards
  - Practical visual grouping
  - Visual primitive packs
  - Template-driven visual grammar
tags:
  - wiki/methodology
  - wiki/interface
  - wiki/cockpit
  - wiki/quadrants
  - wiki/templates
  - status/superseded
date: "2026-07-08"
status: superseded
context: system
visibility: public_reference
updated_at: 2026-07-09
stale_after_days: 45
sources_policy: "local_code_review_plus_read_only_private_cockpit"
gate: github_pr
sensitive_data_policy: public_synthetic_only
related_pages:
  - ../../../docs/references/proposals/recursive-quadrant-centers-refactor-2026-07-07.md
  - ../../../docs/references/proposals/ux-semantic-encoding-2026-07-02.md
  - ../../../docs/references/proposals/one-world-cockpit-plan-2026-07-02.md
  - ../../../docs/references/guides/modular-blocks.md
  - ../../../docs/references/guides/extending-the-kit.md
  - ../../../wiki.templates.yaml
  - ../../../wiki_core/template_blocks.py
  - ../../../apps/wiki-cockpit/src/data/presentation.ts
  - ../../../apps/wiki-cockpit/src/data/surfaces.ts
  - ../../../apps/wiki-cockpit/src/scene/perspectives.ts
  - ../../../apps/wiki-cockpit/src/components/WorldView.tsx
  - ../../../apps/wiki-cockpit/src/components/SystemScene.tsx
  - ../../../apps/wiki-cockpit/src/scene/parts/labels.tsx
  - ../../../apps/wiki-cockpit/src/scene/parts/fallback.tsx
  - ../../../scripts/wiki_build_demo.py
target_version: "historical input absorbed by wiki-viva v8"
audience: "wiki-viva maintainers, cockpit implementers and downstream wiki owners"
scope: "Plan for refactoring visual regions into first-class navigable groups with practical summaries, actions, data-type distinction, attention signals and template-resolved visual primitives, proven in the public synthetic demo and checked read-only against the private cockpit."
---

# Plan - Visual Region Grouping for the Cockpit Map

> **Superseded / absorbed.** This proposal is retained as historical input only. The sole active execution contract is [Wiki Viva v8 Unified Living World](wiki-viva-v8-unified-living-world-execution-plan-2026-07-09.md); implementation status and release evidence belong there.

Updated on: 2026-07-08.

This plan turns cockpit regions from visual labels into practical navigation
groups. A region must answer: what belongs here, what kind of data it is, what
needs action, what deserves attention, and where the operator should go next.
No visual element is ornamental: every color, outline, count, glyph, motion or
panel must map to real snapshot data.

## Current Evidence

The servers were restarted before this plan was written, so the plan references
the current checkouts instead of stale browser state.

- Public kit checkout: `wiki-viva-kit`, local `main` at `71c845fb`
  (`fix(cockpit): keep active center out of quadrants`), one commit ahead of
  `origin/main`.
- Private downstream evidence was recorded under the public-safe identifier
  `private-pilot-01`; exact paths, SHAs, page IDs and content remain private.
- Public demo route used for implementation target:
  `http://127.0.0.1:5173/demo/w/quadrants`.
- Private route used read-only as scale reference:
  `http://127.0.0.1:5174/w/quadrants`.
- The private snapshot was validated read-only in `local_operator` mode; only
  public-safe pass/fail and aggregate behavior may leave that checkout.
- Public synthetic demo was edited and regenerated on 2026-07-08. It now has
  `82 pages` and explicit region-grouping stress content under nested client
  centers.
- Public demo root totals remain intentionally calm: `q1=1`, `q2=6`, `q3=3`,
  `q4=8`, `q0_core=0`.
- Public demo nested grouping totals prove density without private data:
  `hub-clientes` has `q1=4`, `q2=10`, `q3=3`; `company-clearpath-labs` has
  `q1=2`, `q2=7`, `q3=2`, `q4=2`.
- Public remote branches not merged into local `main` at review time:
  `origin/wiki/plan-ops-cockpit-3d` and
  `origin/wiki/plan-sources-templates-facets`.

Do not copy private content into this repo. The private cockpit is evidence of
density, language, and operator ergonomics only.

## Problem

The cockpit already emits `WorldGroup` records in
[apps/wiki-cockpit/src/scene/perspectives.ts](../../../apps/wiki-cockpit/src/scene/perspectives.ts),
and the quadrants view already renders a compass plus rim pills. That is not
yet enough for a 554-page operational wiki:

- A region click mostly focuses the camera. It does not yet behave like an
  operational grouping with a clear work packet.
- The quadrant compass shows totals, but not the composition of the region:
  data types, raw sources, open actions, stale pages, risk flags, review items
  or hidden mass.
- Dense regions, especially Outputs and evidence, become visually heavy because
  their internal structure is not summarized before the operator drills in.
- Hidden cluster counts are honest, but they do not say which hidden items are
  actionable or dangerous.
- The same visual treatment is used for healthy collections, action queues,
  evidence/raw data, review changes and structural/core pages.
- The public demo is too small to prove whether the design works at private
  scale. It needs synthetic stress data that exercises the same grouping
  problem without leaking personal pages.

## North Star

**A region is a work group with a visual contract.**

When the operator selects a region, the cockpit should make the map easier to
navigate by showing a scoped work surface:

- Which pages are in the region.
- Which data families dominate the region.
- Which items need action now.
- Which items are raw/evidence, conclusions, decisions, tasks, people or
  system/process pages.
- Which risks, stale pages, proposals and hidden clusters require attention.
- Which practical next action is valid from this group.

The region is not a decorative overlay. It is the bridge between the world map
and the operator's next move.

## Scope

In scope:

- Define a first-class region grouping contract for quadrant regions, core
  structure, attention buckets and page-type districts.
- Define a small visual primitive vocabulary so region cards, rails, shelves,
  markers and empty states are reusable template components instead of ad hoc
  component styling.
- Extend deterministic snapshot data so groups carry practical summaries,
  action counts, risk counts, type composition and member IDs.
- Refactor the cockpit so quadrant cells, rim pills, minimap labels, keyboard
  traversal and fallback lists all read the same region contract.
- Add a focused region surface: a compact in-world plate or dockless sheet that
  summarizes the active region and gives valid next actions.
- Update the public synthetic demo so it proves dense grouping, hidden mass,
  raw/evidence distinction, action queues and attention signals.
- Validate the public implementation against the private cockpit in read-only
  mode after regenerating the private snapshot.

Out of scope:

- Replacing AQAL quadrants with a different taxonomy.
- Copying private wiki pages, names, values or source details into the public
  kit.
- Creating decorative background effects that do not encode data.
- Creating freeform CSS/theme skins that bypass the semantic primitive
  vocabulary.
- Making the cockpit a generic analytics dashboard separate from the world.
- Weakening the PR/human gate, privacy rules, source provenance or freshness
  checks.

## Vocabulary

### Region

A region is any visible, selectable grouping area in the world. In the current
system this includes quadrant regions, context wedges, attention buckets, page
type districts, focus facets, relation sectors and the honest core structure
ring.

### Region Group

A region group is the data record behind the visible region. It is an evolution
of `WorldGroup`, not a brand-new mental model. It keeps the existing navigation
fields and adds the practical summary needed by the cockpit.

### Active Region

The active region is the currently selected group. In quadrants it is currently
represented by `?quadrant=<facet>`. The refactor should keep this URL
compatible, but the selected region must become more than a camera target.

### Region Work Card

The region work card is the compact summary for the active region: composition,
attention, hidden items and next actions. It can render as an in-world plate on
desktop and as a bottom sheet in the 2D/mobile fallback.

### Visual Primitive

A visual primitive is a named semantic UI unit with a practical data purpose.
It is not a decorative token and not a loose CSS class. Examples:
`region_card`, `region_work_card`, `attention_rail`, `type_shelf`,
`source_badge`, `action_lane`, `risk_notch`, `review_halo`,
`hidden_histogram`, `core_debt_meter`, `empty_region_affordance`,
`bridge_count`, `center_badge`, `scope_chip` and `legend_key`.

Each primitive must state:

- What data it reads.
- What operator question it answers.
- Where it may render: scene, HUD, fallback, dock or reader.
- Which states it supports: normal, selected, muted, attention, blocked,
  empty.
- Which accessibility text and keyboard behavior it requires.

### Visual Primitive Pack

A primitive pack is a named composition of primitives for a scope. It lets a
template say "this anchor uses operational region grouping" without hardcoding
individual component branches everywhere. Packs can be reused by quadrants,
districts, focus facets and later private overrides.

Example packs:

- `region_operations`: cards, rails, type shelves, action lanes and hidden
  histograms for dense work regions.
- `evidence_first`: source badges, evidence shelves, raw/consolidated
  distinction and add-evidence actions.
- `review_first`: review halos, proposal counters, approval links and PR/gate
  warnings.
- `quiet_structure`: center badges, scope chips and core debt meter for root,
  hubs and governance structure.

### Visual Grammar

The visual grammar is the resolved set of primitive packs and slots for an
anchor. It should be emitted by the same template stack that already emits
interface and derived outputs. The cockpit should consume the resolved grammar
rather than ask every component to infer its own styling from page type,
quadrant, dock and language.

### Primitive Slot

A primitive slot is a named mount point in the cockpit: `region.card`,
`region.rail`, `region.shelf`, `region.marker`, `region.empty`,
`cluster.tooltip`, `fallback.card`, `reader.badge`, `dock.action` and
`legend.entry`. Slots make it possible to swap or extend the composition while
keeping layout and accessibility rules stable.

## Data Contract

Extend `WorldGroup` conceptually into `RegionGroup` while preserving the old
fields so existing layouts continue to work during migration.

```ts
type RegionGroup = WorldGroup & {
  purpose: "navigate" | "verify" | "act" | "review" | "understand";
  visualRole: "quadrant" | "core" | "attention" | "type" | "context" | "relation" | "facet";
  visual: {
    grammarId: string;
    packId: string;
    slots: {
      card: string;
      rail: string;
      shelf: string;
      marker: string;
      fallback: string;
      empty?: string;
    };
    emphasis: ("selected" | "attention" | "muted" | "healthy" | "blocked")[];
  };
  summary: {
    total: number;
    shown: number;
    hidden: number;
    stale: number;
    proposal: number;
    risk: number;
    raw: number;
    unsourced: number;
    openActions: number;
    sourceBacked: number;
  };
  typeMix: { pageType: string; count: number; family: string }[];
  actionHints: {
    kind: "refresh" | "review" | "add_evidence" | "create" | "inspect_sources" | "open_blocks";
    labelKey: string;
    target?: { dock?: string; filter?: string; pageId?: string; quadrant?: string };
    count: number;
  }[];
  attentionHints: {
    kind: "stale" | "risk" | "proposal" | "raw" | "unsourced" | "hidden";
    count: number;
  }[];
};
```

Implementation detail: the frontend may keep the name `WorldGroup` in the
first PR to reduce churn, but the new fields and tests should use the language
"region" in comments, UI strings and docs.

### Required Invariants

- `count`, `shown`, `hidden`, `memberIds` and cluster-star counts must stay
  mathematically honest.
- Region summaries are derived from snapshot data; the UI must not invent
  actions or risks.
- Color keeps meaning "area/context"; state remains tone, glow, particles,
  borders and text chips.
- Shape keeps meaning "page kind"; do not encode page type only with color.
- Raw data/source records must remain visually distinct from conclusions.
- The active center remains separate from the reader page and from the active
  region.
- Visual primitive IDs must come from the template vocabulary. Unknown
  primitive IDs should warn during template validation and fall back to a
  readable baseline, never silently change behavior.
- The honest core is allowed, but it must not become a junk drawer. Sources,
  logs, catalogs, registries and governance pages reaching core should be
  reported as classification or projection bugs.

## Visual Primitives And Template Modularization

The region UI should become a small visual language compiled from templates,
not a collection of one-off visual decisions spread across scene parts. The
same philosophy already used by template blocks applies here: YAML can compose
known primitives, but new primitives require code, tests and documentation.

### Purpose-First Primitive Catalog

Start with a deliberately small catalog. Each item names the operator question
it answers:

| Primitive | Purpose | Primary data |
| --- | --- | --- |
| `region_card` | What is this group and how large is it? | total, shown, hidden, purpose |
| `region_work_card` | What should I inspect or do next? | type mix, attention, action hints |
| `attention_rail` | What needs attention inside this group? | stale, risk, proposal, unsourced, raw |
| `type_shelf` | Why is this region dense? | page type family counts |
| `source_badge` | Is this evidence raw, synced or consolidated? | source refs, page type, freshness |
| `action_lane` | Which items are work, not context? | action pages, missions, due flags |
| `risk_notch` | Is there risk without flooding the region red? | risk flags |
| `review_halo` | What is pending approval or PR review? | proposal/gate state |
| `hidden_histogram` | What kind of work is hidden by the render cap? | hidden fresh/stale/proposal/risk/raw |
| `core_debt_meter` | Is core growing beyond root/structure? | q0/core count and warnings |
| `empty_region_affordance` | What valid absence or creation path exists? | required regions, create catalog |
| `bridge_count` | Why do two regions feel connected? | cross-region edges |
| `center_badge` | Which anchor is the current center? | active center and reader page |
| `scope_chip` | What is this view scoped to? | center, region, filter |
| `legend_key` | How do I decode the current visual grammar? | resolved pack and primitive labels |

Do not start with more than this. Expansion should happen only when a new
operator question cannot be answered by composing existing primitives.

### Template Block Shape

Add the interface capability as either a standalone block or a config extension
to `wiki.block.ui_regions.v1`. Prefer a standalone `visual_grammar` block only
if non-region surfaces need the same primitive packs.

Recommended standalone shape:

```yaml
blocks:
  wiki.block.visual_grammar.v1:
    kind: interface
    surface: panels
    family: visual_grammar
    title: "Visual grammar"
    summary: "Semantic visual primitives for region, attention and evidence UI."
    scope: { default_mode: descendants }
    anchors: [root_entity, context_hub, holon, project, source]
    config:
      default_pack: region_operations
      packs:
        region_operations:
          slots:
            region.card: region_card
            region.rail: attention_rail
            region.shelf: type_shelf
            region.marker: action_lane
            region.empty: empty_region_affordance
            cluster.tooltip: hidden_histogram
            legend.entry: legend_key
        evidence_first:
          extends: region_operations
          slots:
            region.shelf: type_shelf
            reader.badge: source_badge
            dock.action: action_lane
        review_first:
          extends: region_operations
          slots:
            region.marker: review_halo
            dock.action: review_halo
```

Recommended `ui_regions` shape if this stays region-specific:

```yaml
blocks:
  wiki.block.ui_regions.v1:
    kind: interface
    surface: panels
    family: ui_regions
    title: "Region groups"
    summary: "Region cards, attention rails and action-aware grouping."
    scope: { default_mode: descendants }
    anchors: [root_entity, context_hub, holon, project, source]
    config:
      summaries: true
      actions: true
      hidden_histograms: true
      attention_rail: true
      visual_pack: region_operations
      allowed_packs: [region_operations, evidence_first, review_first, quiet_structure]
```

### Resolved Output

The deterministic compiler should resolve visual grammar once per anchor,
beside `interface` and `derived`, so the cockpit does not need to chase YAML.

```json
{
  "visual_grammar": {
    "schema_version": "wiki.visual_grammar.v1",
    "default_pack": "region_operations",
    "packs": {
      "region_operations": {
        "slots": {
          "region.card": "region_card",
          "region.rail": "attention_rail",
          "region.shelf": "type_shelf",
          "region.empty": "empty_region_affordance",
          "cluster.tooltip": "hidden_histogram"
        }
      }
    },
    "primitive_purpose": {
      "region_card": "summarize region size and purpose",
      "attention_rail": "filter attention inside the active region"
    }
  }
}
```

`region_groups.json` or `block_stacks.json` can then reference primitive IDs by
pack and slot. They should not carry arbitrary CSS. The frontend registry maps
primitive IDs to React components, icon choices and accessibility copy.

### Frontend Registry

Add a small typed registry, for example
`apps/wiki-cockpit/src/data/visualPrimitives.ts`, with:

- Primitive IDs, pack IDs and slot IDs as TypeScript unions.
- A resolver that merges kit defaults, resolved anchor grammar and local
  presentation overrides.
- A fallback primitive for unknown IDs that renders plain text and reports a
  diagnostic in development/demo mode.
- A purpose string for every primitive, surfaced in the Blocks dock or debug
  panel so a maintainer can answer "why does this visual exist?"

Scene components should ask the registry "what goes in this slot?" and keep
layout constraints local. Data derivation remains in the snapshot/core layer.
This keeps visual modularity practical: templates choose valid semantics,
React components render known primitives, and CSS only handles spacing,
motion and responsiveness.

### Template Resolution Rules

- Kit default defines the baseline visual grammar.
- Context or anchor templates may choose a different pack from the fixed
  vocabulary.
- Page types may request a presentation primitive, but cannot invent one.
- Local private overrides may rename labels, choose allowed packs and tune
  density thresholds, but must not introduce private content into the public
  registry.
- Unknown primitives warn in `validate_blocks()` and fall back visibly.
- A primitive pack must be deterministic: same stack plus same snapshot yields
  same slots and same UI affordances.

### What This Avoids

- No theme marketplace, no arbitrary "make it purple" layer.
- No region-specific CSS branches that cannot be audited from the template
  stack.
- No private-wiki visual behavior that cannot be reproduced with synthetic
  fixture data.
- No action-looking visual affordance unless an action exists in snapshot data.

## Visual Design

### Region Card

Replace the current "label + number" compass cells with compact region cards.
Each card should still fit in the current top-right footprint, but it should
show four practical signals:

- Total pages in the region.
- Top data family or type mix, using shapes/glyphs instead of more color.
- Attention count, using state accents and text.
- Primary valid action for the region.

Example content:

```text
Outputs & evidence
231 pages - 101 shown
raw 42 sources - 18 tasks - 7 stale
Add evidence
```

The public demo can show this in English; the private cockpit must show the
same structure in Portuguese through i18n.

### Region Work Card

Clicking a region should select it and show a work card near the compass or as
an in-world plate. The card should not cover the map permanently. It should
contain:

- A one-line purpose: "Evidence and visible outputs for this center."
- Composition chips: page families with shapes and counts.
- Attention chips: stale, proposal, risk, raw, unsourced, hidden.
- A short "next useful action" row, grounded in existing destinations:
  `Create`, `Sources`, `Approve`, `Health`, `Blocks`, or a composed Codex brief
  when the data supports it.
- A "show only this region" control that scopes nodes and relation lines.
- A "clear region" control.

This card is the main usability change. It makes the region an answerable
group instead of a camera quadrant.

### Data Type Strata

Within a dense region, arrange visible nodes by page-type family shelves:

- Root/hub pages closest to the center.
- Actions and decisions in the next shelf.
- Evidence/source/artifact pages in their own shelf.
- System/process/rule pages in their own shelf.
- People/roles/meetings in their own shelf.

This should reuse the existing shelf idea in `quadrantsLayout()` but expose the
family summary in the region card and fallback list. The operator should be
able to tell whether a region is heavy because it has tasks, sources,
decisions, people or infrastructure.

### Attention Rail

Each active region should have a small attention rail: a non-decorative strip
of chips sorted by urgency:

1. Failing review/proposal items.
2. Risk flags.
3. Stale pages.
4. Unsourced conclusion pages.
5. Raw/source material waiting for treatment.
6. Hidden items beyond the render budget.

The rail should filter the active region in place. For example, clicking
`stale 7` in Outputs and evidence should show stale pages inside that region,
not the whole world.

### Hidden Mass Histogram

Cluster stars should carry a tiny histogram or tooltip:

- Hidden fresh.
- Hidden stale.
- Hidden proposal.
- Hidden risk.
- Hidden raw/unsourced if available.

The current `ClusterStar.histogram` already has state and risk counts. Extend
or pair it with raw/unsourced counts so hidden mass does not hide the real
work.

### Boundary And Link Treatment

When a region is active:

- Keep the selected region boundary bright but restrained.
- Dim nodes outside the region without removing their silhouettes.
- Dim relation lines that do not touch active-region members.
- Emphasize evidence/source lines only when the region's action is about
  evidence or raw data.
- Avoid permanent animated borders. A selected region may breathe briefly on
  selection, then settle.

### Practical Creative Suggestions

These are deliberately practical; each visual cue has a data reason.

- **Region passport:** hover or focus on a region shows a concise passport:
  purpose, totals, dominant data family, overdue count, strongest next action.
- **Task lane:** open `action` pages in the active region appear as comet
  markers along a thin lane, sorted by due/attention. It tells the operator
  "what to do" without opening the Missions tray.
- **Evidence shelf:** raw sources, ingested evidence and source-backed claims
  sit on adjacent shelves, making untreated input visibly different from
  consolidated memory.
- **Review halo stack:** proposal/review pages in a region get a purple halo
  stack count, not just a global approval badge.
- **Risk notch:** risk flags add a red notch to a region card and a text chip;
  no red wash over the whole region.
- **Empty-region affordance:** an empty required region says what is missing
  and offers the right create/brief path. It must not render as blank space
  with no explanation.
- **Cross-region bridge count:** if many relation lines cross between two
  regions, show a small bridge count at the boundary. It helps explain why the
  map is dense and lets the operator inspect cross-region dependencies.
- **Core debt meter:** the core ring shows only unclassified/root-like pages.
  If it grows, the card says "classification debt" and links to the projection
  report or Blocks dock.

## Snapshot And Core Changes

### Backend / Deterministic Core

Add group summaries where the data is already assembled:

- [wiki_core/web/snapshot.py](../../../wiki_core/web/snapshot.py): include
  group summary payloads in the web snapshot, or emit a small
  `region_groups.json` companion file.
- [wiki_core/template_blocks.py](../../../wiki_core/template_blocks.py):
  expose region grouping derived output for anchors that attach
  `wiki.block.quadrants.v1` or a future `ui_regions` interface block.
  Add fixed vocabularies for `VISUAL_PRIMITIVES`, `VISUAL_PRIMITIVE_PACKS` and
  `VISUAL_PRIMITIVE_SLOTS`, plus validation for unknown pack/slot/primitive
  references.
- [wiki_core/template_blocks.py](../../../wiki_core/template_blocks.py):
  emit resolved `visual_grammar` output beside `interface` and `derived` so
  the cockpit reads one deterministic contract per anchor.
- [wiki_core/facets.py](../../../wiki_core/facets.py): keep the facet/type
  fallback aligned with the frontend map.
- [scripts/wiki_quadrant_projection_report.py](../../../scripts/wiki_quadrant_projection_report.py):
  add warnings for oversized core, region imbalance and pages whose type/facet
  summary contradicts their projection.

Recommended shape:

```json
{
  "schema_version": "wiki.region_groups.v1",
  "generated_at": "2026-07-08T00:05:28Z",
  "anchors": {
    "synthetic-root": {
      "regions": [
        {
          "id": "quadrant:intencao",
          "kind": "quadrant",
          "label_key": "intencao",
          "member_ids": ["..."],
          "summary": {
            "total": 40,
            "shown": 17,
            "hidden": 23,
            "stale": 6,
            "proposal": 0,
            "risk": 0,
            "raw": 0,
            "unsourced": 2,
            "open_actions": 3,
            "source_backed": 12
          },
          "type_mix": [
            { "page_type": "claim", "family": "decision", "count": 12 },
            { "page_type": "action", "family": "action", "count": 3 }
          ],
          "visual": {
            "grammar_id": "wiki.visual_grammar.v1",
            "pack_id": "region_operations",
            "slots": {
              "card": "region_card",
              "rail": "attention_rail",
              "shelf": "type_shelf",
              "marker": "action_lane",
              "fallback": "region_work_card"
            },
            "emphasis": ["attention"]
          },
          "action_hints": [
            { "kind": "refresh", "label_key": "region.action.refresh", "count": 6 }
          ]
        }
      ]
    }
  }
}
```

The exact counts above are illustrative. Tests must assert generated values
from synthetic fixtures.

### Template / Wiki Structure

Prefer adding the interface capability as a block rather than hardcoding it for
every world:

```yaml
blocks:
  wiki.block.ui_regions.v1:
    kind: interface
    surface: panels
    scope:
      default_mode: descendants
    config:
      summaries: true
      actions: true
      hidden_histograms: true
      attention_rail: true
```

Then attach it through the default kit package that also offers quadrant views,
or make it implicit when `wiki.block.quadrants.v1` is present. The implementation
should decide the smallest honest contract after reviewing
`composeInstruments()`: if every quadrant map must have region cards, it may be
part of the quadrants block; if other perspectives reuse it, a separate
`ui_regions` block is cleaner.

If the implementation introduces `wiki.block.visual_grammar.v1`, it should be
registered in [wiki.templates.yaml](../../../wiki.templates.yaml) and documented
in the `vocabulary:` section as an author-facing list only. The source of truth
must remain [wiki_core/template_blocks.py](../../../wiki_core/template_blocks.py),
matching the existing block philosophy: templates compose fixed primitives;
code introduces new primitives.

Template authors should choose packs, not style details:

```yaml
blocks:
  - id: wiki.block.ui_regions.v1
    config:
      visual_pack: evidence_first
      density: compact
      show_legend: auto
```

The allowed values for `visual_pack`, density thresholds and slot behavior must
be validated. `density: compact` may alter spacing and count truncation, but it
must not remove warnings, hide action hints or change the meaning of a color,
shape or state.

Update docs after implementation:

- [docs/references/guides/modular-blocks.md](../../../docs/references/guides/modular-blocks.md)
  with the region derived output.
- [docs/references/guides/extending-the-kit.md](../../../docs/references/guides/extending-the-kit.md)
  with the checklist for adding a region-aware perspective.
- [apps/wiki-cockpit/README.md](../../../apps/wiki-cockpit/README.md) with the
  operator-facing behavior.

## Frontend Changes

### Layout Engine

Files:

- [apps/wiki-cockpit/src/scene/perspectives.ts](../../../apps/wiki-cockpit/src/scene/perspectives.ts)
- [apps/wiki-cockpit/src/scene/facets.ts](../../../apps/wiki-cockpit/src/scene/facets.ts)
- [apps/wiki-cockpit/src/scene/layout.worker.ts](../../../apps/wiki-cockpit/src/scene/layout.worker.ts)

Required changes:

- Keep `WorldGroup` compatibility while adding region summary fields.
- Generate region summaries for `quadrantsLayout()`, `radarLayout()`,
  `districtsLayout()` and `focusLayout()` where applicable.
- Make `group.memberIds` represent all visible members, and add an explicit
  `allMemberIds` or backend member list when the region card needs total
  membership beyond the render budget.
- Preserve the current invariant: cluster stars carry true hidden counts.
- Add tests for region math, especially `shown + hidden = count`.

### World Shell

Files:

- [apps/wiki-cockpit/src/components/WorldView.tsx](../../../apps/wiki-cockpit/src/components/WorldView.tsx)
- [apps/wiki-cockpit/src/components/SystemScene.tsx](../../../apps/wiki-cockpit/src/components/SystemScene.tsx)
- [apps/wiki-cockpit/src/router.ts](../../../apps/wiki-cockpit/src/router.ts)

Required changes:

- Treat `?quadrant=<facet>` as the active region for quadrants, not only as a
  camera target.
- Add active-region state to the scene route so the renderer and fallback share
  the same scope.
- Add a region work card component, preferably inside the world shell rather
  than as a separate page.
- Keep keyboard traversal: Tab/arrow group focus should announce region
  purpose, total, hidden and attention counts.
- Preserve Esc behavior: region card closes or clears region before leaving the
  world level.

### Scene Parts

Files:

- [apps/wiki-cockpit/src/scene/parts/labels.tsx](../../../apps/wiki-cockpit/src/scene/parts/labels.tsx)
- [apps/wiki-cockpit/src/scene/parts/fallback.tsx](../../../apps/wiki-cockpit/src/scene/parts/fallback.tsx)
- [apps/wiki-cockpit/src/scene/parts/hud.tsx](../../../apps/wiki-cockpit/src/scene/parts/hud.tsx)
- [apps/wiki-cockpit/src/scene/parts/markers.tsx](../../../apps/wiki-cockpit/src/scene/parts/markers.tsx)
- [apps/wiki-cockpit/src/scene/parts/nodes.tsx](../../../apps/wiki-cockpit/src/scene/parts/nodes.tsx)

Required changes:

- Replace simple rim pills with region pills that can show attention chips in a
  tiny but legible way.
- Add tooltip/passport details on hover/focus.
- Add fallback region cards with the same labels and counts as the 3D scene.
- Update minimap labels so active-region scoping is visible.
- Avoid text overflow on mobile. Long Portuguese labels must wrap or shrink
  predictably without overlapping the command bar.

### i18n And Presentation

Files:

- `apps/wiki-cockpit/src/data/visualPrimitives.ts` (new planned registry)
- [apps/wiki-cockpit/src/data/i18n.ts](../../../apps/wiki-cockpit/src/data/i18n.ts)
- [apps/wiki-cockpit/src/data/presentation.ts](../../../apps/wiki-cockpit/src/data/presentation.ts)
- [apps/wiki-cockpit/src/data/typeCatalog.tsx](../../../apps/wiki-cockpit/src/data/typeCatalog.tsx)

Required changes:

- Add EN and PT strings for region purpose, action hints and attention hints.
- Use existing lucide icons where possible for action hints.
- Keep page-type family labels short enough for region cards.
- Ensure type/family glyphs do not compete with context hue or state accents.

### Visual Primitive Registry

Files:

- `apps/wiki-cockpit/src/data/visualPrimitives.ts` (new planned registry)
- [apps/wiki-cockpit/src/scene/parts/labels.tsx](../../../apps/wiki-cockpit/src/scene/parts/labels.tsx)
- [apps/wiki-cockpit/src/scene/parts/fallback.tsx](../../../apps/wiki-cockpit/src/scene/parts/fallback.tsx)
- [apps/wiki-cockpit/src/components/BlocksDock.tsx](../../../apps/wiki-cockpit/src/components/BlocksDock.tsx)

Required changes:

- Define primitive, slot and pack IDs as closed TypeScript unions.
- Map every primitive to purpose text, allowed slots, required data fields,
  accessibility label builder and component renderer.
- Resolve the active pack from the anchor's `visual_grammar`; fall back to the
  kit baseline when no block is attached.
- Surface the resolved pack and primitive purposes in the Blocks dock so the
  visual grammar is inspectable like any other template-derived behavior.
- Keep CSS variables limited to spacing, tone and motion. Meaning comes from
  primitive ID plus snapshot data, not from arbitrary class names.

## Demo Changes

The public demo must be edited to prove the refactor before downstream use.
The first synthetic stress set was added on 2026-07-08 in
[scripts/wiki_build_demo.py](../../../scripts/wiki_build_demo.py): product
analytics/support sources, ingestion events, region-map artifacts, open region
actions and unsourced/stale claims under the `clientes` and `Clearpath` nested
centers. The remaining work is to make the new region UI expose this data.

Files:

- [scripts/wiki_build_demo.py](../../../scripts/wiki_build_demo.py)
- [docs/references/fixtures/demo-wiki/](../../../docs/references/fixtures/demo-wiki/)
- [apps/wiki-cockpit/public/sample-snapshot/](../../../apps/wiki-cockpit/public/sample-snapshot/)

Required demo scenarios:

- A dense Outputs and evidence region with at least enough synthetic pages to
  trigger hidden clusters and type mix.
- At least two resolved visual primitive packs: for example
  `region_operations` at the root and `evidence_first` or `review_first` under
  a nested client/company center.
- At least one region with open actions, stale pages and unsourced conclusions.
- At least one raw/source-heavy region where untreated input is visually
  distinct from consolidated memory.
- At least one healthy region so the design proves calm state, not only alarm.
- At least one nested center where region summaries change when `?center=...`
  changes.
- At least one empty required quadrant/facet that shows an honest absence and a
  valid create/brief affordance.

Regenerate the demo after fixture edits:

```sh
/opt/anaconda3/bin/python scripts/wiki_build_demo.py
```

The regenerated demo must not require a live private operator and must keep the
banner that marks synthetic data.

## Implementation Phases

### Phase 0 - Branch And Current-State Audit

- Work on `wiki/visual-region-grouping-plan` or a follow-up
  `wiki/visual-region-grouping-impl` branch.
- Re-fetch remotes and record unmerged branches before implementation.
- Keep the current local `main` active-center fixes as the baseline.
- Restart local servers before final visual validation.

### Phase 1 - Data Contract

- Add tests around region summary generation in the Python core or snapshot
  builder.
- Decide whether summaries live in `block_stacks.json` or
  `region_groups.json`.
- Preserve backward compatibility for `quadrant_assignments` and `WorldGroup`.
- Add schema/version metadata.

### Phase 1A - Visual Primitive Contract

- Add `VISUAL_PRIMITIVES`, `VISUAL_PRIMITIVE_PACKS` and
  `VISUAL_PRIMITIVE_SLOTS` to
  [wiki_core/template_blocks.py](../../../wiki_core/template_blocks.py).
- Add validation for unknown primitive IDs, pack IDs and slot IDs.
- Add a resolved `visual_grammar` output per anchor.
- Add or extend `wiki.block.ui_regions.v1` / `wiki.block.visual_grammar.v1` in
  [wiki.templates.yaml](../../../wiki.templates.yaml).
- Add a frontend `visualPrimitives.ts` registry with typed primitive/slot/pack
  IDs and baseline fallback behavior.

### Phase 2 - Public Demo Proof

- Edit the synthetic demo fixture/script to create dense, actionable region
  scenarios.
- Regenerate `apps/wiki-cockpit/public/sample-snapshot/`.
- Add tests or snapshots that assert the public demo contains the required
  region conditions.
- Add fixture coverage for at least two primitive packs and one pack override
  below a nested center.

### Phase 3 - Frontend Region UI

- Add the region work card.
- Upgrade quadrant compass cells and rim pills.
- Add active-region filtering to nodes, labels and relation lines.
- Add fallback/mobile region lists with the same data.
- Replace direct visual branching with primitive-slot resolution where the
  region UI is touched.
- Update i18n strings in EN and PT.

### Phase 4 - Visual And Accessibility Hardening

- Validate desktop and mobile screenshots.
- Validate long PT labels in the private cockpit.
- Validate keyboard group traversal and aria-live region announcements.
- Validate reduced-motion and `?visual=1` fallback.
- Confirm no text overlaps command bar, minimap or reader.

### Phase 5 - Downstream Read-Only Comparison

- Regenerate the private snapshot.
- Run private cockpit at a clean port from the real repo checkout.
- Compare private totals and active-region behavior without writing private
  content into the kit.
- Record any migration warnings as inventory, not hidden failures.

### Phase 6 - Gates

Run the standard repo gates before PR:

```sh
/opt/anaconda3/bin/python scripts/wiki_audit.py --check
/opt/anaconda3/bin/python scripts/wiki_check_methodology_coverage.py --check
/opt/anaconda3/bin/python scripts/wiki_operation_compile.py --check
/opt/anaconda3/bin/python scripts/wiki_input_stage.py --check
/opt/anaconda3/bin/python -m pytest tests/
npm --prefix apps/wiki-cockpit test
npm --prefix apps/wiki-cockpit run build
npm --prefix apps/wiki-cockpit run test:visual
```

If visual snapshots change intentionally, regenerate them only after manual
browser inspection confirms the new region behavior is correct.

## Test Plan

### Unit / Data Tests

- Region summaries count all pages in the region, not only rendered nodes.
- Hidden count equals total minus shown.
- State counts match page records.
- Raw/unsourced counts match source/page-type and evidence rules.
- Action hints are emitted only from existing missions, actions, diff, gates,
  freshness or source data.
- Core count stays narrow; known source/governance pages do not silently fall
  into core.
- Unknown visual primitive, pack or slot IDs produce template validation
  warnings/errors according to the existing WARN-first registry policy.
- Resolved `visual_grammar` output is deterministic for the same stack and
  snapshot.

### Template / Primitive Tests

- `wiki.block.ui_regions.v1` or `wiki.block.visual_grammar.v1` resolves the
  default pack when no override is present.
- Anchor-level pack overrides win over kit defaults without mutating the
  registry.
- Pack extension merges slots key-by-key and does not drop required baseline
  slots.
- Private/local overrides can choose an allowed pack but cannot invent an
  unknown primitive silently.
- `blocks.json` exposes the visual vocabulary for author inspection.

### Frontend Tests

- Quadrant compass cells render total, hidden and attention summaries.
- Selecting a quadrant shows a region work card.
- Region work card filters nodes and relation lines without changing page
  identity.
- Region card actions open the correct dock or filter.
- Fallback renders the same region summaries.
- Primitive slot resolution renders the same semantic primitive in 3D labels,
  fallback cards and Blocks dock diagnostics.
- PT strings fit on mobile.
- Keyboard traversal announces region summaries.

### Browser Checks

Use Playwright/browser inspection on:

- `http://127.0.0.1:5173/demo/w/quadrants`
- `http://127.0.0.1:5173/demo/w/quadrants?visual=1`
- `http://127.0.0.1:5173/demo/w/quadrants?quadrant=pratica`
- `http://127.0.0.1:5174/w/quadrants` read-only after private snapshot rebuild
- a mobile viewport for both demo and private cockpit

Checks:

- No overlap between region card, command bar, minimap and reader.
- Region selection is visually obvious but not alarm-colored unless data says
  there is attention.
- Dense private regions become easier to inspect than the current cloud of
  nodes and lines.
- The demo still clearly says it is synthetic sample data.

## Risks And Countermeasures

- **Risk: region card becomes another dashboard panel.** Keep it compact,
  scoped and dismissible. It exists to navigate the world, not replace it.
- **Risk: action hints become fabricated advice.** Derive them only from
  existing mission/action/gate/source data and test that empty data emits no
  action.
- **Risk: color semantics drift.** Keep hue=context and state=tone/annotation.
  Use shapes, glyphs and text for type/action differences.
- **Risk: visual primitives become a theming API.** Keep primitives semantic,
  closed and purpose-documented. Allow labels, density and local pack choice,
  not arbitrary CSS or private-only behaviors.
- **Risk: primitive packs hide important signals.** Require baseline slots for
  attention, hidden mass and empty states; pack overrides can replace the
  renderer but cannot remove required warnings.
- **Risk: mobile regression.** Treat fallback/mobile as first-class in the same
  PR, not a follow-up.
- **Risk: public demo under-proves the private problem.** Add synthetic density
  and hidden clusters before claiming the design works.
- **Risk: core hides classification bugs.** Add report warnings and card copy
  that names core growth as classification debt.
- **Risk: unmerged branches contain relevant work.** Review the two public
  unmerged plan branches before implementation and either supersede them in the
  PR description or cherry-pick only deliberate pieces.

## Definition Of Done

The refactor is complete only when all of these are true:

- A public synthetic demo shows region grouping at realistic density without
  private data.
- Region summaries are deterministic snapshot data, not UI-only guesses.
- Visual primitive, pack and slot vocabularies are fixed in code, validated by
  the template compiler and documented for authors.
- Every new visual cue appears in the primitive registry with purpose, input
  data, allowed slots and fallback behavior.
- Quadrant regions, core and hidden clusters expose type mix, attention and
  valid next actions.
- Selecting a region changes navigation, filtering and explanation, not only
  camera position.
- 3D, minimap, 2D fallback, keyboard and mobile all expose the same region
  contract.
- EN and PT labels are implemented and visually checked.
- The public demo proves at least two primitive packs and one nested-center
  pack override using synthetic data.
- The private cockpit is checked read-only after snapshot regeneration.
- Standard Python gates, cockpit tests, build and visual tests pass or any
  failures are documented as true blockers.
- The PR explains the public/private boundary and why each visual cue exists.

## Open Questions

- Should region summaries be a new `region_groups.json` file or an extension of
  `block_stacks.json`? Prefer `region_groups.json` if the payload becomes large.
- Should active region stay as `?quadrant=<facet>` for quadrants and
  `:group` for other perspectives, or should the router gain a generic
  `?region=<kind>:<key>` query? Prefer compatibility first, then generic query
  only if cross-perspective region state becomes confusing.
- Should `ui_regions` be a standalone interface block, or should region cards
  be considered part of any `ui_views`/quadrants-capable world? Prefer a
  standalone block if non-quadrant perspectives reuse it.
- Should visual grammar be a separate `wiki.block.visual_grammar.v1` block, or
  a config section under `wiki.block.ui_regions.v1`? Prefer `ui_regions` first
  if the first implementation only affects region grouping.
- Should primitive pack overrides be allowed per page type, per anchor, or only
  per anchor stack? Prefer anchor stack first; page-type presentation should
  select primitives, not override the full grammar.
