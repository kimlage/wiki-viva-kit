---
page_id: system-wiki-coverage
page_type: source_catalog
context: system
visibility: private_self
updated_at: 2026-06-09
stale_after_days: 30
sources_policy: cobertura_de_contextos
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
---

# Wiki coverage by context

Updated on: 2026-06-09.

Tracks the state of each memory context declared in
[wiki.config.yaml](../../wiki.config.yaml). Replace the example row with the
contexts of your repo.

| Context | Coverage | Pending items | Risk | Gate |
| --- | --- | --- | --- | --- |
| System | method, ingestion process, contract, coverage, log, perception | evolve as the repo grows | low | human PR |
| Example | demonstration hub | replace with real contexts | low | human PR |

## Ontology

| Layer | State | Next evolution |
| --- | --- | --- |
| Contexts/hubs | one index hub per context in [memories/](../) | add contexts as needed |
| Decisions/actions | fed to the cockpit when they exist | create as real work happens |

## Related

- Method coverage: [methodology-coverage-v5.md](methodology-coverage-v5.md).
- Cockpit: [operations.md](../operations.md).
