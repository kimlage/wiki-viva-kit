# Template - page contract

```yaml
---
page_id: example
page_type: context_hub
title: "Human title"
aliases:
  - Short page name
  - Alternative name for wikilink
tags:
  - wiki/context
  - context/system
  - status/active
status: active
context: system
context_id: holon-system
parent_context_id:
audience:
  - private_self
visibility: private_self
purpose: "Why this page exists."
updated_at: YYYY-MM-DD
stale_after_days: 30
sources_policy: fontes_vivas_primeiro
allowed_sources:
  - markdown_memory
  - source_manifest
  - human_note
quadrants_required:
  - exterior_individual
  - exterior_collective
claims_policy:
  require_source: true
  allow_uncertain_claims: true
  uncertainty_label_required: true
compilation_policy:
  update_mode: diff_proposal
  merge_pending_updates: true
  supersede_old_proposals: true
gate: github_pr
gates:
  - gate_id: page_steward_approval
    required_for:
      - canonical_change
      - visibility_change
    approvers:
      - role: wiki_steward
    quorum: one
    sla_hours: 72
agents_allowed:
  - wiki-memory-router
  - wiki-ingestion-agent
  - wiki-operation-compiler
outputs_allowed:
  - markdown_page
  - timeline_entry
  - insight_candidate
  - action_candidate
sensitive_data_policy: private_sensitive_allowed
owner: {{owner_id}}
related_holons: []
roles: []
responsibilities: []
source_refs: []
source_counts:
  live_sources: 0
  references: 0
  derived_artifacts: 0
claims: []
decisions: []
actions: []
evidence_refs: []
moc_parent: memories/index.md
related_pages: []
backlinks_expected: []
attachment_policy: "Attachments live in data/raw, data/derived or docs/references with a Markdown link."
---
```

# Title

Updated at: YYYY-MM-DD

## Contract

- Purpose:
- Audience:
- Accepted sources:
- Required quadrants:
- Claims policy:
- Compilation policy:
- Gate:
- Parent MOC:
- Related pages:
- Expected backlinks:
- Attachment policy:
- Include freely (private personal repo): personal data/PII -- CPF, CNPJ,
  names, values, dates, counterparties, addresses, documents, decisions and
  financial/professional details. On a private page they raise no warning; redact only
  before exporting/publishing.
- Never include (anywhere): tokens, cookies, passwords, access codes,
  credentials, individualized secure links or full dumps without criteria.
- Links: every local path cited must be a clickable Markdown link.
- Obsidian: follow [obsidian-conventions.md](obsidian-conventions.md); aliases and
  tags help the graph/Dataview, but do not replace real Markdown links.

## Consolidated content

-

## Related

- MOC:
- Related pages:
- Expected backlinks:

## Pending items

-
