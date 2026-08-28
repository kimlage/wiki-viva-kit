# Wiki Viva v8.1.3

Released on 2026-08-28.

This downstream-safety patch moves the canonical standalone source-workspace
route contract into `apps/wiki-cockpit/README.md`, a kit-managed file shared by
public and private consumers. Its regression gate now validates that managed
document instead of assuming a consumer's private root README belongs to the
kit.

The canonical routes remain `/w?view=sources&dock=source` for an operator-backed
wiki and `/demo/w?view=sources&dock=source` for the synthetic public demo.
