# Authoring page templates (and source recipes)

The **page type** is the unit of customization in Wiki Viva. A type decides
three things at once (four since v2 — see [§5](#5-the-v2-layer-the-type-as-a-complete-module)):

1. **Schema** — which frontmatter fields are pinned (required to be filled),
   validated by `wiki.page-types.yaml`.
2. **Body skeleton** — the Markdown template a new page starts from.
3. **View + interaction** — how the cockpit renders the page and what controls
   it offers, declared in `wiki.templates.yaml`.
4. **Module contract** (v2) — which blocks, identity, subpages and creation
   rules the type carries. See [modular-blocks.md](modular-blocks.md).

You add a new type by **composing a fixed vocabulary in YAML** — no code. The
kit ships ~29 types; a wiki adds its own in `wiki.templates.local.yaml`, which is
merged on top of the kit registry (same override philosophy as the presentation
config). New *primitives* (a panel kind that does not exist yet) need code; new
*types* do not.

This is the power of the system: a wiki models its own world — `deal`,
`patient`, `sprint`, `recipe`, `song` — and the 3D cockpit renders and navigates
it without a rebuild.

---

## 1. The fixed vocabulary

Everything you compose comes from these sets. The registry validator
(`wiki_audit.py`, WARN gate) flags anything outside them, so a typo fails loudly
instead of rendering nothing.

| Block | Allowed values |
| --- | --- |
| `view.center` | `document` · `timeline` · `dashboard` · `entity` |
| `view.panels[].kind` | `list` · `table` · `timeline` · `badges` · `text` · `diff` |
| `view.badges[]` | `freshness` · `evidence` · `approval` · `privacy` · `sync` |
| `controls[].kind` | `brief` · `nav` · `filter` · `run` · `focus` |
| `scene.shape` | `sphere` · `crystal` · `hub` · `slab` · `spark` · `comet` · `diamond` |
| `facets` keys | `intencao` · `pratica` · `relacoes` · `sistemas` |

`scene.emphasis` is a free label the scene reads as a hint (e.g. `intention`,
`none`); unknown emphasis degrades to `none`.

> These are the **v1 per-page primitives** (how one page renders). The v2
> layer adds a second vocabulary — block kinds, scope modes, surfaces, scene
> layouts, identity landmarks — fixed in `wiki_core/template_blocks.py` and
> documented in [modular-blocks.md](modular-blocks.md).

---

## 2. Anatomy of a type

```yaml
# wiki.templates.local.yaml — merged on top of the kit's wiki.templates.yaml
# (the kit registry itself is schema_version: wiki_templates.v2; a local file
# that composes only the v1 keys below still works — v2 keys are additive)
schema_version: wiki_templates.v2

types:
  deal:                                   # the page_type (also add it to
    extends: relation_base                # wiki.page-types.yaml for validation)
    body_template: docs/references/templates/deal.md
    pinned_fields: [updated_at, stage, amount, owner]
    facets:
      intencao: [decisions]               # why the deal exists (q1)
      pratica:  [actions, evidence_refs]  # what is being done (q2)
      relacoes: [people, roles]           # who is involved (q3)
      sistemas: [source_refs]             # the systems behind it (q4)
    view:
      center: dashboard
      badges: [freshness, approval]
      panels:
        - { kind: table, from: actions, label: reader.actions }
        - { kind: list,  from: people,  label: reader.people }
    controls:
      - { kind: focus }                   # the four-lens view
      - { kind: nav, rel: moc_parent }
    scene: { shape: crystal, emphasis: intention }
```

### `extends`

Types inherit from a **base** (defined under `bases:`). The kit's
`relation_base` gives every content page a sane facet mapping, a freshness/
evidence badge row, and the Focus + nav controls. Your type overrides only what
it emphasizes; the rest is inherited. The resolution order is
`default → base chain → your keys` (your keys win).

### `pinned_fields`

The frontmatter fields a well-formed page of this type should carry. The cockpit
template inspector shows conformity ("in mold" / "out of mold") and can compose a
brief to fill the gaps. `wiki_migrate_templates.py --pinned` reports every page
missing them. Pinning does not *invent* values — it marks what a human (or agent)
still needs to fill.

### `facets` — the Focus view

Each lens maps to the frontmatter fields that fill it. When a page is centered in
**Focus** (key `F`), its neighbors are bucketed into these four lenses — one
per AQAL quadrant (q1..q4), so all four quadrants are honestly present:

- **intencao** (q1, interior-individual) — identity and intent: why it exists,
  what it means, what it prioritizes and how it is perceived.
- **pratica** (q2, exterior-individual) — outputs and evidence: observable
  behavior, actions, artifacts, direct outputs and metrics.
- **relacoes** (q3, interior-collective) — culture and relations: shared
  meaning, lived roles, rituals, norms and relationship context.
- **sistemas** (q4, exterior-collective) — systems and governance: channels,
  tools, pipelines, workflows, rules and process infrastructure.

A lens with no neighbor renders as an **honest empty wedge** ("no *X* lens
registered") with an offer to fill it — never a fabricated link. The bucketing of
a *neighbor* also has a deterministic default keyed by the neighbor's own
`page_type` (see `wiki_core/facets.py`); the `facets:` block is the per-type
override of which *fields* count as which lens.

---

## 3. Source types carry a recipe

A `source_config` page adds one more thing: a **recipe** — the executable
ingestion manual, as data (schema `wiki_source_recipe.v1`), in a fenced
` ```yaml ` block. It tells an agent how to ingest the source on demand, with
**no credentials ever** (structural metadata only — the validator rejects any
`token`/`secret`/`key` field).

```yaml
recipe:
  schema_version: wiki_source_recipe.v1
  platform: slack                         # slack|gchat|whatsapp|gmail|drive|web|repo|file|calendar|manual
  locator: T0123ABCD                      # the platform-native workspace/id
  pipelines:                              # typed, independently cadenced
    - { kind: content, cadence_days: 7 }
    - { kind: metadata, cadence_days: 30 }
  streams:                                # channels/folders as first-class rows
    - id: eng-releases
      label: "#eng-releases"
      selected: true
      privacy: team_shared                # private_self|private_sensitive_allowed|team_shared|public_ok
      filters: { since: "2026-01-01" }
      target_pages: [memories/system/releases.md]
    - id: random
      label: "#random"
      selected: false
      skip_reason: "off-topic — no wiki value"
  how_to_export: "Slack → export the channel history as JSON, drop it in data/raw/."
  ingest:
    argv: [python3, scripts/wiki_ingest.py, --source, "<export>", --stream, eng-releases]
```

The cockpit's **source dock** (`?dock=source&src=<id>`) reads this to show sync
health, per-stream freshness vs cadence, and an "ingest N channels" brief.

---

## 4. Validate, migrate, verify

- **Validate** the registry: `python3 scripts/wiki_audit.py` runs the
  `templates_registry` and `source_recipes` checks (WARN-first) — unknown
  primitives, bad facet keys, or credential-smell recipe keys are reported.
- **Migrate** legacy sources into the contract:
  `python3 scripts/wiki_migrate_templates.py` (dry-run) →  `--apply`. It is
  additive-only and never invents data; unknown values become `TODO`
  placeholders you complete before merge. See the
  [command reference](../../../memories/system/wiki/command-reference.md).
- **Verify** in the cockpit: open a page of the new type, click the type chip to
  see the template inspector (mold + facet field-map), and press `F` to center it
  through the four lenses.

---

## 5. The v2 layer: the type as a complete module

Since `wiki_templates.v2`, a type is not just a view spec — it is the complete
contract of an information module. All v2 keys are **additive and optional**
(a v1 registry resolves them to safe defaults); they are read by the compiler
in `wiki_core/template_blocks.py` and resolved into `TemplateSpec`
(`wiki_core/templates_registry.py`):

| Key | Meaning |
| --- | --- |
| `blocks:` | the blocks every instance of the type applies (interpretation lenses, interface surfaces, gates) — e.g. `source` brings its recipe gate, privacy boundary, intake and sync missions |
| `packages:` | *(frontmatter only, on anchor pages)* named groups of blocks — `gamification`, `quadrant_lenses` |
| `can_anchor_blocks:` | whether pages of this type may attach `blocks:`/`packages:` in frontmatter (kit: `root_entity`, `context_hub`, `holon`, `project`, `source`, `template_block`) |
| `creatable:` | whether a human can seed this type from a create surface; `false` marks generated/system/rite-owned types — the palette never offers what cannot be born |
| `home_quadrant:` | the local AQAL quadrant pages of this type use when read inside their active center (facet name or `q1..q4`); use the Wilber/AQAL placement Q1 upper-left, Q2 upper-right, Q3 lower-left, Q4 lower-right; page frontmatter `subject_role`, `home_quadrant` and `observed_quadrants` still win |
| `parent_projection:` | *(frontmatter only, on nested anchor pages)* how the parent center should see this whole sub-world, e.g. a company root projects to `q4/sistemas` under a person root |
| `projection_overrides:` | *(frontmatter only)* exceptional per-center projection overrides when the normal nested-center rule is not precise enough |
| `identity:` | the anchor's look in the scene — `landmark`/`motif`/`ambient`/`horizon_label`; a page-level `identity:` overrides the type's |
| `subpages:` | structure born with the page — `{rel, page_type, slug?, required\|generated}`; missing required subpages become conformity missions and create-surface obligations |
| `skills:` | `{human: […], agent: […]}` capability references |

How the stack of blocks resolves per page, how the interface materializes from
it, and the honesty rules around creation are covered in
[modular-blocks.md](modular-blocks.md); the exact file checklists for
extensions that DO need code are in [extending-the-kit.md](extending-the-kit.md).

Everything lands **kit-first**, through the PR gate, then cascades (code only) to
a private wiki for its owner's approval.
