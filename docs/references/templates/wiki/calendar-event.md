# Template - calendar event

Calendar event as an entity (lives in `calendar/` in memory). Links its attendees
(person pages), the associated meeting (when there is one) and the source (the
invite). The connector that fetches the event is the AGENT/skill's job, not the
toolkit's.

```yaml
---
page_id: calendar-event-YYYY-MM-DD-topic
page_type: calendar_event
title: "Event - topic"
aliases:
  - Event topic
tags:
  - wiki/event
  - status/active
status: active
context: example
visibility: private_self
updated_at: YYYY-MM-DD
stale_after_days: 30
sources_policy: source_and_impact
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
owner: person-organizer
starts_at: "YYYY-MM-DDThh:mm"
ends_at: "YYYY-MM-DDThh:mm"
attendees: []            # person-... ids; linked in the body
related_holons: []
roles: []
responsibilities: []
source_refs: []          # source-... (invite/calendar)
claims: []
decisions: []
actions: []
evidence_refs: []
# config_ref: <ingestion-rules page for the calendar source>   # optional
---
```

# Event - topic

Starts: YYYY-MM-DDThh:mm. Ends: YYYY-MM-DDThh:mm.

## Attendees

Each attendee is a link to that person's page (see
[memories/people/index.md](../../../../memories/people/index.md)).

| Person | Confirmed |
| --- | --- |
|  |  |

## Related

- The associated meeting (when there is one) and the source (the invite) as
  links.
