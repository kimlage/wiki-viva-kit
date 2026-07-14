# Setup — adopt and configure the wiki in a repo

Goal: take a repo from nothing to a working living wiki whose gates are green.
The kit is self-contained; "setup" is mostly **configuration + scaffolding**, not
code. Names below are the English defaults; if you pin a localized layout
(step 4) substitute your own.

## 1. Bring the kit in

Copy the kit into the repo (or start the repo from it) — the deterministic core,
the CLIs, the tests, the templates, the method pages, the skills and the profile:

```text
wiki_core/                         # deterministic core
scripts/                           # wiki_* CLIs
tests/                             # the core's test suite
docs/references/templates/wiki/    # page contracts and templates
memories/system/                   # method pages (process, contract, coverage, log)
.skills/                           # portable agent skills (this one included)
.github/workflows/wiki.yml         # the gates in CI
wiki.config.yaml  wiki.targets.yaml  requirements.txt  pytest.ini  .gitignore  AGENTS.md  README.md
```

```sh
pip install -r requirements.txt   # PyYAML is the only runtime dependency
python3 -m pytest tests/ -q       # sanity: the kit's own suite must pass
```

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

For a v3 downstream upgrade, localization does not authorize an arbitrary
localized memory or references-tree C3 delta. The runner reads the immutable
Git blob at `consumer_B0:wiki.config.yaml` and derives exactly three
config-bound roles: the exact `command_reference_page`, the exact
`operational_pass_page`, and `release_records` below the configured
`references_root/releases/**` subtree. The live worktree and the later C1/C2/C3
subjects cannot redefine or widen those paths. All three surfaces are C3-only:
each changed artifact must be inert UTF-8 Markdown in a regular `100644` Git
blob, with release records restricted to `.md` descendants. Never place them in
C1 or C2. A different B0 config blob or derived-authority digest requires a new
plan and invalidates all C3-bound state, receipts and reports.

This prospective rule does not rewrite an in-flight v2 migration. Keep its
sealed C3 and receipts byte-for-byte historical, complete its original gate
matrix, and introduce routing/localization changes only in a fresh v3 plan.

## 6. Verify the gates are green

```sh
python3 scripts/wiki_audit.py --check
python3 scripts/wiki_check_methodology_coverage.py --check
python3 scripts/wiki_operation_compile.py --check
python3 scripts/wiki_input_stage.py --check
python3 -m pytest tests/ -q
```

If `wiki_audit` complains about a missing core page, you renamed/omitted one of
`audit.core_pages` — create it or update the config. If methodology coverage
fails, a required page/template is missing or empty. Green here means the repo is
ready to operate — go to [operating.md](operating.md).
