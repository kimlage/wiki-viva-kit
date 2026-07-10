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
safe step; a completed/cancelled action must carry its receipt.
`due_at`, `completed_at`, `completion_receipt` and `cancellation_receipt` are
optional and should be present only when the corresponding fact exists.

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
