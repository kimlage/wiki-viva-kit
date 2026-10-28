"""Verified structural limits for the existing occurrence-bound causal review.

These helpers do not approve meaning or suppress factual prerequisite checks.
"""
from __future__ import annotations

import copy
from collections import Counter, defaultdict, deque

from wiki_core.document_records import digest, substantive_digest


def scope_identity(graph, node, *, correspondences=None):
    return dict(document=graph.get('verified_record_documents', {}).get(node, node),
                selection=(correspondences or {}).get(node,
                    graph.get('verified_record_shapes', {}).get(node, 'whole_document')),
                evidence=graph['nodes'][node].get('evidence_source'))


def qualified_documentary_deltas(base, current, documentary_edits):
    """Derive comparison support from existing, independently reviewed proofs.

    No authored waiver or new plan language is accepted. Geometry is supplied
    only by the native projector. These correspondences never alter either
    graph, the census or freshness; same-seed arrivals still grant causal use.
    """
    from wiki_core.document_records import edge_digest, structured_digest
    from wiki_core.freshness_impact import REFERENCE

    verified = (set(documentary_edits) | set(current.get('verified_record_observations', {}))
                | set(current.get('verified_record_reviews', {})))
    correspondences, retired = {}, set()
    partitions = current.get('verified_h2_partition_changes', {})
    if partitions != base.get('verified_h2_partition_changes', {}):
        raise ValueError('partition correspondence requires the same projected pair')
    for path, proof in partitions.items():
        if not set(proof['changed_components']) <= verified:
            continue
        old, new = proof['base_shapes'], proof['current_shapes']
        # All changed components need their own qualification. An insertion
        # receipt never certifies a simultaneous rewrite of an old sibling.
        gone = set(old) - set(new)
        if any(not documentary_edits.get(node, {}).get('retired') for node in gone):
            continue
        retired.update(gone)
        for node in old.keys() & new.keys():
            if old[node] != new[node]:
                correspondences[node] = copy.deepcopy(old[node])

    def literal_signature(row):
        # Roles, labels, Markdown style and positions do not erase a reference
        # to the same destination. Repeated uses remain ambiguous and closed.
        return structured_digest(dict(consumer=row['consumer'], target=row['raw']['target']))

    occurrences = [graph.get('verified_record_body_occurrences', []) for graph in (base, current)]
    counts = [Counter(literal_signature(row) for row in rows) for rows in occurrences]
    removed_edges = set()
    for row in occurrences[0]:
        proof = documentary_edits.get(row['consumer'])
        if not proof or proof.get('retired'):
            continue
        key = literal_signature(row)
        # Repeated indistinguishable uses do not prove which occurrence was
        # removed. A surviving literal whose binding changed is not a deletion.
        if counts[0][key] == 1 and counts[1][key] == 0:
            removed_edges.update(row['projected'])
    for raw in base['edges']:
        consumer = raw['source'] if raw['type'] in REFERENCE else raw['target']
        if (consumer in retired or raw.get('basis') == 'document_record.v2'
                and raw.get('field') == 'document_components' and raw['target'] in retired):
            removed_edges.add(edge_digest(raw))
    return dict(scopes=correspondences, retired=sorted(retired), removed_base_edges=sorted(removed_edges))


