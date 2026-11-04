# Experimental explicit multi-owner requalification

`wiki_core.folder_requalification_batch_v2` is a synthetic, internal
caller-trust coordinator prototype. It accepts 1–16 explicit v1 requirement
selections, each with its own folder, selected context index, consumer,
requirement index, original v1 packet and result, and fixed proposal revision.
It does not discover consumers, infer grants from the batch, or create a new
registry. Each packet budget is capped at 1 MB and the supplied batch at
16 MB. All results remain separate `review_pending` proposals.

Before opening selected consumers, sources or historical bodies, the batch
checks every selected consumer's current owner and read/write limits, every
index's current owner/read permission, the v1 packet/result bindings, all
current evidence connections and denies. It checks all instruction-path denies
before opening any current instruction chain. It then opens the selected
`AGENTS` chains to verify declared indexes and mandatory references for every
item. The host-authorized global coordinator next checks v1 ownership and
read/write limits at the consumed-content, packet-policy and proposal
revisions, as well as source ownership and bilateral connections at those
three revisions. It checks the packet policy's mandatory declarations and
denies. It verifies ancestry before opening those
historical manifest bodies. Only after these checks can it read selected
consumer or source bodies. Cross-owner evidence
still requires the exact current bilateral connection; a list of selections
never grants access. User-declared instruction references are not themselves
permissions.

The host must independently authorize the coordinator to read the full v1
historical manifest set required by the legacy global loader. The function does
not establish caller identity or enforce an ACL, and cannot convert a role label
or a boolean into proof of authority. Historical policy and Git ancestry are
not independent evidence of historical approval. The result retains the
original requirement and revisions; it performs no write or migration and does
not prove execution or factual freshness. A later policy revision can make the
whole batch fail closed.

Only individually requalifiable explicit v1 requirements are supported. V1
queries remain blocked; no historic query digest is reused as v2. Auxiliary
instruction folders that cannot be qualified through the existing individual
coordinator, unknown owners, missing or revoked bilateral grants, failed packet
reproduction and changed or unverifiable selections fail closed. This prototype
has no CLI, executor integration, published schema or consumer inventory; it
requires independent review and synthetic tests before any downstream use.
