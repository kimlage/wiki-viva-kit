# Wiki Viva v8.1.4

Released on 2026-08-28.

This downstream-portability patch corrects the three contracts reported after
applying v8.1.3 to a separate consumer:

- the sync CLI now defaults to the canonical
  `docs/references/upgrades/sync-manifest.yaml`;
- root-only block patterns no longer remove the demo fixture's own registries,
  and the portable set includes the two authored tests referenced by scenario
  proof IDs;
- the deterministic C2 demo validates experience packs against the fixture's
  synthetic contracts instead of a consumer-owned root registry;
- when `wiki.page-types.yaml` exists, its `allowed_dirs` contract is
  authoritative over the legacy English/Portuguese ontology fallback.

## Upgrading

Use the v8.1.4 tag or commit from this release as the kit source. Run B0 first:

```sh
python3 /path/to/wiki-viva-kit/scripts/wiki_sync_from_kit.py \
  --kit /path/to/wiki-viva-kit \
  --consumer /path/to/consumer \
  --dry-run
```

After review, run the same command without `--dry-run` on a focused consumer
branch. C1 must preserve consumer-owned root configuration, C2 must complete,
and a second B0 must report no add/change/remove operations.
