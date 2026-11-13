---
page_id: template-subagent-brief
page_type: operational_template
title: "Subagent brief"
aliases:
  - Subagent brief
  - Agent brief
tags:
  - wiki/template
  - wiki/subagent
  - status/template
status: template
context: system
visibility: private_reference
updated_at: YYYY-MM-DD
stale_after_days: 90
sources_policy: contrato_wiki_operacional
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
owner: {{owner_id}}
moc_parent: docs/references/templates/wiki/obsidian-conventions.md
related_pages:
  - docs/references/templates/wiki/page-contract.md
---

# Template - subagent brief

Complete this brief with references to the existing wiki. The brief and a
prepared context packet do not grant access or create another task record. See
the [delegation contract](../../guides/context-coordinators.md#delegation-contract).

## Objective

- Canonical repository, action ID and action page:
- Intended result and evidence required to call it complete:
- Base action revision and context packet hash (when a packet is used):

## Scope

- Sender and their role in this handoff:
- Intended recipient, their current role and the scope coordinator:
- Delegated work, existing owner/executor and permitted changes:
- Existing actor responsible for consolidation/publication after this slice:
- Existing task/run or contribution IDs to reconcile, if already assigned:

## Required wiki context

- Current approval, operational and ingestion policies, with page references:
- Granted authorization and its limits; any decision not yet authorized:
- Domain pages, source/configuration IDs and evidence to read:
- Destination pages and the existing ingestion/consolidation path:

Bind the complete protected task packet: canonical context ID, current approved
policy revision, content revision and packet digest. Read all mandatory rule
bodies and selected evidence; references, hashes or truncated samples are not
substitutes. Profiles preserve routing/history and never grant access. Mandatory
rules come from canonical context instructions/skills/templates; selected
cross-context evidence requires approved imports/exports. Do not construct a
handoff from legacy `common_context` or `context_pages`.
Resolve superseded instructions through the current policy, without treating
historical notes as new consent requirements or widening access.
On opening and resumption, distinguish a sender's description of their own
role from instructions to the recipient. It does not reassign the recipient;
only explicit direction from the scope coordinator or owner does so. Resolve
unclear sender or recipient identity from existing context before treating a
message as a role change. This template does not authenticate either identity.

## Capability check by the executor

| Required tool or service | Expected host, account and resource | Verified capability and evidence | Available or blocked |
| --- | --- | --- | --- |
| | | | |

The executing instance records its own check and time. Do not inherit a parent's
tools, account or GUI permissions. A read check proves only the tested access,
not write permission. Keep credentials out of the record. The context composer
continues to report `runtime_connected: false` and `execution_ready: false`;
this brief does not change runtime admission or those flags.

## May read

-

## May edit

-

## Must produce

- Result/patch and reproducible evidence, tied to the canonical action and base:
- Source/event references and destination updates required for consolidation:
- Applicable validations and independent review required by the current policy:

## Blocker and bounded recovery

- Affected step, exact missing context/capability or denied operation, and receipt:
- Applicable current instruction or reproducible failure and operation/limit:
- Classification: actual denial, unverified capability or agent-imposed restriction:
- Work that can continue independently:
- Attempt limit and changed precondition required for another attempt:
- Next responsible actor and existing question/event ID, if one exists:

Without an explicit retry budget, stop the affected attempt after recording the
blocker. Do not create repeated repair tasks for an unchanged denial or ask
again for consent already granted within scope. A new scope/access decision
uses the existing action conversation; a tool denial is not bypassed. Before
resuming, reconcile the existing action, event and task/run IDs, current
revisions, STOPs and other blockers. A timeout does not prove failure or justify
duplicating an external effect.
Reuse still-valid authorization after checking this instance's identity and
access; an offline execution limit alone does not forbid an authorized read.
For a required generated artifact, use the independently reviewed preparation
and final-gate order in the existing [delegation contract](../../guides/context-coordinators.md#delegation-contract).

## Must not do

- Do not revert changes made by other agents.
- Do not write outside the agreed scope.
- Do not persist tokens, cookies, passwords, access codes, credentials, or individualized secure links.

## Response format

- Canonical action and base/final revisions:
- Delegated delivery status and any consolidation/publication still assigned to another actor:
- Changed files:
- Evidence, source/event IDs and consolidated destination pages:
- Validations:
- Risks:
- Pending items, exact blockers and the condition for resuming:

## Acceptance criteria

- Accept the delegated slice when its agreed result and evidence are delivered
  within the permitted scope. A read-only or patch-only executor need not gain
  writer/publisher access to complete that slice.
- The named responsible actor integrates the result through the existing wiki
  ingestion/consolidation process, with provenance and destination references.
  Close the canonical action only after that integration and its completion
  criteria pass; accepting the delegated slice alone does not close it.
- Review and applicable gates satisfy the current repository policy.
- Remaining blockers stay visible on the same canonical action. No duplicate
  action, queue or separate memory was created to represent the handoff.

## Related

- MOC: [obsidian-conventions.md](obsidian-conventions.md)
- Page contract: [page-contract.md](page-contract.md)
