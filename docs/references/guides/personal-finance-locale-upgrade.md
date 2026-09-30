---
page_id: guide-personal-finance-locale-upgrade
page_type: reference_guide
title: Personal Finance 0.1.1 locale compatibility upgrade
context: system
visibility: public_candidate
updated_at: 2026-09-30
stale_after_days: 90
sources_policy: published_contract_and_synthetic_lifecycle_tests
gate: github_pr
sensitive_data_policy: no_personal_data
---

# Personal Finance 0.1.1 — Upgrading

The current [pack validator](../../../wiki_core/_experience_pack_validation.py)
and presentation contract require EN, ES and PT-BR. Earlier installed 0.1.0
bundles may contain only EN/PT-BR. An upgrade must select a strictly newer
version, so replacing 0.1.0 metadata in place is insufficient.

[Version 0.1.1](../../../packs/personal-finance-0.1.1/README.md) supplies a
coherent install declaration and explicit `0.1.0-to-0.1.1` migration with
`data_policy: preserve_user_content`. Its capabilities, privacy constants,
templates and temporal adapters preserve the current public contract. The
0.1.0 source and registry default remain unchanged; adoption is explicit.

## Adopt after the kit pin

Consume the approved kit through the [B0/C1/C2/C3 process](wiki-viva-v8-downstream-upgrade.md).
On the consumer's reviewed `wiki/*` branch, inspect the zero-write plan:

```sh
python3 scripts/wiki_pack_adopt.py personal-finance --version 0.1.1 --dry-run
```

Review the existing immutable bundle and the conceptual diff, then run the
same command without `--dry-run` as an explicit C3 step. The helper delegates
to the existing bounded pack upgrade: it does not execute user-content
transformations. Mutation remains limited to `.wiki-viva/packs`,
`.wiki-viva/pack-receipts` and `wiki.packs.lock.yaml`. Source pins, migration,
version ordering, reviewed branch, prior bundle hashes and bound receipts
remain checked. An edited installed bundle fails instead of being overwritten.
Move intentional customizations through a separate reviewed proposal; this
upgrade does not guess their destination.

Replaying adoption at 0.1.1 validates source/installed pins, bundle bytes and
receipts and reports `unchanged` with an empty diff. It never silently reinstalls,
enables a disabled pack or installs a missing pack. The underlying `upgrade`
command retains its strict version rule.

Run `wiki_pack.py validate --all`, the consumer's gates and real snapshot
readback before promotion. The [synthetic tests](../../../tests/test_personal_finance_upgrade.py)
prove the legacy failure, repeatable dry-run, preserved authored pages,
custom templates and config, receipt closure, replay with no writes, and
refusal of drift both before and after upgrade. No private consumer content
is included in this release.
