# Extending the kit — the four axes

Four things you can add, from cheapest to most invasive: a **block**, a **page
type**, a **dock**, a **perspective**. The first two are mostly YAML; the last
two are code across several files — this guide lists every file honestly, as
the code is today, so you don't discover the fifth file after shipping four.

Everything lands **kit-first** through the PR gate; a private wiki only ever
receives cascaded code, never hand edits.

---

## A. A new BLOCK

Composing existing vocabulary is YAML-only; new vocabulary is code.

**YAML-only (the common case):**

1. Define it under `blocks:` in
   [wiki.templates.yaml](../../../wiki.templates.yaml) (kit) or
   `wiki.templates.local.yaml` (one wiki), or as a wiki page of
   `page_type: template_block` with a frontmatter `block:` mapping carrying a
   `block_id` (the page wins over the registry on an id clash). Required keys:
   `kind` (one of `interpretation|interface|gate|skill`), `scope.default_mode`;
   interface blocks also need `surface:`.
2. Attach it — `types.<t>.blocks` in the registry, or frontmatter
   `blocks:`/`packages:` on a page whose type has `can_anchor_blocks: true`.
3. Validate: `python3 scripts/wiki_audit.py` (the `templates_registry` check
   runs `validate_blocks` from
   [wiki_core/template_blocks.py](../../../wiki_core/template_blocks.py)).

**When code is needed:**

- A new *kind, surface, scope mode, mission provider, intake form, score loop,
  scene layout/overlay or identity landmark*: add it to the corresponding
  frozenset in [wiki_core/template_blocks.py](../../../wiki_core/template_blocks.py)
  (`BLOCK_KINDS`, `SURFACES`, `SCOPE_MODES`, `MISSION_PROVIDERS`,
  `INTAKE_FORMS`, `SCORE_LOOPS`, `SCENE_LAYOUTS`, `SCENE_OVERLAYS`,
  `IDENTITY_LANDMARKS`/`_MOTIFS`/`_AMBIENTS`) — the validator rejects unknown
  values by design.
- A new *derived output* (something the compiler computes from the scope, like
  `quadrant_assignments` or `relations`): implement it in
  `template_blocks.py` (`derived_outputs()` and a builder like
  `relations_derived()`).
- A new *mission provider's actual computation*: providers are validated in
  `template_blocks.py` but executed either by the compiler (`derived_outputs`
  — quadrant absence, relations, subpage conformity) or by the cockpit
  ([apps/wiki-cockpit/src/components/MissionsPanel.tsx](../../../apps/wiki-cockpit/src/components/MissionsPanel.tsx),
  `deriveMissions()` — stale, gates, approvals…). Add code where the data
  lives.
