# Agent contributions to canonical actions

An optional local agent can use the [native board](native-action-board.md),
[context packets and dialogue](context-coordinators.md), and the same
[contribution CLI](../../../scripts/wiki_contribution.py). No Hermes, Dot,
provider SDK, account, scheduler or second task database is required. The agent
application already open on the project remains the executor; the kit never
launches another agent. Claude, Codex, Hermes or a manual operator can supply
reviewable material through this trusted local interface.

This increment covers **one existing action's body**, not arbitrary files or
complete project integration. Lifecycle, questions, answers and direction still
use the existing canonical transition API. The contribution cannot replace
frontmatter, ownership, tool scope or authority. It preserves legitimate
canonical dialogue suffixes, with receipts checked against a known Git base;
conflicting body edits or unproved metadata changes are refused.

## Request and independent review

A request uses `schema_version: wiki_action_contribution.v1` and contains:

- `task_ref`: `{repo_id, action_id}` from the canonical wiki.
- `run_ref`: `{runtime, task_id, run_id}` with stable, nonempty strings. Runtime
  names are open vocabulary; these are references, not claims of live access.
- `session_ref`: `{session_id, coverage}`; optional `thread_id`, `turn_id`,
  `lineage` and `history_ref` remain the original author's identifiers.
  `coverage` is a nonempty string (maximum 2,000 characters) describing retained
  history and its limitations. A reference grants no transcript access and does
  not imply full history or private reasoning is available.
- `effect_key`: a stable, bounded key assigned before the material hash; reuse
  with different material is an explicit conflict.
- `files`: exactly one `{path, base_sha256, sha256, text}`. Text is the complete
  proposed UTF-8 action document, whose frontmatter must equal the known base.
  `base_commit` (full Git SHA) is recommended on that file; without it the port
  searches at most 200 ancestor changes for the pinned base hash.

`material_sha256` is optional on the request and returned by the port. Compute
it over the entire request **except that field**, using UTF-8 JSON with sorted
keys, `ensure_ascii=False`, `allow_nan=False`, and separators `(',', ':')`.
The file's `sha256` binds its complete text, not only the body. Do not change the
request or replace original run/session references after review.

The separate review object contains `material_sha256`, `reviewer_session_id`,
`evidence_ref`, `report: {criteria, findings}` and `decision: approved`. Criteria
must be nonempty, findings must be an empty list, and the reviewer session must
differ from the author session. These assertions come from the trusted local
adapter and are recorded as **independent agent/operator review**, never as a
fabricated human approval, provider execution, permission grant or CI pass.

## CLI and Git workflow API

```sh
python3 scripts/wiki_contribution.py prepare --root /path/to/project \
  --request /path/to/request.json --review /path/to/review.json --apply
python3 scripts/wiki_contribution.py publish --root /path/to/project \
  --request /path/to/request.json --apply
python3 scripts/wiki_contribution.py integrate --root /path/to/project \
  --request /path/to/request.json --pr 123 --apply
python3 scripts/wiki_contribution.py reconcile --root /path/to/project \
  --request /path/to/request.json --pr 123 --apply
```

Omitting `--apply` validates a dry run and performs no effect. The corresponding
`run_git_workflow` operations are `prepare_contribution`,
`publish_contribution`, `integrate_contribution` and `reconcile_contribution`,
with `request`, optional `review`, and `pr` in the payload. Existing operator
HTTP authorization applies to this API; it is not an unauthenticated bot route.

Preparation starts from the approved Git base, creates an isolated proposal,
and invokes the real auditor, input-stage check, PR summary and diff check.
Consumer-owned `approval.contribution_gates` can add argv arrays of normal
project gates. Model work and auditing hold no application checkout lock.
Ref installation then revalidates HEAD, policy and source bytes under the
canonical writer's cross-process guards and Git ref CAS. It never switches the
application's branch, stages its files or overwrites disjoint WIP. The action's
existing history receives a body-integration receipt binding material, review,
references, effect key and before/after body hashes. Generated receipt time is
not a refresh of the business evidence or a waiver of freshness checks.

Publication/integration currently implements the consumer's `github_pr`
policy. Other policies return `waiting_policy_adapter`; no GitHub account is
created. Publication opens a draft. Mark it ready through the project's normal
review process. Integration checks the exact proposal head, target branch,
remote CI success, outstanding review/draft status and current committed policy
before an exact-head merge. An explicitly configured
`approval.require_human_review: true` additionally requires a real GitHub user
approval of that commit. The local review JSON cannot satisfy that human gate.
No access, absent CI or a pending gate is a refusal/wait, never successful
adoption. Local-only projects can prepare/review proposals; another integration
policy requires its own explicit adapter.

## Recovery and adoption coverage

A prepared proposal is identified by its Git branch and recorded effect, so a
repeated identical preparation reuses it. Source changes during preparation or
after its freeze cause an explicit conflict. Reprepare only after inspecting
that conflict; do not silently discard dialogue, replace the request, reopen a
question or rerun a model. No exclusion of all history is used as a shortcut.

After a timeout or `unknown`, call **reconcile only**. It queries the PR and
reads actual Git objects and bytes; it never repeats the merge. A failed
readback stays unknown/refused. Even a successful remote merge is not proof of
local application adoption: `remote_merged` and `source_commit` report Git
facts, while `canonical_body_adopted` requires the selected checkout to contain
the merged source and matching action bytes. Otherwise the result is
`waiting_worktree_adoption`. The operator owns that adoption; the port does not
reset, stash or update the active checkout. `served_adoption_verified` remains
false: reader/service adoption is a separate operator readback, not implied by
this receipt. Completion of one card body does not prove complete project or
runtime integration.

Tests distinguish synthetic adapter reports and mocked GitHub CI from real
local Git/CLI execution. Neither proves a model or provider was called. Public
fixtures contain only fictional content; personal configuration and material
remain in each private consumer.
