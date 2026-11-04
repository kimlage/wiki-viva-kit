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
3. Use the extracted text and chunks prepared by the selected ingestion flow.
   The standalone [extractor](../../scripts/wiki_extract_text.py) is a separate
   coordinator operation, not an automatic expansion of the executor's scope.
4. Consult only the selected authorized evidence. A global index rebuild with
   [scripts/wiki_build_index.py](../../scripts/wiki_build_index.py) is a separate
   operation for a coordinator with authority over its full readset.
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
7. INTEGRATE — the recorded result is not integration. In folder mode, review
   the exact proposal and preflight, incorporate it only with the project's
   authorization, then read back the selected destination and assess affected
   consumers. Preserve prior source projections and requirements. The folder
   proposal does not generate or close a legacy v1 event.
   In v1 mode, use the event and packet from step 6: resolve conflicts, fill the
   event's `consolidated_into`, and maintain source backlinks without a source
   identity page referencing itself. In either flow, update selected hubs and
   concepts, record conflicts and ambiguities, and create or update load-bearing
   claims where appropriate. Give new pages their appropriate `moc_parent` and
   quadrant placement. The v1 event check covers only that legacy flow.
8. Run the project's applicable audit, quality and independent review gates for
   the exact proposal. [wiki_new_ingest.py](../../scripts/wiki_new_ingest.py)
   is a separate legacy global proposal tool; it is not a folder-bound step and
   requires a coordinator authorized for its actual readset and output.

## Output

- Manifest path.
- Text/chunk paths.
- LLM context status.
- Folder mode: selected request/results, proposal, preflight, review,
  integration, destination readback and reassessment states.
- V1 mode: input-stage status, inherited targets, event and packet paths,
  targets updated and `consolidated_into` state.
- Pages impacted.
- Privacy and gate risks.
