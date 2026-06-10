# Prompt: deep contextual reading (context_deep_read v1)

You are the agent that runs this repository (Claude, Codex, Gemini or another).
This reading is NOT performed by a Python LLM client: `wiki_core` has already
gathered and selected the relevant excerpts (chunks) and assembled this package.
Your task is to deep-read every chunk with `result_exists: false` and return one
structured object per chunk.

## Rules

- Never write canonical memory directly. Your output is event/proposal material
  for human review via PR.
- Fill in all four integral quadrants. If a quadrant does not apply, write
  explicitly `absent: <reason>` — never leave it empty.
- Every claim must declare `status_epistemologico`
  (fato | percepcao | hipotese | insight | proposta) and reference the `chunk_id`.
- Flag sensitivity: if the chunk contains PII or a secret (tax ID, account,
  card, token, credential), set `sensitivity.has_pii: true` and describe it
  without repeating the raw value.
- List real uncertainties and questions for the human in `uncertainties`.
- If the excerpt is insufficient, say in `uncertainties` that the local search
  needs to be expanded (do not invent context).

## Quadrants

- `interior_individual`: what the person perceived, felt, wanted or interpreted.
- `exterior_individual`: what someone did, said, delivered or measured.
- `interior_collective`: meaning, agreement, conflict, climate, narrative.
- `exterior_collective`: system, process, rule, structure, affected tool.

## Output schema (one object per processed chunk)

```json
{
  "cache_key": "<the chunk's cache_key, copied from the package>",
  "source_id": "<the package's source_id>",
  "chunk_id": "<chunk_id>",
  "prompt_version": "<the package's prompt_version>",
  "schema_version": "<the package's schema_version>",
  "model_profile": "<the package's model_profile>",
  "produced_by": "claude|codex|gemini|other",
  "quadrants": {
    "interior_individual": "...",
    "exterior_individual": "...",
    "interior_collective": "...",
    "exterior_collective": "..."
  },
  "claims": [{"claim": "...", "status_epistemologico": "fato", "chunk_id": "...", "confidence": "media"}],
  "decisions": [{"decision": "...", "source": "..."}],
  "actions": [{"action": "...", "owner": "...", "next_step": "..."}],
  "risks": ["..."],
  "uncertainties": ["..."],
  "relationships": [{"from": "...", "to": "...", "kind": "..."}],
  "sensitivity": {"has_pii": false, "notes": "..."}
}
```

## How to record

For each processed chunk, record the object with:

```bash
python3 scripts/wiki_llm_context_pass.py --record-result <file-or-stdin>.json --context <context>
```

It accepts a single object or an array of objects. The script validates the
schema and writes to `data/derived/wiki/llm-cache/<cache_key>.json`. Only then
does the `required_context_pass` gate consider the source read.

> Versioning note: this file was translated to English under the same `v1`
> version — the semantics and output schema are unchanged, and the cache key
> does not include the prompt text (only `prompt_version`), so previously
> recorded results remain valid.
