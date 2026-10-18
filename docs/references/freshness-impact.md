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

## Explicit documentary records

Consumers may opt into `audit.freshness_records: path/to/records.json` through
their own reviewed C3 migration. This is an authored semantic declaration for
one exact base/candidate pair, not a permanent waiver or an automatically
generated claim of independence. The JSON `document_record.v1` contract contains:

- `base_documents_sha256` and `current_documents_sha256`: complete maps of every
  authored page to its UTF-8 content SHA256, including unchanged pages.
- `documents`: declarations with `path` and `records`. Each record has a stable
  `id`, exact unique top-level H2 `heading`, `base_sha256` and `current_sha256`
  for the complete section, including its heading and trailing whitespace.
  `null` means absent in that snapshot, never an ambiguous selector.
  Optional `leading_blank_lines` (0–2) includes explicitly hashed blank separator
  lines before the heading; nonblank padding and overlapping selectors fail.
- Each record explicitly declares `independent: true`, a substantive `rationale`,
  `recorded_on` (ISO date), `epistemic_status` (`observation`, `proposal`,
  `decision`, or `hypothesis`), and `context_records` (other required record IDs
  in that document, or `remainder`; explicitly `[]` when none applies).
- Optional `bindings` identify `origin` (`base` or `current`), `edge_sha256`,
  `consumer_record`, `target_record`, `consumed_sha256` and a substantive
  `rationale`. Omit `consumer_record` only for an unpartitioned consumer;
  a partitioned consumer must name its record or `remainder`. The edge hash
  is produced by `wiki_core.document_records.edge_digest` over the complete raw
  occurrence, including its field, source, target and Markdown offset. A binding
  applies only to that exact version and occurrence. It cannot silently narrow
  a historical citation when only the current version is declared. Bindings are
  applied after inheritance: narrowing one record never narrows its siblings.

The selector uses CommonMark blocks. Nested/fenced headings and duplicate titles
are not selectors. A section includes subsections and ends at the next top-level
H1/H2. Removing all selected sections must reproduce the exact remaining bytes
in both versions before the evaluator can replace a whole-page seed with changed
record seeds. Mixed body/metadata edits, reordering, moving a record relative to
unselected content, changing document-wide link definitions, and other changed pages stay
conservative. Removed/retargeted record dependencies participate from the base.

Preservation is a mechanical fact; independence is an authored assertion that
requires content review. A new block that revokes, reinterprets or relies on a
sibling must declare that context. Page-level factual metadata and introduction
references outside H2 sections (including introductions after subsequent H1s)
are always inherited. Record dates/statuses are descriptive: all
records retain the page's freshness policy and date without renewal.

An unqualified consumer of a document consumes every record and the remainder.
It receives the new impact and keeps old prerequisites. A qualified consumer
depends only on its declared record, whose own premises still participate.
`remainder` means all bytes outside selected records, not an empty/ignored node.
The evaluator does not infer narrow consumption from a link fragment alone.

The contract lives outside the Markdown payload, avoiding circular content
hashes. It must be a local repository-relative file; it is itself hash-bound in
the report and checked for concurrent modification along with the full input
snapshot. A mismatch or incomplete binding fails closed. Updating the snapshot
requires renewed semantic review; hashes alone do not approve a declaration.

### Occurrence roles and immutable evidence

A binding defaults to `role: consumption`. Three other reviewed roles are
available for the exact occurrence and consumer: `navigation` identifies a
place to visit, `change_target` identifies the object of a recorded change, and
`provenance` identifies origin while retaining separately verified evidence.
These require `target_document_sha256` for the complete referenced document in
that origin. They do not apply to other occurrences, siblings, or the other
snapshot. A role is a substantive authored assertion, never a shortcut justified
by the desired gate result. A real premise must remain a dependency.

`provenance` requires nonempty `evidence` IDs. These become real prerequisites of
the consumer, replacing whole-page factual consumption at that occurrence only.
The optional `artifacts` array declares each ID separately for `origin: base`
or `current`, with one of these two verifiable sources:

- `path` and `sha256`: a repository-relative immutable capture. The reader checks
  exact bytes, includes the file in its complete input hashes and concurrency
  check, and performs no network access or source refresh.
- `document`, `field`, `match_key`, `match_value` and `sha256`: one unique mapping
  in a top-level frontmatter list, such as a result event. Its digest uses
  `structured_digest` (canonical JSON); its parent document is bound by the
  complete snapshot hash. Missing, ambiguous, or changed events fail closed.

Records can also declare `base_evidence` and `current_evidence` ID lists for
direct prerequisites. An artifact is reported as `historical_evidence`, not as
a newly fresh page. This state is assigned only by the verifier, never accepted
from authored frontmatter. It proves the captured bytes/event at the declared
cut; it does not prove the event's every claim, current sales, account access,
authorization, successful callbacks, or current execution. Content review must
keep these distinctions and any other necessary source dependencies.

A result file without a job/action identifier does not prove which execution
produced it. Include the corresponding event or delivery receipt as a separate
prerequisite. Preserve source dates and existing page freshness; a hash check is
not an update of a living financial, operational or corporate source. Captures
and their declarations stay within the consumer's privacy boundary and normal
review, secrets and publication gates.

## Conservative boundary

Outside explicit navigation items, Markdown citations cannot distinguish live
evidence from historical mentions. They remain conservative dependencies. A log
with many historical citations or a factual catalogue table may therefore have
a wide closure unless reviewed record/consumption declarations are available.
Inclusion through such a page does not
prove factual impact on every included domain. The report exposes the chain and
occurrence responsible. Do not delete citations or add exemptions just
to obtain a passing gate. Record declarations preserve conservative treatment
wherever authored semantic evidence is missing.

The [synthetic tests](../../tests/test_freshness_impact.py) cover transitive
dependencies, shared sources, structural navigation, removed links, renames,
unknown freshness, invalid unrelated relations, concurrent edits and multiline
card dialogue. No private consumer content is used as public test data.
