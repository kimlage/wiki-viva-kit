---
page_id: perspective-artifacts-evidence
page_type: perspective
title: "Artifacts and evidence perspective"
aliases:
  - Artifact lens
  - Evidence lens
tags:
  - wiki/perspective
  - status/active
status: active
context: system
visibility: private_self
updated_at: 2026-06-25
stale_after_days: 90
sources_policy: perspective_contract
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
applies_to_source_types:
  - reference
  - document
  - repo
  - code_change
  - spreadsheet
concerns: "Artifacts, repositories, documents, outputs, evidence and observable state."
extracts:
  - artifacts
  - repositories
  - documents
  - evidence
  - metrics
target_page_types:
  - root_entity
  - artifact
  - source
  - project
  - claim
prompt_profile: perspective_artifacts_evidence
quadrant: q2
inherits_from_root: true
target_obligation: updated_or_no_change_reason
moc_parent: memories/system/perspectives/index.md
related_pages:
  - memories/system/perspectives/index.md
---

# Artifacts and evidence perspective

## Concern

Which observable artifacts, outputs, repositories, documents or evidence should
be preserved as part of the operational model.

## Quadrant

| Field | Value |
| --- | --- |
| Quadrant | `q2` |
| Inherits from root entity | `true` |
| Target obligation | `updated_or_no_change_reason` |

## Extraction Questions

- Which artifact, repository, document, report or metric appears?
- What does the artifact prove or fail to prove?
- Which source/config page should own future refreshes?

## Target Pages

- Root entity, artifact, source, project and claim pages.

## Correspondence Rules

- Artifact evidence should back claims and should not replace root or hub
  synthesis.

## Inheritance Rules

- Applies by default to channels that carry documents, repos, dashboards or
  other observable outputs.
