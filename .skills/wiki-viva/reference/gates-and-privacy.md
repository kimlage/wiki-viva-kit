# Gates and privacy — keeping the wiki honest

The wiki's claims about freshness, coverage and traceability require evidence,
not prose alone. For this kit, [AGENTS.md](../../../AGENTS.md) defines the
mandatory local privacy and integrity audits and diff check. Select additional
local tests and deterministic checks for the actual change; normal public CI
runs the configured suites in [.github/workflows/wiki.yml](../../../.github/workflows/wiki.yml).
Consumers retain their own applicable gate and review policies.

## The honesty gates

| Gate | What it verifies | Command |
| --- | --- | --- |
| Contract audit | Frontmatter, clickable local links, secrets blocked everywhere, PII at the public boundary, cockpit, ingestion events with quadrants, gate state, visibility promotion, LLM-pass gate, log update | [wiki_audit.py](../../../scripts/wiki_audit.py) `--check` |
| Methodology coverage | Presence **and content** of the method (pages, templates, scripts, config), real use of the perceptive layer, an executed LLM pass (not a plan) | [wiki_check_methodology_coverage.py](../../../scripts/wiki_check_methodology_coverage.py) `--check` |
| Cockpit freshness | The cockpit page equals a recompile at HEAD (deterministic view) | [wiki_operation_compile.py](../../../scripts/wiki_operation_compile.py) `--check` |
| Input stage freshness | The generated root/channel/source staging page equals a recompile at HEAD | [wiki_input_stage.py](../../../scripts/wiki_input_stage.py) `--check` |
| Source registry freshness | Canonical source registry equals source page frontmatter | [wiki_source_registry.py](../../../scripts/wiki_source_registry.py) `--check` |
| Consolidation closed | Ingesting = integrating: a deep-read-complete source needs its event and at least one non-source `consolidated_into` target; each non-source target references the source back, source identity targets stay acyclic, and candidate claims are linked or explicitly waived (`sem_claim`) | [wiki_consolidate.py](../../../scripts/wiki_consolidate.py) `--check` + [wiki_audit.py](../../../scripts/wiki_audit.py) `--check` |
| Quality and hierarchy | Dense pages, low repetition, closed events, operational coverage and relation pages routed through `moc_parent`/parent hubs when configured | [wiki_quality_report.py](../../../scripts/wiki_quality_report.py) `--check` |
| Tests | The deterministic core behaves within the selected test scope | Focused tests locally as applicable; full suite in normal public CI |

Useful audit modes:

- `--public-export --check` — pre-publication: PII becomes an error on **any**
  page, not just public ones. Run this before exporting anything publicly.
- `--strict-local` — requires that links to gitignored derived/raw artifacts
  actually exist on disk.

Qualify a gate's complete read scope before execution. A denied or unqualified
required gate remains blocked, not passed; a candidate policy cannot authorize
its own review. Fix the cause of a failing gate without weakening it. A passing
result establishes only the scope actually checked.

## Privacy — two independent axes

```mermaid
flowchart TD
    item["Something in a page"] --> q1{"Access secret?<br/>token / password / key / cookie"}
    q1 -->|yes| block["Blocked everywhere — never versioned"]
    q1 -->|no| q2{"Personal data (PII)?"}
    q2 -->|no| ok["Fine"]
    q2 -->|yes| q3{"Public boundary?<br/>public page / --public-export"}
    q3 -->|no| okpriv["Welcome on private pages — no warning"]
    q3 -->|yes| blockpub["Blocked at the public boundary"]
```

- **Access secrets** — always blocked, in any file, by the detectors and the
  auditor. The ingestion pre-scan blocks them at the origin (exit `2`).
- **Personal data (PII)** — names, amounts, counterparties, tax ids: welcome on
  private pages (that is the point of operational memory); blocked only at the
  public boundary. Detail: the privacy page in the meta-wiki (routed from
  [AGENTS.md](../../../AGENTS.md)) and
  [wiki-privacy-publication](../../wiki-privacy-publication/SKILL.md).

When material crosses its intended privacy boundary, remove the exposed content
from history and retained surfaces under the owner's control, not only the current
files. Preserve legitimate work and coordinate affected refs, checkouts and
their owners. Request provider removal where retained pull-request refs, cached
views or other provider-controlled copies require it. Track the incident without
reproducing the data in public records; verify old object accessibility and
derived surfaces. Do not claim complete removal while copies remain accessible
or a provider response is pending. Clones and external retention may be outside
the owner's control; record those limits and follow-up responsibilities.

## The gate state machine (proposals)

Proposals move through explicit states; transitions are recorded in
`gate_history`. The exact states and edges are documented (and enforced) in the
gates-and-audit page of the meta-wiki (routed from
[AGENTS.md](../../../AGENTS.md)); use [wiki_gate.py](../../../scripts/wiki_gate.py)
to transition, and never edit `gate_state` by hand.