def repaired_boundary(base, current, node, *, documentary_deltas=None):
    """A complete, substantively repaired unit with unchanged declared scope."""
    from wiki_core.causal_review import _document
    if node not in base['nodes'] or node not in current['nodes']:
        return False
    try:
        before, after = _document(base, node), _document(current, node)
    except ValueError:
        return False
    qualifications = documentary_deltas or {}
    scopes = qualifications.get('scopes', {})
    removed_edges = set(qualifications.get('removed_base_edges', []))
    if before != after or scope_identity(base, node, correspondences=scopes) != scope_identity(current, node, correspondences=scopes):
        return False
    if substantive_digest(base['documents'][before]) == substantive_digest(current['documents'][after]):
        return False
    if node not in current['documents']:
        old = base.get('verified_record_substantive_sha256', {}).get(node)
        new = current.get('verified_record_substantive_sha256', {}).get(node)
        if old is None or new is None or old == new:
            return False
    # Stopping interpretation at a repaired unit must not hide a narrowed
    # selection anywhere in its already-consumed factual context. The only
    # equivalent shape changes require the projector's exact append-only or
    # independently qualified complete-partition proof.
    from wiki_core.causal_review import _interpretation_state
    old_scopes = _interpretation_state(base, node, append_equivalence=True,
        scope_correspondences=scopes, ignored_edges=removed_edges)['scopes']
    new_scopes = _interpretation_state(current, node, append_equivalence=True,
        scope_correspondences=scopes)['scopes']
    if any(new_scopes.get(prerequisite) != scope for prerequisite, scope in old_scopes.items()):
        return False
    # A repaired upstream unit does not authorize loss/reclassification of any
    # already-consumed transitive relation or changed mandatory context. Scope
    # equality alone misses removal when another path still reaches the same
    # prerequisite. Freeze the BASE consumer closure for both sides; genuinely
    # new nodes remain additional factual premises, without inventing BASE uses.
    # Exact unique relocation remains reviewed by the arrival declaration.
    from wiki_core.causal_review import _normalized_interpretation_edge
    from wiki_core.document_records import edge_digest, structured_digest
    from wiki_core.freshness_impact import REFERENCE, STRUCTURAL, ASSOCIATION
    states, contexts, occurrences = [], [], []
    for graph in (base, current):
        edges, local_context, exact = [], [], defaultdict(list)
        for raw in graph['edges']:
            if graph is base and edge_digest(raw) in removed_edges:
                continue
            if raw['type'] in STRUCTURAL | ASSOCIATION:
                continue
            consumer = raw['source'] if raw['type'] in REFERENCE else raw['target']
            if consumer not in old_scopes:
                continue
            edge = _normalized_interpretation_edge(raw)
            full = structured_digest(edge)
            edge.pop('body_section', None)
            edge.pop('section', None)
            signature = structured_digest(edge)
            edges.append(signature)
            exact[signature].append(full)
            if raw.get('field') == 'context_records':
                local_context.append(structured_digest(edge))
        states.append(Counter(edges));contexts.append(Counter(local_context));occurrences.append(exact)
    if contexts[0] != contexts[1]:
        return False
    for key, count in states[0].items():
        # Additional uses are allowed only when every old semantic occurrence
        # survives, including its section and multiplicity. They remain factual
        # premises in the pair/census and still require freshness and review.
        if Counter(occurrences[0][key]) <= Counter(occurrences[1][key]):
            continue
        # An old use that disappeared may only be the existing uniquely
        # reviewed relocation. Relocation plus duplication is ambiguous.
        if count != 1 or states[1][key] != 1:
            return False
    return True


def updated_paths(inventory, decisions):
    """Reachability from each seed through validated updated arrivals only.

    No traversal crosses a potential no_change/revalidated/blocked arrival.
    Cycles cannot manufacture a first proof of reachability.
    """
    downstream = defaultdict(list)
    for oid, item in decisions.items():
        if item['disposition'] != 'updated':
            continue
        obligation = inventory['obligations'][oid]
        edge = inventory['edges'][obligation['edge_id']]
        downstream[obligation['seed'], edge['prerequisite']].append((oid, edge['consumer']))
    result = {}
    for seed in inventory['seeds']:
        paths, queue = {seed: []}, deque([seed])
        while queue:
            parent = queue.popleft()
            for oid, node in downstream[seed, parent]:
                if node not in paths:
                    paths[node] = [*paths[parent], oid]
                    queue.append(node)
        result[seed] = paths
    return result


def reachable_repaired_frontiers(inventory, decisions, base, current, is_repaired, *, paths=None):
    """Only validated updated paths from the SAME seed supply a frontier."""
    paths = updated_paths(inventory, decisions) if paths is None else paths
    return {seed: {node: path for node, path in reached.items()
                   if node != seed and is_repaired(node)}
            for seed, reached in paths.items()}


