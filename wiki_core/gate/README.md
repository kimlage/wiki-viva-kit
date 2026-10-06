# Gate Core

Deterministic proposal-gate state machine used by the wiki CLIs.

The package validates approved proposal states. PR review under the repository's
[AGENTS.md](../../AGENTS.md) remains the boundary between generated ingestion
output and committed memory. The legacy `needs_human_gate` state is retained;
its name does not require or prove human review.