- If the block should gate a top-level instrument (a command-bar destination,
  the weather, the perspectives offer): wire it in
  [apps/wiki-cockpit/src/data/surfaces.ts](../../../apps/wiki-cockpit/src/data/surfaces.ts)
  (`composeInstruments()` — the ONE place that answers "which instruments
  exist in this world, and why").
- If the block contributes region grouping or visual grammar: use the existing
  `ui_regions` surface when possible. New visual primitives, primitive packs or
  slots require code in
  [wiki_core/template_blocks.py](../../../wiki_core/template_blocks.py)
  (`VISUAL_PRIMITIVES`, `VISUAL_PRIMITIVE_PACKS`,
  `VISUAL_PRIMITIVE_SLOTS`), a frontend registry entry in
  `apps/wiki-cockpit/src/data/visualPrimitives.ts`, and tests. YAML may choose
  a known pack; it must not introduce arbitrary styling.
- Give it a face: an icon in `BLOCK_ICONS` and an i18n `block.desc.<family>`
  line (EN + PT) in
  [apps/wiki-cockpit/src/data/typeCatalog.tsx](../../../apps/wiki-cockpit/src/data/typeCatalog.tsx)
  and [apps/wiki-cockpit/src/data/i18n.ts](../../../apps/wiki-cockpit/src/data/i18n.ts).
  Fallbacks exist (generic Boxes icon, the registry `summary`), so this step
  degrades honestly rather than blocking.

## B. A new PAGE TYPE

No frontend code required for a working type; the cockpit falls back to a
readable default for unknown types. The full checklist:

1. **Validation contract** — add the type to
   [wiki.page-types.yaml](../../../wiki.page-types.yaml): `template:` path,
   `allowed_dirs`, `required_frontmatter`, `field_types`. Without this,
   `scripts/wiki_new.py` refuses to create pages of the type — if you skip it
   on purpose, set `creatable: false` in the registry so the palette never
   offers what cannot be born.
2. **Body template** — the Markdown skeleton under
   [docs/references/templates/wiki/](../templates/wiki/).
3. **Presentation contract** — a `types:` entry in
   [wiki.templates.yaml](../../../wiki.templates.yaml) (or
   `wiki.templates.local.yaml`): usually `extends: relation_base` plus the
   keys the type emphasizes (`view`, `scene`, `facets`, `pinned_fields`) and
   the v2 module keys where they apply (`creatable`, `home_quadrant`,
   `can_anchor_blocks`, `blocks`, `identity`, `subpages`, `skills`). A
   `home_quadrant:` here is honored as the type's local semantic default — the
   compiler's active-center projections (`_home_quadrant_overrides` +
   `project_quadrants` in `template_blocks.py`) and the seed flow's ghost
   position (`homeOverrides` in
   [apps/wiki-cockpit/src/scene/spatial.tsx](../../../apps/wiki-cockpit/src/scene/spatial.tsx))
   both read it.
   For a type that can become a center under another center, also decide its
   parent projection. Built-in root entities already default to
   `company -> q4`, `product -> q2`, `person/team/community -> q3`,
   `project -> q1`; page frontmatter `parent_projection:` can override this.
4. **The human face** (recommended) — in
   [apps/wiki-cockpit/src/data/typeCatalog.tsx](../../../apps/wiki-cockpit/src/data/typeCatalog.tsx):
   an icon in `TYPE_ICONS`; in
   [apps/wiki-cockpit/src/data/i18n.ts](../../../apps/wiki-cockpit/src/data/i18n.ts):
   `type.desc.<t>` (what it is / when to use it), `type.namePrompt.<t>` and
   `type.nameExample.<t>` — in BOTH the `EN` and `PT` dictionaries. Fallbacks:
   the family description, the generic name prompt, a FileText icon.
