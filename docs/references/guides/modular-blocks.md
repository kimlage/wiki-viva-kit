# Modular template blocks (wiki_templates.v2)

A **template** is the complete contract of an information module: how content
below it is interpreted (lenses), what the interface offers (surfaces), how the
place looks (identity), what structure is born with it (subpages). A **block**
is the modular unit of those contributions.

Source of truth: the compiler in
[wiki_core/template_blocks.py](../../../wiki_core/template_blocks.py) owns the
vocabulary, the validation and the stack resolution; the kit's block registry
lives in [wiki.templates.yaml](../../../wiki.templates.yaml) (`blocks:` and
`packages:` sections, `schema_version: wiki_templates.v2`). The compiler reads
the registry, the pages and the link graph; it writes nothing. Its outputs land
in the snapshot as `blocks.json` (the registry + vocabulary) and
`block_stacks.json` (one resolved record per anchor), which the cockpit reads.

---

## 1. What a block is

A block contributes one kind of thing to a scope (`BLOCK_KINDS`):

| Kind | Contributes | Kit examples |
| --- | --- | --- |
| `interpretation` | a lens — how pages below the anchor are read | `wiki.block.quadrants.v1`, `wiki.block.relations.v1`, `wiki.block.perspective_bundle.v1` |
| `interface` | a surface — something the cockpit offers | `ui_views`, `ui_missions`, `ui_create`, `ui_intake`, `gamification` |
| `gate` | a rule that can fail — errors/warnings for the audit | `privacy_boundary`, `git_human_gate`, `source_recipe` |
| `skill` | a capability reference (human or agent) | declared per type under `skills:` |

Interface blocks name their surface (`SURFACES`): `views`, `missions`,
`create`, `intake`, `score`, `panels`. Interpretation blocks *reference*
perspective pages (e.g. `quadrants.v1` maps q1→`perspective-identity-intent`);
the lens content lives on those pages, human-authored and PR-gated — the block
never duplicates it.

`ui_regions` is the interface block for practical region grouping. It turns the
same interpreted regions into work groups: region cards, attention rails, type
shelves, hidden histograms and action hints. The visual layer is still a fixed
vocabulary: templates choose known primitive packs (`region_operations`,
`evidence_first`, `review_first`, `quiet_structure`), never arbitrary CSS.

The vocabulary is **fixed in code** — a new kind, surface, mission provider,
intake form, score loop, scene layout/overlay or identity landmark needs code
in `wiki_core/template_blocks.py`, never just YAML. The `vocabulary:` section
in `wiki.templates.yaml` documents it for authors; `validate_blocks()` flags
anything outside it (WARN-first, surfaced by the `templates_registry` check in
[scripts/wiki_audit.py](../../../scripts/wiki_audit.py)).

## 2. Scope modes

A block applies to a scope relative to its **anchor** (`SCOPE_MODES`):

- `self` — the anchor page only (e.g. `source_recipe` on a source).
- `children` — direct `moc_parent` children.
- `descendants` — the whole `moc_parent` subtree (the default for most blocks).
- `context` — every page sharing the anchor's `context` value.

Each block declares a `scope.default_mode` (and optionally `allowed_modes`);
an attachment can override it (`{ id: …, scope: children }`).

## 3. Anchors (`can_anchor_blocks`)

Only page types with `can_anchor_blocks: true` in the template registry may
carry `blocks:` / `packages:` in frontmatter — the kit's anchor types are
`root_entity`, `context_hub`, `holon`, `project`, `source` and
`template_block`. Attaching blocks to a non-anchor page is a validation error.
The `TemplateSpec` dataclass in
[wiki_core/templates_registry.py](../../../wiki_core/templates_registry.py)
carries the full v2 type contract: `can_anchor_blocks`, `blocks`, `identity`
(landmark/motif/ambient/horizon_label), `subpages` ({rel, page_type, slug?,
required|generated}), `skills`, `home_quadrant` and `creatable`.

## 4. Packages

A **package** is a named group of blocks — attachment sugar for setup flows and
frontmatter (`packages: [gamification]`). Blocks remain the primitive; a
package expands to its blocks, in order, at the ring where it is attached. The
kit ships two:

- `gamification` → `ui_missions.v1` + `gamification.v1` (missions, weather,
  karma — no leaderboard, ever).
- `quadrant_lenses` → `quadrants.v1` + `relations.v1`.

## 5. Where blocks are defined vs. where they apply

Blocks come from three rings of **definition**:

1. the kit registry (`wiki.templates.yaml` `blocks:`),
2. a per-wiki local override (`wiki.templates.local.yaml`, merged on top),
3. wiki pages of `page_type: template_block` carrying a frontmatter `block:`
   mapping with a `block_id` (the page wins over the registry on an id clash).

They apply to a page through **four rings of resolution** (`resolve_stack()`),
each ring overriding the previous, config merged key-by-key so the nearest ring
wins:

