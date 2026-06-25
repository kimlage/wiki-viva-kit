---
name: wiki-source-auditor
description: Audit source traceability, manifests, extracted text, chunks, indexes, LLM cache metadata, Markdown links and access-secret exclusions in a portable wiki repo.
---

# Wiki Source Auditor

## Checks

- Original source exists or has a live-source policy.
- Local source has hash, size and source ID.
- Derived manifest, text, chunks and LLM plan exist or have explicit skip reason.
- Canonical source/config pages declare their hierarchy parent (`moc_parent`);
  provenance fields such as `source_refs` do not replace navigation.
- Input-stage routing is current: root entity, input channels, source configs,
  inherited perspectives and target pages compile with
  [scripts/wiki_input_stage.py](../../scripts/wiki_input_stage.py) `--check`.
- Markdown links point to real local targets when local.
- No token, cookie, password, access code, credential or individualized secure link is persisted.
- Public candidates have a redaction checklist.
