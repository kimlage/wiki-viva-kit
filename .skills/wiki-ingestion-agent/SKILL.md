---
name: wiki-ingestion-agent
description: Convert a new source into deterministic manifest, extracted text/chunks, normalized event, contextual LLM plan, and PR-ready ingestion proposal without writing canonical memory directly.
---

# Wiki Ingestion Agent

## Workflow

1. Create or refresh a manifest with [scripts/wiki_extract_source_manifest.py](../../scripts/wiki_extract_source_manifest.py).
2. Extract text and chunks with [scripts/wiki_extract_text.py](../../scripts/wiki_extract_text.py).
3. Build or check the index with [scripts/wiki_build_index.py](../../scripts/wiki_build_index.py).
4. Plan the contextual LLM pass with [scripts/wiki_llm_context_pass.py](../../scripts/wiki_llm_context_pass.py)
   (`--emit-request`, deep read by the agent, `--record-result`).
5. Consolidate with [scripts/wiki_consolidate.py](../../scripts/wiki_consolidate.py):
   `--source <source_id> --emit-event --packet` generates the normalized event
   in [memories/system/ingestion/events/](../../memories/system/ingestion/events/)
   from the recorded deep read (quadrants filled, claims/decisions/actions
   candidates, `consolidated_into: []` to close) plus the gitignored integration
   packet; [docs/references/templates/wiki/ingestion-event.md](../../docs/references/templates/wiki/ingestion-event.md)
   stays as the manual fallback.
6. INTEGRATE — ingesting = integrating, the work does not end at the recorded
   result: guided by the packet, update the target hubs/concepts incrementally;
   create/update load-bearing claim pages (conflict fields `supersedes`/
   `superseded_by`/`conflicts_with`/`conflict_resolution` when claims collide);
   resolve or record every conflict and ambiguity; fill the event's
   `consolidated_into` (each target page references the source in
   `source_refs`); keep [scripts/wiki_consolidate.py](../../scripts/wiki_consolidate.py)
   `--check` and [scripts/wiki_audit.py](../../scripts/wiki_audit.py) `--check` green.
7. Generate or update the ingestion proposal with [scripts/wiki_new_ingest.py](../../scripts/wiki_new_ingest.py).

## Output

- Manifest path.
- Text/chunk paths.
- LLM context status.
- Event path.
- Integration status: packet path, targets updated, `consolidated_into` closed.
- Proposal path.
- Pages impacted.
- Privacy and gate risks.
