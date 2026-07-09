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

Use [wiki_web_snapshot.py](wiki_web_snapshot.py) to generate the local/static
JSON read model for the web cockpit, and [wiki_web_server.py](wiki_web_server.py)
to run the localhost-only operator API with allowlisted commands.
Use [wiki_web_deploy_bundle.py](wiki_web_deploy_bundle.py) when one
implementation needs portable static deploy inputs plus a deployment proof
without choosing Vercel, GCP or any other host inside the core kit.

The v8 downstream release flow is read-only by default:

- [wiki_upgrade_inventory.py](wiki_upgrade_inventory.py) validates the
  public-safe consumer/wave inventory.
- [wiki_upgrade_preflight.py](wiki_upgrade_preflight.py) checks the pinned
  release, consumer branch/worktree, current gate receipts, portable drift,
  snapshot, overrides and privacy/redaction without copying files.
- [wiki_upgrade_report.py](wiki_upgrade_report.py) validates allowlisted import
  evidence and compiles deterministic JSON/Markdown migration reports with
  gates, visual QA and rollback.

The package and runbook live under
[docs/references/upgrades/wiki-viva-v8](../docs/references/upgrades/wiki-viva-v8/upgrade-package.yaml)
and
[wiki-viva-v8-downstream-upgrade.md](../docs/references/guides/wiki-viva-v8-downstream-upgrade.md).
