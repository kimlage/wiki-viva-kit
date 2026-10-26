"""Verified structural limits for the existing occurrence-bound causal review.

These helpers do not approve meaning or suppress factual prerequisite checks.
"""
from __future__ import annotations

import copy
from collections import Counter, defaultdict, deque

from wiki_core.document_records import digest, substantive_digest


def scope_identity(graph, node):
    return dict(document=graph.get('verified_record_documents', {}).get(node, node),
                selection=graph.get('verified_record_shapes', {}).get(node, 'whole_document'),
                evidence=graph['nodes'][node].get('evidence_source'))


def repaired_boundary(base, current, node):
    """A complete, substantively repaired unit with unchanged declared scope."""
    from wiki_core.causal_review import _document
    if node not in base['nodes'] or node not in current['nodes']:
        return False
    try:
        before, after = _document(base, node), _document(current, node)
    except ValueError:
        return False
    if before != after or scope_identity(base, node) != scope_identity(current, node):
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
    # equivalent shape change is the projector's exact append-only proof.
    from wiki_core.causal_review import _interpretation_state
    old_scopes = _interpretation_state(base, node, append_equivalence=True)['scopes']
    new_scopes = _interpretation_state(current, node, append_equivalence=True)['scopes']
    if any(new_scopes.get(prerequisite) != scope for prerequisite, scope in old_scopes.items()):
        return False
    # A repaired upstream unit does not authorize loss/reclassification of its
    # old premises or changed mandatory context. Exact relocation is reviewed
    # by the arrival declaration; additional references remain real premises.
    from wiki_core.causal_review import _normalized_interpretation_edge
    from wiki_core.document_records import structured_digest
    from wiki_core.freshness_impact import REFERENCE, STRUCTURAL, ASSOCIATION
    states, contexts, occurrences = [], [], []
    for graph in (base, current):
        edges, local_context, exact = [], [], defaultdict(list)
        for raw in graph['edges']:
            if raw['type'] in STRUCTURAL | ASSOCIATION:
                continue
            consumer = raw['source'] if raw['type'] in REFERENCE else raw['target']
            if consumer != node:
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
    if contexts[0] != contexts[1] or any(states[1][key] != count for key, count in states[0].items()):
        return False
    if any(sorted(occurrences[0][key]) != sorted(occurrences[1][key]) and count != 1
           for key, count in states[0].items()):
        return False
    return True


def reachable_repaired_frontiers(inventory, decisions, base, current, is_repaired):
    """Only validated updated paths from the SAME seed supply a frontier.

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
        frontiers = {}
        while queue:
            parent = queue.popleft()
            for oid, node in downstream[seed, parent]:
                if node not in paths:
                    paths[node] = [*paths[parent], oid]
                    queue.append(node)
                    if is_repaired(node):
                        frontiers[node] = paths[node]
        result[seed] = frontiers
    return result


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
