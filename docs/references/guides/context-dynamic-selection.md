# Authorized dynamic collections

Dynamic selection uses the existing [repository reader](../../../wiki_core/repository_reader.py)
and [task packet](../schemas/wiki-task-context-v1.schema.json). It builds no
snapshot, persistent index, additional graph or background process. Exact evidence
selectors and their existing callers remain unchanged.

A trusted coordinator may add up to eight `queries` to the task accepted by
[protected coordination](context-coordination-protected.md), or by
[the context CLI](../../../scripts/wiki_context.py). Each query names an existing
collection contract and a literal descendant scope. For example, a synthetic
owner with a `source_catalog` page identified by `page_id: cost-collection` at
`finance/costs/index.md` may request:

```json
{
  "target": "finance/costs/index.md",
  "reason": "Assess the declared collection",
  "use": "interpret",
  "classification": "synthetic",
  "query": {
    "scope": "finance/costs/items",
    "filters": {"status": "active"},
    "field": "amount",
    "max_enumerated": 100,
    "max_matches": 20,
    "max_scan_bytes": 500000
  }
}
```

The anchor must have a nonempty stable page ID and existing `context_hub`, `ontology_index`,
`source_catalog` or `root_entity` type from the existing page contract. Its directory must contain the scope;
the scope may be that same directory. The anchor is structurally excluded
from member selection and enumeration, declared as `excluded_anchor` in the
receipt and bound into query identity. Its full body remains one required input
and counts against the read and packet budgets. An arbitrary filename or
`index.md` alone establishes no collection role. Both anchor and scope belong
to the selected owner under **current approved policy**. A scope directly in
another context or a denied prefix is refused. A valid broader owner scope
excludes subcontexts and denied paths before opening or counting their blobs.
This initial query interface offers no cross-owner collection imports, even
when an exact evidence connection exists. Use the existing exact selector for
an approved import. A folder packet with additional readers currently refuses
queries and requires separate requalification; an allowlist is not itself a
grant to expand the query.

The universe is tracked, regular, safe UTF-8 Markdown inside that authorized
scope, with page identity in frontmatter. Markdown without frontmatter/page ID
is not a page; malformed frontmatter, duplicate YAML keys, duplicate page IDs,
non-UTF-8 content/path, unsupported YAML aliases and nonregular candidates fail closed.
Protected JSON requests also reject duplicate keys and non-finite values. Unsafe credential
paths are excluded by the reader and never become catalog members. Invalid
candidates outside the authorized scope are not opened or described. All
predicate keys and values are untrusted; secret detection rejects a request or
metadata without echoing the value. Filters are AND of exact **typed scalar**
equalities. A list of up to 16 distinct scalar values means OR for that field;
it is not substring search or membership in a page's list. No glob, expression,
regular-expression predicate or implicit page-ID lookup is supported.

Each query must supply all three local limits: `max_enumerated` (1–1000),
`max_matches` (1–128) and `max_scan_bytes` (1–2000000). The byte ceiling counts
the anchor and every authorized candidate blob, including nonmatches; Git blob
sizes are checked before opening them. With eight queries, their declared read
ceilings sum to at most 16000000 bytes, conservatively counting shared blobs
again. Authorized revalidation/impact also stops at a conservative 32000000
selection-read bytes per invocation across historical/current comparisons,
including repeated/shared blobs. If that ceiling is reached, reduce the explicitly
authorized operation; no partial report is certified. This limits selection work separately from the complete canonical packet
`max_bytes` and from mandatory policy inputs. These are byte limits, not token,
latency or exact process-memory guarantees. Any exceeded limit blocks the whole
packet without truncation or partial results. The protected route gives an
opaque recoverable blocker; no protected path/count is included in errors.

