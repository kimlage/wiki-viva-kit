# Wiki Viva documentation

The documentation is organized around the current operating contract, not the
retired release-certification machinery.

## Start here

- [Wiki Viva v8 downstream upgrade](references/guides/wiki-viva-v8-downstream-upgrade.md):
  B0 dry-run, C1 sync, C2 regeneration, explicit C3 and `kit.lock`.
- [Wiki templates](references/templates/wiki/README.md): canonical page types.
- [Experience packs](../packs/README.md): complete visual and operational
  packages for use cases such as study, finance and team work.
- [Command reference](../memories/system/wiki/command-reference.md): deterministic
  CLI catalog.

## Upgrade artifacts

`references/upgrades/sync-manifest.yaml` is the canonical active portable sync
contract. The nested `wiki-viva-v8/sync-manifest.yaml` remains a compatibility
copy for explicit older commands; the CLI default always selects the canonical
contract. `upgrade-package.yaml` is frozen historical evidence from the
retired subject/lane/capsule design and must not be edited or used as a gate.

Downstream repositories keep their own `kit.lock`; private migration output,
screenshots, routes and data stay in the private consumer or ignored local
storage.

## Release documentation

- [Wiki Viva v8.1.4](references/releases/wiki-viva-v8.1.4.md): portable downstream sync and registry-authority corrections
- [Wiki Viva v8.1.3](references/releases/wiki-viva-v8.1.3.md): downstream-safe source-workspace documentation gate
- [Wiki Viva v8.1.2](references/releases/wiki-viva-v8.1.2.md): canonical standalone source-workspace routes and regression coverage
- [Wiki Viva v8.1.1](references/releases/wiki-viva-v8.1.1.md): source operations documentation and additive source-config migration fix
- [Wiki Viva v8.1.0](references/releases/wiki-viva-v8.1.md): consolidated v8
  runtime with the self-contained source operations workspace and portable
  downstream migration.
- [Wiki Viva v8 history](references/releases/wiki-viva-v8.md): historical v8
  release investigation and retired certification evidence.
- [Wiki Viva v6.10.1](references/releases/wiki-viva-v6.10.1.md),
  [v6.10.0](references/releases/wiki-viva-v6.10.0.md) and
  [v6.9.3](references/releases/wiki-viva-v6.9.3.md): preserved release notes
  from the source-operations work that preceded the consolidated v8.1 line.

Every release should have a tag, release notes and an **Upgrading** section that
states:

- the source tag/SHA;
- portable contract changes;
- required C2 generators;
- explicit consumer-owned C3 migrations;
- normal kit and consumer gates;
- compatibility or rollback notes.

The consumer PR is the reversible promotion boundary.

## Reading rule

Canonical knowledge lives in Markdown pages under the configured memory root.
Generated snapshots and indexes are read models, not replacement truth. All
public examples must be synthetic; access secrets are blocked everywhere.

## Per-PR gate

Run the commands in [AGENTS.md](../AGENTS.md), inspect the conceptual diff and
use a human-reviewed PR. Shared-core defects are reproduced here with synthetic
fixtures before downstream adoption.
