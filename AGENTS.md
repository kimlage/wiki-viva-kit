# Wiki Viva Kit

Reusable Markdown/Git kit for a living operational wiki. Deterministic work
lives in Python and TypeScript; contextual LLM reading is delegated to the
agent operating the repository.

## Working contract

- `main` is approved truth. Work in `wiki/<theme>` (or another focused branch),
  run the project gates, review the conceptual diff and use a human-reviewed PR.
- Public-kit corrections are proved here with public synthetic fixtures before
  downstream use. Never copy private personal, financial or client data into
  this repository.
- Canonical memory lives in [memories/](memories/index.md). References and
  templates live in [docs/](docs/README.md); [data/raw and data/derived](data/README.md)
  are ignored cache.
- Source ingestion enters through [scripts/wiki_ingest.py](scripts/wiki_ingest.py).
  The agent writes the delegated LLM result through
  [.skills/wiki-llm-context-agent](.skills/wiki-llm-context-agent/SKILL.md).

## Upgrades and releases

The certification state machine is retired. Rc41, subjects, lanes, capsules,
attestations, exact release matrices and receipts are historical records, not
release gates. [upgrade-package.yaml](docs/references/upgrades/wiki-viva-v8/upgrade-package.yaml)
is frozen history and must not be edited to satisfy retired tests.

Current downstream adoption is one reviewable PR:

```sh
python3 /path/to/wiki-viva-kit/scripts/wiki_sync_from_kit.py \
  --kit /path/to/wiki-viva-kit --consumer . --dry-run
python3 /path/to/wiki-viva-kit/scripts/wiki_sync_from_kit.py \
  --kit /path/to/wiki-viva-kit --consumer . \
  --c3-command "python3 scripts/consumer_migration.py"
```

- B0 is the read-only plan.
- C1 copies Git-tracked kit-owned files byte-for-byte and preserves executable
  mode. Only paths previously owned in `kit.lock` may be pruned.
- C2 runs deterministic generators declared in the sync manifest.
- C3 is explicit consumer-owned migration; the kit never guesses domain edits.
- `kit.lock` records source SHA, manifest/tree digests and managed files without
  host paths or private evidence.
- Reversibility is the PR. Promotion requires the kit's normal CI, the
  consumer's own gates and the human PR gate.

A kit release is a tag, release notes and an **Upgrading** section describing
consumer migrations. No capsule or certification ceremony is required.

## Privacy

- Personal data is valid in private consumer pages. It is blocked only at a
  public/public-export boundary.
- Access secrets (tokens, passwords, keys, cookies) are blocked everywhere.
- Privacy and secret failures are fail-closed and never waivable.

## Core structure

- [wiki_core/](wiki_core/README.md): deterministic contracts.
- [scripts/](scripts/README.md): `wiki_*` command-line tools.
- [apps/wiki-cockpit/](apps/wiki-cockpit/README.md): web cockpit.
- [packs/](packs/registry.yaml): versioned public synthetic experience packs.
- [.skills/](.skills/README.md): portable agent skills.
- [docs/references/templates/wiki/](docs/references/templates/wiki/README.md):
  page contracts and templates.

## Gates before a PR

```sh
python3 scripts/wiki_audit.py --check
python3 scripts/wiki_audit.py --public-export --check
python3 scripts/wiki_check_methodology_coverage.py --check
python3 scripts/wiki_operation_compile.py --check
python3 scripts/wiki_input_stage.py --check
python3 scripts/wiki_semantic_inventory.py --check
python3 scripts/wiki_web_snapshot.py --check-contract
python3 scripts/wiki_pack.py validate --all
python3 -m pytest tests/
npm --prefix apps/wiki-cockpit test
npm --prefix apps/wiki-cockpit exec -- tsc -p apps/wiki-cockpit/tsconfig.json --noEmit
npm --prefix apps/wiki-cockpit run build
```

Configure each consumer through `wiki.config.yaml`; no context, owner or memory
root may be hardcoded in shared core.