Receipts bind the normalized predicate, excluded anchor, owner-selected members
and fixed content SHA. They also retain the fixed selection `policy_revision`
and an `authority_digest` of relevant owner/read/deny boundaries and excluded
subcontext roots. No protected boundary paths are exposed by that digest. `members_digest` identifies the ordered path/page-ID set;
`selected_digest` identifies the actual consumed selectors plus the complete
anchor contract. Revision provenance and the packet's `query_fingerprint` are
separate: changing a revision is not itself a membership change. An empty query
has the same reproducible identities and means no matches **in this authorized
universe at that revision**, never global absence. Each member's selected body,
section or field is delivered as real text. The anchor body and mandatory
lineage bodies are also delivered, with all delivered inputs in the read set.

A completed [task result](../schemas/wiki-task-result-v1.schema.json) must report
all delivered `observed_refs` and every receipt's `query_id` in
`read_coverage.observed_queries`. This is reported coverage, not proof of
comprehension. Before an effect or merge, the coordinator must revalidate current
policy and the historical selection against the current approved base.
[Preflight](context-impact-integration.md) performs that check, including newly
matching/removed pages even if all previously consumed bytes stayed unchanged.
It also compares against the exact proposed HEAD, refusing a proposal that
changes its consumed collection or makes the consumer one of its own members.
It does not perform an effect or approve a merge.

## Canonical dependency and later invalidation

The existing `information_requirements` entry keeps `target` equal to the
collection anchor, `fields: ['*']`, temporal policy, fixed `consumed_revision`,
`use` and `classification`. It additionally keeps the **whole query descriptor**,
`members_digest`, `selected_digest`, `query_policy_revision` and
`authority_digest`. Historical authority is reconstructed from that fixed
approved ancestor for proof only. Its relevant coverage must equal current
authority before any historical candidate blob is opened. Changed or unknown
coverage requires requalification; comparing two sets already filtered under
a newly narrowed policy cannot establish equivalence. An unrelated documentary
commit with the same relevant authority does not invalidate just by SHA.
All effective content reads still use current permission. Do not replace it with a list of the
original matches: that would lose additions and empty-to-nonempty transitions.
The same requirement is preserved on the existing inventory edge. Preflight
accepts a new query requirement only when its descriptor and digests exactly
match the packet and its reported reads. An unchanged existing query requirement
on an edited consumer is also revalidated; an explicit-only packet cannot carry
a stale set receipt through preflight. The `requirements` command proposes
that same declaration after synthetic/real approved incorporation; it writes
nothing. Older parsers/schemas reject the extra query fields rather than
silently treating only the hub as the dependency.

Use [the finite flow CLI](../../../scripts/wiki_context_flow.py) for current
revalidation or immediate one-hop review candidates:

```sh
python3 scripts/wiki_context_flow.py --repo REPO --approved-revision APPROVED_SHA \
  revalidate --context OWNER --consumer CONSUMER.md
python3 scripts/wiki_context_flow.py --repo REPO --approved-revision APPROVED_SHA \
  impact --context OWNER --consumer CONSUMER.md --before BEFORE_SHA --after AFTER_SHA
```

The [revalidation schema](../schemas/wiki-context-query-revalidation-v1.schema.json)
separates these checks from factual readiness. `revalidate` checks the declared historical digests under current authority and
reports whether current members and selected bytes are equivalent. A changed
predicate value on a page, addition, removal or relevant selected value creates
an impact candidate without editing the hub. Unselected content and changes
outside the selection do not create a candidate. No scan is scheduled: an
integrator invokes these checks at its admission boundary, then follows normal
independent review and final-head gates.

Generic graph readiness/impact lacks current context authority and therefore
reports that an affected dynamic query needs authorized revalidation; it cannot certify
only the anchor. The authorized result supplies useful **set/byte equivalence**,
with `fact_freshness: not_assessed`. Equivalence does not establish verification,
external observation or readiness for a factual decision; those existing gates
still apply. Current revocation blocks revalidation rather than preserving an
old grant. YAML, Git, links and query receipts remain declarations/provenance,
not filesystem or service isolation.

## Change-scoped audit

