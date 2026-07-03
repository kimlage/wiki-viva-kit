# Authoring page templates (and source recipes)

The **page type** is the unit of customization in Wiki Viva. A type decides
three things at once:

1. **Schema** — which frontmatter fields are pinned (required to be filled),
   validated by `wiki.page-types.yaml`.
2. **Body skeleton** — the Markdown template a new page starts from.
3. **View + interaction** — how the cockpit renders the page and what controls
   it offers, declared in `wiki.templates.yaml`.

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
| `facets` keys | `intencao` · `percepcao` · `pratica` · `relacoes` |

`scene.emphasis` is a free label the scene reads as a hint (e.g. `intention`,
`none`); unknown emphasis degrades to `none`.

---

## 2. Anatomy of a type

```yaml
# wiki.templates.local.yaml — merged on top of the kit's wiki.templates.yaml
schema_version: wiki_templates.v1

types:
  deal:                                   # the page_type (also add it to
    extends: relation_base                # wiki.page-types.yaml for validation)
    body_template: docs/references/templates/deal.md
    pinned_fields: [updated_at, stage, amount, owner]
    facets:
      intencao: [decisions]               # why the deal exists
      pratica:  [actions, evidence_refs]  # what is being done
      relacoes: [people, roles]           # who is involved
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
**Focus** (key `F`), its neighbors are bucketed into these four lenses:

- **intencao** — why it exists: decisions, priorities, responsibilities.
- **percepcao** — how it is lived/perceived: insights, journals, claims.
- **pratica** — what is done and with what: actions, processes, artifacts,
  evidence, sources.
- **relacoes** — who and how together: people, roles, meetings.

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

Everything lands **kit-first**, through the PR gate, then cascades (code only) to
a private wiki for its owner's approval.
