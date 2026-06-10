# Template - journal (private perceptual entry)

```yaml
---
page_id: template-journal
page_type: journal_entry
title: "Journal - perceptual entry"
aliases:
  - Journal
  - Diary
  - Journal entry
tags:
  - wiki/template
  - wiki/percepcao
  - wiki/journal
  - status/template
status: template
context: sistema
visibility: private_self
purpose: "Record perception, feeling, tension, and personal learning before it becomes collective memory."
owner: {{owner_id}}
updated_at: YYYY-MM-DD
stale_after_days: 30
status_epistemologico: percepcao
moc_parent: memorias/index.md
related_pages:
  - docs/referencias/templates/wiki/insight.md
  - docs/referencias/templates/wiki/page-contract.md
perception_policy:
  layer: perceptiva
  is_canonical_truth: false
  subjective_inputs_allowed: true
  preferred_outputs:
    - texto_livre
    - lista_de_tensoes
    - nota_de_humor
  accessibility:
    alt_text_required: true
    color_only_encoding_forbidden: true
    plain_language_summary_required: true
  promotion:
    requires_consent: true
    requires_anonymization: true
    target_visibility: private_reference
    gate: github_pr
source_counts:
  live_sources: 0
  references: 0
  derived_artifacts: 0
attachment_policy: "Optional attachments in data/raw with a Markdown link; never tokens, passwords, or credentials."
---
```

# Journal - perceptual entry

Updated on: YYYY-MM-DD

> This page is **private** (`visibility: private_self`). It is perception, not
> canonical truth (`status_epistemologico: percepcao`). Nothing here becomes an
> insight or collective memory without explicit consent and anonymization (see
> `## Promote?`).

## Entry

- Date and moment:
- Context (what was happening):
- State/mood:

## What became clear

-

## Where I felt tension

-

## Learning about my role

-

## Promote? (consent)

Promotion turns private perception into shareable knowledge. It only
happens with active consent + anonymization.

- Do I want to promote anything from here? `yes` | `no`
- What exactly can be promoted (a slice, not the whole entry):
- Anonymization applied (names/details removed or encrypted): `yes` | `no`
- Target visibility after promotion: `private_reference`
- Promotion gate: PR on GitHub
- Becomes which artifact: insight | claim | context note

## Related

- MOC: [index.md](../../../../memorias/index.md)
- Derived insight (if any): [insight.md](insight.md)
- Conventions: [obsidian-conventions.md](obsidian-conventions.md)
