# Freshness of a proposed change

The [auditor](../../scripts/wiki_audit.py) can gate freshness on the pages a
change actually touches and their dependencies. A stale unrelated page remains
visible as debt without preventing that integration. Global integrity, privacy,
secrets, links, page shapes and impact-closure checks still run unchanged.

## Upgrading

This is an explicit consumer-owned C3 configuration migration through the
[normal sync workflow](../../AGENTS.md). The default remains `global`, preserving
the existing `freshness_budget` maintenance policy. Do not raise the budget or
renew page dates as a substitute for source reconciliation.

```yaml
audit:
  freshness_scope: impact
  freshness_base: origin/main
```

The base must resolve to a commit that is an ancestor of HEAD. Fetch sufficient
history before CI; for review, prefer passing the exact agreed base SHA. There
is no implicit merge-base fallback. The same SHA is used for the diff and the
historical graph. Committed, staged, unstaged, untracked and deleted memory
pages participate, including metadata-only changes and former rename paths.

```sh
python3 scripts/wiki_audit.py --check --freshness-base BASE_SHA \
  --freshness-report /tmp/new-freshness-report.json
```

The report destination must not exist. Evidence contains page paths, relation
provenance and content hashes: retain it at the consumer's privacy boundary,
not as a public fixture. `--only freshness_budget` is diagnostic, not a complete
release gate. `freshness_budget` keeps its registry name for compatibility.

## Dependency semantics

The [scope evaluator](../../wiki_core/freshness_impact.py) reuses the authored
relation contract from the [semantic inventory](../../wiki_core/semantic_inventory.py)
and the [Git graph inventory](../../scripts/wiki_page_graph.py).

1. Start with every changed memory page and every removed page.
2. Follow factual dependencies to all transitive dependents of those changes.
3. Follow prerequisites of that set transitively. Do not expand dependents again
   from newly discovered prerequisites: sharing a source does not couple siblings.

Source references and citations point from the dependent to its prerequisite;
blockers and supporting evidence point toward the dependent. Explicit
untyped reference fields are conservatively included. Explicit `related_pages`
and `related_holons` associations express context and discovery, not factual
dependency. The latter uses the existing template-block relations/culture and
contextual reach contract, distinct from `source_refs`. Hierarchy,
ownership, participation and collection edges alone do not transmit factual
freshness. Markdown citations between the same pages still transmit freshness:
matching structural endpoints do not establish that a citation is navigation.
No whole page type or domain is exempted.

An occurrence is navigation only when it repeats a locally declared structural
or association target in a link-only, top-level list item immediately under a
`Related`, `Relacionados`, `Navigation` or `Navegação` heading. The complete item,
including multiline continuations, must contain only links and punctuation.
Prose, tables, nested lists, fenced blocks and subsections such as `Sources`
remain conservative citations. Classification precedes deduplication: another
factual citation to the same target still participates. Every occurrence records
its body-relative line, section and classification reason.

The existing MOC template convention also permits a local structural declaration
in the body: an exact `MOC:`, `Parent MOC:` or `MOC pai:` prefix in that same
top-level navigation-list format. After the prefix, only links and punctuation
are allowed. This occurrence records its literal relation label and does not
create or modify the canonical `moc_parent`. Arbitrary footer labels such as
Evidence, Source or Responsibility are not treated as navigation.

Both historical and current relations participate. Removing or retargeting a
link cannot conceal its old dependency. Deleted pages are reported as removed;
their surviving dependents are evaluated. Invalid current typed relations remain
errors even outside the freshness closure. Historical relation diagnostics stay
in evidence, allowing a change to repair an invalid old declaration.

Every stale or unknown-freshness page in the closure blocks, regardless of the
global budget or an impact acknowledgment. Existing explicit evergreen semantics
are preserved. A clean/no-memory-change tree reports debt without change-scoped
freshness blockers; use `global` mode for a whole-wiki maintenance gate.

The deterministic report records seeds, inclusion reasons, relation paths,
base/current origin, excluded structural edges, unrelated debt, exact Git SHAs
and hashes of all evaluated inputs. Missing Git/base, unreadable inputs and
concurrent changes fail closed. Other audit errors are never filtered by scope.

## Conservative boundary

Outside explicit navigation items, Markdown citations cannot distinguish live
evidence from historical mentions. They remain conservative dependencies. A log
with many historical citations or a factual catalogue table may therefore have
a wide closure: freshness and dependencies currently belong to the whole page,
not individual assertions or table rows. Inclusion through such a page does not
prove factual impact on every included domain. The report exposes the chain and
occurrence responsible. Do not delete citations or add exemptions just
to obtain a passing gate. A narrower historical-reference contract would need
its own semantic design and review.

The [synthetic tests](../../tests/test_freshness_impact.py) cover transitive
dependencies, shared sources, structural navigation, removed links, renames,
unknown freshness, invalid unrelated relations, concurrent edits and multiline
card dialogue. No private consumer content is used as public test data.
