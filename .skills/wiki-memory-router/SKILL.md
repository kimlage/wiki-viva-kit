---
name: wiki-memory-router
description: Route reading, editing and delegation in Markdown/Git living-wiki repositories through their configured memory roots, current policies, source evidence and ingestion/consolidation process. Use before operating a repository that adopted Wiki Viva Kit, including remote checkouts and agent handoffs.
---

# Wiki Memory Router

## Choose the task first

Identify your role and authorized read scope before opening repository content.
An authorized coordinator or integrator uses the checkout instructions and the
index for the selected context to route work. For a concrete folder entry, start
in that folder: read applicable ancestor/local AGENTS instructions, its context
index and the skills required there, within the authorized scope. The global
index and [task entry points](../../scripts/README.md#task-entry-points) help with
cross-context work when needed. A packet-bound executor follows the scoped
handoff below.
Consumer-specific requirements apply within the current authority; navigation
links never grant additional read access.

A coordinator follows the [coordinator role](../wiki-viva/reference/coordinator.md)
at opening and resumption. Route implementation, tests, integration and
infrastructure to existing integrators; the workflow below does not assign
their execution steps to the coordinator.

- For locating or reading a candidate, use direct lookup or the known page.
  Report origin and coverage limits. This alone does not require ingestion,
  a new model run, a server startup or global maintenance.
- For a consolidated factual claim, current-state assertion, absence or total,
  load the relevant domain/relations and original evidence. State incomplete
  coverage explicitly; search hits alone do not prove completeness or freshness.
- For resumed ingestion, canonical changes or delegation, follow the workflow
  below and its applicable gates. A read-only lookup must not silently turn
  into refresh, publication or a write.

## Packet-bound executor

- Use a packet validated by the trusted coordinator/adapter against current
  approved policy. A hash or an unverified packet alone cannot establish that
  authority. Verify the executing instance's actual tools and interface; do not
  infer accounts or permissions from YAML or the parent's capabilities.
- Identify the sender and intended recipient of each handoff, including on
  resumption. A sender's statement about their own role or thread does not
  reassign the recipient. Only explicit direction from the coordinator for that
  scope or the owner changes the assignment; resolve unclear identities from
  the existing context before interpreting a message as a role change.
- Read the delivered instruction/template bodies, local context map and exact
  evidence selectors. Do not reopen the global memory index, generated input
  stage or every other front merely because those files are linked. Select a
  shared skill/template only when applicable to this task and included in its
  authorized handoff.
- If required context is absent, expired, denied or exceeds the actual harness
  window, return the structured blocker to the coordinator. Request a concrete
  authorized slice or stage; do not expand the readset, truncate a rule or claim
  complete coverage. Use supported native question/approval interfaces as
  described in [the context-reading skill](../wiki-llm-context-agent/SKILL.md).
- Keep proposed writes within the delivered task's scope and review policy.
  Report selected inputs, changed paths and unresolved gaps to the integrator;
  do not replace required integration gates with a claim that the packet was read.

## Workflow for synthesis, ingestion, changes and delegation

The steps below apply within the authorized role and repository scope. A
coordinator routes and consolidates; the integrator performs the applicable
implementation and gates. They are not a mandate for a scoped executor to read
or run global maintenance.

1. Identify the authorized checkout root, using `git rev-parse --show-toplevel`
   when available. Read that root's [AGENTS.md](../../AGENTS.md) and applicable
   scoped instructions before acting. Resolve paths against the checkout,
   not an agent installation or a fixed host directory.
   For an authorized local folder entry, read the physical instruction chain
   and context index; see [bounded ingestion](../../docs/references/guides/bounded-ingestion.md)
   for selection and its limits. Neither the folder nor a link grants access,
   and local preparation is separate from the approved packet in step 3.
2. Read [wiki.config.yaml](../../wiki.config.yaml) for configured names and resolve
   the selected folder's context index under `paths.memory_root`, including
   nested contexts. Use its ancestor/local instructions and applicable skills;
   the global memory index is required only when the task needs root or
   cross-context navigation. A local query does not require global execution.
3. Read the consumer's current approval policy, operational contract and
   ingestion process identified by its entry instructions. For a task handoff,
   use the complete protected packet with explicit canonical context, current
   approved revision, content revision and selected evidence. Read all its
   mandatory instructions and selected bodies; references, hashes or truncated
   samples do not replace the packet. Profiles in `wiki.coordination.yaml`
   preserve routing and history only: `common_context` and `context_pages` do
   not authorize or prepare task bodies. Place mandatory rules in the appropriate
   canonical context instructions/skills/templates; cross-context evidence needs
   approved imports/exports. Report missing canonical rules or selection before
   relying on a handoff; do not silently widen scope or change configuration.
   See [protected coordination](../../docs/references/guides/context-coordination-protected.md).

4. Select applicable source/channel/template inputs for this context and the
   configured root entity only when the task consumes it. The global generated
   input-stage catalog is coordinator navigation;
   do not insert its complete body as every task's mandatory instruction.
5. Recover the selected context's existing actions, source pages, pending work
   and responsible threads from its index/handoff. Inspect current runs and
   reconcile uncertain effects before resuming the same action and IDs; a
   finished turn alone does not close delivery. Open the global operation page
   resolved by `WikiPaths.operation_page` only for an applicable dependency or
   authorized cross-context coordination, not as a prerequisite to every folder.
6. Use the selected context's current handoff/short-term memory before older
   execution/event pages. Open `WikiPaths.operational_pass_page` when the task
   needs the global operational pass; its existence does not widen a local read.
7. When resuming ingestion or integration, the responsible integrator checks for
   deep reads awaiting integration within the authorized scope. For an authorized
   repository-wide check, run [scripts/wiki_consolidate.py](../../scripts/wiki_consolidate.py)
   with `--check`; a local lookup alone does not trigger that global operation.
8. Select the context-specific skills from its index and applicable instructions.
   Missing local instructions, evidence or authority are a concrete pending item
   on the existing action/handoff, with recipient and resume condition; they do
   not justify opening every context or inventing a parallel action list.
9. Treat configured `paths.references_root` as references, templates and audit
   history, not as live memory.
10. For new sources, the responsible integrator creates or confirms input-stage context, manifest, text/chunks, event, LLM context plan, integration (consolidated event with `consolidated_into` closed) and PR-ready proposal.
11. Before delegating, complete the existing [subagent brief](../../docs/references/templates/wiki/subagent-brief.md)
    under the [delegation contract](../../docs/references/guides/context-coordinators.md#delegation-contract).
    Bind the canonical task/base, policy sources, evidence and destinations.
    Verify tools, host/session and account in the executing instance; do not
    assume the parent's capabilities transfer. Record an exact blocker and a
    bounded condition for resuming the same IDs, preserving independent work.
12. Before finalizing a canonical change, the responsible integrator runs [scripts/wiki_audit.py](../../scripts/wiki_audit.py), [scripts/wiki_consolidate.py](../../scripts/wiki_consolidate.py) with `--check`, [scripts/wiki_quality_report.py](../../scripts/wiki_quality_report.py) with `--check`, [scripts/wiki_input_stage.py](../../scripts/wiki_input_stage.py) with `--check`, [scripts/wiki_check_methodology_coverage.py](../../scripts/wiki_check_methodology_coverage.py) when methodology files changed, [scripts/wiki_operation_compile.py](../../scripts/wiki_operation_compile.py) and [scripts/wiki_pr_summary.py](../../scripts/wiki_pr_summary.py).

## Rules

- Do not persist access secrets.
- Private useful operational context may be extracted in private repos when the repo policy allows it.
- Every local file, directory, script, template or page reference in Markdown should be a real Markdown link.
- Canonical memory changes go through a branch and the PR review policy in [AGENTS.md](../../AGENTS.md).
- Apply already granted authorization within its stated scope without requesting
  the same consent again. Preserve independent review and technical gates;
  policy does not grant missing tool access or override a tool denial.
- Record technical review and any required human acceptance separately; neither
  discovery, a prepared proposal nor a merged sub-delivery closes remaining
  acceptance. Preserve current STOPs and pending handoffs on the same action.
- Resolve historical wording through the current canonical policy. Record a
  missing decision or capability on the existing action instead of repeatedly
  assigning the unchanged blocker to new agents.
- Keep navigation hierarchical: root MOC -> context/domain hub -> entity/subdomain hub -> relation/evidence pages -> execution/event pages.
- Use the configured root entity as the semantic top page; the root MOC remains
  the technical map of content.
- Relation pages (`action`, `claim`, `decision`, `meeting`, `person`, `project`, `source`, `source_config`) need a declared `moc_parent`; do not treat `source_refs` as the parent.
- Consolidate current synthesis into hubs first, then link down to typed child pages when detail or audit history needs its own page.
