---
page_id: perspective-artifacts-evidence
page_type: perspective
title: "Outputs and evidence perspective"
aliases:
  - Artifacts and evidence perspective
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
source_refs:
  - sources-wiki-viva-methodology
applies_to_source_types:
  - reference
  - document
  - repo
  - code_change
  - spreadsheet
concerns: "Owned artifacts, direct outputs, documents-as-evidence, metrics and observable state."
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

# Outputs and evidence perspective

## Concern

Which observable artifacts, outputs, documents or evidence should be preserved
as the exterior-individual trace of the root entity. Repositories belong here
only when they are treated as owned codebase/output/evidence; coordination tools
and workflow platforms belong to Q4.

## Quadrant

| Field | Value |
| --- | --- |
| Quadrant | `q2` |
| Inherits from root entity | `true` |
| Target obligation | `updated_or_no_change_reason` |

## Extraction Questions

- Which artifact, repository-as-output, document, report or metric appears?
- What does the artifact prove or fail to prove?
- Is this item output/evidence of the root holon, or is it a coordination
  platform/process that belongs to Q4?
- Which source/config page should own future refreshes?

## Target Pages

- Root entity, artifact, source, project and claim pages.

## Correspondence Rules

- Artifact evidence should back claims and should not replace root or hub
  synthesis.
- Do not classify Slack, Jira, Drive, CI, calendars, portals or other
  coordination platforms as Q2 unless the specific item is an exported
  artifact/evidence. The operating platform itself is Q4.
- The same file can carry Q2 evidence, Q3 interpretation and Q4 process context;
  classify the fact being extracted, not just the file extension.

## Inheritance Rules

- Applies by default to channels that carry documents, codebases as outputs,
  dashboards as evidence or other observable outputs.
