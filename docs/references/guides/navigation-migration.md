# Physical navigation migration

Moving pages changes navigation, not their historical facts or authorization.
The [Git resolver](../../../wiki_core/navigation.py) proves an old reference
without an alias registry or a copy of the old tree. The link, consolidation,
semantic-inventory and information-use audits share this resolution.

An unchanged document must have an exact committed preimage containing the
reference while its target existed. The target needs a unique, explicit
`page_id` in the configured memory root. Each move in its surviving Git lineage
must preserve the blob and file mode. Same-path content revisions remain ordinary
history. A moved record also needs a surviving unique identity. This works across
merge commits and when a later proposal's base already includes the migration.
Relation projections retain the literal target, Git origin and authored role;
historical link-role digests, source pins and document bytes remain untouched.

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
   with its exact current SHA-256 and the proposed body. The adapter retains
   normal authorization and route checks. The writer accepts only real inline
   Markdown destination changes to the same proven page, keeping labels,
   fragments, queries, code, images and other body bytes. It preserves the
   original frontmatter bytes, including owners, states, facts, dates and
   transition receipts. Existing typed historical occurrences stay intact;
   regenerate current projections through their owning producer.
4. Commit the structural reconciliation before subsequent ordinary writer
   edits. The [action audit](../../../scripts/wiki_audit.py) keeps the original
   approved base and validates every intervening action version as structural.
   Only a committed ancestor whose exact bytes and revision match the first
   receipt's preimage can bridge to the ordinary receipt chain. It also checks
   that subsequent content and frontmatter differences are bound by that chain.
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

## Synthetic verification

[The regression suite](../../../tests/test_navigation_migration.py) creates
local Git repositories for historical links and consolidation, terminal CAS
reconciliation, structural-stage/receipt chains, merged/future proposals and
the context renderer. It exercises missing/ambiguous/unsafe identity, deletion,
resurrection, body/frontmatter tampering, fabricated/off-branch intermediates
and unchanged historical bytes. No consumer artifacts are test inputs.
