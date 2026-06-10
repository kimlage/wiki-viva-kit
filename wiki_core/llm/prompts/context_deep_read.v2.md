# Prompt: deep contextual reading (context_deep_read v2)

You are the agent that runs this repository (Claude, Codex, Gemini or another).
This reading is NOT performed by a Python LLM client: `wiki_core` has already
gathered and selected the relevant excerpts (chunks) and assembled this package.
Your task is to deep-read every chunk with `result_exists: false` and return one
structured object per chunk.

The goal is **operational memory that is specific and connected** — not generic
summaries. Two failure modes to avoid above all:

1. **Generic / meta output.** Never write filler ("to fill in", "depends on
   extraction"), and never narrate the ingestion process itself. Write about the
   SUBJECT: the concrete facts, people, decisions and tensions in the chunk. If a
   quadrant genuinely has nothing, say `absent: <why>` — do not pad it.
2. **Orphan information.** Bring useful information **with its connections**. Every
   person, source, tool, decision or page you name should be captured as an
   `entity` or `relationship` so the wiki can link it. A title or a name with no
   link is a defect.

## Rules

- Never write canonical memory directly. Your output is event/proposal material
  for human review via PR.
- Fill in all four integral quadrants with SPECIFIC content from the chunk, and
  give each a `quadrant_confidence` of `high | medium | low`. If a quadrant does
  not apply, write `absent: <reason>` — distinguish "truly absent in this chunk"
  from "present elsewhere, not in this excerpt" (the latter goes in `uncertainties`).
- Every claim must declare `status_epistemologico`
  (fato | percepcao | hipotese | insight | proposta) and reference the `chunk_id`.
- Extract `entities` (people, organizations, tools/systems, sources) and
  `relationships` between them — this is what makes pages connected. Name each
  entity exactly as it appears so a person/source page can be linked on mention.
- Judge `context_fit`: which memory context this belongs to and WHY, and a
  `suggested_stale_after_days` reflecting how fast this kind of information ages
  (a live project decision ages fast; a stable reference ages slowly). Context is
  what determines the update cadence.
- Flag sensitivity: if the chunk contains PII or a secret (tax ID, account, card,
  token, credential), set `sensitivity.has_pii: true` and describe it without
  repeating the raw value.
- List real uncertainties and questions for the human in `uncertainties`. If the
  excerpt is insufficient, say so (do not invent context).

## Quadrants — what to look for (with examples)

Each quadrant crosses **interior↔exterior** (subjective meaning vs observable
fact) with **individual↔collective** (a single person vs a group/system).

- `interior_individual` — what a specific person perceived, felt, wanted, feared
  or interpreted. *Look for:* stated motivations, worries, intentions, judgments.
  *Example:* "Ana is worried the migration slips past Q3 and wants a buffer."
  *Not:* what Ana did (that is exterior_individual).
- `exterior_individual` — what a specific person did, said, delivered or measured;
  observable acts. *Look for:* actions, commitments, deliverables, numbers tied to
  a person. *Example:* "Bruno shipped the auth fix and closed PR #214 on the 9th."
- `interior_collective` — shared meaning: agreement, disagreement, climate,
  narrative, culture, unspoken norms across a group. *Look for:* "the team feels
  …", consensus/conflict, how the group frames something. *Example:* "The squad
  treats the legacy gateway as untouchable, so no one proposes replacing it."
- `exterior_collective` — systems, processes, rules, structures, tools, the
  affected machinery. *Look for:* workflows, policies, architectures, tools/
  services, org structure. *Example:* "Deploys go through a manual approval in
  Jira; releases are weekly."

Disambiguation: if you can attribute it to ONE named person, it is individual; if
it is about the group or the system, it is collective. If it is a feeling/meaning,
it is interior; if it is an observable act/structure, it is exterior.

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
    {"name": "Ana Souza", "type": "person", "role_hint": "PM", "mentions": ["Ana"]},
    {"name": "Jira", "type": "tool", "mentions": ["the board"]},
    {"name": "Q3 migration plan", "type": "source", "mentions": []}
  ],
  "claims": [{"claim": "...", "status_epistemologico": "fato", "chunk_id": "...", "confidence": "media"}],
  "decisions": [{"decision": "...", "by": "Ana Souza", "source": "..."}],
  "actions": [{"action": "...", "owner": "Bruno", "next_step": "..."}],
  "risks": ["..."],
  "uncertainties": ["..."],
  "relationships": [{"from": "Ana Souza", "to": "Q3 migration plan", "kind": "owns"}],
  "context_fit": {"context": "<one of the repo's contexts>", "why": "...", "suggested_stale_after_days": 30},
  "sensitivity": {"has_pii": false, "notes": "..."}
}
```

`quadrant_confidence`, `entities` and `context_fit` are new in v2 and optional for
schema validation, but you should always provide them — they are what makes the
resulting pages specific (confidence), connected (entities/relationships) and
correctly scheduled (context_fit). Keep `produced_by` honest.

## How to record

For each processed chunk, record the object with:

```bash
python3 scripts/wiki_llm_context_pass.py --record-result <file-or-stdin>.json --context <context>
```

It accepts a single object or an array of objects. The script validates the
schema and writes to `data/derived/wiki/llm-cache/<cache_key>.json`. Only then
does the `required_context_pass` gate consider the source read.

> Versioning note: v2 enriches the guidance and adds optional `quadrant_confidence`,
> `entities` and `context_fit` fields; the required output schema is a superset of
> v1. The cache key includes `prompt_version` (not the prompt text), so bumping to
> v2 asks for a fresh deep-read rather than reusing v1 results.
