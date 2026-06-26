---
title: "Release notes - Wiki Viva v6.8.2"
page_id: release-wiki-viva-v6-8-2
page_type: release_notes
context: system
visibility: private_self
updated_at: 2026-06-26
stale_after_days: 90
sources_policy: release_notes
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
source_refs:
  - source-wiki-viva-kit-repo
---

# Release notes - Wiki Viva v6.8.2

Status: implemented in the open-source kit first, with synthetic tests.

Runtime anchor: `wiki_core.__version__ = "6.8.2"`.

## Changed

- The generated daily cockpit no longer writes `generated_from_commit` or
  `generated_from_branch` into the versioned page.
- The "Current state" section now tells agents to check live Git state and the
  PR before acting, instead of preserving branch/commit snapshots that become
  stale after merge.
- `stable_cockpit_view` still ignores legacy commit/branch fields and legacy
  "Compiled from" lines, so older pages fail only when deterministic cockpit
  content is actually stale or the page is intentionally regenerated.

## Why it matters

A versioned cockpit cannot reliably contain its own final commit hash, and a
proposal branch snapshot becomes misleading once the PR is merged. The cockpit
is the daily operational entry point, so its committed text should describe
deterministic memory state and direct the agent to verify live Git state, not
pretend that stale branch provenance is current.

## Validation

```sh
python3 -m pytest tests/test_operation_compile.py
python3 scripts/wiki_operation_compile.py --check
python3 scripts/wiki_audit.py --check
python3 -m pytest tests/
```
