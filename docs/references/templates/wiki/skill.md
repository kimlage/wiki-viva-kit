# Template - skill

A SKILL as a wiki page — the visible, machine-readable contract that pairs with
a matching skill playbook and a `types.<t>.skills` registration. A
skill NEVER executes directly: the runner composes a brief and hands it to the
approval ladder (PR-gated). Human skills = capabilities (q2); agent skills =
automation (q4).

```yaml
---
page_id: {{page_id}}
page_type: skill
title: "{{title}}"
context: {{context}}
visibility: private_self
updated_at: {{updated_at}}
stale_after_days: {{stale_after_days}}
moc_parent: memories/system/skills/index.md
skill_type: agent            # human | agent
execution: brief             # checklist | brief | local_operator
playbook_ref: ""             # .skills/<name>/SKILL.md
model_hint: any
writes: proposal_branch_only
inputs: []
outputs: []
gates: []
---
```

# {{title}}

## Purpose

What this skill does and when it runs.

## Contract

- Inputs it needs; outputs it produces.
- What it must never do (writes stay proposal-branch-only; no secrets).

## Playbook

1. Step-by-step, or a link to the matching skill playbook under the skills root.

## Related

- Parent MOC: [memories/index.md](../../../../memories/index.md) (a real skill page sets its own skills index)
