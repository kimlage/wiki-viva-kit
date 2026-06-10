---
page_id: sistema-journal-2026-06-09-construcao-wiki
page_type: journal_entry
title: "Journal - building the living wiki without losing honesty"
aliases:
  - Wiki construction journal
tags:
  - wiki/percepcao
  - wiki/journal
  - status/active
status: active
context: sistema
visibility: private_self
updated_at: 2026-06-09
stale_after_days: 60
sources_policy: percepcao_pessoal_privada
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
status_epistemologico: percepcao
purpose: "Record the owner's perception during the living-wiki construction round, before it becomes canonical memory."
moc_parent: memorias/sistema/percepcao/index.md
related_pages:
  - memorias/sistema/cobertura-metodologia-v5.md
  - memorias/sistema/percepcao/mapa-relacoes-sistema-wiki.md
perception_policy:
  layer: perceptiva
  is_canonical_truth: false
  subjective_inputs_allowed: true
  preferred_outputs:
    - texto_livre
    - lista_de_tensoes
  accessibility:
    alt_text_required: true
    color_only_encoding_forbidden: true
    plain_language_summary_required: true
  promotion:
    requires_consent: true
    requires_anonymization: true
    target_visibility: private_reference
    gate: github_pr
---

# Journal - building the living wiki without losing honesty

Updated on: 2026-06-09.

> **Private** page (`visibility: private_self`) and **perception**, not canonical
> truth (`status_epistemologico: percepcao`). Nothing here becomes an insight or
> collective memory without explicit consent (see `## Promote?`).

## Plain-language summary

Personal note on what it was like to build the living-wiki methodology in this
round: what brought relief, where it got tight, and what I learned about my role
as the owner of the system.

## Entry

- Date and moment: 2026-06-09, during the roadmap consolidation round.
- Context: integrate score, gate, detectors, and the LLM pass that were turning
  into islands triggered only by manual CLI, and close that into a single
  orchestrator.
- State/mood: tense but optimistic focus; relief each time a gate starts to "bite".

## What became clear

- The bigger risk was not a lack of code, it was **code that exists but does not
  run in the flow**. The orchestrator (manifest -> chunks -> index -> pre-scan ->
  LLM package -> score) is what turned loose pieces into an organism.
- Honesty is worth more than coverage: I preferred to mark "partial/absent" with
  evidence rather than say "done" without real use. The two-dimensional status
  (code exists vs. is in use) was born from that tension.
- Privacy and operation do not fight: in a repo that is only mine, hiding my own
  data was pointless friction. Separating PII (welcome in private) from secret
  (always blocked) unlocked the memory without opening real risk.

## Where I felt tension

- Fear of overclaiming: the temptation to declare the perceptive layer "ready"
  just because the templates existed. This very page exists to undo that — it is
  real use, not a template.
- Pace vs. review: merging a PR too early while the CI was still in the queue
  produced a misleading "failure". I learned to wait for the real completion.

## Learning about my role

- My role is not "having done everything", it is keeping the system **alive and
  honest**: every capability with evidence of use, every gate biting, every PR
  reviewable by a human. I am the owner who protects the honesty of the gate, not
  the one who inflates the scoreboard.

## Promote? (consent)

- Do I want to promote anything from here? `yes`
- What exactly may be promoted: the learning "code that does not run in the flow
  is an island" and the idea of two-dimensional status — they become a note in the
  [method coverage](../cobertura-metodologia-v5.md) and a derived insight.
- Anonymization applied: `not` needed (private repo, no third parties).
- Target visibility after promotion: `private_reference`.
- Becomes which artifact: insight + methodology note.

## Related

- MOC: [index.md](index.md).
- Relationship map: [mapa-relacoes-sistema-wiki.md](mapa-relacoes-sistema-wiki.md).
- Coverage: [cobertura-metodologia-v5.md](../cobertura-metodologia-v5.md).