The impact audit treats a query as affected when the consumer, anchor, scope,
context policy or declared normative inputs change, or when dependency
propagation reaches its consumer. An unrelated change does not require every
query to be rescanned. A change to `wiki.config.yaml` is compared against the
relevant authority; an equivalent unrelated section does not by itself require
replaying the query. When a current operation depends on a selection whose
authority or content cannot be requalified, that dependency remains a blocker.
An old v1 receipt with no verifiable authority is instead queued for
requalification on demand when it is not a current dependency; it is not
silently treated as fresh.

This audit materializes a global graph before applying any query binding. It
is a caller-trust tool for an explicitly authorized **global integration
operator**; its output and logs are private. `--query-context` limits only
query recomputation. It is not an ACL or isolation boundary for the audit as a
whole. A scoped executor must not run this audit or receive its global output;
use the owner-only context flow for scoped reads instead.

A trusted global integration operator can bind one context to a clean, exact
proposal for in-process revalidation; no supplied receipt file is accepted:

```sh
python3 scripts/wiki_audit.py --check --freshness-base APPROVED_SHA \
  --query-context CONTEXT --query-policy-revision APPROVED_SHA --query-head PROPOSAL_SHA
```

The policy revision must equal the current trusted approval ref and the audit
base; the proposal HEAD must be exact, committed and clean. Query recomputation
is limited to the selected context. The query-revalidation result reports that
coverage outside it was not assessed, without identifying or counting
unauthorized queries or edges. This does not scope the surrounding global graph.
The audit recomputes historical, approved-base and
proposal selections under current authority. A changed set for an unchanged
consumer produces a pending interpretation review; a proposed policy or
normative change instead produces pending requalification under the approved
base policy without evaluating proposed grants. An edited consumer combined
with such a change remains blocked; an edited consumer must
instead declare a valid equivalent current selection. A replacement after
revocation is verified under current permission without opening revoked
historical members. Removing a requirement is not a substitute for review.
These checks establish set and selected-byte equivalence only; they do not
assess factual freshness, run preflight, grant an effect or approve integration.


A revalidated changed collection creates a pending interpretation obligation,
not a claim that its consumer's facts changed. Existing typed information-change obligations may trigger relevant query
recomputation; they do not rerun the generic graph traversal or turn unrelated
ordinary impact into a context boundary. The query closure uses a separate
in-memory projection of explicit current `information_requirements`, authored
operational-prerequisite roles, and declared projections. Legacy Markdown links,
`source_ref`, navigation and historical links remain in the global caller-trust
impact report, but do not alone establish current consumption for query closure.
A typed path remains effective even when a legacy path reaches the same page.
Both the generic audit's query blockers and the bound audit's affected-query
selection use this typed reach, together with direct changes to the consumer,
anchor, scope or policy. They do not treat a legacy-only reach as an affected
query in another context. When typed paths converge, every reached cause is
checked under current authority before it can seed scoped closure; an urgent
denied upstream remains a blocker even if another typed path is authorized.
An inactive downstream reached only from an on-demand obligation retains
on-demand priority; a currently active or directly affected dependency can
require immediate review or block when its authority remains unknown.
This does not authorize reading any source, remove global pending reviews or
mark information verified. Ordinary age debt does not seed closure. The scoped audit follows existing
typed nonhistorical consumption edges from that obligation and checks whether a
downstream query contains a pending member and consumes a potentially affected
field, or an authorized candidate currently excluded from the set has a pending
filter field (or page identity) that could admit it. A pending selected field
alone does not admit an excluded candidate. These create separate upstream-pending review reasons; byte
equivalence alone does not discharge them. Navigation and historical relations
do not propagate. This closure remains within the bound owner and current read
authority. A boundary required by the current operation can block; other
contexts are outside the selected coverage, not silently certified complete.
Cycles are deduplicated and finite limits (including the shared query
read budget) fail closed. Validated query selections are reused only within the
same fenced audit operation; failed proofs are not cached. The surrounding audit remains global `caller_trust`;
the query binding is not an ACL for the global graph or its output.

A legacy historical query may be removed when its page is explicitly
superseded and inactive. Its previous declaration remains in the approved Git
history; the audit reports the retirement without claiming revalidation.
Review changed consumers as usual. Current and folder-authority queries do not
use this retirement path.
