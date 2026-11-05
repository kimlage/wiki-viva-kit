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

The shared-cache checks report missing deep reads and unconsolidated events
within their actual coverage. Protected source artifacts use a separate cache
and are not inspected by generic audit or consolidation scans. Inspect their
bound request, results and event through the protected stages; a green generic
check does not prove the protected source was read or incorporated.

## Flow

1. Start with the validated task packet and the authorized folder. Read the
   applicable instructions, context index and selected bodies. Missing or
   omitted context remains a coverage gap; links and packet hashes do not
   grant access or prove the agent read the content.
2. For an approved folder-policy source, use the `prepare` stage through the
   existing trusted host or the trusted-local-operator interface in
   [wiki_coordination.py](../../scripts/wiki_coordination.py). Select the
   source, current policy revision, entry folder/index, explicit context inputs,
   any required perspective paths and authorized integrator. Choose budgets
   appropriate to the harness. Follow [bounded ingestion](../../docs/references/guides/bounded-ingestion.md#host-bound-protected-source-preparation)
   for the stage payloads, supported formats and exact coverage limitations.
   Unsupported or unavailable inputs block; no route silently falls back.
3. Inspect the returned request and its `coverage`, `source_id`, `request_id`,
   prompt and chunk identities. If the business root was omitted or linked
   sources were not inspected, do not decide a task that needs those inputs.
   For independent Git evidence, select only grants already pinned by the host;
   paths, configured origin and receipts do not grant access. See
   [protected independent Git](../../docs/references/guides/protected-independent-git.md).
4. Read each chunk and context body, then produce one result per chunk using the
   keys and cache identities in the request. Approved folder requests require
   the [v5 prompt](../../wiki_core/llm/prompts/context_deep_read.v5.md); a
   consumer pinned to an older prompt must update its approved configuration
   and re-emit the request. Preserve older captures and results.
5. Submit the result objects through `--source-stage record` with the same
   source, context selection, policy, limits and integrator. Repeat any
   perspective and host-pinned repository selections. If a source, binding or
   selection changes, re-prepare and read the new request. A failed write may
   leave partial effects; inspect the reported state before retrying.
6. Use `--source-stage consolidate` with the same selectors, an authorized
   source page, canonical event target and any additional candidates. Declared
   source/config/channel paths and targets are resolved with current authority;
   connected hubs contribute subject candidates without requiring a duplicate
   manual mapping. Inspect unresolved references before claiming full coverage.
   Git-derived events need the host's separate publication grant. The event and
   packet are proposal material; neither proves review or incorporation.
   The optional `compare` stage gives a manual review suggestion for selected
   repository evidence, with file consumption remaining unknown.
7. Return the affected subjects to the coordinator through the existing task
   response. The coordinator updates the existing task sequence using declared
   `information_requirements`: prerequisite changes first, then each consuming
   subject's own interpretation. Reuse pending work for the same subject and
   input revision. Hub navigation alone creates no factual dependency. Record
   each subject as updated, still valid or blocked; propagate again only when
   its resulting output or consumed prerequisite changes. Newly discovered
   subjects remain proposals within the authorized scope.
8. The authorized integrator reviews the proposal, updates the appropriate
   targets in the authorized proposal, records `consolidated_into`, runs the
   applicable gates on the exact proposed SHA and follows the repository's PR policy. Read back the result
   after an authorized integration. An event, cache result or green low-level
   test is not a completed ingestion.

For a separately authorized working-tree folder route, use
[wiki_ingest.py](../../scripts/wiki_ingest.py) with `--folder` or a nested
working directory and follow the local selection and cache instructions in the
guide. That route does not enforce the approved folder policy. Its
[wiki_llm_context_pass.py](../../scripts/wiki_llm_context_pass.py) recording and
check commands are separate from the host-bound stages. Old approved-v1 flags
on those commands are refused for new operations; retained historical artifacts
are not deleted or automatically requalified.

## Rules

- The authorized integrator may update target memory pages in the proposal;
  applying them to the approved version follows the repository's PR policy and
  [AGENTS.md](../../AGENTS.md).
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
