# Physical navigation migration

Moving pages changes navigation, not their historical facts or authorization.
The [Git resolver](../../../wiki_core/navigation.py) proves an old reference
without an alias registry or a copy of the old tree. The link, consolidation,
semantic-inventory and information-use audits share this resolution.

An unchanged document must have an exact committed preimage containing the
reference while its target existed. Source and target need unique, explicit
`page_id` in the configured memory root. Each move in its surviving Git lineage
must preserve the blob and file mode, except a same-commit move and the narrowly
qualified physical `moc_parent` reframing described below can preserve identity
when all other document and body bytes are unchanged. The old grouping must
already have a unique surviving identity at the reference's original revision;
its later creation or resurrection cannot establish that authority. Same-path
content revisions remain ordinary history. A moved record also needs a surviving unique identity. This works across
merge commits and when a later proposal's base already includes the migration.
Relation projections retain the literal target, Git origin and authored role;
historical link-role digests, source pins and document bytes remain untouched.
Global blob-count events (including adding/removing a source copy) never renew
a broken lineage. The physical source directory is part of a relative href's
meaning. A byte-identical source move beside a different existing target cannot
retarget the old occurrence silently, even when neither target moved. Integrity,
graph/snapshot and link readers refuse this collision. A newly authored reference
at the new location can establish its own target; it cannot borrow an earlier
blob's origin. Equal href literals alone do not prove equal relations.

An accumulating log can retain an old occurrence without claiming that its new
whole-document blob existed before the move. Every old dated
`## [YYYY-MM-DD] ...` record must survive byte for byte, uniquely and in the same
relative order. New dated records may precede, follow or separate old records.
The preamble stays exact, and original record separators and LF/CRLF bytes stay
intact. Additional blank separators may follow a preserved record; they cannot
replace or remove its old bytes. This maps complete parsed H2 records, never a
substring or whole-body prefix heuristic. Each relevant
committed version must preserve the old records and metadata; a factual detour
followed by a revert fails. Attribution maps the current occurrence offset back
to its exact original record, Git commit/path and original body offset.
Changed facts, headings, association, pins or role/digest markers, copied records
and new uses of the old URL do not qualify.
Callers with repeated URLs must supply the individual body offset; an ambiguous
occurrence cannot borrow another record's proof. This is not general similarity
matching or permission to rewrite a log, digest or pin. A log's `updated_at` may
reflect new entries. A `moc_parent` change requires the separately qualified
physical hierarchy contract below; other metadata stays semantically exact.

Generated output resolves references at its actual source. The ingestion-closure
compiler projects proven canonical targets with event-origin provenance; the
snapshot derives relations from that event too. A freshly compiled projection
does not need (and cannot assert) its own historical whole-blob preimage.
The original event bytes, verification date, consumed revision and role digest
remain intact. Unsupported source references remain subject to ordinary gates.

An actual inline occurrence in a committed document or a uniquely preserved
dated log record can also prove that a **directory address** existed as a Git
tree at its origin. This is historical address evidence only: it supplies no
current directory or page target, and does not satisfy page requirements,
consolidation evidence, or grant access. A missing original tree, a duplicated
or altered occurrence, or ambiguous origin refuses the link. If the old path
was removed and later occupied again, or a moved source would redirect its
relative href to a different directory, the link audit reports the collision.
The children may have moved to several locations; no equivalent current
directory is inferred. The repository host must qualify Git history and reads.

Missing history, identity collisions, deletion/resurrection, copies with the
same identity, symlinks, nested repositories and unsafe paths cannot establish
relocation. Reoccupying a former path cannot steal an unchanged record's
historical identity. A newly authored or changed document cannot acquire an old alias.
Only an origin with a coexisting explicit memory target can establish relocation;
missing targets and non-memory artifacts do not trigger a page-lineage proof.
Artifact references remain subject to their ordinary checks.
Current information requirements must name the canonical target. Historical
requirements retain their original consumed revision and original target;
query/policy authority is not transferred through relocation. Both routes check
identity before accepting an existing path. An original pin cannot describe a
different occupant, including after the consuming document gains a new blob.
An obsolete current path requires explicit reconciliation, rather than losing
its obligation in a future freshness proposal. A historical path which is now
occupied ambiguously fails closed; an unoccupied proven move keeps the original
pin and projects the canonical identity.

Resolution is discovery only. Callers must still enforce the destination's
owner, context, route and access policy. It grants no source reading, execution,
refresh, promotion or secret access. Raw Markdown retains its historical URLs;
this does not install filesystem aliases or redirects on a Markdown host.

## Upgrading

Adopt the code through the [normal B0/C1/C2/C3 PR](../../../AGENTS.md).
Use an explicit consumer-owned C3 adapter for the selected navigation scope:

1. Preserve a clean approved base and fetch sufficient Git history. Keep all
   domain data in the consumer. Do not change freshness bases to hide a diff.
