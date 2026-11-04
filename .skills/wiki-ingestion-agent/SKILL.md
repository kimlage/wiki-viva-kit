---
name: wiki-ingestion-agent
description: Convert a new source into deterministic manifest, extracted text/chunks, normalized event, contextual LLM plan, and PR-ready ingestion proposal without writing canonical memory directly.
---

# Wiki Ingestion Agent

## Workflow

1. Follow the [memory router](../wiki-memory-router/SKILL.md) for your role.
   An authorized coordinator selects applicable root, channel, source config,
   template and perspective inputs. A packet-bound executor uses those bodies
   and exact slices; it does not read the global index/input-stage catalog or
   other fronts automatically. Missing required context is a structured blocker.
2. Use the canonical [wiki_ingest.py](../../scripts/wiki_ingest.py) approved-context
   path and explicit byte limits described in [bounded ingestion](../../docs/references/guides/bounded-ingestion.md).
   The standalone manifest/text/index tools below remain compatibility entry
   points for an authorized coordinator; they do not replace approved source
   admission or extend the executor's scope.
3. Extract text and chunks with [scripts/wiki_extract_text.py](../../scripts/wiki_extract_text.py).
4. Build or check the index with [scripts/wiki_build_index.py](../../scripts/wiki_build_index.py).
5. Plan the contextual LLM pass with [scripts/wiki_llm_context_pass.py](../../scripts/wiki_llm_context_pass.py)
   (`--emit-request`, deep read by the agent, `--record-result`).
6. For folder mode, prepare the [folder consolidation proposal](../../docs/references/guides/folder-v2-experimental-usage.md), review it and run preflight before authorized integration. The proposal itself is not integration. For the historical v1 flow, [scripts/wiki_consolidate.py](../../scripts/wiki_consolidate.py)
   `--mode v1 --source <source_id> --emit-event --packet` generates the normalized event
   in the ingestion-events directory resolved from `wiki.config.yaml` by
   `WikiPaths.ingest_events_dir`
   from the recorded deep read (quadrants filled, claims/decisions/actions
   candidates, `consolidated_into: []` to close) plus the gitignored integration
   packet; the consumer's configured ingestion-event template stays as the
   manual fallback.
7. INTEGRATE — ingesting = integrating, the work does not end at the recorded
   result: guided by the packet, update the target hubs/concepts incrementally
   before creating parallel relation pages;
   create/update load-bearing claim pages (conflict fields `supersedes`/
   `superseded_by`/`conflicts_with`/`conflict_resolution` when claims collide);
   resolve or record every conflict and ambiguity; fill the event's
   `consolidated_into` (each non-source target page references the source in
   `source_refs`; source identity targets use the event/lifecycle closure and
   never self-reference); every new action/claim/decision/meeting/person/project/source
   page declares the hub it belongs under in `moc_parent`; keep its
   quadrant placement relative to the page's active center (`subject_ref`,
   `subject_role`, `parent_projection` for nested roots/templates, and
   `projection_overrides` for exceptions) instead of flattening everything
   against the wiki root; run
   [scripts/wiki_consolidate.py](../../scripts/wiki_consolidate.py) `--mode v1 --check` (v1 coverage only),
   [scripts/wiki_audit.py](../../scripts/wiki_audit.py) `--check` and
   [scripts/wiki_quality_report.py](../../scripts/wiki_quality_report.py)
   `--check` green.
8. Generate or update the ingestion proposal with [scripts/wiki_new_ingest.py](../../scripts/wiki_new_ingest.py).

## Output

- Manifest path.
- Text/chunk paths.
- LLM context status.
- Input-stage status and inherited target pages.
- Event path.
- Integration status: packet path, targets updated, `consolidated_into` closed.
- Proposal path.
- Pages impacted.
- Privacy and gate risks.
