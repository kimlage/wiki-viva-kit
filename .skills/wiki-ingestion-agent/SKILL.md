---
name: wiki-ingestion-agent
description: Convert a new source into deterministic manifest, extracted text/chunks, normalized event, contextual LLM plan, and PR-ready ingestion proposal; update target memory pages in the authorized proposal and follow the repository policy for applying it.
---

# Wiki Ingestion Agent

## Workflow

1. Follow the [memory router](../wiki-memory-router/SKILL.md) for your role.
   An authorized coordinator selects applicable root, channel, source config,
   template and perspective inputs. A packet-bound executor uses those bodies
   and exact slices; it does not read the global index/input-stage catalog or
   other fronts automatically. Missing required context is a structured blocker.
2. For an approved folder-policy source, use [wiki_coordination.py](../../scripts/wiki_coordination.py)
   `--source-stage prepare` with the explicit folder, index, source, context
   selection, approved revision and any authorized integrator. Read the
   [bounded ingestion guide](../../docs/references/guides/bounded-ingestion.md)
   for stage payloads, byte limits, formats and coverage. Host-pinned independent
   Git selections require their own grants and remain supporting evidence.
3. Read the complete returned request and selected context. The agent performs
   the contextual deep read; `wiki_core` does not call a model. Retain omissions
   and produce results bound to the request's chunk identities.
4. Record results through `--source-stage record` with the same selections,
   policy, limits and integrator. Use `--source-stage inspect` for authorized
   readback of explicitly selected results or a retained integration proposal.
   Recording and inspection do not prove comprehension or incorporation.
5. Prepare the event and integration packet through `--source-stage consolidate`
   with the same bound request, authorized source page, canonical event target
   and explicitly selected candidates. Git-derived events need a separate
   host publication grant. A failed write can leave partial effects to inspect.
6. The standalone manifest/text/index tools and
   [wiki_ingest.py](../../scripts/wiki_ingest.py) without approved flags remain
   separate working-tree compatibility paths for authorized callers; they do
   not apply folder policy. The old approved-v1 ingestion and recording flags
   are refused for new operations. Generic shared-cache checks do not inspect
   protected artifacts.
7. INTEGRATE — ingesting = integrating, the work does not end at the recorded
   result: the authorized integrator, guided by the packet, must update target
   hubs/concepts in the authorized proposal incrementally
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
   [scripts/wiki_consolidate.py](../../scripts/wiki_consolidate.py) `--check`,
   [scripts/wiki_audit.py](../../scripts/wiki_audit.py) `--check` and
   [scripts/wiki_quality_report.py](../../scripts/wiki_quality_report.py)
   `--check` green within their coverage, and separately inspect the bound
   protected request, results and event. These checks do not prove that the
   agent read or incorporated content. Apply the proposal to the approved
   version only through the repository's approval and PR policy.
8. When the project requires a separate flat ingestion proposal, use its
   existing process and [scripts/wiki_new_ingest.py](../../scripts/wiki_new_ingest.py)
   within the authorized scope. A protected event is not itself a flat gate
   proposal, and neither a proposal nor an event proves integration.

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
