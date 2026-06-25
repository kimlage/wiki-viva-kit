# Template - meeting

Meeting as a first-class entity (lives in `meetings/` in memory). Links its
participants (person pages), decisions, actions and the source. Every mention of
a participant in the body must be a link to that person's page. The live
connector that fetches the meeting is the AGENT/skill's job, not the toolkit's.

```yaml
---
page_id: meeting-YYYY-MM-DD-topic
page_type: meeting
title: "Meeting - topic"
aliases:
  - Meeting topic
tags:
  - wiki/meeting
  - status/active
status: active
context: example
visibility: private_self
updated_at: YYYY-MM-DD
stale_after_days: 60
refresh_policy: event_driven
refresh_cadence_days: 7
# next_refresh_at: YYYY-MM-DD  # ideally within 2 days after the meeting if decisions/actions exist
# refresh_trigger: "review when there is a follow-up, open action, or new minutes"
sources_policy: normalized_event_with_quadrants
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
owner: person-organizer
moc_parent: memories/index.md
participants: []          # person-... ids; each one linked in the body
related_holons: []
roles: []
responsibilities: []
source_refs: []           # source-... (recording, minutes, invite)
claims: []
decisions: []             # decision-... made in the meeting
actions: []               # action-... that came out of it
evidence_refs: []
# config_ref: <ingestion-rules page for the meeting source>   # optional
---
```

# Meeting - topic

Date: YYYY-MM-DD. Source: link to the recording/minutes/invite.

Freshness: if the meeting still has open actions, review within 7 days; if it
just happened, set `next_refresh_at` within 2 days so decisions, actions, claims
and source links do not drift.

## Participants

Each participant is a link to that person's page (see
[memories/people/index.md](../../../../memories/people/index.md)).

| Person | Role in the meeting |
| --- | --- |
|  |  |

## Agenda and discussion

- (topic) — who said what; tie back to claims/decisions.

## Decisions and actions

| Type | Item | Owner | Link |
| --- | --- | --- | --- |
| Decision |  |  |  |
| Action |  |  |  |

## Related

- Parent MOC:
- Source:
- People:
