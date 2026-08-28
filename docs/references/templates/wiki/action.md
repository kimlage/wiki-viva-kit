# Template - action

```yaml
---
page_id: action-example
page_type: action
title: "Action - example"
aliases:
  - Action example
tags:
  - wiki/action
  - status/pending
status: pending
action_state: open
action_state_history: []
next_action: "Describe the next executable or externally blocked step."
priority: normal
attention_basis: "Explain why this action deserves its declared priority."
owner_kind: unassigned
owner_ref: ""
created_at: YYYY-MM-DD
due_at: YYYY-MM-DD
blocked_by: []
context: system
visibility: private_self
updated_at: YYYY-MM-DD
stale_after_days: 30
sources_policy: evidencia_de_acao
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
moc_parent: memories/index.md
related_holons: []
roles: []
responsibilities: []
source_refs: []
claims: []
decisions: []
actions: []
evidence_refs: []
---
```

# Action - example

Runtime state (`action_state`): `open` | `in_progress` | `blocked` |
`waiting_human` | `done` | `cancelled`.

`status` may keep human/editorial wording during migration, but the cockpit,
overlays and reader consume the canonical `action_state`. Recurrence is a
cadence, not a runtime state. A blocked or waiting action must state the next
safe step. Blocker fields exist only while `action_state: blocked`. A completed
or cancelled action carries the matching terminal receipt plus `completed_at`,
and carries no `next_action` or stale blocker fields. The shared writer records
`completed_at` as the same offset-aware instant used by its transition receipt;
migrated historical pages may retain an honest day-precision ISO date when no
finer clock is known. `due_at` remains optional. `completion_receipt` belongs
only to `done`, while `cancellation_receipt` belongs only to `cancelled`; neither
may be pre-recorded.

Lifecycle writes use the shared `wiki_core.action_transition` boundary or the
local operator endpoint `/api/actions/transition`. The operator request is
bound to the page's exact `content_sha256` and appends a chained
`action_state_history` receipt. A direct Markdown/agent edit that changes
the semantic lifecycle state without that receipt is rejected by
`wiki_audit.py` at the PR gate. Equivalent legacy-to-canonical adoption remains
a permitted migration no-op. `/api/actions/run` is intentionally different: it
runs an allowlisted operator command card and does not change a domain action.

The current cockpit does not yet expose a direct transition control; this slice
ships the core/operator boundary and audit enforcement for future experience
packs and agent workflows. Legacy `state`, `status`, `State:` and `Estado:`
values remain readable and can be canonicalized through the same boundary, but
new targets must use the exact canonical vocabulary.

Deleting an existing action is not a lifecycle transition and is rejected by
the audit because it would discard the history. Cancel it with a
`cancellation_receipt` and retain the page. A pure file move/rename that keeps
the same `page_id` is a structural operation under the normal human PR gate;
the auditor follows that identity and still validates any lifecycle change.

| From | Allowed next states |
| --- | --- |
| `open` | `in_progress`, `blocked`, `waiting_human`, `done`, `cancelled` |
| `in_progress` | `blocked`, `waiting_human`, `done`, `cancelled` |
| `blocked` | `open`, `in_progress`, `waiting_human`, `cancelled` |
| `waiting_human` | `in_progress`, `blocked`, `done`, `cancelled` |
| `done` | terminal |
| `cancelled` | terminal |

> Illustrate by default: track the action's status as a table row, not loose
> prose. See the representation conventions in
> [obsidian-conventions.md](obsidian-conventions.md).

## Status

| Runtime state | Owner | Due | Next action | Blocker (if any) |
| --- | --- | --- | --- | --- |
| `open` |  | YYYY-MM-DD |  |  |

## Expected result

-

## Related

- Parent MOC:
- Decisions:
- Evidence:
