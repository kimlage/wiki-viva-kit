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

### Roles carried by Markdown producers

Authors and deterministic producers can declare the intent of one link with
[declare_link_role](../../wiki_core/markdown_link_roles.py). The producer supplies
`navigation` for a place to visit or `change_target` for a destination to update.
These are the same nonfactual roles used by the documentary projection below;
they do not exempt a page, table, context, or another link to the same endpoint.
An ordinary citation or an unrecognized role remains conservative.

```python
from wiki_core.markdown_link_roles import declare_link_role

cell = declare_link_role("[Command reference](commands.md)", "navigation")
```

The helper appends an invisible, versioned Markdown comment binding the role to
the SHA256 of that literal link. This is an **authored declaration requiring
content review**, not authentication of a producer, a permission, or proof that
the role is true. The CommonMark parser must confirm the link and the immediately
adjacent inline comment as the same tokenized occurrence and exact source span.
An altered link, unknown role, ambiguous mapping, marker in a label, fenced/inline
code, image, or HTML block cannot qualify a citation. Reference-style links retain
their independent occurrences. A factual second citation remains a dependency.

The [input-stage renderer](../../wiki_core/input_stage.py) emits `change_target`
only for the known `target_pages` column. Source, state, config and channel cells
retain their existing semantics. Navigation-table authors use the same explicit
helper; a table heading or page type alone never implies a role. The evaluator
records the declaration and its origin through the existing association graph.
Inline `provenance` is not supported: verified replacement evidence still uses
the documentary contract below.

A declaration in the candidate never narrows an unqualified historical citation.
Legacy migration needs semantic review of each relevant historical occurrence
through the existing origin-bound role contract; adding candidate markers alone
cannot hide an old dependency. Regenerating a producer changes its artifact,
not the freshness or truth of its input business sources.

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
are not selectors. Repeated H2 titles still delimit sections: their references
stay in the unselected remainder, rather than becoming common introduction
premises for a different record. A section includes subsections and ends at the next top-level
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
These require `prerequisite_document_sha256` for the complete prerequisite
document in that origin (`target_document_sha256` remains an alias for reference
relations). Direction is normalized: references depend on their target, while
forward factual relations depend on their source. Factual metadata authored on
another page is inherited by every record of its dependent, too. They do not apply to other occurrences, siblings, or the other
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

### Reviewed causal boundaries (opt-in v2)

A localized policy change can reach unchanged intermediate consumers and then
stale assertions whose meaning it does not affect. Freshness alone does not
prove that absence of impact. The optional `causal_review` object in the existing
`document_record.v2` contract records a separately reviewed causal disposition;
it never changes source dates, factual relations or access authority.

The [causal verifier](../../wiki_core/causal_review.py) first computes the full
BASE/CURRENT occurrence census. Its schema is `wiki_causal_review.v1`, with
`author`, `pair_sha256`, `census_sha256`, `dispositions` and `review_evidence`.
Each disposition has an exact `obligation_id`, substantive `reason` and one of:

- `no_change`: the complete consumer unit and documentary interpretation are
  identical, its own freshness is valid in BASE and CURRENT, and independent content review explains
  why this exact delta does not change the consumed conclusion or duty. Only
  this causal arrival stops propagating downstream. The consumer and all its
  actual prerequisites remain evaluated.
- `updated`: the affected record has a substantive repair. Dates, freshness
  intervals or exemption flags alone cannot constitute that repair. Content
  review must establish pertinence to the exact obligation; a lateral edit is
  not enough. Impact continues to the repaired consumer's dependents.
- `blocked`: the obligation remains unresolved, even when the consumer is fresh.

Missing dispositions also block. Every reached seed/occurrence is checked;
another path or BASE occurrence cannot be cleared by the first review. Cycles
terminate without discarding pending causes. The full census and downstream
debt beyond reviewed boundaries stay in the report. Such debt has not been
individually reviewed or factually updated.

For a verified record, the complete unit is its exact selected bytes; a repair
to an independent sibling does not require editing that intact unit. Raw WHOLE
consumption still compares the entire document. A sibling's new publication
date cannot renew an unchanged unit whose BASE freshness has expired.

