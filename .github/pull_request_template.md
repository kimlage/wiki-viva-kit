# Objective

-

## Ingestion context

-

## Sources consulted

-

## Pages changed

-

## Privacy (PII free in private, secrets blocked)

- [ ] Personal data/PII (values, CPF/CNPJ, counterparties, documents, relationships) were kept freely when they help operational memory, reconciliation, CRM, decision making, or context -- private personal repo, no warning.
- [ ] No access secret (token, cookie, password, access code, credential, individualized secure link) nor full dump was copied -- nowhere.
- [ ] If any page became public/public_candidate, I ran `wiki_audit.py --public-export` and redacted the PII.
- [ ] [docs/](../docs/) was not used as primary memory.
- [ ] Local paths cited became real Markdown links.

## Decisions made

-

## Pending items

-

## Commands run

- [ ] `python3 scripts/wiki_audit.py --check`  Links: [scripts/wiki_audit.py](../scripts/wiki_audit.py).
- [ ] `python3 scripts/wiki_ingest.py --source <source> --context <context> --dry-run`  Links: [scripts/wiki_ingest.py](../scripts/wiki_ingest.py).
- [ ] `python3 scripts/wiki_check_methodology_coverage.py --check`  Links: [coverage](../scripts/wiki_check_methodology_coverage.py).
- [ ] `python3 scripts/wiki_operation_compile.py --check`  Links: [cockpit](../scripts/wiki_operation_compile.py).
- [ ] `python3 scripts/wiki_okf_export.py --out tmp/okf-smoke --clean`  Links: [scripts/wiki_okf_export.py](../scripts/wiki_okf_export.py).
- [ ] `python3 scripts/wiki_okf_check.py --bundle tmp/okf-smoke --check`  Links: [scripts/wiki_okf_check.py](../scripts/wiki_okf_check.py).
- [ ] `python3 scripts/wiki_pr_summary.py`  Links: [scripts/wiki_pr_summary.py](../scripts/wiki_pr_summary.py).
- [ ] `git diff --check`

## Approval checklist

- [ ] [memories/](../memories/) contains an actionable synthesis.
- [ ] [docs/](../docs/) remains restricted to references, templates, snapshots, and evidence.
- [ ] No full dump without criteria and no access secret was copied into Markdown.
- [ ] [memories/system/log.md](../memories/system/log.md) was updated.
- [ ] [scripts/wiki_audit.py](../scripts/wiki_audit.py) `--check` validated clickable local links.
- [ ] Existing scripts remain valid if they were touched.

## Human review

> The CI validates links, secrets, and tests; it does NOT validate whether the idea is correct. The
> items below belong to the human reviewer (even when an agent opened the PR).

- [ ] **I read the conceptual diff** (what changes in behavior), not just the list of files.
- [ ] **Privacy checked**: PII only on a private page (ok); no access secret; public export redacted.
- [ ] **Cockpit recompiled** if the memory changed (`wiki_operation_compile.py --check` green).
- [ ] **Honest status**: no claim of "done" without evidence of a real artifact/page (no overclaim).

## PR size (split rule)

> Large PRs hide problems and tire the review. Keep one PR = one theme.

- [ ] This PR fits in **one thematic block**. If it exceeds ~400 lines of diff OR ~15 files, I split it into chained thematic PRs (or I justify below why it is indivisible).
- Justification (if large and indivisible):
