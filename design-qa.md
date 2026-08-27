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
  - mobile registry remains visible before the source detail
  - Playwright console: 0 errors
- remaining external limitation: the current operator exposes no live Google Drive connector to Codex or Claude. The UI reports that boundary and never claims a live collection occurred; a real source job will populate the monitor when the connector is available.

final result: pass with external connector limitation
