---
page_id: template-operational-pass-closeout-wiki
page_type: operational_template
title: "Operational pass closeout"
aliases:
  - Operational pass closeout
  - Source/action closeout
tags:
  - wiki/template
  - wiki/operations
  - status/template
status: template
context: system
visibility: private_reference
updated_at: YYYY-MM-DD
stale_after_days: 90
sources_policy: operational_pass_evidence_and_gates
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
owner: {{owner_id}}
moc_parent: docs/references/templates/wiki/obsidian-conventions.md
related_pages:
  - docs/references/templates/wiki/operation.md
  - docs/references/templates/wiki/pr-checklist.md
  - memories/system/wiki/daily-operation.md
---

# Template - operational pass closeout

Use this report after a source/action consolidation round. It is not the
canonical memory; it is the auditable closeout that proves what the round
actually changed, what stayed blocked and which gates were run.

## Scope

- Plan / prompt / issue:
- Operational pass:
- Cockpit:
- Source registry:
- Related context hubs:

## Requirement Matrix

| Requirement | Evidence | State |
| --- | --- | --- |
| Shared toolkit/core updated first, when required. |  |  |
| New toolkit behavior applied to this repo. |  |  |
| Sources classified by state. |  |  |
| Actions compiled with owner, priority or blocker. |  |  |
| Pending decisions linked to the actions they block. |  |  |
| Context hubs updated with dense synthesis, not only links. |  |  |
| Public/private boundary checked. |  |  |
| Quality and ingestion closure inspected. |  |  |

## Live Sources Left Open

Do not claim completion for a source that was not opened or could not be read
back. Convert it into an explicit action, decision or blocked source row.

| Source / front | Why it remains open | Page carrying the next step |
| --- | --- | --- |
|  |  |  |

## Quality And Compression Evidence

| Evidence | Result |
| --- | --- |
| [wiki_audit.py](../../../../scripts/wiki_audit.py) with `--check` |  |
| [wiki_page_graph.py](../../../../scripts/wiki_page_graph.py) with `--check --impact --base <reviewed-base-sha>` |  |
| [wiki_quality_report.py](../../../../scripts/wiki_quality_report.py) with `--check` |  |
| [wiki_consolidate.py](../../../../scripts/wiki_consolidate.py) with `--check` |  |
| [wiki_operational_pass.py](../../../../scripts/wiki_operational_pass.py) with `--check` |  |
| [wiki_operation_compile.py](../../../../scripts/wiki_operation_compile.py) with `--check` |  |
| `git diff --check` |  |

## Operational Conclusion

State the boundary plainly:

- Closed:
- Still open:
- Owner decision required:
- Next safe action:

Completion means the wiki now knows where the next action belongs and what
would prove it. It does not mean a live source was read when access, owner
approval or current readback was missing.
