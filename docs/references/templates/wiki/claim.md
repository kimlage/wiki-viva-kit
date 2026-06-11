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

# Claim - example

Status: `fato` | `percepcao` | `hipotese` | `insight` | `proposta` | `decisao`.

## Statement

-

## Related

- Source:
- Evidence:
- Decisions:

## Conflicts and ambiguities

- Record here the conflict with other claims (linked), the ambiguity
  observed, and the resolution (or the decision to keep the conflict open).
