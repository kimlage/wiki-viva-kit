"""Deterministic information-use impact, independent of PR approval and age debt.

This is the shadow comparison engine until consumer activation is reviewed.
It does not renew verification dates, grant access, execute refreshes, or persist
another backlog. Its pending rows are inputs for the existing source queue.
"""
from __future__ import annotations

from collections import defaultdict, deque
import datetime as dt
import json
from wiki_core.frontmatter import parse_frontmatter
from wiki_core.freshness import freshness_state, is_stale_exempt
from wiki_core.information_relations import dependency_edges


def changed_fields(previous: str | None, current: str | None) -> set[str]:
    if previous is None or current is None:
        return {'*'}
    before, before_body = parse_frontmatter(previous)
    after, after_body = parse_frontmatter(current)
    fields = {field for field in set(before) | set(after) if before.get(field) != after.get(field)}
    if before_body != after_body:
        fields.add('body')
    return fields


def evaluate_information_impact(current: dict, base: dict, changed: set[str], *, today: dt.date) -> dict:
    """Propagate relevant information downstream; never import sibling facts.

    Factual relevance creates a review obligation, not proof of a contradiction.
    Current-use prerequisites are checked separately at execution. Missing
    referenced artifacts and relation errors remain integrity failures.
    """
    changed = changed | (set(base['nodes']) - set(current['nodes']))
    seeds = changed & (set(current['nodes']) | set(base['nodes']))
    adjacency = defaultdict(list)
    nonpropagating = []
    for origin, graph in [('base', base), ('current', current)]:
        dependencies, context = dependency_edges(graph, origin=origin)
        nonpropagating.extend(context)
        for edge in dependencies:
            adjacency[edge['prerequisite']].append(edge)
    for edges in adjacency.values():
        edges.sort(key=lambda edge: json.dumps(edge, sort_keys=True))
    fields = {p: changed_fields(base['documents'].get(p), current['documents'].get(p)) for p in seeds}
    reasons = {p: {'path': p, 'seed': p, 'distance': 0, 'fields': sorted(fields[p]), 'chain': []} for p in seeds}
    work = deque(sorted(seeds))
    incoming = defaultdict(list)
    while work:
        parent = work.popleft()
        for edge in adjacency[parent]:
            consumed = set(edge['consumed_fields'])
            if '*' not in consumed and '*' not in fields[parent] and not (consumed & fields[parent]):
                continue
            target = edge['dependent']
            if edge not in incoming[target]:
                incoming[target].append(edge)
            produced = set(edge['produced_fields'])
            previous = fields.get(target, set())
            enlarged = previous | produced
            if '*' in enlarged:
                enlarged = {'*'}
            if target in reasons and enlarged == previous:
                continue
            if target not in reasons:
                reasons[target] = {'path': target, 'seed': reasons[parent]['seed'],
                                   'distance': reasons[parent]['distance'] + 1,
                                   'chain': [*reasons[parent]['chain'], edge]}
            fields[target] = enlarged
            work.append(target)
    for path, reason in reasons.items():
        reason['fields'] = sorted(fields[path])
        reason['causes'] = incoming[path]
    pending = []
    for path, reason in sorted(reasons.items()):
        if path not in current['nodes']:
            continue  # Removed consumers retain impact history, not a live review obligation.
        values = current['nodes'].get(path, {})
        age = freshness_state(values.get('updated_at'), values.get('stale_after_days'), today,
                              stale_exempt=is_stale_exempt(values.get('stale_exempt')))
        if reason['causes'] or age in {'stale', 'unknown'}:
            pending.append({**reason, 'state': 'review_pending', 'age_state': age,
                            'priority': 'active' if values.get('action_state') in {'open', 'in_progress'} else 'on_demand',
                            'reason': 'information_changed' if reason['causes'] else 'verification_age',
                            'last_recorded_at': str(values['updated_at']) if values.get('updated_at') is not None else None,
                            'verification_performed': False})
    missing = set(current.get('missing_evidence', set()))
    missing_used = sorted({edge['prerequisite'] for edges in adjacency.values() for edge in edges
                           if edge['origin'] == 'current' and edge['prerequisite'] in missing})
    return {'schema_version': 'wiki_information_impact.v1', 'seeds': sorted(seeds),
            'included': [reasons[p] for p in sorted(reasons)], 'pending_reviews': pending,
            'integrity_blockers': [{'path': p, 'reason': 'missing_evidence'} for p in missing_used],
            'relation_errors': current['errors'], 'nonpropagating_relations': nonpropagating,
            'ok': not missing_used and not current['errors']}
