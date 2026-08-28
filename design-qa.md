# Design QA — Source operations workspace

- visual references: approved option 1 (registry + selected source) and option 3
  (source-scoped execution monitor), kept outside the public repository
- implementation evidence: Playwright captures were reviewed against realistic
  private-consumer data but remain outside this public repository
- viewport reviewed: desktop 1440x1000 and responsive 768x900
- comparison performed: yes — both references and the final implementation states were inspected together in one visual comparison
- alignment:
  - self-contained 2D source registry and selected-source workspace, with product navigation kept outside the source actions
  - explicit Records, Update, Configure and History tabs
  - deterministic inventory before contextual work
  - source-scoped execution monitor with status, steps, cancel action and safe log tail when a job exists
  - real empty and blocked states instead of simulated executions
- intentional differences from the mocks:
  - the implementation keeps the existing Wiki Viva design system and icon library
  - real source metadata and privacy-safe labels replace illustrative provider artwork
  - monitoring is embedded in Update rather than promoted to a separate product perspective
- functional/visual result:
  - covered and intentionally excluded records are not labelled as never ingested
  - one-shot, on-demand and event-driven sources do not become stale from elapsed time
  - the registry can be expanded or collapsed, canonical source titles remain unchanged in data, and the presentation removes generic source prefixes
  - semantic platform/type icons, readable names, source kinds and record counts identify each source without relying on repeated `Source -` text
  - authorization is always visible and distinguishes no-credential, configured pointer, ready connector, verified live access and required action
  - the update panel adapts to deterministic connector, deterministic script, agent connector and manual-export routes
  - script routes require an authorized RAW path before their plan can be checked; connector routes never ask for a fake RAW path
  - mobile registry remains visible before the source detail
  - Playwright console: 0 errors
- integration boundary: the public kit describes the route and authorization contract without claiming that a provider is available. Consumer repositories can add deterministic adapters, and live access is only reported after a successful preview.

final result: pass with explicit update and authorization contracts
