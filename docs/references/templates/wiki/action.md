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
context: system
visibility: private_self
updated_at: YYYY-MM-DD
stale_after_days: 30
sources_policy: evidencia_de_acao
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
owner: {{owner_id}}
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

State: `pending` | `in_pr` | `completed` | `blocked` | `recurring`.

> Illustrate by default: track the action's status as a table row, not loose
> prose. See the representation conventions in
> [obsidian-conventions.md](obsidian-conventions.md).

## Status

| State | Owner | Due | Last update | Blocker (if any) |
| --- | --- | --- | --- | --- |
| `pending` |  | YYYY-MM-DD | YYYY-MM-DD |  |

## Expected result

-

## Related

- Parent MOC:
- Decisions:
- Evidence:
