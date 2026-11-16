# Setup — adopt and configure the wiki in a repo

Goal: take a repo from nothing to a working living wiki whose gates are green.
The kit is self-contained; "setup" is mostly **configuration + scaffolding**, not
code. Names below are the English defaults; if you pin a localized layout
(step 4) substitute your own.

## 1. Bring the kit in

Adopt the kit with the sync, as one reviewable PR in the consumer repo:

```sh
python3 /path/to/wiki-viva-kit/scripts/wiki_sync_from_kit.py \
  --kit /path/to/wiki-viva-kit --consumer . --dry-run      # B0: read-only plan
python3 /path/to/wiki-viva-kit/scripts/wiki_sync_from_kit.py \
  --kit /path/to/wiki-viva-kit --consumer .                # C1 copy, C2 generators
```

The sync copies only the kit-owned paths listed in the
[sync manifest](https://github.com/kimlage/wiki-viva-kit/blob/main/docs/references/upgrades/sync-manifest.yaml)
(the deterministic core, the `wiki_*` CLIs, the cockpit runtime, the skills,
packs and shared guides, schemas and templates) and records them in `kit.lock`.
Those paths change only through a later sync; a defect in them is a kit issue.

The sync does **not** copy the kit's test suites, demo fixtures or CI workflow.
The generic Python and cockpit suites run once in the kit CI at the revision
recorded in `kit.lock`; a second copy in the consumer would drift from that pin.
Enabling CI in the consumer is the consumer's own decision.

The consumer creates and owns the rest, starting from the kit's examples where
they help: `wiki.config.yaml`, `wiki.targets.yaml`, its root
[AGENTS.md](../../../AGENTS.md) and `README.md`, a skills index, `requirements.txt`,
`pytest.ini`, `.gitignore`, its memory pages (the hubs and the method pages under `<memory_root>/system/`) and the
page templates it uses. Never copy a path that the B0 plan lists as kit-owned:
an unmanaged copy blocks the sync as a conflict.

```sh
pip install -r requirements.txt   # PyYAML is the only runtime dependency
```

### Minimum consumer-owned tests

A new consumer starts with its own `tests/`, never the kit's:

1. Copy the [kit-lock contract](../../../docs/references/templates/consumer/kit_lock_contract.py)
   once to `tests/test_kit_lock.py`. It fails when a kit-managed file differs
   from `kit.lock`, so core changes keep arriving only through the sync.
2. Add a synthetic test for every consumer-owned script, adapter and C3
   migration command, and for any domain invariant that the generic gates do
   not cover.
3. Keep the step 6 gates in the consumer's own validation (local checks, a
   pre-push hook or its own CI); they are not pytest tests.

## 2. Configure the repo profile — [wiki.config.yaml](../../../wiki.config.yaml)

Read [wiki_core/config.py](../../../wiki_core/config.py) for the authoritative key
list and defaults. The essentials:

| Key | Meaning |
| --- | --- |
| `repo_id`, `owner_label` | Identity used in generated pages/ids |
| `language` | `en` or `pt` — drives **generated output** (cockpit, proposals) via string tables; code stays English |
| `contexts` | Comma list; each needs a `<memory_root>/<ctx>/index.md` hub |
| `default_context` | Context used when a command omits `--context` |
| `root_entity` | Semantic top page, entity type, input-stage page and default perspective bundle |
| `default_visibility` | Usually `private_self` |
| `private_sensitive_allowed` | `true` = PII welcome on private pages; `false` = strict mode |
| `paths` | Repo layout (English defaults; pin to localize — step 4) |
| `coverage` | Methodology-coverage gate targets |
| `audit.core_pages` | Pages the audit requires to exist |
| `audit.legacy_docs_prefixes` | Retired docs-layout prefixes the audit rejects; absent keeps the kit default. Declare the list (or `[]`) when legitimate sources live under a default prefix |
| `llm` | Chunking, model profile, prompt versions, `required_context_pass` |
| `audit` | `freshness_budget`, link/secret/frontmatter switches |

