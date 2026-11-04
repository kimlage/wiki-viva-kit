# Finite context operation

This runbook describes a manual, reviewable path from an explicitly selected task to approved content. The coordinator and context packet are finite preparation tools; the chosen external harness supplies a thread and tools, and an authorized integrator performs Git review and integration. No step below starts a resident runner, installs a scheduler, proves a sandbox, or grants a new external account. The two-thread synthetic pilot establishes contract behavior within one harness, not qualification of two harness products or a deployed installation.

## 1. Select the context and the exact task

Enter through the context folder and its applicable `AGENTS.md` instructions;
read the context index and relevant bodies. Verify native instruction discovery
and effective permissions for the actual session. The [folder, source and
repository guide](context-folders-sources-repositories.md) describes that entry
and its boundaries. It complements the protected packet below, which remains
required whenever the installation uses that policy path.

The coordinator identifies the purpose, owner, output, integrator and the smallest explicit evidence set. Determine the current approved Git SHA from the trusted host reference and choose an approved content SHA; record omissions and unknown coverage. The executor must have the actual host/service capabilities for its task: a YAML capability or an administrative session is not proof of those capabilities. If an input crosses owners, both the producer's current export and the consumer's exact import must allow the same selector, use and classification. A link, old profile, parent directory or silence is not a grant. Route a specific connection request through an interface allowed to receive its metadata; leave it pending until genuinely approved.

Do not put a page's title, source details or other protected metadata into a task's generic text before that page is authorized. If editing an existing approved output requires reading it, select it as evidence too. Preserve the actual read set: an unrecorded read cannot be hidden by refreshing the result later.

## 2. Prepare the approved packet

Use the [protected coordinator](context-coordination-protected.md), configured by the trusted local operator at startup. The capability endpoint reports the host-bound context choices and trusted policy SHA only to an authenticated local session. Choose the context explicitly. The packet endpoint takes explicit task/evidence and checks current policy, canonical owner, approved history, exact bilateral grants and any supplied expected document digest before returning bytes. It provides context purpose and boundaries, mandatory rules, selected content, provenance, coverage and a bounded canonical digest.

For a trusted local CLI caller, the same packet can be prepared without a web server:

```sh
python3 scripts/wiki_coordination.py --root REPO --context-id CONTEXT \
  --approved-revision APPROVED_SHA --revision CONTENT_SHA --packet-request REQUEST.json
```

`REQUEST.json` is the task object documented in the protected coordinator guide. Replace all uppercase placeholders with actual authorized values. CLI output wraps the packet in `packet`; save that object unchanged for preflight. `max_bytes` limits the complete canonical JSON packet, including metadata and digest. Missing mandatory content or overflow is an error, never silent truncation. A fixed digest proves bytes, not that an agent read or understood them. The packet also supports [bounded dynamic queries](context-dynamic-selection.md) anchored to a canonical collection within the selected owner. Selection is limited to its authorized scope and reports coverage for that universe, not global absence. For imports between owners, use an exact selector with the required current bilateral authorization.

The older profile/snapshot coordinator remains a separate `caller_trust` compatibility mode. It may read a broad catalogue and is not an owner-scoped authorization boundary. It must not be presented as the protected route or used as its fallback.

For source ingestion, follow the separate [bounded ingestion guide](bounded-ingestion.md): select an approved local source and context, choose the business root explicitly or omit it, and set context and request byte budgets. Unsupported source access remains blocked until a qualified adapter is available.

## 3. Execute in a short worktree

The operator or external harness creates a task-specific worktree/branch from the approved base and delivers the packet to the selected context thread. The executor reads the supplied rules and selected inputs, works only within the declared and actually enforced scope, and reports its real reads, omissions, changes and blockers. If an input is missing, access is denied or the result of an effect is uncertain, record the specific blocker and resume condition; do not invent an interface or repeat an uncertain effect. Continue independent work only when it is authorized.

The existing [task-result schema](../schemas/wiki-task-result-v1.schema.json) binds task ID, context ID and packet digest, with changes, read coverage and blockers. A result is a report, not evidence of integration or semantic comprehension. When a proposed page adds an `information_requirements` declaration, record the precise source selector, the revision actually consumed, use/classification and explicitly chosen temporal policy. Do not turn a normative rule or a page's prior self-read into a factual self-dependency.

## 4. Preflight and independent integration

The integrator checks the exact base and branch HEAD, packet, result and actual diff. Use `POST /api/coordination/protected/preflight` in a host-bound authenticated operator, or the finite CLI:

```sh
python3 scripts/wiki_context_flow.py --repo REPO --approved-revision APPROVED_SHA \
  preflight --context CONTEXT --base BASE_SHA --head HEAD_SHA --branch wiki/TASK \
  --packet PACKET.json --result RESULT.json
```

Preflight checks current policy, selected bytes and read claims, owner/write scope, active normative files, new requirement declarations and Git branch identity. It neither runs the proposal code nor approves, tests, publishes or merges it. Browser-supplied capability reports do not authorize this route. An independent reviewer must review the final HEAD, including any integration edit, and applicable gates must be tied to that HEAD and configuration. A failed or skipped gate is not a pass.

An authorized external Git integrator serializes the merge under the repository's existing PR policy. Keep one integrator per target until a provider-enforced current-base queue or equivalent is qualified. Recheck base and exact HEAD immediately before the effect. If either advances, rebuild the packet and result against the current approved base, reconcile the actual read set, rerun preflight and obtain renewed independent review when necessary. Branches and worktrees are not confidentiality boundaries or merge locks.

## 5. Read back and assess impact

After an authorized merge, update the trusted approved reference through the installation's existing process and read back the exact integrated output. The `requirements` command can derive a **proposal** for canonical `information_requirements` from the bound packet and reported result after the proposal is incorporated; it verifies Git bytes and writes no page. The `impact --consumer PATH` command reads the authorized consumer's approved Markdown requirements through the existing relation parser and compares selected input revisions. See the [impact and integration guide](context-impact-integration.md) for arguments and scope.

A changed authorized slice may produce an immediate review candidate for each eligible consumer in the authorized inventory; coverage is limited to that inventory, and each context interprets independently. Do not copy a producer's conclusion, treat an unpinned legacy dependency as current, or propagate transitively before a new output actually changes. Preserve trace and handle fan-out continuations; a cycle/limit is a visible blocker, not permission to drop remaining work. A review disposition is reported evidence, not proof of fact freshness. Actual external facts require their own authorized observation and validity policy.

## 6. Optional wake

If the installation later adopts an external scheduler, it may call the bounded [context schedule advice](../context-schedules.md) using a declaration and context-scoped observation. A no-op needs no LLM. `eligible` is advice only: it never grants execution, installs a schedule, sends a message or proves a binding. The external adapter remains responsible for pause, real due times, atomic reservations, attempts, deduplication, capacity, interaction, effect receipts and reconciliation of uncertain outcomes. Previously paused schedules remain paused unless separately changed by the authorized operator.

## Stop and preserve

If current policy or the host binding changes, the source selection becomes unavailable, a review/gate is missing, or an external effect is uncertain, stop the dependent effect and retain its task ID, exact blocker and evidence. Do not turn the approved packet into a sandbox claim, use a new branch to bypass a denial, or call a prepared proposal installed. Public/private installation, restart, bundle replacement and rollback require their own qualified runbook and readback.
