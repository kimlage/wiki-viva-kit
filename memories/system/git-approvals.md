---
page_id: system-git-approvals
page_type: operational_rule
context: system
visibility: private_self
updated_at: 2026-06-09
stale_after_days: 90
sources_policy: contrato_wiki_operacional
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
---

# Approvals via Git and PR

Updated on: 2026-06-08

The GitHub PR is the human approval flow of the simple operational wiki.

## Branches

The prefix is `wiki/` -- tool-neutral: any agent (Claude, Codex,
Gemini, or another) uses the same convention, without forcing a tool name into the
branch or into the merge commits.

- Standard: `wiki/ingest-YYYY-MM-DD-<topic>`.
- System adjustments: `wiki/system-<topic>`.
- Small fixes: `wiki/fix-<topic>`.

Do not create parallel branches for the same page when a proposal already exists.
Update the existing branch, rebase against `main`, and mark old proposals
as `superseded`.

## Proposal states

| State | Meaning | Next transition |
| --- | --- | --- |
| `created` | proposal created with source and context | `compiling` |
| `compiling` | agent creating manifests, events, quadrants, and diff | `ready_for_review` |
| `ready_for_review` | local validations ready for PR | `needs_human_gate` |
| `needs_human_gate` | awaiting human review | `approved`, `rejected`, or `superseded` |
| `approved` | approved in the PR | `published` |
| `published` | consolidated into `main` | `archived` when obsolete |
| `superseded` | replaced by a more recent proposal | `archived` |
| `rejected` | rejected for scope, risk, or error | `archived` |
| `archived` | history preserved | end |
| `no_ingest` | evaluated and kept out of the wiki | `archived` |

## Default gate

- `gate_id`: `github_pr_human_review`.
- `approver_policy`: the repo owner or person explicitly responsible for the context.
- `quorum`: one human approver.
- `sla_hours`: 72 hours by default, adjustable by operational urgency.
- `superseded_policy`: a newer proposal for the same page/context must
  mark the previous one as `superseded` before merge.

## Suggested labels

- `wiki`
- `privacy-review`
- `system`
- `<context>` (one per context declared in the config)

## PR checklist

- [memories/](../index.md) contains actionable synthesis.
- [docs/](../../docs/README.md) did not become the main memory.
- Relevant personal data (PII) was extracted when useful (private repo).
- No access secret, individualized secure link, or full dump without
  criteria was copied.
- [memories/system/log.md](log.md) was updated.
- Local paths cited in the diff are real Markdown links.
- [scripts/wiki_audit.py](../../scripts/wiki_audit.py) --check passed.
- `git diff --check` passed.

## PR draft vs ready

Open as a draft when there is a privacy risk, financial classification,
change of a living source, scope doubt, or broad consolidation. Make it ready
only after the local audit and review of the diff.

## Merge

`main` represents the approved wiki. Merge should only happen after human review
of the complete package: sources, synthesis, risks, validations, and pending items.
