# Physical navigation migration

Moving pages changes navigation, not their historical facts or authorization.
The [Git resolver](../../../wiki_core/navigation.py) proves an old reference
without an alias registry or a copy of the old tree. The link, consolidation,
semantic-inventory and information-use audits share this resolution.

An unchanged document must have an exact committed preimage containing the
reference while its target existed. Source and target need unique, explicit
`page_id` in the configured memory root. Each move in its surviving Git lineage
must preserve the blob and file mode. Same-path content revisions remain ordinary
history. A moved record also needs a surviving unique identity. This works across
merge commits and when a later proposal's base already includes the migration.
Relation projections retain the literal target, Git origin and authored role;
historical link-role digests, source pins and document bytes remain untouched.
Global blob-count events (including adding/removing a source copy) never renew
a broken lineage. Graph/snapshot readers also refuse a former path's distinct
occupant instead of displaying a valid edge to the wrong identity.

An append-only log can retain an old occurrence without claiming that its new
whole-document blob existed before the move. The resolver accepts only an exact
body prefix from a committed source of the same surviving identity. The old
occurrence must lie within a dated `## [YYYY-MM-DD] ...` record, and the addition
must start a new dated record. The old body prefix must survive every relevant
committed version. Attribution records the original Git commit/path and exact
body offsets/record boundaries. Changed facts, headings, association or role
markers, copied records and newly appended uses of the old URL do not qualify.
Callers with repeated URLs must supply the individual body offset; an ambiguous
occurrence cannot borrow another record's proof. This is not general similarity
matching or permission to rewrite a log, digest or pin.

Generated output resolves references at its actual source. The ingestion-closure
compiler projects proven canonical targets with event-origin provenance; the
snapshot derives relations from that event too. A freshly compiled projection
does not need (and cannot assert) its own historical whole-blob preimage.
The original event bytes, verification date, consumed revision and role digest
remain intact. Unsupported source references remain subject to ordinary gates.

Missing history, identity collisions, deletion/resurrection, copies with the
same identity, symlinks, nested repositories and unsafe paths cannot establish
relocation. Reoccupying a former path cannot steal an unchanged record's
historical identity. A newly authored or changed document cannot acquire an old alias.
Current information requirements must name the canonical target. Historical
requirements retain their original consumed revision and original target;
query/policy authority is not transferred through relocation.

Resolution is discovery only. Callers must still enforce the destination's
owner, context, route and access policy. It grants no source reading, execution,
refresh, promotion or secret access. Raw Markdown retains its historical URLs;
this does not install filesystem aliases or redirects on a Markdown host.

## Upgrading

Adopt the code through the [normal B0/C1/C2/C3 PR](../../../AGENTS.md).
Use an explicit consumer-owned C3 adapter for the selected navigation scope:

1. Preserve a clean approved base and fetch sufficient Git history. Keep all
   domain data in the consumer. Do not change freshness bases to hide a diff.
2. Commit the reviewed physical moves with identical bytes and executable
   mode. Keep source records, historical declarations, curation and authority
   intact. A simultaneous move and factual rewrite does not prove relocation.
3. Reconcile current references to canonical destinations. For an action body,
   use [reconcile_action_navigation](../../../wiki_core/action_transition.py)
   with the SHA-256 of its exact current file bytes and the proposed body. CRLF
   is part of those bytes; a hash of newline-normalized text is not its CAS.
   The adapter retains
   normal authorization and route checks. The writer accepts only real inline
   Markdown destination changes to the same proven page, keeping labels,
   fragments, queries, code, images and other body bytes. It preserves the
   original frontmatter bytes, including owners, states, facts, dates and
   transition receipts. Existing typed historical occurrences stay intact;
   regenerate current projections through their owning producer.
4. Commit the structural reconciliation before subsequent ordinary writer
   edits. The [action audit](../../../scripts/wiki_audit.py) keeps the original
   approved base and validates the complete relevant ancestry through HEAD:
   structural versions precede native, content-bound writer versions. A factual
   detour after the stage remains refused even when a later commit reverts it.
   Only a committed ancestor whose exact bytes and revision match the first
   receipt's preimage can bridge to the ordinary receipt chain. It also checks
   that subsequent content and frontmatter differences and every new receipt's
   exact pre-write hash/revision are bound by that chain. Existing committed
   preimages are used directly. Where unchanged values and body material remain
   available, the native canonical prefix can be checked against both stored
   hashes without creating a Git ancestor or changing a receipt. If an overwritten
   intermediate is unavailable, retain/recover the actual preimage on the proposal
   chain; hashes alone cannot recover its values. Old receipt history is not
   rehashed or migrated.
   A dangling blob, unrelated branch, fabricated intermediate, factual detour
   or broken CAS is refused. Do not rehash old receipts or rewrite history.
5. Regenerate the operational pass with its existing generator, then run the
   consumer's normal audits, scoped freshness, gates and independent PR review.
   The renderer links context labels to their declared hubs; absent hubs remain
   visible rather than acquiring guessed destinations.

`page_edit` and `integrate_action_body` also admit this strictly structural
body reconciliation on `done`/`cancelled` actions, with CAS. The result has an
empty lifecycle `receipt_id`: this is a Git-reviewed navigation change, not a
new action event or a fresh verification. All other terminal body/owner/title
edits remain refused. Ordinary nonterminal edits retain native receipts.

If a consumer already emitted valid receipts against an uncommitted structural
preimage, retain the original bytes, receipts and proposal. Commit the actual
reviewed structural stage on its authorized proposal chain before applying the
unchanged writer result, then audit against the original base. If that exact
preimage or its structural lineage cannot be recovered, the gate stays closed;
an arbitrary Git blob or a newly chosen base is not a repair.

Reversibility and promotion remain the consumer PR. There is no new migration
certificate, historical recertification or reusable authorization receipt.

### Restricted hierarchy reframing

A C3 structural stage may change an action's scalar `moc_parent` from a real
`context_hub` to its directly declared child hub, including while moving the
action into the child's physical subtree. Both hubs must have distinct, unique
IDs in the committed stage, the same explicit context and equal owner/access
policy fields. The action retains its context, owner, lifecycle, facts, dates,
history and body bytes. The ancestry gate checks the actual committed stage
before any ordinary writer edit and retains the original approved base.

This is hierarchy construction, not identity relocation: neither hub becomes an
alias. Non-hubs, unrelated hubs, unsafe paths, policy changes and mixed factual
stages fail closed. The body-only terminal writer does not acquire a general
hierarchy/frontmatter patch API. Operator authorization, owner and route checks
remain the caller's responsibility; this predicate grants none of them.

Git parents, object metadata and identity parses are cached only within one
invocation. Identical memory trees share their identity inventory. The bounded
ancestry read is reused across resolutions; missing/truncated history fails
closed. Writes still recheck HEAD, selected identity uniqueness, mode and exact
bytes. This reduces repeated local work without a global cache or latency SLA.

## Synthetic verification

[The regression suite](../../../tests/test_navigation_migration.py) creates
local Git repositories for historical links and consolidation, terminal CAS
reconciliation, structural-stage/receipt chains, merged/future proposals and
the context renderer. It exercises missing/ambiguous/unsafe identity, deletion,
resurrection, body/frontmatter tampering, fabricated/off-branch intermediates
and unchanged historical bytes. It also covers post-stage factual detours and
reverts, each new CAS, exact CRLF frontmatter, distinct parent/child hubs,
preserved dated log occurrences and source-derived fresh projections. The
original snapshot cache/parity test is unchanged. No consumer artifacts are
test inputs.
