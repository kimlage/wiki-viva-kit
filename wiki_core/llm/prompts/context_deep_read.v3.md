# Prompt: deep contextual reading (context_deep_read v3)

You are the agent that runs this repository. `wiki_core` has already selected
the chunks and built this request; your job is to deep-read each chunk with
`result_exists: false` and return one structured object per chunk.

v3 keeps the integral-quadrant extraction from v2 and adds **perspectives**:
explicit lenses that say what this source must extract for downstream pages.
Read the chunk once, extract neutral claims/entities/decisions/actions, then
fill each required perspective from that extracted material. Do not reread the
source separately for each perspective.

## Rules

- Never write canonical memory directly. Output only the result object that will
  be recorded in the LLM cache and later reviewed through the PR flow.
- Fill all four quadrants with specific content or `absent: <reason>`.
- Every claim must include `status_epistemologico`, `chunk_id` and confidence.
- Extract entities and relationships so named concepts can be linked later.
- If the request contains `perspectives_required`, every listed perspective id
  must appear in `perspectives`.
- Perspective status must be one of: `extracted`, `not_applicable`, `pending`,
  `blocked`, `skipped_with_reason`.
- `not_applicable`, `blocked` and `skipped_with_reason` require `reason`.
- Do not drop a required perspective silently. Absence is a recorded result.
- Flag PII/secrets in `sensitivity` without repeating raw secret values.

## Quadrants — canonical Wilber/AQAL semantics

Each quadrant crosses **interior/exterior** with **individual/collective**.
Use this mapping even when a root entity is a team, company, product or
project.

| Key | AQAL position | Extract |
| --- | --- | --- |
| `interior_individual` | `I`, interior individual | First-person subjective meaning: what a specific person or root entity intends, values, fears, perceives or interprets. |
| `exterior_individual` | `It`, exterior individual | Observable behavior, direct output, owned artifact, evidence or metric of a specific person/root entity. |
| `interior_collective` | `We`, interior collective | Shared meaning, culture, relationship, norm, agreement, conflict, role expectation or team narrative. |
| `exterior_collective` | `Its`, exterior collective | Systems, tools/platforms, channels, processes, rules, structures, institutions, workflows and infrastructure. |

Boundary rule: classify the fact being extracted, not merely the source type. A
repository, document, dashboard or ticket can be `exterior_individual` when it
is an owned artifact/output/evidence. The platform or workflow that coordinates
people around it (Jira, Slack, Drive, calendar, CI, CRM, ERP, support system,
governance cadence) is `exterior_collective`. A plain roster, org chart, RACI or
workflow assignment is not `interior_collective` by itself; it becomes
`interior_collective` only when the source preserves shared meaning, culture,
relationship quality, mutual expectation or roles-as-lived. Otherwise, treat the
administered structure as `exterior_collective`.

## Output schema

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
    "interior_individual": "...specific content, or `absent: <why>`...",
    "exterior_individual": "...",
    "interior_collective": "...",
    "exterior_collective": "..."
  },
  "quadrant_confidence": {
    "interior_individual": "high|medium|low",
    "exterior_individual": "high|medium|low",
    "interior_collective": "high|medium|low",
    "exterior_collective": "high|medium|low"
  },
  "entities": [
    {"name": "System", "type": "tool", "mentions": ["System"]}
  ],
  "claims": [
    {"claim": "...", "status_epistemologico": "fato", "chunk_id": "...", "confidence": "media"}
  ],
  "decisions": [],
  "actions": [],
  "risks": [],
  "uncertainties": [],
  "relationships": [],
  "context_fit": {"context": "<repo context>", "why": "...", "suggested_stale_after_days": 30},
  "perspectives_required": ["perspective-technical"],
  "perspectives": {
    "perspective-technical": {
      "status": "extracted",
      "claims": ["claim indexes or short summaries consumed by this perspective"],
      "decisions": [],
      "actions": [],
      "risks": [],
      "metrics": {"risk_count": 0, "decision_count": 0},
      "target_page_types": ["project", "claim", "decision"]
    }
  },
  "sensitivity": {"has_pii": false, "notes": "..."}
}
```

For a required perspective with no relevant material:

```json
"perspectives": {
  "perspective-publication": {
    "status": "not_applicable",
    "reason": "The chunk contains only internal operational mechanics, with no public-facing claim."
  }
}
```

Record each object with:

```bash
python3 scripts/wiki_llm_context_pass.py --record-result <file-or-stdin>.json --context <context>
```

> Versioning note: v3 adds perspective coverage. The cache key includes
> `prompt_version` and `schema_version`, so v3 results do not reuse v2 cache.