2. Commit the reviewed physical moves preserving executable mode. Identical
   bytes establish the normal move. A simultaneous move and narrowly qualified
   `moc_parent` change can establish the same identity under the checks above;
   other simultaneous rewrites are not established by this resolver. Keep
   source records, historical declarations, curation and authority intact. A
   simultaneous move and factual rewrite does not prove relocation.
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
   structural versions precede native, content-bound writer versions. It selects
   all commits newly reachable in `base..HEAD`, including a merged branch forked
   before the base. Every merge parent participates: an excluded parent retains
   its actual already-approved action version as a boundary, without reauditing
   all approved history. Clean side branches pass. A factual
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

### Qualified physical hierarchy reframing

A C3 structural stage may correct an old grouping such as `alpha` to an existing
qualified `organization-beta/project-gamma/index.md`. The old grouping need not
be an ancestor of the new project and can itself remain a `project` page rather
than being relabeled as a context hub. Such a grouping page may point to the
preferred index in its own folder; another same-folder page cannot serve as
that physical index. The old grouping must exist with one unique page identity
in the original audited base; a proposal cannot introduce it later or substitute
another occupant or resurrect it after deletion before the structural change.
A conventional `index.md`/`README.md` may be a
`project`; it need not be relabeled `context_hub`. Editorial `context` labels and
`sources_policy` curation may differ among grouping indexes. The action retains
its own context, owner, lifecycle, facts, dates, history and body bytes. The
ancestry gate checks the real committed stage before native writer edits against
the original approved base.

The physical route uses the same entry/index selection and instruction-chain
inspection as [context_packet](../../../wiki_core/context_packet.py). It needs
nonempty committed instructions and an entry index, distinct unique page IDs,
real enclosing index ancestry and a destination inside the selected project's
subtree. A declared parent cannot skip a nearer physical index. The route stays
within one effective physical context, with existing read authority on the
grouping/index chain and write scope on the selected source/destination. Equal
human owners or read connections do not authorize cross-context writing. The
previous narrow direct-child `context_hub` transformation remains supported.

Normal host binding and preflight remain required for a protected caller:
`prepare_packet` qualifies the approved physical entry and exact C3 evidence;
`prepare_preflight` rechecks the same trusted policy, complete changed-path set
and actual write authority. Neither the structural audit nor a Git blob grants
access. Existing nested folder contexts still need their own current binding and
owner checks; this route does not migrate ACLs or authorize a cross-owner move.
No access entry, bilateral connection or new approval mechanism is generated.

The public positive fixture has a root physical context with existing explicit
writes limited to `memories/actions` and
`memories/organization-beta/project-gamma`, root instructions/entry, and distinct
editorial organization/project indexes inheriting that boundary. Its bound
preflight sees exactly the old action deletion and new action creation; its
result still requires independent review. The old shape-only probes lack these
physical/binding prerequisites and are not promoted to authorized projects.

Preserved dated logs can also change only `moc_parent` under this qualified
contract, with exact old records and committed physical moves. Arbitrary projects,
missing instructions/binding, read-only scope, owner/access changes, false
hierarchy, record transplant or mixed factual stages remain refused. Neither
group becomes an identity alias. The body-only terminal writer acquires no
general hierarchy/frontmatter patch API.

Git parents, object metadata and identity parses are cached only within one
invocation. Identical memory trees share their identity inventory. The bounded
ancestry read, document/link parses, record mappings and record-lineage checks are
reused across occurrences; missing/truncated history fails closed. Writes still
recheck HEAD, selected identity uniqueness, mode and exact
bytes. This reduces repeated local work without a global cache or latency SLA.

## Synthetic verification

[The regression suite](../../../tests/test_navigation_migration.py) creates
local Git repositories for historical links and consolidation, terminal CAS
reconciliation, structural-stage/receipt chains, merged/future proposals and
the context renderer. It exercises missing/ambiguous/unsafe identity, deletion,
resurrection, body/frontmatter tampering, fabricated/off-branch intermediates
and unchanged historical bytes. It also covers post-stage factual detours and
reverts, each new CAS, exact CRLF frontmatter, distinct parent/child hubs,
preserved dated log occurrences and source-derived fresh projections.
[Identity regressions](../../../tests/test_navigation_integrity.py) cover pinned
reoccupants, relative-source collisions, explicit current reconciliation and
clean/detour branches forked before the base. [Qualified capability
fixtures](../../../tests/test_navigation_capacity.py) cover alpha → organization
beta/project gamma through normal host preflight, preserved newest-first records,
mapped offsets, structural log metadata and their authority/identity negatives.
They qualify missing physical prerequisites explicitly, without changing the
retained shape probes. The
original snapshot cache/parity test is unchanged. No consumer artifacts are
test inputs.