An exact `explicit_view_v2` edit retains its raw document seed for WHOLE
downstream consumers. When the projector proves stable selection/context
shapes, preserved remainder, reference definitions, ordering and anchors, its
changed components supply the semantic upstream roots. The redundant raw
representation alone does not request revalidation of untouched independent
siblings. Raw seeds, component edges, the complete occurrence census and causal
review remain present. If an actual WHOLE consumer or a real context reaches
those siblings, their factual prerequisites are still required and can block.
Uncovered edits, changed shapes and unverified authored markers get no such
qualification. This behavior requires the existing reviewed causal contract;
ordinary unreviewed impact evaluation remains conservative.

The pair digest binds full input documents, projected relations, record lineage
and verified evidence classifications. Interpretation checks include the
consumed selections, remainder exclusions and transitive factual contexts.
Positions of already projected occurrences are compared semantically without
their line/offset or binding locator hash; section, roles, targets, selections
and multiplicity remain significant. The complete pair and occurrence census
still bind those exact positions, so shifting a link invalidates an old receipt.
Reviewing a migration must additionally compare the prior approved contract:
narrowing both origins is not justified by their mutual equality. No legacy
`impact_closure` statement becomes a freshness waiver.

`review_evidence` names one CURRENT immutable JSON file artifact. Its
`wiki_causal_review_receipt.v1` receipt has `author`, a distinct `reviewer`,
`decision: approved`, an empty `unresolved_findings` list and `plan_sha256`
(the structured digest of the complete plan except `review_evidence`). This
binds review content; it does **not** authenticate the claimed reviewer or
approve publication. The existing independent review on the final PR HEAD,
native effect admission and all other gates remain mandatory. Changing any
bound input invalidates the review.

This initial scope refuses added/removed consumers and combinations with
`locator_changes`. Removed seeds retain their BASE obligations. Contracts
without `causal_review` preserve previous behavior. Consumers author and review
the optional C3 input after adopting the public kit SHA; no automatic private
migration or source revalidation occurs. The
[synthetic regressions](../../tests/test_causal_review.py) cover causal cuts,
alternate causes, preserved prerequisites, scope reduction and stale receipts.

### Reviewed custody locator changes (opt-in)

An optional `locator_changes` list in the existing record contract distinguishes
a verified change of an artifact's custody address from a factual content
update. This adds a review obligation, not factual freshness. Existing contracts
retain their behavior. Invalid declarations fail closed.

Each declaration supplies a unique `id`, document `path`, substantive `rationale`
and nonempty `replacements`. A replacement supplies the exact `base_markdown`
and `current_markdown`, `locator_use: historical_artifact_address`, original
`artifact_sha256`/`size_bytes`, and `custody_evidence` (a CURRENT file-artifact ID).
Optional `custody_entry` selects one exact entry in an existing receipt's
`files` mapping. The receipt records `source_path`, `sha256`, `size_bytes`,
`view_url` and a timezone-aware `verified_at`.

The CommonMark parser must prove unique literal inline links in both complete,
hash-bound snapshots. Only their destinations may differ; applying all declared
substitutions must reproduce CURRENT byte for byte. Image/link changes, labels,
titles, metadata, norms, dates and other prose cannot share this qualification.
The initial scope supports local artifact paths becoming HTTPS custody links;
reference-style, autolinks, title-bearing links and ambiguous mappings are
conservative. A CURRENT custody event is never assigned to BASE.

Wrapped list and quote paragraphs can retain a supported literal link even
when CommonMark removes container indentation outside that link. The mapper
must align complete source lines with the parsed inline lines, accepting only
unambiguous container prefixes and unchanged link bytes. Normalization inside
the link, duplicate literals and uncertain line mappings stay unsupported;
a matching spelling inside code cannot supply the span of another AST link.
The complete BASE-to-CURRENT byte replay remains required.

The file verifier checks the pinned receipt's bytes. Content review must verify
its claimed original identity and remote custody, and establish that the URL is
only an artifact address for this operation. Neither a hash nor this declaration
proves remote state, account access, permission, semantic independence or current
profile content. A URL used as identity, authority, version or an assertion
remains factual. No network access or new source ingestion happens here.

Consumer intent is separately authored for each origin and inherited variant.
An existing `role: consumption` binding to an explicit `observation` record can
add `locator_review: {change_id: ID, consumption:
historical_observation_without_locator, rationale: ...}`.
The ID must identify the custody change of that binding's prerequisite document;
it cannot qualify a stale observation in another document.
This does not narrow WHOLE or `remainder`, does not apply retroactively to BASE, and does not alter
the factual dependency for any other change. Record independence, contexts and
ordinary semantic review remain required. An active rule or current external
use must not be mislabeled as historical consumption.