5. **Static quadrant fallback** (only if needed) — the compiler's derived
   assignments are authoritative, but bare worlds without a resolved stack fall
   back to the static per-type maps: `DEFAULT_PAGE_TYPE_FACET` in
   [wiki_core/facets.py](../../../wiki_core/facets.py) and `PAGE_TYPE_FACET` in
   [apps/wiki-cockpit/src/scene/facets.ts](../../../apps/wiki-cockpit/src/scene/facets.ts).
   A default sub-lens inside the quadrant is `SUBLENS_DEFAULT_BY_TYPE` in
   `template_blocks.py` (else the quadrant's first sub-lens is used).
6. Validate + verify: `python3 scripts/wiki_audit.py`, then create one page and
   inspect it in the cockpit (type chip → template inspector, `F` → Focus).

## C. A new DOCK

Docks are the in-world work surfaces (`?dock=…`). Adding one touches several
files today — all of them:

1. [apps/wiki-cockpit/src/router.ts](../../../apps/wiki-cockpit/src/router.ts)
   — add the id to the `DOCKS` const (URL validation; unknown ids parse to
   `""`). Esc-closing, the one-surface-at-a-time singleton and `?src=` cleanup
   in `patchWorld` are generic — no work there.
2. A component in `apps/wiki-cockpit/src/components/<Name>Dock.tsx` (follow
   `BlocksDock.tsx` / `GatesDock.tsx` for the shape: props in, `onClose` out).
3. [apps/wiki-cockpit/src/App.tsx](../../../apps/wiki-cockpit/src/App.tsx) —
   import it and add the render block gated on
   `route.query.dock === "<id>"` (see `blocksDockOpen` and friends around the
   `<*Dock … onClose={…dock: null…}/>` cluster). If the dock should also be
   reachable from the 2D pages' left rail, add it to `Nav`'s items and the
   `dockNavId` highlight map.
4. [apps/wiki-cockpit/src/components/WorldView.tsx](../../../apps/wiki-cockpit/src/components/WorldView.tsx)
   — add an entry (icon, label, live count, tone) to the command-bar
   destinations array. The button only renders if the destination is offered.
5. [apps/wiki-cockpit/src/data/surfaces.ts](../../../apps/wiki-cockpit/src/data/surfaces.ts)
   — decide WHEN the destination exists and push it into
   `Instruments.destinations` in `composeInstruments()`. A destination exists
   only when a block on the stack provides its surface (or, like
   `approve`/`gates`, because it is law-tier and arrives with the root) — do
   not add an unconditional button for a conditional surface.
6. [apps/wiki-cockpit/src/data/i18n.ts](../../../apps/wiki-cockpit/src/data/i18n.ts)
   — `nav.<x>` (the label) and `dock.mission.<id>` (the purpose tooltip), in
   BOTH `EN` and `PT`.

Note the two docks that are deliberately NOT command-bar destinations today:
`codex` (opened from diagnostics affordances) and `work` (opened from the work
tray) — `DOCKS` membership and destination membership are separate decisions.

## D. A new PERSPECTIVE

Perspectives are the world layouts (`/w/:perspective/…`). The full list, as the
code is today:

1. [apps/wiki-cockpit/src/router.ts](../../../apps/wiki-cockpit/src/router.ts)
   — add the id to `PERSPECTIVES`. If a selected AQAL quadrant should scope it,
   also add it to the `QUADRANT_AWARE` set; if it is ego-centric (page in the
   URL, no group slot), teach the positional-grammar special case in
   `parseRoute` and `isEgoPerspective` in `WorldView.tsx` (like
   `trails`/`focus`).
2. [apps/wiki-cockpit/src/scene/perspectives.ts](../../../apps/wiki-cockpit/src/scene/perspectives.ts)
   — write the layout function (deterministic; emits `nodes`, `groups`,
   `clusterStars` with TRUE hidden counts, `guides`) and dispatch it in
   `computeWorldLayout()`. If the perspective has drillable groups, extend
   `groupKeyForPage()` so page selection can emit canonical URLs.
   If the perspective reuses operational groups, keep `WorldGroup` compatible
   and attach compiled region payloads (`derived.region_groups`) in the shell
   rather than recalculating attention/action summaries inside the layout.
3. [apps/wiki-cockpit/src/components/WorldView.tsx](../../../apps/wiki-cockpit/src/components/WorldView.tsx)
   — add the id to the perspective-glyphs array in the command bar (the button
   renders only if the stack offers the view).
4. [apps/wiki-cockpit/src/components/SystemScene.tsx](../../../apps/wiki-cockpit/src/components/SystemScene.tsx)
   — the digit-hotkey map (`perspectiveKeys`: today `1`–`5` for
   radar/atlas/districts/trails/quadrants; `focus` hangs on `F`).
5. [apps/wiki-cockpit/src/data/presentation.ts](../../../apps/wiki-cockpit/src/data/presentation.ts)
   — a glyph in `perspectiveLabel()`, plus i18n `perspective.<id>` and
   `perspective.<id>.hint` (EN + PT) in
   [apps/wiki-cockpit/src/data/i18n.ts](../../../apps/wiki-cockpit/src/data/i18n.ts).
6. Offer it: the default views offer is deliberately small (home + atlas +
   focus). A wiki opts in per scope via the `ui_views` block
   (`config.available`) — `composeInstruments()` intersects that list with
   what the code ships, so the YAML and the code must both know the id. If
   blocks should be able to name it as a `scene_profile.layout`, also add it
   to `SCENE_LAYOUTS` in
   [wiki_core/template_blocks.py](../../../wiki_core/template_blocks.py).

After any axis: `python3 scripts/wiki_build_demo.py` regenerates the demo
fixture and the genesis stage snapshots — if the demo does not show the new
capability, the phase that introduced it is not done.
