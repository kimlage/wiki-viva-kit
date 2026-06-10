---
page_id: system-methodology-coverage-v5
page_type: source_catalog
title: "Living wiki methodology coverage"
aliases:
  - Methodology coverage
tags:
  - wiki/coverage
  - wiki/methodology
  - status/active
status: active
context: system
visibility: private_self
updated_at: 2026-06-09
stale_after_days: 30
sources_policy: metodologia_e_implementacao
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
purpose: "Coverage matrix: what the kit implements of the living wiki methodology."
moc_parent: memories/index.md
related_pages:
  - memories/sources/wiki-viva-methodology-v5.md
  - memories/system/ingestion-process.md
---

# Living wiki methodology coverage

Updated on: 2026-06-09.

This matrix tracks what the kit implements of the
[methodology](../sources/wiki-viva-methodology-v5.md).

| Component | Status | Evidence |
| --- | --- | --- |
| Per-repo configuration | implemented | [wiki.config.yaml](../../wiki.config.yaml) (repo_id, owner, contexts, policy) |
| Reusable core | implemented | [wiki_core/](../../wiki_core/) (config, chunks, detectors, gate, index, llm, score, insight) |
| Deterministic manifest | implemented | [scripts/wiki_extract_source_manifest.py](../../scripts/wiki_extract_source_manifest.py) |
| Text and chunk extraction | implemented | [scripts/wiki_extract_text.py](../../scripts/wiki_extract_text.py) |
| Local index (FTS) | implemented | [scripts/wiki_build_index.py](../../scripts/wiki_build_index.py) |
| Ingestion orchestrator | implemented | [scripts/wiki_ingest.py](../../scripts/wiki_ingest.py) |
| Contextual LLM pass (gate) | implemented | [scripts/wiki_llm_context_pass.py](../../scripts/wiki_llm_context_pass.py); delegated to the agent |
| Proposal gate + rebase | implemented | [wiki_core/gate/](../../wiki_core/gate/), [scripts/wiki_gate.py](../../scripts/wiki_gate.py) |
| Secret/PII detectors | implemented | [wiki_core/detectors/](../../wiki_core/detectors/); `--public-export` and `--strict-local` modes |
| Visibility model | implemented | PII free in private; blocked at the public boundary; secret always blocked |
| System agents (skills) | implemented | [.skills/](../../.skills/) portable `wiki-*` skills |
| Operation page (cockpit) | implemented | [memories/operations.md](../operations.md), [scripts/wiki_operation_compile.py](../../scripts/wiki_operation_compile.py) |
| Gamification with karma | implemented | [wiki_core/score/](../../wiki_core/score/); 8-dimension karma, append-only |
| Perceptive layer | implemented | [memories/system/perception/](perception/) (real journal + map); coverage requires use |
| Information -> Insight cycle | implemented | [scripts/wiki_insight_job.py](../../scripts/wiki_insight_job.py) (proposal for the human gate) |
| Audit + coverage in CI | implemented | [scripts/wiki_audit.py](../../scripts/wiki_audit.py), [scripts/wiki_check_methodology_coverage.py](../../scripts/wiki_check_methodology_coverage.py) |

## Overall status

- The kit runs end to end: ingestion, gate, score (karma), cockpit, perceptive layer,
  and insight job, with a blocking audit in CI.
- The contexts and the owner are configurable; no context is hardcoded in the code.

## Related

- Methodology: [wiki-viva-methodology-v5.md](../sources/wiki-viva-methodology-v5.md).
- Process: [ingestion-process.md](ingestion-process.md).