The same evaluator joins obligations monotonically across every route and both
origins. Unknown/WHOLE consumption and unqualified own premises require factual
review; an actual factual source or policy change always remains factual even
when rendered output coincides. Such a requirement dominates a competing
representational reason. Upstream expansion still does not restart downstream
traversal. A first witness cannot override a later factual route.

Raw seeds, paths, hashes and `stale`/`unknown` verdicts remain visible. The report
and review packet expose verified locator declarations and per-node obligations;
raw seeds use their document identity, while component seeds use lineage built
by the projector from validated partitions. Ordinary frontmatter fields cannot
reassign either identity or borrow another document's custody qualification.
`preserved_content_debt` shows expired content whose only obligation in this
operation is custody review. Only that obligation can be satisfied by the
receipt. A factual requirement reached by another route remains blocking. The
source's freshness policy, schedule and dates are never renewed or exempted.
An `explicit_view_v2` raw document continues to consume all its components;
unqualified component premises therefore remain factual and may still block.

For upgrades, author the optional declarations and BOTH-origin qualifications
as explicit consumer-owned C3 input after custody and claim review. Run the
normal gates; this feature does not promise to remove unrelated or genuinely
required debt. The synthetic regression
[`test_locator_review_requirements.py`](../../tests/test_locator_review_requirements.py)
exercises the normal projector, repository report and review APIs, including
mixed policy changes and competing WHOLE consumption.

### Explicit view entries (opt-in v2)

`document_record.v2` adds whole table-row selectors and explicit publication /
composition slots to the **same** projector, review command and impact evaluator.
It does not infer which views are generated or which claims are independent.
Existing `document_record.v1` contracts retain their H2 behavior. A v2 contract
requires `document_modes` with exactly one entry for every declared document:
`h2_v1` preserves its original declarations and bindings; `explicit_view_v2`
requires the selectors below. Converting a document is a reviewed migration,
not an automatic consequence of bumping the schema version.

In an explicit view, records retain stable IDs, independence, rationale,
epistemic status, recorded date, contexts and evidence. Replace `heading` with
`selectors: {base: ..., current: ...}`. Each origin also retains its exact
`base_sha256` / `current_sha256` for the **complete lexical selection**:

- `kind: h2`, `heading`, optional `leading_blank_lines`: the existing unique
  top-level H2 section, including its full content.
- `kind: markdown_preamble` with no other keys: the complete Markdown body
  prefix, including H1, introduction and separators, up to the first parser-proven
  top-level H2. Frontmatter stays common context. A missing H2 boundary refuses
  selection; nested, quoted and fenced headings cannot provide it. The prefix
  has a stable record ID and independent exact hashes in BASE and CURRENT.
  This is a factual record, never an ignored span or publication envelope.
  References from it remain prerequisites; records whose validity relies on the
  introduction must declare that context. WHOLE consumers retain its impact,
  invalid/uncovered deltas stay conservative and page freshness is unchanged.
- `kind: table_row`, `container_heading_path` (complete heading titles),
  `header_sha256` (both raw header/separator lines), `key_column` (zero based),
  `key: {kind: link_destination, value: ...}` or a plain `text` key, and
  `required_match_count: 1`. The GFM table AST must identify one top-level table
  and one complete single-line row. Every cell, qualifier and link is hashed;
  a convenient cell is not the record. Duplicate paths, tables or keys fail.

`null` selector and hash together mean proven absence using the other origin's
identity, never parser failure. A changed container/header that prevents proving
absence is rejected. New documents without BASE remain WHOLE in this first
scope. Escaped pipes and LF/CRLF bytes are preserved. Fenced/HTML fake tables,
overlapping selections, missing hashes and ambiguous boundaries fail closed.
Canonical reference-style occurrences with block-wide offsets cannot receive a
focal v2 binding; their dependencies stay conservative. This does not change
the authored graph's lexical dependency enumeration.

The optional `envelope` list shares the record ID namespace. Every slot declares
`selectors` in both origins, both hashes, `rationale`, `context_records` and one
of these limited claims:

- `artifact_publication_date`: a `frontmatter_field` selector with an explicit
  YAML `path` and `value_shape: canonical_iso_date`.
- `declared_view_membership`: a `frontmatter_field` with
  `value_shape: unique_string_sequence`.