def upstream_closure(inventory):
    """Return a memoized factual BASE/CURRENT closure for each arrival input."""
    from functools import lru_cache
    upstream = defaultdict(set)
    for edge in inventory['edges'].values():
        upstream[edge['consumer']].add(edge['prerequisite'])

    @lru_cache(maxsize=None)
    def closure(prerequisite):
        seen, queue = {prerequisite}, deque([prerequisite])
        while queue:
            parent = queue.popleft()
            for node in upstream[parent] - seen:
                seen.add(node)
                queue.append(node)
        return frozenset(seen)

    return closure


def preserved_components(upstream):
    """Strong components of an already verified, unchanged unit graph.

    Membership is structural, not a proof. Callers must ground every external
    input and reviewed arrival before accepting a component. Iterative walks
    avoid a recursion limit on large documentary chains.
    """
    visited, order = set(), []
    reverse = defaultdict(set)
    for node, inputs in upstream.items():
        for other in inputs:
            reverse[other].add(node)
    for start in sorted(upstream):
        if start in visited:
            continue
        visited.add(start)
        stack = [(start, iter(sorted(upstream[start])))]
        while stack:
            node, inputs = stack[-1]
            other = next(inputs, None)
            if other is None:
                order.append(node)
                stack.pop()
            elif other not in visited:
                visited.add(other)
                stack.append((other, iter(sorted(upstream[other]))))
    groups, assigned = [], set()
    for start in reversed(order):
        if start in assigned:
            continue
        members, queue = {start}, [start]
        assigned.add(start)
        while queue:
            node = queue.pop()
            for other in reverse[node] - assigned:
                members.add(other)
                assigned.add(other)
                queue.append(other)
        groups.append(frozenset(members))
    return groups


def append_only_partitions(graphs, partitions, declarations, modes):
    """Projector-only proof of added units entirely outside the old document."""
    from wiki_core.document_records import node_id, reference_definitions, sections
    result = {}
    base, current = graphs['base'], graphs['current']
    for declaration in declarations:
        path = declaration['path']
        before, after = base['documents'][path], current['documents'][path]
        old, new = partitions['base'][path], partitions['current'][path]
        old_ids, new_ids = set(old['parts']), set(new['parts'])
        added = new_ids - old_ids
        if (not added or not old_ids <= new_ids or not after.startswith(before) or after == before
                or old['remainder'] != new['remainder']
                or reference_definitions(before) != reference_definitions(after)):
            continue
        shapes = [g['verified_record_shapes'] for g in (base, current)]
        preserved = all(
            shapes[0][node_id(path, rid)] == shapes[1][node_id(path, rid)]
            and old['parts'][rid]['content_sha256'] == new['parts'][rid]['content_sha256']
            and all(old['parts'][rid].get(k) == new['parts'][rid].get(k) for k in ('start', 'end', 'remainder_anchor'))
            for rid in old_ids - {'remainder'})
        if not preserved:
            continue
        lines = (after if modes.get(path) == 'explicit_view_v2' else sections(after)[0]).splitlines(keepends=True)
        prior_lines = (before if modes.get(path) == 'explicit_view_v2' else sections(before)[0]).splitlines(keepends=True)
        cursor, selected = len(prior_lines), []
        valid = True
        for rid in sorted(added, key=lambda rid: new['parts'][rid]['start']):
            part = new['parts'][rid]
            if part['start'] != cursor:
                valid = False
                break
            selected.append(''.join(lines[part['start']:part['end']]))
            cursor = part['end']
        if not valid or cursor != len(lines) or ''.join(selected) != after[len(before):]:
            continue
        remainder = node_id(path, 'remainder')
        result[remainder] = dict(document=path, base_sha256=digest(before), current_sha256=digest(after),
            base_shape=copy.deepcopy(shapes[0][remainder]), current_shape=copy.deepcopy(shapes[1][remainder]),
            remainder_sha256=base['nodes'][remainder]['record_sha256'], added_records=sorted(added))
    return result