1. **Kit defaults** — top-level `vocabulary.default_blocks` in the registry, if
   any (the kit currently declares none).
2. **The anchor chain, root-first** — every ancestor anchor's *template* blocks
   plus its *frontmatter* blocks and packages, kept only if their scope reaches
   the page.
3. **The page's own template** — the blocks its type declares
   (`types.<t>.blocks` in the registry).
4. **The page's own frontmatter** — `blocks:` and `packages:` on the page
   itself (nearest, wins last).

Every resolved block carries its `origin` (`kit`, `anchor:<page_id>`,
`template:<page_type>`, `page`) — the Blocks dock (`?dock=blocks`) shows this
X-ray per anchor, read straight from `block_stacks.json`.

## 6. Derived outputs

For each anchor, `derived_outputs()` computes:

### Quadrant assignments

When `wiki.block.quadrants.*` is on the stack, pages are projected into
`q1..q4` or the honest `q0_core` **relative to the active anchor**. Quadrants are
not global page attributes. The same page can be `q4` for a person/root because
it belongs to a company system, and `q1` for that company because it states the
company's own perception or intent.

`q0_core` is deliberately narrow: it is the active center/root position, not a
parking lot for pages the model has not classified. Source pages, source
catalogs, source registries, logs, ingestion events and dashboards are Q2 when
they are observable traces/evidence of the wiki's work. Operational rules,
processes, input channels, source configs and other coordination machinery are
Q4. Hubs and nested centers should either have an explicit parent projection or
use the built-in center defaults; they should not silently disappear into Q0.

