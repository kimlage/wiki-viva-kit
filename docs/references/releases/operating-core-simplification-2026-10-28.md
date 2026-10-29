# Operating core simplification — 2026-10-28

The project remains a living Markdown/Git wiki with source ingestion, consolidated
memory, perspectives, an independent action board and a spatial cockpit.

This change removes retired release certification executables and their skipped
suites, and retires documentary H2 partitions, full-document hash maps, occurrence
bindings and causal review dossiers. Existing canonical writes, independent
review, exact-head checks, source tracking, CAS and public/secret boundaries remain.

[Freshness](../freshness-impact.md) uses changed pages and both old and new factual
dependencies. A reasoned documentary-only classification suppresses just a seed;
another factual change still reaches that page. Source dates are preserved and
future dates are unknown. Referenced tracked artifacts also participate in impact.

[Snapshot projection](../../../wiki_core/web/snapshot_projection.py) is separate
from [atomic publication/recovery](../../../wiki_core/web/snapshot.py). Public
entry points remain compatible. No cockpit interface redesign is included.

## Upgrading

Use the [normal sync](../../../AGENTS.md#upgrades-and-releases) from the merged
commit. The [manifest](../upgrades/sync-manifest.yaml) no longer distributes the
public demo, its fixture/generator, upstream browser journeys or generic Python
suite files. Only previously managed paths may be pruned automatically. Review
consumer-owned copies separately and retain genuine domain/integration coverage.

In C3, remove `audit.freshness_records` and `approval.contribution_record_support`.
Archive old generated dossiers in Git history, repairing historical links to
immutable revisions. Use the approved proposal base for scoped freshness; preserve
all source dates and substantive facts. Existing old contribution proposals that
include documentary support need explicit reconciliation before continuing.

Regenerate actual consumer read models, validate the consumer's full applicable
suite and review the exact adoption SHA. A successful kit build is not proof of
consumer adoption. Browser/visual verification is separately required for future
interface changes.

Validation results and independent review belong to the PR at its exact head.


## Completion of the six-part plan

The initial cut above is historical. The follow-up closes remaining structural
work, in addition to the separately integrated cockpit fixes:

| Plan item | Final implementation and evidence |
| --- | --- |
| Retire legacy | Certification and documentary-contract executables were removed in the initial cut. The remaining unused adapter-manifest generator, schema, guide and suite are now removed; no runtime consumer remained. Git preserves history. |
| Simplify freshness | [Scoped freshness](../freshness-impact.md) retains source dates, uncertainty, real dependencies and independent review without H2/hash dossiers. Existing freshness regressions remain. |
| Slim distribution | The [sync manifest](../upgrades/sync-manifest.yaml) excludes generic frontend/script tests and fixtures as well as the already excluded generic Python suite, demo and development journeys. Domain and native integration checks stay with each consumer. |
| Reduce repeated computation | A snapshot builds its canonical page graph once, sharing it across blocks, quality and graph projection. [Parity regression](../../../tests/test_snapshot_frontmatter_cache.py) compares all payloads and proves a later build sees edits. Storage/recovery remains separate. |
| Consolidate instructions | [AGENTS](../../../AGENTS.md), the router and existing command guide are the active entry points; removed adapter instructions no longer claim a preflight consumer. Consumer-specific rules remain consumer-owned. |
| Test behavior | The unused adapter suite and retired marker are removed. Generic tests run upstream, with domain and native integration downstream. Existing acceptance scenarios now cover provenance through consolidation/reingestion, persisted action readback and exact Git rollback. |

The [ingestion scenario](../../../tests/test_e2e_context_pass.py) uses a recorded
synthetic LLM result, not a new model invocation. It verifies context invalidation
when newly consolidated knowledge changes the context packet, then safe reuse.
The [action scenario](../../../tests/test_web_server.py) rereads the live snapshot
after the canonical Markdown transition. The [sync scenario](../../../tests/test_wiki_sync_from_kit.py)
verifies idempotence and restoration of the original Git tree after adoption/revert.

### Upgrading this follow-up

Run normal B0 and C1 from the merged commit. Previously managed generic tests and
fixtures are pruned; keep consumer-owned domain/native integration tests. Run the
consumer's Python/domain suite, typecheck, build, architecture, asset and native
operator checks. Generic `npm test` and `npm run test:gates` belong to the public
kit and are validated by its CI at the adopted pin. No source dates, source states,
private data or credentials are migrated. The adoption PR remains reversible.

### Bounded snapshot measurement

On the same local machine and a synthetic fixture of 200 pages with 20 outgoing
links per page, three builds of the previous revision had median 1.136 seconds;
three builds with graph reuse had median 0.582 seconds (about 49% less). Each old
build constructed three graphs; each new build constructed one. All six complete
payload hashes were identical. This is a local comparative measurement under
concurrent validation load, not a universal latency guarantee. The regression
also proves changed and newly added pages appear in the next build.

A separate synthetic live operator was opened in the browser: its action started
in Ready to plan, a canonical HTTP transition persisted `in_progress` in Markdown,
and a browser reload showed the action in In progress. No private action was
changed by this acceptance check. Final suites, GPU/browser results and exact-head
independent review are recorded with the PR.
