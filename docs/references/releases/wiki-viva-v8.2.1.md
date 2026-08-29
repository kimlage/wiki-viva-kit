# Wiki Viva v8.2.1

Released on 2026-08-29.

This source-lifecycle patch resolves the two public issues reported against the
v8.1.5/v8.2.0 source workflow:

- `wiki_new.py --type source` now resolves the configured owner placeholder so
  both normal creation and `--dry-run` produce valid YAML with an honest initial
  `source_lifecycle` (`configured`, `never_synced`, `never`, `pending`), without
  implying that ingestion already happened;
- append-only occurrence records with an explicit `processing_state` no longer
  inherit the recurring provider/series cadence as record-level staleness;
- only `discovered`, `changed`, `pending` and `queued` occurrence records count
  as pending ingestion work, while an already `ingested` historical occurrence
  remains complete without a cursor;
- recurring mutable streams without `processing_state` keep their existing
  cursor-based cadence, preserving the folder/channel/repository behavior;
- the cockpit labels processed occurrence records as complete in English,
  Spanish and Portuguese instead of rendering a missing cursor as "not yet
  ingested";
- regression fixtures cover one historical ingested occurrence and one newly
  discovered occurrence under both on-demand and recurring schedules.

## Upgrading

Use the v8.2.1 tag or commit from this release as the kit source. Run B0 first:

```sh
python3 /path/to/wiki-viva-kit/scripts/wiki_sync_from_kit.py \
  --kit /path/to/wiki-viva-kit \
  --consumer /path/to/consumer \
  --dry-run
```

After reviewing B0 on a focused consumer branch, apply C1/C2:

```sh
python3 /path/to/wiki-viva-kit/scripts/wiki_sync_from_kit.py \
  --kit /path/to/wiki-viva-kit \
  --consumer /path/to/consumer
```

No consumer-owned C3 migration is required for this patch. Existing source
pages and recipes are not rewritten. Append-only source recipes should keep an
explicit `filters.processing_state` on occurrence streams; mutable streams that
must continue aging by cursor should leave that field unset. Run a second B0
and the consumer's audit, Python, frontend and visual gates before merging the
upgrade PR.

Rollback is the consumer PR: revert to its previous `kit.lock` and kit tag.