Methodological sources: the kit follows the Wilber/AQAL quadrant axes summarized
by Integral Life: Q1 is upper-left/interior-individual, Q2 is
upper-right/exterior-individual, Q3 is lower-left/interior-collective and Q4 is
lower-right/exterior-collective. See [Four Quadrants](https://integrallife.com/four-quadrants/),
[The Four Quadrants: A Guided Tour](https://integrallife.com/the-four-quadrants-a-guided-tour/),
[What Is Integral Approach?](https://integrallife.com/what-is-integral-approach/)
and [The Five Elements of AQAL](https://integrallife.com/five-elements-aqal/).
The local audit report
[AQAL quadrant alignment check](../reports/aqal-quadrant-alignment-2026-06-25.md)
records how those sources map into the kit's operational tests.

The compiler emits two compatible outputs:

- `quadrant_assignments`: the legacy page-id buckets consumed by the cockpit.
- `quadrant_projections`: the auditable reason for each bucket
  (`page_semantics`, `subject_role`, `projection_override`,
  `nested_center_self_projection`, `nested_center_projection`).

The cockpit keeps this center separate from the reader page. Without an
explicit center it uses the selected page's nearest anchor, preserving old deep
links. When a user chooses a root, company, project, source or template anchor
as the active center, the URL stores it as `?center=<anchor_id>`; opening a
different reader page keeps that center so the PageReader can show both
"placement here" and the page's local placement inside its subject center.

Projection rules:

1. `projection_overrides.<center>:` on the page wins for exceptional cases.
2. If the active anchor has a nested anchor below it, all pages in that nested
   sub-world first project through the immediate child anchor. Example: Alex
   sees Clearpath Labs and its descendants as `q4/sistemas` (systems and
   governance); Clearpath sees its product as `q2/pratica` (outputs and
   evidence); the product sees its own claim as `q1/intencao` (identity and
   intent).
3. A nested center's `parent_projection:` states how its parent should see it.
   If absent, `root_entity_type` defaults apply (`company -> q4`,
   `person/team/community -> q3`, `product -> q2`, `project -> q1`).
4. Inside the active center, local semantics apply: `subject_role`, then
   `observed_quadrants`, then explicit `quadrant`, then `home_quadrant`, then the registry's
   `home_quadrant`, then the type default from
   [wiki_core/facets.py](../../../wiki_core/facets.py), then edge fallback.
5. Else `q0_core` — only an actually unclassified center/root-like page should
   reach this bucket. A source, log, catalog, registry or evidence page reaching
   Q0 is a classification bug.

Within a projected quadrant a page also gets a **sub-lens** (the quadrant
interior, `SUB_LENSES` — e.g. q1: percepcao/intencao/identidade): explicit
frontmatter `sub_lens:` wins, then a per-type/default projection lens, then the
quadrant's first option. Required quadrants left empty become
`quadrant_absence` missions.

### Relations

When `wiki.block.relations.*` is on the stack, `person` pages in scope are read
as a cared-for network: `relationship.contact_cadence_days` vs the last
interaction (derived from the graph — the newest meeting/journal/ingestion
event that links the person, never a new store), `dates:` within 30 days, and
`commitments:` due within 7 days. Breaches become `relation_cadence_overdue`,
`date_upcoming` and `commitment_open` missions.

### Subpage obligations

A type's `subpages:` with `required: true` that are absent become
`template_conformity` missions (and feed the create surface's
`obligations` list).

### Region groups and visual grammar

When a quadrant-capable anchor also has `wiki.block.ui_regions.v1` (or receives
it through a package), the compiler emits:

- `visual_grammar`: the resolved primitive packs and slots for the anchor.
- `derived.region_groups`: one deterministic work-group record per quadrant
  and, when populated, the honest core group.

Each region group carries practical counts (`total`, `shown`, `hidden`,
`stale`, `raw`, `unsourced`, `open_actions`, `source_backed`), `type_mix`,
`attention_hints`, `action_hints`, member IDs and the resolved visual primitive
slots. The cockpit uses this payload in the quadrant compass, rim cards,
fallback list and Blocks dock. It does not infer actions from styling.

## 7. How the interface materializes from the stack

The stack decides what interface exists — per anchor in the compiler
(`resolve_interface()`), and for the whole cockpit shell in
[apps/wiki-cockpit/src/data/surfaces.ts](../../../apps/wiki-cockpit/src/data/surfaces.ts)
(`composeInstruments()`, which reads the ROOT anchor's record):

- **Empty world → founding rite.** With zero pages, `composeInstruments`
  returns `worldEmpty: true` — no destinations, no search, no missions. The
  founding rite (`FoundingRite` in
  [apps/wiki-cockpit/src/scene/spatial.tsx](../../../apps/wiki-cockpit/src/scene/spatial.tsx))
  is the empty world's ONLY interface: 3+1 cards (person/team/company, plus
  project/community/product behind "something else…"), a ghost root, one name
  question. Its single outcome is a create brief for the `root_entity` — the
  root is rite-owned, never offered by the generic palette.
- **Views.** The home view comes from the stack: `ui_views` config `default`,
  else `quadrants` when the quadrants block is attached, else `radar`. The
  default offer is deliberately small (`[default, atlas, focus]`) — radar/
  districts/trails exist in the vocabulary but a wiki opts INTO them via
  `available:`. A view that has no purpose yet has no button.
- **`ui_create` catalog → curated palette.** The scope's `catalog:` is the
  small first level of the create surface; everything else creatable waits
  behind "more types…" ([apps/wiki-cockpit/src/data/creation.ts](../../../apps/wiki-cockpit/src/data/creation.ts),
  `curatedPalette()`). Arrangement is `by_quadrant` only when the quadrants
  block is present. A catalog may be empty with a `disabled_reason` (the kit's
  `source` type: content is born by ingestion, not by hand).
- **`ui_missions` / `gamification` → missions + weather.** The missions surface
  exists only when `ui_missions` is on the stack (usually via the
  `gamification` package). Providers = explicit config, else the block's
  declared defaults, plus whatever interpretation blocks contribute
  (`contributes.missions_providers`). The world's weather/condition strip is
  gated the same way — the world only asks for attention when a template asks
  it to.
- **Destinations.** The command-bar docks exist per surface: `approve` and
  `gates` arrive with the root (law-tier), `intake` only with intake forms,
  `create` only with `ui_create` on the stack, `source` only when source pages
  exist (or an intake form is `source_sync`), `blocks` whenever there is a
  root anchor.
- **Identity.** `resolve_identity()` merges the type's `identity:` with a
  page-level frontmatter `identity:` override — one `root_entity` type can show
  as an observatory while a team holon shows as a plaza, without a new page
  type per flavor.

## 8. The creatable honesty rule

`creatable: false` on a type means: **a human can never seed this type from a
create surface.** It marks generated/system types (`ingestion_event`,
`ontology_index`, `source_registry`, `source_catalog`, `input_stage`,
`system_log`, `relationship_map`, `source_config`, `template_block`), types
without a `wiki.page-types.yaml` contract yet (`initiative`, `insight` —
`wiki_new` would refuse them), and the rite-owned root (`root_entity`). Offering the uncreatable is lying to the user;
`isCreatable()` in `creation.ts` enforces it on every create surface, and a
`?src=` URL naming a forbidden type falls back to the picker instead of
short-circuiting.

## 9. Authoring checklist

1. Compose the block in YAML (`wiki.templates.local.yaml` `blocks:`, or a
   `template_block` page) using only the fixed vocabulary.
2. Attach it: `types.<t>.blocks` for every instance of a type, or frontmatter
   `blocks:`/`packages:` on one anchor page.
3. Validate: `python3 scripts/wiki_audit.py` (the `templates_registry` check
   runs `validate_blocks`).
4. Inspect: open the anchor in the cockpit and press the **Blocks** dock — the
   resolved stack with each block's origin, the composed interface and the
   derived outputs.

For the exact file lists when a block needs new code, see
[extending-the-kit.md](extending-the-kit.md).
