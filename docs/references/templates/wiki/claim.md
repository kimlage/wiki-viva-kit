# Template - claim

```yaml
---
page_id: claim-example
page_type: claim
title: "Claim - example"
aliases:
  - Claim example
tags:
  - wiki/claim
  - status/candidate
status: candidate
context: system
visibility: private_self
updated_at: YYYY-MM-DD
stale_after_days: 45
sources_policy: fonte_rastreavel
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
owner: {{owner_id}}
moc_parent: memories/index.md
related_holons: []
roles: []
responsibilities: []
source_refs: []
claims: []
# Incremental consolidation: claim versioning and conflict.
supersedes: []          # claim-... that this claim replaces
superseded_by: ""       # claim-... that replaced this one (reciprocal of supersedes)
conflicts_with: []      # claim-... in open conflict
conflict_resolution: "" # how the conflict was resolved (or why it remains open)
decisions: []
actions: []
evidence_refs: []
---
```

When an additional folder-bound RAW or repository source contributes to an
existing claim, its optional `folder_source_provenance` uses the
[v2 source-provenance schema](../../schemas/wiki-folder-source-provenance-v2.schema.json).
Existing singleton projections and requirements remain unchanged; each added
entry is linked to its exact source requirement and needs normal review. This
metadata does not prove a read or grant access.

# Claim - example

Status: `fato` | `percepcao` | `hipotese` | `insight` | `proposta` | `decisao`.

## Statement

-

## Related

- Parent MOC:
- Source:
- Evidence:
- Decisions:

## Conflicts and ambiguities

- Record here the conflict with other claims (linked), the ambiguity
  observed, and the resolution (or the decision to keep the conflict open).
