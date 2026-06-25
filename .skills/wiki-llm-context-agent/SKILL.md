---
name: wiki-llm-context-agent
description: Run the deep contextual reading (LLM pass) over the chunks selected by wiki_core, write the result to the cache, and then consolidate and INTEGRATE what was read into the target wiki pages (ingesting = integrating). The intelligence lives in the agent that runs the repo (Claude/Codex/Gemini), not in a Python LLM client.
---

# Wiki LLM Context Agent

## Architecture model

`wiki_core` does the deterministic work (root/input-stage compilation,
download/gather sources, extract text, chunking, index, excerpt selection) and
assembles a **context package**. YOU, the
agent that runs this repo, perform the deep reading, write the result, and then
consolidate and INTEGRATE what you read into the target wiki pages — the work
does not end at the cache. There is no embedded Python LLM client — by design.

The honesty gate: as long as there is a chunk without a valid recorded result and
`required_context_pass: true` in `wiki.config.yaml`, the auditor fails. A complex
source is not consolidated without the deep reading. And the consolidation gate
([scripts/wiki_consolidate.py](../../scripts/wiki_consolidate.py) `--check`, in
CI) fails while there is a source with a complete deep read but no closed event:
ingesting = integrating.

## Flow

1. Compile/check the input stage with
   [scripts/wiki_input_stage.py](../../scripts/wiki_input_stage.py) so root
   entity, input channel, inherited perspectives and target pages are current.
2. Generate/update the deterministic artifacts of the source (manifest, text, chunks,
   index) with the `wiki_extract_*` and `wiki_build_index` scripts.
3. Assemble the context package:
   ```bash
   python3 scripts/wiki_llm_context_pass.py --source <source> --context <context> --emit-request
   ```
   This writes the context package (one request file per source, in
   `extraction-events/`) containing: prompt (versioned instruction),
   `result_required_keys`, `quadrants_required` and, per chunk, `chunk_id`,
   `cache_key`, `text` and `result_exists`. For repo-local source pages it also
   includes `root_entity`, `input_channel`, `quadrant_map`, `target_pages` and
   `input_stage_status`.
4. For each chunk with `result_exists: false`, do the deep reading following the
   `prompt` of the package and the template
   [context_deep_read.v3.md](../../wiki_core/llm/prompts/context_deep_read.v3.md).
   Produce one object per chunk with the keys of `result_required_keys`
   (use the `cache_key` of the chunk itself).
5. Record the results:
   ```bash
   python3 scripts/wiki_llm_context_pass.py --record-result <file|->.json --context <context>
   ```
   Accepts a single object or an array. The script validates the schema (including
   non-empty quadrants and `sensitivity.has_pii`) and writes the result to the LLM
   pass cache (`llm-cache/`).
6. Confirm the gate:
   ```bash
   python3 scripts/wiki_llm_context_pass.py --source <source> --context <context> --check
   ```
   It should return `ok: true` / exit 0.
7. Consolidate and INTEGRATE — the work does NOT end at `--record-result`.
   Generate the normalized event and the integration packet with
   [scripts/wiki_consolidate.py](../../scripts/wiki_consolidate.py):
   ```bash
   python3 scripts/wiki_consolidate.py --source <source_id> --emit-event --packet
   # optional: --source-page <path> / --source-ref <page_id> of the source's canonical page
   ```
   `--emit-event` generates the normalized event from the deep read recorded in
   the llm cache (quadrants filled, candidate claims/decisions/actions and
   `consolidated_into: []` for you to close); `--packet` emits the integration
   packet (gitignored) with related pages, root impact, target pages,
   overlapping claims, and potential conflicts per claim/entity.
8. Guided by the packet, INTEGRATE for real: update the target hubs/concepts
   incrementally first; create/update load-bearing relation pages only when the
   detail needs its own page and give each one a `moc_parent` hub (with the conflict
   fields `supersedes`/`superseded_by`/`conflicts_with`/`conflict_resolution`
   when claims collide); resolve or record EVERY conflict and ambiguity; fill in
   the event's `consolidated_into` (each target page must reference the source
   in `source_refs`). Close with the gates green:
   ```bash
   python3 scripts/wiki_audit.py --check
   python3 scripts/wiki_consolidate.py --check
   python3 scripts/wiki_quality_report.py --check
   ```
   Only then does the source page receive `ingestion_state: ingested` +
   `last_ingested_at` + a line in the ingestion log, the source registry is
   regenerated, and the change goes out in a PR.

## Rules

- Never write canonical memory directly; the result is event/proposal material for
  human review via PR.
- Fill in the four quadrants or declare explicit absence (the validator
  fails an empty quadrant).
- Every claim declares `status_epistemologico` and references the `chunk_id`.
- Mark `sensitivity.has_pii: true` when there is personal data (PII -- allowed
  on a private page) and `sensitivity.has_secret: true` when there is an access
  secret (always blocked). Never repeat the raw value in either case.
- Reuse the cache: do not reprocess a chunk whose `cache_key` already has a result, unless
  the source, the chunk, the prompt_version, the schema_version, or the profile changes.
- When the excerpt is insufficient, record in `uncertainties` that it is necessary to
  expand the local search — do not invent context.
- `source_refs` proves provenance; `moc_parent`/parent hub proves navigation.
  Do not leave generated relation pages parallel to the context hierarchy.
