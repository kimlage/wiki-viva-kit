# Wiki Viva v8.2.0

Released on 2026-08-29.

This multilingual-core release makes English, Spanish and Portuguese selectable
without forking the shared runtime:

- `wiki.config.yaml` accepts the explicit project languages `en`, `es` and `pt`
  and fails closed for unsupported values;
- generated input-stage, operation, audit, source-registry, score, quadrant,
  consolidation, insight and PR-summary output uses parity-checked language
  tables;
- the cockpit ships complete English, Spanish and Portuguese catalogs, accepts
  regional browser/runtime values such as `es-MX` and `pt-BR`, and preserves
  per-installation string overrides;
- the Spanish AQAL projection uses `Yo`, `Ello`, `Nosotros` and `Ellos`, while
  persisted quadrant identifiers and semantic contracts remain unchanged;
- the Study/Research and Personal Finance packs now require and ship `en`, `es`
  and `pt-BR` presentation catalogs with repinned immutable tree digests;
- the public composition schema, synthetic snapshot and downstream sync proof
  carry the three-locale contract end to end.

## Upgrading

Use the v8.2.0 tag or commit from this release as the kit source. Run B0 first:

```sh
python3 /path/to/wiki-viva-kit/scripts/wiki_sync_from_kit.py \
  --kit /path/to/wiki-viva-kit \
  --consumer /path/to/consumer \
  --dry-run
```

After reviewing B0 on a focused consumer branch, apply C1/C2. No consumer-owned
C3 migration is required solely to keep an existing `language: en` or
`language: pt` installation working:

```sh
python3 /path/to/wiki-viva-kit/scripts/wiki_sync_from_kit.py \
  --kit /path/to/wiki-viva-kit \
  --consumer /path/to/consumer
```

To select Spanish generated output, set `language: es` in the consumer's
`wiki.config.yaml`; this root configuration remains consumer-owned and is not
copied by C1. A cockpit-only regional value such as `es-MX` may be set in
`wiki-cockpit.config.json`, but the canonical wiki configuration accepts the
base values `en`, `es` and `pt` only.

Consumer-authored experience packs must add `es` to `i18n.locales`, provide a
complete `i18n/es.yaml` catalog with key and placeholder parity, and repin both
`manifest_sha256` and `tree_sha256` after the final pack-file change. Run
`python3 scripts/wiki_pack.py validate --all`, a second B0, and the consumer's
audit, Python, frontend and visual gates before merging its upgrade PR.

Rollback is the consumer PR: revert to its previous `kit.lock` and kit tag.
Persisted page IDs, quadrant IDs, source IDs and user-authored content are not
migrated or rewritten by this release.
