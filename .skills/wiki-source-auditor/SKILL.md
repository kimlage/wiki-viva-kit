---
name: wiki-source-auditor
description: Audit source traceability, manifests, extracted text, chunks, indexes, LLM cache metadata, Markdown links and access-secret exclusions in a portable wiki repo.
---

# Wiki Source Auditor

## Checks

- Source original exists or has live-source policy.
- Local source has hash, size and source ID.
- Derived manifest, text, chunks and LLM plan exist or have explicit skip reason.
- Markdown links point to real local targets when local.
- No token, cookie, password, access code, credential or individualized secure link is persisted.
- Public candidates have a redaction checklist.
