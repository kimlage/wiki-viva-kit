---
page_id: people-index
page_type: ontology_index
title: "People - registry"
context: example
visibility: private_self
updated_at: 2026-07-10
stale_after_days: 45
moc_parent: memories/index.md
parent_projection:
  quadrant: q3
  sub_lens: pessoas
  reason: "The people registry is the relational doorway to real person pages."
collection:
  member_types: [person]
  contexts: ['*']
sources_policy: memoria_consolidada
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
owner: ""
related_holons: []
roles: []
responsibilities: []
source_refs: []
claims: []
decisions: []
actions: []
evidence_refs: []
---

# People - registry

This is the people registry: one page per person, carrying their contacts and a
**sourced perspective** (viewpoint, positions, priorities over time, each
supported by a linked claim/decision). Every mention of a person elsewhere in
the wiki must link to that person's page here.

The per-person template is
[person.md](../../docs/references/templates/wiki/person.md).

## People

The public kit intentionally ships this canonical collection with no personal
member pages. Downstream private wikis populate it with real `page_type: person`
pages; the empty table here is a privacy-safe starting state, not a failed query.

| Person | Role in the wiki | Page |
| --- | --- | --- |
|  |  |  |

## Policy

- A person page is private by default.
- This repo is personal and private: sensitive personal data may enter the wiki
  when it is needed for CRM, relational context, decision, document, procedure,
  operational memory, or reconciliation.
- Public or professional profiles use a reviewed synthesis; the private page may
  keep raw feedback or internal detail when operationally useful.
- Never record credentials, tokens, cookies, passwords, access codes,
  individualized secure links, or full dumps without curation.
