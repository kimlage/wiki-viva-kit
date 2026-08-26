---
page_id: system-wiki-coverage
page_type: source_catalog
context: system
visibility: private_self
updated_at: 2026-08-26
stale_after_days: 30
sources_policy: cobertura_de_contextos
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
---

# Wiki coverage by context

Updated on: 2026-08-26.

Tracks the state of each memory context declared in
[wiki.config.yaml](../../wiki.config.yaml). Replace the example row with the
contexts of your repo.

| Context | Coverage | Pending items | Risk | Gate |
| --- | --- | --- | --- | --- |
| System | meta-wiki, source entity/recipe, ingestion, consolidation, contract, coverage, log and perception | no blocked public-kit source | low | human PR |
| Example | evergreen synthetic demonstration hub | consumer replaces or extends it with real contexts | low | human PR |

## Ontology

| Layer | State | Next evolution |
| --- | --- | --- |
| Contexts/hubs | one index hub per context in [memories/](../index.md) | add contexts as needed |
| Decisions/actions | fed to the cockpit when they exist | create as real work happens |
| Sources | one repository-local methodology source with a valid recipe and closed 2026-08-26 event | consumer wikis declare their own sources |

## Related

- Method coverage: [methodology-coverage-v5.md](methodology-coverage-v5.md).
- Cockpit: [operations.md](../operations.md).
