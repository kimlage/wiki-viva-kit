# Wiki Viva Kit

Reusable Markdown/Git kit for a living operational wiki. Deterministic work
lives in Python and TypeScript; contextual LLM reading is delegated to the
agent operating the repository.

## Working contract

- `main` is approved truth. Work in `wiki/<theme>` (or another focused branch),
  run the project gates and use an independently reviewed PR with passing CI.
- Public-kit corrections are proved here with public synthetic fixtures before
  downstream use. Never copy private personal, financial or client data into
  this repository.
- Canonical memory lives in [memories/](memories/index.md). References and
  templates live in [docs/](docs/README.md); [data/raw and data/derived](data/README.md)
  are ignored cache.
- Source ingestion enters through [scripts/wiki_ingest.py](scripts/wiki_ingest.py).
  The agent writes the delegated LLM result through
  [.skills/wiki-llm-context-agent](.skills/wiki-llm-context-agent/SKILL.md).

## Coordinator role

When acting as a cross-front coordinator, follow the
[coordinator role contract](.skills/wiki-viva/reference/coordinator.md) at
opening and every resumption. Maintain direction, dependencies and acceptance;
check integrator deliveries while product integrators perform implementation,
tests, integration and infrastructure work. Recheck the owner's current
direction and pauses before dispatch: an old queued message does not release a
pause. This is an operator instruction; the host must bind the role and enforce
current authority.

## Integrator role

At opening or resumption, on receiving results and before ending a turn, check
authorized threads and their actions, artifacts and PRs; a completed turn is not
a completed delivery. Check for an active run before resuming an authorized,
executable next step in the same thread with its acceptance; preserve artifacts
and WIP, follow the result and conduct review and integration. Do not stop at
an acknowledgement. Reconcile uncertain effects
before retrying. Do not repeat a denial without new evidence, resume an explicit
pause or interrupt an active run solely for lack of visible progress. Record a
real blocker's evidence, missing input or dependency, responsible recipient and
resume condition on the existing action; continue independent work. Close the
accepted scope only after review and applicable gates, approved-main readback,
wiki reconciliation and settlement. A sub-delivery or merged PR does not close a
front with remaining scope or acceptance. After the turn ends, an authorized
observer, coordinator or host checks the effective settled state. If it hides
pending work, restore visibility and resume the same thread only under current
direction and STOPs; if no observer is available, report verification pending
without guessing its cause. See the [continuity and closeout contract](docs/references/guides/context-coordinators.md#thread-continuity-and-closeout).

## PR review policy

- Before merging this kit, a reviewer independent of the change's author must
  approve the conceptual diff, privacy and validation evidence. The reviewer
  may be another agent or a human; the author cannot self-approve.
- Record the reviewer, exact reviewed head SHA, findings and their resolution
  in the PR or a referenced review artifact. All applicable project gates and
  normal CI must pass on that head. A later head change requires renewed review.
- Human review is not an additional kit requirement. Describe agent review as
  agent review, never as human review. Publication still requires operator
  authorization; privacy and secret failures remain non-waivable.
- Consumers retain their own PR review and promotion policies. Historical
  references and legacy identifiers such as `needs_human_gate` do not override
  this policy; stored states, transition checks and history remain unchanged.

## Upgrades and releases

The certification state machine is retired. Rc41, subjects, lanes, capsules,
attestations, exact release matrices and receipts are historical records, not
release gates. [upgrade-package.yaml](docs/references/upgrades/wiki-viva-v8/upgrade-package.yaml)
is frozen history and must not be edited to satisfy retired tests.

Current downstream adoption is one reviewable PR:

```sh
python3 /path/to/wiki-viva-kit/scripts/wiki_sync_from_kit.py \
  --kit /path/to/wiki-viva-kit --consumer . --dry-run
python3 /path/to/wiki-viva-kit/scripts/wiki_sync_from_kit.py \
  --kit /path/to/wiki-viva-kit --consumer . \
  --c3-command "python3 scripts/consumer_migration.py"
```

- B0 is the read-only plan.
- C1 copies Git-tracked kit-owned files byte-for-byte and preserves executable
  mode. Only paths previously owned in `kit.lock` may be pruned.
- C2 runs deterministic generators declared in the sync manifest.
- C3 is explicit consumer-owned migration; the kit never guesses domain edits.
- `kit.lock` records source SHA, manifest/tree digests and managed files without
  host paths or private evidence.
- Reversibility is the PR. Promotion requires the kit's normal CI, the
  consumer's own gates and its own PR review policy.

A kit release is a tag, release notes and an **Upgrading** section describing
consumer migrations. No capsule or certification ceremony is required.

## Privacy

- Personal data is valid in private consumer pages. It is blocked only at a
  public/public-export boundary.
- Access secrets (tokens, passwords, keys, cookies) are blocked everywhere.
- Privacy and secret failures are fail-closed and never waivable.

## Core structure

- [wiki_core/](wiki_core/README.md): deterministic contracts.
- [scripts/](scripts/README.md): `wiki_*` command-line tools.
- [apps/wiki-cockpit/](apps/wiki-cockpit/README.md): web cockpit.
- [packs/](packs/registry.yaml): versioned public synthetic experience packs.
- [.skills/](.skills/README.md): portable agent skills.
- [docs/references/templates/wiki/](docs/references/templates/wiki/README.md):
  page contracts and templates.

## Gates before a PR

Run the privacy and repository-integrity audits and check the diff locally:

```sh
python3 scripts/wiki_audit.py --check
python3 scripts/wiki_audit.py --public-export --check
git diff --check origin/main
```

Select additional local checks for the actual change and record their scope in
the PR: focused Python tests for affected behavior and security boundaries;
the relevant deterministic compiler, snapshot or pack checks for generated
contracts; and frontend tests, typecheck and build when UI code or a consumed
interface changes. When impact is uncertain or cross-cutting, widen the local
selection. A documentation-only change does not require an unrelated local
unit or browser suite.

The normal public CI runs the full Python and frontend suites, configured
browser journeys and Windows checks on the PR merge result associated with the
reviewed head and current base. Do not duplicate those entire suites locally for
every PR; a failed or missing CI check is not replaced by a local result. Run
additional tests when a change, failure or unresolved risk warrants them.
Coordinate the independent review after the proposal is stable; if the head
changes, the reviewer verifies the new head and the affected delta.

Configure each consumer through `wiki.config.yaml`; no context, owner or memory
root may be hardcoded in shared core.

## Keep the operating core small

- Technical documentation edits use [scoped freshness](docs/references/freshness-impact.md),
  exact changed paths and a reviewed rationale. Never renew source dates merely
  because documentation was edited. Do not recreate documentary hash dossiers.
- Generic Python suites, demo fixtures and public browser journeys are maintained
  and tested in this kit. Consumer sync copies runtime and shared contracts;
  consumers retain their domain checks and native operator integration tests.
- The public static demo is built and checked here. Consumers serve the cockpit
  through their operator, whose live runtime configuration supplies the snapshot.