- `artifact_publication_date` in a `markdown_generation_paragraph`: explicit
  `container_heading_path`, `required_match_count: 1`, and a literal `template`
  with `prefix`, `suffix`, and `value_format: iso_date` or
  `iso_datetime_minutes` (`YYYY-MM-DD HH:MM`). The entire top-level single-line
  paragraph must be exactly that timestamp; links, extra sentences and
  continuations fail.

Envelope selectors/templates must be identical across origins. YAML selection
uses complete field lexemes without reserialization; duplicate/complex keys,
aliases, anchors, merges, tags and comments within selected fields are refused.
There is no arbitrary ignored span and no default volatile field list.
Calling a field `updated_at` does not establish that its meaning is publication:
semantic review must establish that claim. Norms, authority, freshness policy,
identity, interpretation and operational cadence remain real premises.

Raw changed/removed paths and the raw view node/seed are preserved in v2.
A WHOLE consumer references that raw document, which consumes all its
components through normal factual `source_ref` edges. A narrow consumer
references the reviewed component. With identical common remainder, reference
definitions, surviving order and anchors, only changed/added/removed components
receive **additional** seeds. Any uncovered delta or reordering seeds all
components. Unchanged components still enter the upstream required closure;
that inclusion does not start a new downstream traversal to their consumers.
No BFS direction, raw-source seed or policy changes.

Rows and envelope slots remain factual, freshness-checked components using the
original page metadata. WHOLE/date/hash/composition/count/rank consumers must
retain those premises. A calculation that uses `as_of` must explicitly consume
its temporal context even if its rendered text coincides on two dates. Common
FM and introduction/table-header references remain inherited; located row and
envelope references belong to their actual component. Other H2 contexts require
the existing explicit `context_records` when materially needed.

For a claim limited to canonical fields observed at a compilation cut, existing
`provenance` evidence can describe the exact per-entry read set, parent/config
hashes, algorithm/version and material parameters. File verification proves
bytes, not field correspondence: review must compare each origin's capture
with its complete parent and the actual producer. Never manufacture BASE from
CURRENT. Such an observation does not prove current external progress, access,
authority or cadence compliance. Those dependencies remain LIVE.

The public synthetic mixed example is in
[`mixed-example.json`](../../tests/fixtures/document-view/mixed-example.json).
Its captures deliberately copy two canonical fields, rather than claiming to
reproduce every production algorithm. Tests also use the actual source-registry
renderer, retaining LIVE sources and the status column's temporal premise.
Producer boundaries remain different:

| Surface | Possible entry | Premises that remain material |
| --- | --- | --- |
| Source registry | Complete source row | Recipe schedule, type/state, cadence, `as_of` and interpretation |
| Operation cockpit | Complete action/decision row | Effective state, receipt, queue/closure, alerts and aggregate vitality |
| Input stage | Complete source row | Root, channel, config, privacy, perspectives and non-rendered JSON inputs |
| Operational pass | Complete table row | Explicit next-refresh precedence, blockers, priority, top-five/order and summaries |
| Authored action index | Complete authored row/H2 | Norms, qualifications, later revocation, factual FM and current aggregates |

An authored index is not automatically generated metadata. Ranking/top-five
entries are not independent just because they are rows. Output equality never
removes a raw source/config change. A second WHOLE occurrence, BASE occurrence,
alternative factual route, cycle or stale upstream prerequisite can still
include/block a narrow consumer. A complete private migration needs one exact
reviewed packet for both origins, all declarations/bindings/contexts/evidence,
normal gates and its own PR policy. A public v2 PASS is not private adoption or
proof that existing freshness debt has disappeared.

For a read-only occurrence census and a new exact v1 transaction, follow
[authoring the complete consumption frontier](guides/software-change-records.md#authoring-the-complete-consumption-frontier).

For a complete software log/catalogue example using these existing v1
primitives, see [Software changes under living wiki rules](guides/software-change-records.md).
It preserves live norms and factual support while distinguishing reviewed
historical origins and recording destinations; it is not an automatic migration.

An optional v2 occurrence qualification can express the obligation to append
the **new canonical contribution** to the configured log. It retains the
ordinary CURRENT guard and is usable only by the opted-in contribution port
after real receipt and exact append proof; it is not a freshness exemption.
It cannot carry evidence, apply to BASE, qualify another target or survive a
changed consumer context. Historical proof requires separate reviewed C3
authorship. See [exact documentary support](guides/agent-contributions.md#exact-documentary-support-optional).
This does not refresh generated views, dates, policy or external facts.

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
