---
title: "Wiki Viva v6.9"
page_id: release-wiki-viva-v6-9
page_type: release_note
context: system
visibility: public_candidate
updated_at: 2026-07-07
stale_after_days: 365
sources_policy: release_note
gate: github_pr
sensitive_data_policy: no_personal_data
---

# Wiki Viva v6.9

Modular template blocks + the spatial cockpit release: templates become
complete module contracts, and the interface materializes from them.

## What Changed

- **Template blocks v2.** [wiki.templates.yaml](../../../wiki.templates.yaml)
  moves to `schema_version: wiki_templates.v2` with `blocks:` and `packages:`
  sections; the new compiler
  [wiki_core/template_blocks.py](../../../wiki_core/template_blocks.py) owns
  the fixed vocabulary (block kinds, scope modes, surfaces, providers,
  landmarks), the validation (wired into `wiki_audit.py`'s
  `templates_registry` check) and the 4-ring stack resolution
  (kit → anchor chain → template → page frontmatter, nearest ring winning
  config, every block carrying its origin). Per-anchor derived outputs —
  quadrant assignments with sub-lenses, the relations network, subpage
  obligations — ship in the snapshot as `blocks.json` + `block_stacks.json`.
  `TemplateSpec` ([wiki_core/templates_registry.py](../../../wiki_core/templates_registry.py))
  gains the v2 module keys: `can_anchor_blocks`, `blocks`, `identity`,
  `subpages`, `skills`, `home_quadrant`, `creatable`. Concept guide:
  [modular-blocks.md](../guides/modular-blocks.md).
- **Founding rite + spatial surfaces.** The interface lives IN the world
  ([apps/wiki-cockpit/src/scene/spatial.tsx](../../../apps/wiki-cockpit/src/scene/spatial.tsx)):
  an empty world's only interface is the founding rite (choose who the world
  is, a ghost root, one question); creating a page is the seed flow (curated
  cards, a ghost at the type's home quadrant); the first reading level is an
  anchored summary plate at the node; the genesis tutorial speaks through a
  beacon anchored to each step's subject. The shell composes its instruments
  from the root's resolved block stack
  ([apps/wiki-cockpit/src/data/surfaces.ts](../../../apps/wiki-cockpit/src/data/surfaces.ts))
  — no gamification package, no missions and no weather; no quadrants block,
  no quadrant map; empty world, no instruments at all.
- **Curated creation.** Every create surface reads
  [apps/wiki-cockpit/src/data/creation.ts](../../../apps/wiki-cockpit/src/data/creation.ts)
  instead of dumping the registry: the scope's `ui_create` catalog is the small
  first level, everything else creatable waits behind "more types…", and
  `creatable: false` types (generated/system/rite-owned) are never offered —
  the palette must not offer what cannot be born.
- **Quadrant derivation obeyed by the scene.** Quadrants is the default landing
  view (key `5`); the root entity sits at the crossing of the axes, and the
  scene's per-page classification is the compiler's derived
  `quadrant_assignments` (frontmatter `home_quadrant`/`observed_quadrants`,
  sub-lenses and registry overrides all honored) with the static page-type map
  only as fallback ([apps/wiki-cockpit/src/scene/facets.ts](../../../apps/wiki-cockpit/src/scene/facets.ts)).
  A selected quadrant scopes the quadrant-aware perspectives
  (quadrants/radar/districts).
- **Source sync derived from ingestion events.**
  [wiki_core/web/sources.py](../../../wiki_core/web/sources.py) indexes the
  wiki's own `ingestion_event` pages per source; when a source page's `sync:`
  block is absent or still says `never`, the newest event supplies the status
  honestly (`derived_from_event: true` so the UI can say so).
- **Root is the world's top.** In
  [wiki.page-types.yaml](../../../wiki.page-types.yaml), `moc_parent` is now
  OPTIONAL for `root_entity`: the root descends from nothing; everything
  descends from it (the anchor-scope model).
- **Operator snapshot cache TTL.**
  [wiki_core/web/server.py](../../../wiki_core/web/server.py) caches the live
  snapshot for `SNAPSHOT_CACHE_TTL_S = 600`; every mutating action invalidates
  it, so the TTL only bounds staleness from external edits — a browsing session
  no longer pays a full wiki walk per request.
- **Staged demo.** [scripts/wiki_build_demo.py](../../../scripts/wiki_build_demo.py)
  builds the demo as a real fixture wiki (Alex Rivera) compiled by the same
  `build_snapshot` as any wiki, plus one real snapshot per genesis stage
  (`stages/<k>/` + `stages.json`). `/demo` is a title screen: start from zero
  (`/demo/genesis`) or the full world (`/demo/world`). Stages differ only by
  data — the tutorial swaps bundles; it never simulates state client-side.

## Validation

```sh
python3 -m pytest tests/test_template_blocks.py tests/test_templates_registry.py \
  tests/test_web_sources.py tests/test_web_server.py
python3 scripts/wiki_audit.py
python3 scripts/wiki_build_demo.py
npm --prefix apps/wiki-cockpit test
```
