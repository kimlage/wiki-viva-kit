---
name: wiki-ingestion-agent
description: Convert a new source into deterministic manifest, extracted text/chunks, normalized event, contextual LLM plan, and PR-ready ingestion proposal without writing canonical memory directly.
---

# Wiki Ingestion Agent

## Workflow

1. Create or refresh a manifest with [scripts/wiki_extract_source_manifest.py](../../scripts/wiki_extract_source_manifest.py).
2. Extract text and chunks with [scripts/wiki_extract_text.py](../../scripts/wiki_extract_text.py).
3. Build or check the index with [scripts/wiki_build_index.py](../../scripts/wiki_build_index.py).
4. Plan the contextual LLM pass with [scripts/wiki_llm_context_pass.py](../../scripts/wiki_llm_context_pass.py).
5. Create an event in [memories/system/ingestion/events/](../../memories/system/ingestion/events/) using [docs/references/templates/wiki/ingestion-event.md](../../docs/references/templates/wiki/ingestion-event.md).
6. Generate or update the ingestion proposal with [scripts/wiki_new_ingest.py](../../scripts/wiki_new_ingest.py).

## Output

- Manifest path.
- Text/chunk paths.
- LLM context status.
- Event path.
- Proposal path.
- Pages impacted.
- Privacy and gate risks.
