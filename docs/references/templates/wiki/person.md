# Template - person

Person page: contacts, roles, and the person's **perspective** (viewpoint,
positions, priorities) over time. Single purpose — heavy ingestion rules, when
they exist, live on a config page linked via `config_ref`. Every mention of this
person on another page must be a link back here.

```yaml
---
page_id: person-example
page_type: person
title: "Person - example"
aliases:
  - Example person
tags:
  - wiki/person
  - status/active
status: active
context: example
visibility: private_self
updated_at: YYYY-MM-DD
stale_after_days: 45
sources_policy: memorias_consolidadas
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
owner: person-example
contacts:
  email: ""
  phone: ""
  handles: []
related_holons: []
roles: []
responsibilities: []
source_refs: []
claims: []
decisions: []
actions: []
evidence_refs: []
# config_ref: <ingestion-rules page for this person/source>   # optional, single purpose
---
```

# Person - example

## Contacts

| Channel | Value |
| --- | --- |
| Email |  |
| Phone |  |
| Handles |  |

## Profiles

-

## Roles and responsibilities

- Role in a holon, with a link to the role page and the holon page.

## Perspective

The person's viewpoint/positions, with sources. Each statement links the
claim/decision that supports it (without that link it becomes an orphan title).
Update this when the perspective changes.

- (position) — supported by a linked claim/decision.

## Privacy boundaries

- Contact data is PII: welcome on a private page; redact only before exporting.

## Related

- MOC: [memories/people/index.md](../../../../memories/people/index.md)
- Roles:
- Responsibilities:
