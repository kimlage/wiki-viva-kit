# Scripts

Command-line entry points for operating the wiki viva kit.

The scripts wrap deterministic behavior from [wiki_core](../wiki_core/README.md):
ingestion, audit, source registry, operation cockpit, quality reports, PR
summaries and format conversions. They do not call an LLM directly; model
reading remains delegated to the agent running the repo.

Use [wiki_audit.py](wiki_audit.py), [wiki_input_stage.py](wiki_input_stage.py),
[wiki_operation_compile.py](wiki_operation_compile.py) and
[wiki_pr_summary.py](wiki_pr_summary.py) as the default PR gate surface.

Use [wiki_quadrant_contract.py](wiki_quadrant_contract.py) when an external
consumer needs the canonical Wilber/AQAL `q1/q2/q3/q4` mapping without scraping
templates or historical proposals.
