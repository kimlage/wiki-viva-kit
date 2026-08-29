# Wiki Viva Kit

A Markdown/Git-first living operational wiki with a deterministic core,
privacy-aware honesty gates, a dense visual cockpit and deep reading delegated
to the AI agent operating the repository. No LLM client is embedded.

The wiki is one navigable world rather than a set of dashboard islands. Pages
remain canonical Markdown; registered views project the same world as spatial
quadrants, timelines, graph relations, source provenance and operational work.

Current public baseline: [Wiki Viva v8.2.0](docs/references/releases/wiki-viva-v8.2.0.md).

```mermaid
flowchart LR
    Sources["Sources + Markdown"] --> Snapshot["Atomic snapshot"]
    Packs["Experience packs"] --> Snapshot
    Events["Typed multi-clock events"] --> Snapshot
    Snapshot --> World["Spatial world"]
    Snapshot --> Timeline["Chronoscope + timelines"]
    Snapshot --> Reader["Reader + operations"]
```

## Try the public synthetic demo

```sh
npm --prefix apps/wiki-cockpit ci
npm --prefix apps/wiki-cockpit run dev
```

Open `http://localhost:5173/demo`. The demo contains synthetic Study/Research
and Personal Finance scenarios and requires no account, token or private data.

## What the kit provides

- deterministic source manifests, extraction, chunking and local search;
- secret detection everywhere and PII checks at public boundaries;
- delegated LLM context packages with auditable consolidation;
- a self-contained source operations workspace for grouping, authorizing,
  inventorying, refreshing and monitoring real sources;
- typed relations, temporal events and multiple timeline projections;
- a responsive React/Three.js cockpit with equivalent information surfaces;
- declarative experience packs with synthetic conformance fixtures;
- per-PR gates, operational compilation and Git-native review history.

## Quickstart

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 scripts/wiki_audit.py --check
python3 scripts/wiki_web_snapshot.py --check-contract
```

Edit `wiki.config.yaml` to define the repository id, owner label, root entity,
memory root, contexts and privacy boundary. See [docs/README.md](docs/README.md)
and the [Wiki Viva skill](.skills/wiki-viva/SKILL.md).

Code, comments and official documentation stay in English. Generated pages,
experience-pack presentation and the cockpit are selectable with
`language: en`, `language: es` or `language: pt`, so downstream projects can
localize output without forking the core.

## Operating data sources

Open `/w?view=sources&dock=source` in an operator-backed consumer wiki, or
`/demo/w?view=sources&dock=source` in the public synthetic demo. Sources have a dedicated 2D
workspace; it is not a modal over the 3D world and does not mix source work with
the wiki's other perspectives.

The workspace provides:

- a collapsible, draggable-width registry with editable categories, source
  movement and representative platform or consumer-owned brand icons;
- an initial overview of every source pending attention and one governed
  **Update all pending** action;
- record selection for inspection while updates continue to inventory the
  entire declared folder, account, endpoint or repository;
- separate **Records**, **Update**, **Configure** and **History** surfaces;
- source and lifecycle configuration through content-bound previews, explicit
  confirmation and immutable operation receipts;
- authorization diagnostics, deterministic scripts and inventories, plus
  monitored Codex and Claude delegation when the required connector is usable.

Every source declares both its update scope (`item`, `collection`, `account`,
`endpoint` or `repository`) and lifecycle (`one_shot`, `on_demand`,
`event_driven` or `recurring`). Only recurring sources can become overdue merely
because time passed. Updating a collection means checking its complete declared
scope for new, changed, enriched, removed or inaccessible records; selecting a
record never silently narrows that scope to one file.

The operator never stores credentials in Git. It accepts only reviewed source
fields, checks local authorization and connector capabilities, previews the
exact deterministic change, and fails closed if the recipe changed before
confirmation. Registration, deterministic collection, ingestion evidence and
sync receipts remain distinct, so an existing ingested source is not falsely
shown as “never synchronized”.

Detailed operating and configuration contract:
[source refresh and source workspace guide](docs/references/guides/source-refresh-cadence.md).

## Downstream upgrading

The previous subject/lane/capsule/attestation machine is retired. Its final
`upgrade-package.yaml` is frozen as historical documentation; it is not a
current gate.

The supported flow is a single consumer PR:

```sh
# B0: readable and mutation-free
python3 /path/to/wiki-viva-kit/scripts/wiki_sync_from_kit.py \
  --kit /path/to/wiki-viva-kit --consumer /path/to/consumer --dry-run

# C1 + C2; add one or more explicit consumer-owned C3 commands when required
python3 /path/to/wiki-viva-kit/scripts/wiki_sync_from_kit.py \
  --kit /path/to/wiki-viva-kit --consumer /path/to/consumer \
  --c3-command "python3 scripts/consumer_migration.py"
```

The command is idempotent, copies only Git-tracked kit-owned paths, regenerates
declared derived artifacts and writes `kit.lock`. It never copies consumer
memory or configuration and never invents C3 domain changes. The PR itself is
the reversible boundary. Run the kit's normal CI, the consumer's own gates and
obtain human approval before promotion.

Full instructions: [downstream upgrade runbook](docs/references/guides/wiki-viva-v8-downstream-upgrade.md).

## Release policy

A kit release consists of:

1. a Git tag;
2. release notes describing product and contract changes;
3. an **Upgrading** section with required consumer migrations;
4. green normal CI: audit, pytest, Vitest, TypeScript and production build;
5. a human-reviewed PR.

No capsule, receipt or exact-matrix rite is required.

## Privacy

Personal data belongs in private consumer wikis and needs no warning there.
Public pages/exports must remain public-safe. Access secrets—tokens, passwords,
private keys, cookies and equivalent credentials—are blocked everywhere.

## Repository layout

| Path | Purpose |
| --- | --- |
| `wiki_core/` | Deterministic core and contracts |
| `scripts/` | `wiki_*` command-line operations |
| `apps/wiki-cockpit/` | Visual cockpit and local operator |
| `memories/` | Public synthetic canonical wiki |
| `docs/` | Guides, templates and references |
| `packs/` | Declarative experience packs |
| `.skills/` | Portable agent playbooks |

## Normal gates

```sh
python3 scripts/wiki_audit.py --check
python3 scripts/wiki_audit.py --public-export --check
python3 -m pytest tests/
npm --prefix apps/wiki-cockpit test
npm --prefix apps/wiki-cockpit exec -- tsc -p apps/wiki-cockpit/tsconfig.json --noEmit
npm --prefix apps/wiki-cockpit run build
```

Core changes should use public synthetic fixtures first. Private repositories
are downstream QA, never the source of public examples.

## License

See [LICENSE](LICENSE) and [CONTRIBUTING.md](CONTRIBUTING.md).
