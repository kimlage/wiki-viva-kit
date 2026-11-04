# Experimental separate query anchor, v3

This synthetic-only internal prototype separates the context index from the
collection anchor. The caller explicitly selects both: the index remains subject
to the existing v2 folder declaration and ownership checks, and the anchor
must itself be readable under the same owner. A Markdown link is not a grant.

`wiki_core.folder_query_anchor_v3.build_anchor_query_packet_v3` accepts a
current, reproduced v2 base packet and one query. Before reading packet or query
bodies, it checks the index, anchor, entire query scope and every explicit
packet evidence input under current policy. Nested owners, denied paths,
ambiguous instruction folders, unsupported Git objects, auxiliary starts,
historical content and budget overruns fail closed. It returns the actual
anchor body separately as a required reported input, along with selected source
bodies and a new v3 receipt and identity. The full envelope shares the base
packet byte budget.

`preflight_anchor_query_v3` reconstructs the packet, requires reports for all
base inputs, the anchor and selected results, and rejects any proposal changing
the anchor, index or query scope before reading proposal bodies. It delegates
other checks, including whole prior output evidence for modifications and
deletions, to existing v2 preflight. Its result remains
`independent_review_required`; a reported read is not execution evidence.

This is a separate internal candidate with no CLI, published JSON schemas,
historical replay, impact traversal, consumer discovery, v1/v2 receipt conversion
or automatic activation. It does not establish native instruction loading,
access enforcement, equivalence to a historic query, independent review or
merge approval. The host must enforce actual access. Synthetic tests alone do
not authorize use in a downstream wiki.
