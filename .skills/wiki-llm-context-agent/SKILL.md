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

The legacy global honesty gate fails when a globally stored request has a chunk
without a valid recorded result and `required_context_pass: true`. It does not
inspect the separate folder-v2 artifact namespaces; use the selected folder
request with `wiki_llm_context_pass.py --check`, inspect `pending_llm_calls`
even if the exit code is zero, and validate the request and its results with
folder preflight. Neither check proves execution or review. A complex source is
not consolidated without the deep reading. And the consolidation gate
([scripts/wiki_consolidate.py](../../scripts/wiki_consolidate.py) `--mode v1 --check`, in
CI) covers v1 and fails while there is a source with a complete deep read but no closed event:
ingesting = integrating.

## Flow

For the folder-bound flow, start in the authorized context, read its index
and relevant bodies, and follow [folder ingestion](../../docs/references/guides/bounded-ingestion.md#folder-bound-ingestion)
with an explicit host binding. Prepare a folder consolidation proposal, review
it, run folder preflight and integrate under the project's policy. A proposal
or recorded result does not prove reading, review or integration; the v1 gate
does not establish folder-v2 closure. The commands below describe the explicit
historical v1 flow.

1. Use the task's validated packet and selected root/channel/template inputs.
   An authorized coordinator can compile/check [the input stage](../../scripts/wiki_input_stage.py)
   when routing requires it; a scoped executor does not read the full global
   catalog or every front as mandatory context. Missing required inputs return
   a blocker instead of expanding the task's readset. An explicitly omitted
   business root remains missing coverage; do not decide a question that needs
   it, and do not omit mandatory lineage rules.
2. Use the canonical [ingestion entry](../../scripts/wiki_ingest.py) to extract,
   scan and prepare the full request before persistence:
   ```bash
   python3 scripts/wiki_ingest.py --mode v1 --source SOURCE --context SOURCE_CONTEXT --approved-revision APPROVED_SHA --policy-context CONTEXT_ID --context-max-bytes 100000 --request-max-bytes 256000
   ```
   These positive byte ceilings bound context and complete canonical UTF-8
   request respectively; they do not guarantee a model token window. Select a
   ceiling compatible with the actual harness. Approved context failure never
   falls back to working-tree compatibility. See [bounded ingestion](../../docs/references/guides/bounded-ingestion.md).
3. Read the emitted request from the configured extraction-events directory.
   Mandatory context appears once, followed by every extracted chunk with
   `chunk_id`, `cache_key`, `text` and `result_exists`. Actual policy and required
   perspective bodies accompany the root entity, channel and targets.
   [wiki_llm_context_pass.py](../../scripts/wiki_llm_context_pass.py) can re-emit
   or check the existing extraction using the same source, approval, context
   and limits. Oversize is a recoverable blocker; obtain an explicit smaller
   source/stage or an authorized ceiling rather than truncating content.
4. For each chunk with `result_exists: false`, do the deep reading following the
   `prompt` of the package and the template
   [context_deep_read.v4.md](../../wiki_core/llm/prompts/context_deep_read.v4.md).
   Produce one object per chunk with the keys of `result_required_keys`
   (use the `cache_key` of the chunk itself).
5. Record the results:
   ```bash
   python3 scripts/wiki_llm_context_pass.py --mode v1 --source SOURCE --context SOURCE_CONTEXT --approved-revision APPROVED_SHA --policy-context CONTEXT_ID --context-max-bytes 100000 --request-max-bytes 256000 --record-result RESULT.json
   ```
   Accepts a single object or an array. The script validates the schema (including
   non-empty quadrants and `sensitivity.has_pii`) and writes the result to the LLM
   pass cache (`llm-cache/`).
6. Confirm the gate:
   ```bash
   python3 scripts/wiki_llm_context_pass.py --mode v1 --source SOURCE --context SOURCE_CONTEXT --approved-revision APPROVED_SHA --policy-context CONTEXT_ID --context-max-bytes 100000 --request-max-bytes 256000 --check
   ```
   It should return `ok: true` / exit 0.
7. Consolidate and INTEGRATE — the work does NOT end at `--record-result`.
   Generate the normalized event and the integration packet with
   [scripts/wiki_consolidate.py](../../scripts/wiki_consolidate.py):
   ```bash
   python3 scripts/wiki_consolidate.py --mode v1 --source <source_id> --emit-event --packet
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
   the event's `consolidated_into` (each non-source target must reference the
   source in `source_refs`; source identity targets use event/lifecycle closure
   and never self-reference). Close with the gates green:
   ```bash
   python3 scripts/wiki_audit.py --check
   python3 scripts/wiki_consolidate.py --mode v1 --check
   python3 scripts/wiki_quality_report.py --check
   ```
   Only then does the source page receive `ingestion_state: ingested` +
   `last_ingested_at` + a line in the ingestion log, the source registry is
   regenerated, and the change goes out in a PR.

## Rules

- Never write canonical memory directly; the result is event/proposal material for
  PR review under the repository's [AGENTS.md](../../AGENTS.md).
- Fill in the four quadrants or declare explicit absence (the validator
  fails an empty quadrant).
- Every claim declares `status_epistemologico` and references the `chunk_id`.
- Mark `sensitivity.has_pii: true` when there is personal data (PII -- allowed
  on a private page) and `sensitivity.has_secret: true` when there is an access
  secret (always blocked). Never repeat the raw value in either case.
- Reuse only a result matching the current request's cache key and complete
  bound contract. In folder mode, changes to instructions, selected context,
  queries, limits or the chunk manifest can require a new read even if the
  source and model versions are unchanged. Rebuild the current request and
  inspect `result_exists` or the selected `--check` pending count: retained
  request flags describe the original emission. Cache reuse does not prove
  reading or review.
- When the excerpt is insufficient, record in `uncertainties` that it is necessary to
  expand the local search — do not invent context.
- `source_refs` records declared source links; qualify the association and
  revision using the applicable bound request, provenance and review. A link
  alone does not prove a read. `moc_parent`/parent hub records navigation.
  Do not leave generated relation pages parallel to the context hierarchy.


## Missing input and approval interfaces

- Use the executing harness's actual native question interface for missing
  information, and its actual approval interface for a concrete effect still
  requiring authorization. Honor existing grants; do not ask again merely
  because a generic procedure mentions approval.
- Return the structured blocker to the coordinator through the existing task
  response: exact action, target, sanitized reason, owner, required action,
  supported interface and resume condition. Preserve its identity on retry.
  Do not send notifications to external channels without existing authorization.
- Never invent a login diagnosis, deep link, tool capability or approval button.
  Do not request passwords, tokens or MFA values in the task text. If no native
  question/approval interface is available, report that concrete limitation,
  keep dependent work pending and continue independent authorized work.
- A timeout, silence or an operator saying “done” does not prove a grant or a
  completed effect. Verify the supported resume condition. A denied action
  remains denied until materially new, relevant evidence permits one bounded
  retry; observe an uncertain outcome before attempting its effect again.
