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

## Documentary-only edits

A reviewer may classify a changed existing page as documentary-only for this
proposal: spelling, formatting, navigation or a technical catalogue update
that makes no new claim about the source's current facts. Read the complete
diff and explain the classification in the PR. For example:

```sh
python3 scripts/wiki_audit.py --check --freshness-base BASE_SHA \
  --documentary-only 'memories/system/commands.md=Command spelling corrected; no source facts changed'
```

This is an authored classification, not automatic proof. It removes only the
initial seed. A factual change elsewhere still reaches the page and all its
old dependencies. Unknown intent stays factual. The option accepts only exact
changed existing paths with a rationale; no globs, deleted pages or permanent
config exemptions. It refuses changes to dates, cadence or evergreen policy.
Missing, invalid and future dates remain unknown. A document edit does not
prove that its source was reread: preserve the source's verification date.

The graph uses the union of the approved base and candidate. Independent review
of the exact final SHA remains required. The machine cannot determine semantic
truth from Markdown, and a hash never established it.

## Receiving operational communication

A native action comment retains the original factual date and body, with a
separate event timestamp. Only a valid single comment append with its original
preimage and canonical receipt qualifies automatically. Mixed edits, forged
receipts and batches remain conservative. Another factual seed still reaches
the action and its old source dependencies. Physical bytes remain protected by
Git, readsets, CAS and independent review.

## Migrating from documentary contracts

Remove `audit.freshness_records` and `approval.contribution_record_support` in
the consumer's reviewed adoption PR. Preserve existing dates and source content;
use an exact approved base or `origin/main` for subsequent proposals. The active
contract is no longer regenerated. Old contracts remain recoverable in Git
history and may be removed from the active tree after replacing their links
with immutable historical links. The evaluator refuses an active old pointer
instead of silently claiming that its qualifications still apply.

H2 partitions, full document maps, occurrence bindings, custody qualifications
and causal receipts are retired. No replacement JSON dossier is required.
Historical links can point to the pre-migration commit. Current reference roles
from [Markdown producers](../../wiki_core/markdown_link_roles.py) continue to
classify individual navigation links; another factual citation still counts.
