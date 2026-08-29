# Wiki Viva v8.1.5

Released on 2026-08-28.

This source-migration patch resolves the two strict downstream failures reported
against v8.1.4:

- generated input-stage warnings preserve their stable JSON strings while the
  Markdown projection links each leading repository-local page path, satisfying
  `audit.require_markdown_links: true` without hand-editing generated output;
- `wiki_migrate_templates.py --operational-recipes` can promote an exact,
  untouched TODO recipe scaffold created by an earlier framework migration;
- the promotion is fail-closed: removing the scaffold marker or changing any
  recipe field protects the block as owner-authored content;
- the source migration remains idempotent after promotion and reports the
  replacement explicitly in dry-run and apply output.

## Upgrading

Use the v8.1.5 tag or commit from this release as the kit source. Run B0 first:

```sh
python3 /path/to/wiki-viva-kit/scripts/wiki_sync_from_kit.py \
  --kit /path/to/wiki-viva-kit \
  --consumer /path/to/consumer \
  --dry-run
```

After reviewing B0 on a focused consumer branch, apply C1/C2 and run the source
migration plus generated read models as explicit C3 commands:

```sh
python3 /path/to/wiki-viva-kit/scripts/wiki_sync_from_kit.py \
  --kit /path/to/wiki-viva-kit \
  --consumer /path/to/consumer \
  --c3-command "python3 scripts/wiki_migrate_templates.py --apply --operational-recipes" \
  --c3-command "python3 scripts/wiki_source_registry.py --write" \
  --c3-command "python3 scripts/wiki_input_stage.py --write" \
  --c3-command "python3 scripts/wiki_operation_compile.py --write"
```

Review every promoted recipe in the consumer PR. Recipes that differ from the
original framework scaffold are deliberately preserved and must be updated by
the owner. Run a second B0 and the consumer's own audit, Python, frontend and
visual gates before merge.