## 3. Declare the root entity

Create one top page that says what this wiki is about. For a personal wiki it
is the person page; for a team it is the team page; for a company it is the
company page; for this kit it is the page declared by `root_entity.page`.
Configure it in
[wiki.config.yaml](../../../wiki.config.yaml):

```yaml
root_entity:
  page: memories/system/wiki-viva-kit.md
  entity_type: product
  input_stage_page: memories/system/input-stage.md
  perspective_bundle:
    required:
      - perspective-identity-intent
      - perspective-artifacts-evidence
      - perspective-roles-relationships
      - perspective-systems-processes
```

Then create input-channel pages for the systems or document streams that feed
the root entity, and run:

```sh
python3 scripts/wiki_input_stage.py --write
python3 scripts/wiki_input_stage.py --check
```

## 4. Declare contexts and their targets

A **context** is a top-level area of memory (e.g. `finance`, `system`). For each:

1. Create the hub `<memory_root>/<ctx>/index.md` (the audit requires it). Start
   from a copy of the example context hub.
2. Map it in [wiki.targets.yaml](../../../wiki.targets.yaml): which pages and
   entity ids a source in that context typically impacts. This keeps
   [wiki_new_ingest.py](../../../scripts/wiki_new_ingest.py) generic — names live
   only in the profile, never in code.

The kit ships an `example` context — replace or keep it as a living sample.

## 5. (Optional) Pin a localized layout

The defaults are English; [wiki_core/config.py](../../../wiki_core/config.py)
lists every layout key and its default. To run the tree in another language, pin
every name you rename under the `paths:` block in
[wiki.config.yaml](../../../wiki.config.yaml), plus `default_context`, the
`coverage` pages and `audit.core_pages`. Example (Portuguese):

```yaml
default_context: sistema
paths:
  memory_root: memorias
  references_root: docs/referencias
  system_dirname: sistema
  ingest_dirname: ingestao
  events_dirname: eventos
  archive_dirname: arquivo
  decisions_dirname: decisoes
  actions_dirname: acoes
  pending_actions_filename: pendentes.md
  sources_dirname: fontes
  operation_page: memorias/operacao.md
  command_reference_page: memorias/sistema/wiki/referencia-comandos.md
  operational_pass_page: memorias/sistema/passe-operacional.md
```

The code never hardcodes layout paths; it reads them from here via
[wiki_core/paths.py](../../../wiki_core/paths.py). The directory and file names
then follow your pins, while code, comments and CLIs stay English.

For a downstream update, localization remains consumer-owned C3. Review the B0
plan first, let C1 copy only kit-owned paths, regenerate configured read models
in C2, and apply localized routing/config changes through an explicit C3
command. The resulting `kit.lock` records only portable kit-owned inventory;
it must never contain local paths, routes, private evidence or consumer data.
The consumer PR is the reversible review and promotion boundary.

The consumer's effective [AGENTS.md](../../../AGENTS.md) and any applicable
scoped instructions remain consumer-owned: C1 does not select the root agent
instructions. Carry the coordinator and integrator opening, resumption and
closeout obligations into the effective instructions through the consumer's
authorized normative process, referencing the existing [continuity and closeout contract](../../../docs/references/guides/context-coordinators.md#thread-continuity-and-closeout).
Check the actual instruction chain, including applicable overrides, and verify
what the agent receives on opening and resumption. Updating the kit contract
alone does not establish consumer adoption or runtime delivery.

## 6. Verify the gates are green

```sh
python3 scripts/wiki_audit.py --check
python3 scripts/wiki_check_methodology_coverage.py --check
python3 scripts/wiki_operation_compile.py --check
python3 scripts/wiki_input_stage.py --check
python3 -m pytest tests/ -q      # the consumer's own suite (step 1)
```

If `wiki_audit` complains about a missing core page, you renamed/omitted one of
`audit.core_pages` — create it or update the config. If methodology coverage
fails, a required page/template is missing or empty. Green here means the repo is
ready to operate — go to [operating.md](operating.md).
