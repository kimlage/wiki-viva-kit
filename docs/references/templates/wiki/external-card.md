# Template - external card (Jira/ticket)

External-tool card (Jira, GitHub issue, Trello, ...) as an entity (lives in
`cards/` in memory). Links its owner (the assignee person), a decision/action and
the source. The connector that fetches the card is the AGENT/skill's job, not the
toolkit's.

```yaml
---
page_id: external-card-JIRA-1234
page_type: external_card
title: "Card - JIRA-1234"
aliases:
  - JIRA-1234
tags:
  - wiki/card
  - status/active
status: active
context: example
visibility: private_self
updated_at: YYYY-MM-DD
stale_after_days: 30
sources_policy: source_and_impact
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
owner: person-assignee
card_tool: jira          # jira | github | trello | ...
card_id: JIRA-1234
card_status: in_progress
card_url: ""             # external link (never version an access secret)
related_holons: []
roles: []
responsibilities: []
source_refs: []
claims: []
decisions: []
actions: []
evidence_refs: []
# config_ref: <ingestion-rules page for this board's source>   # optional
---
```

# Card - JIRA-1234

Tool: jira. Status: in_progress. External URL: link.

## Summary

- What the card asks for and its current status.

## Related

| Relation | Item |
| --- | --- |
| Owner (person) |  |
| Decision |  |
| Action |  |
| Source |  |

The owner is a link to that person's page (see
[memories/people/index.md](../../../../memories/people/index.md)).
