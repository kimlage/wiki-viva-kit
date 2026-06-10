---
name: wiki-llm-context-agent
description: Run the deep contextual reading (LLM pass) over the chunks selected by wiki_core and write the result to the cache. The intelligence lives in the agent that runs the repo (Claude/Codex/Gemini), not in a Python LLM client.
---

# Wiki LLM Context Agent

## Architecture model

`wiki_core` does the deterministic work (download/gather sources, extract text,
chunking, index, excerpt selection) and assembles a **context package**. YOU, the
agent that runs this repo, perform the deep reading and write the result. There is
no embedded Python LLM client — by design.

The honesty gate: as long as there is a chunk without a valid recorded result and
`required_context_pass: true` in `wiki.config.yaml`, the auditor fails. A complex
source is not consolidated without the deep reading.

## Flow

1. Generate/update the deterministic artifacts of the source (manifest, text, chunks,
   index) with the `wiki_extract_*` and `wiki_build_index` scripts.
2. Assemble the context package:
   ```bash
   python3 scripts/wiki_llm_context_pass.py --source <source> --context <context> --emit-request
   ```
   This writes the context package (one request file per source, in
   `extraction-events/`) containing: prompt (versioned instruction),
   `result_required_keys`, `quadrants_required` and, per chunk, `chunk_id`,
   `cache_key`, `text` and `result_exists`.
3. For each chunk with `result_exists: false`, do the deep reading following the
   `prompt` of the package and the template `wiki_core/llm/prompts/context_deep_read.v1.md`.
   Produce one object per chunk with the keys of `result_required_keys`
   (use the `cache_key` of the chunk itself).
4. Record the results:
   ```bash
   python3 scripts/wiki_llm_context_pass.py --record-result <file|->.json --context <context>
   ```
   Accepts a single object or an array. The script validates the schema (including
   non-empty quadrants and `sensitivity.has_pii`) and writes the result to the LLM
   pass cache (`llm-cache/`).
5. Confirm the gate:
   ```bash
   python3 scripts/wiki_llm_context_pass.py --source <source> --context <context> --check
   ```
   It should return `ok: true` / exit 0.

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
