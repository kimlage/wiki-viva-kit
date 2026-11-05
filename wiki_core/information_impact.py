"""Deterministic information-use impact, independent of PR approval and age debt.

This is the shadow comparison engine until consumer activation is reviewed.
It does not renew verification dates, grant access, execute refreshes, or persist
another backlog. Its pending rows are inputs for the existing source queue.
"""
from __future__ import annotations

from collections import defaultdict, deque
import datetime as dt
import json
import re
from wiki_core.frontmatter import parse_frontmatter
from wiki_core.freshness import freshness_state, is_stale_exempt
from wiki_core.information_relations import dependency_edges, semantic_equal


def changed_fields(previous: str | None, current: str | None) -> set[str]:
    if previous is None or current is None:
        return {'*'}
    before, before_body = parse_frontmatter(previous)
    after, after_body = parse_frontmatter(current)
    fields = {field for field in set(before) | set(after) if (field in before)!=(field in after) or not semantic_equal(before.get(field),after.get(field))}
    if before_body != after_body:
        fields.add('body')
    return fields


def affected_dynamic_queries(current: dict, base: dict, changed: set[str], reached: set[str], *, legacy_authority_unavailable: bool = False, include_preserved: bool = False) -> list[dict]:
    """Select touched queries without treating preserved history as fresh or authorized."""
    from wiki_core.context_policy import within, is_context_instruction
    found = {}
    graphs = [(origin, dependency_edges(graph, origin=origin)[0])
              for origin, graph in (('base', base), ('current', current))]
    def query_keys(edges):
        return {(edge['dependent'], json.dumps(edge['requirement'], sort_keys=True, ensure_ascii=False))
                for edge in edges
                if 'query' in edge.get('requirement', {})}
    unchanged = query_keys(graphs[0][1]) & query_keys(graphs[1][1])
    current_by_source = defaultdict(set)
    current_queries = []
    for _origin, edges in graphs:
        for edge in edges:
            if edge.get('temporal_use') in ('historical', 'as_observed'):
                continue
            current_by_source[edge['prerequisite']].add(edge['dependent'])
            if 'query' in edge.get('requirement', {}):
                current_queries.append((edge['dependent'], edge['requirement']['query']['scope']))
    def possible_current_consumers(path):
        # No inference of independence from a projection's selected fields:
        # its output may still incorporate this historical interpretation.
        return current_by_source[path] | {dependent for dependent, scope in current_queries if within(path, scope)}
    legacy_policy_changed = any(p == 'context.yaml' or p.endswith('/context.yaml') or is_context_instruction(p) for p in changed)
    for origin, edges in graphs:
        for edge in edges:
            req = edge.get('requirement', {})
            if 'query' not in req:
                continue
            consumer, anchor, scope = edge['dependent'], req['target'], req['query']['scope']
            key = (consumer, json.dumps(req, sort_keys=True, ensure_ascii=False))
            pinned_history = (req.get('authority_format') != 'folder'
                              and req.get('temporal') == 'historical'
                              and all(isinstance(req.get(field), str) and re.fullmatch(pattern, req[field])
                                      for field, pattern in (
                                          ('consumed_revision', r'[0-9a-f]{40}|[0-9a-f]{64}'),
                                          ('query_policy_revision', r'[0-9a-f]{40}|[0-9a-f]{64}'),
                                          ('authority_digest', r'[0-9a-f]{64}'),
                                          ('members_digest', r'[0-9a-f]{64}'),
                                          ('selected_digest', r'[0-9a-f]{64}'))))
            current_consumers = possible_current_consumers(consumer) if pinned_history else set()
            direct_change = (consumer in reached or consumer in changed or anchor in changed or anchor in reached
                             or bool(current_consumers & (changed | reached))
                             or any(within(p, scope) for p in changed | reached))
            if req.get('authority_format') == 'folder':
                entry_folder = req['entry_folder']
                def affects_folder_policy(path):
                    if path == 'wiki.config.yaml': return True
                    if path == req['entry_index']: return True
                    directory = path.rsplit('/', 1)[0] if '/' in path else '.'
                    return ((is_context_instruction(path) or path.rsplit('/', 1)[-1] in ('index.md', 'README.md'))
                            and within(entry_folder, directory))
                policy_changed = any(affects_folder_policy(path) for path in changed)
            else:
                # A folder audit cannot inspect an unbound legacy manifest to
                # exclude a changed path from its old normative inputs.
                policy_changed = (legacy_policy_changed or (pinned_history and 'wiki.config.yaml' in changed)
                                  or (legacy_authority_unavailable and bool(changed)))
            if pinned_history and key in unchanged and not direct_change and not current_consumers:
                # This preserves an unchanged historical receipt only.
                # Using it still requires current authorized revalidation.
                if include_preserved and policy_changed:
                    found[key] = {'path': consumer, 'requirement': req, 'origin': origin,
                                  'reason': 'historical_query_preserved_unverified'}
                continue
            if not (policy_changed or direct_change):
                continue
            found[key] = {'path': consumer, 'requirement': req, 'origin': origin,
                          **({'current_consumers_present': True} if current_consumers else {})}
    return [found[key] for key in sorted(found)]


def explicit_current_consumption(edge):
    """Select only canonical, explicitly declared current consumption edges.

    Legacy citations stay in the global graph; they are not proof for scoped
    query closure. Dynamic query dependencies are revalidated separately.
    """
    kind = edge.get('type')
    requirement = edge.get('requirement')
    if kind == 'operational_prerequisite':
        if isinstance(requirement, dict):
            return 'query' not in requirement and requirement.get('temporal') == 'current'
        return edge.get('authored_role') == 'operational_prerequisite'
    if kind in ('projection', 'projection_state'):
        return edge.get('field') == 'projection_inputs' or edge.get('authored_role') == kind
    return False


def typed_consumption_graph(graph):
    """Project existing graph edges without reading or changing canonical data."""
    return {**graph, 'edges': [edge for edge in graph['edges'] if explicit_current_consumption(edge)]}


def authorized_pending_edge(edge, policy, context_id):
    """Closure never imports another owner's provenance or a denied path."""
    from wiki_core.context_policy import PolicyError
    try:
        source, target = edge['prerequisite'], edge['dependent']
        if edge.get('requirement', {}).get('source_kind') == 'mandatory':
            from wiki_core.context_normative import normative_history
            requirement = edge.get('requirement', {})
            return (edge.get('type') == 'operational_prerequisite'
                and edge.get('field') == 'information_requirements'
                and requirement.get('target') == source
                and requirement.get('use') == 'normative' and requirement.get('fields') == ['*'] and requirement.get('temporal') == 'current'
                and policy.owner_of(target) == context_id and policy.permits(context_id, 'read', target)
                and normative_history(policy, context_id, source, requirement.get('consumed_revision'),
                    authority_format=requirement.get('authority_format'), entry_folder=requirement.get('entry_folder'), entry_index=requirement.get('entry_index')))
        if (policy.owner_of(source) != context_id or policy.owner_of(target) != context_id
                or not policy.permits(context_id, 'read', source) or not policy.permits(context_id, 'read', target)):
            return False
        return policy.connection(context_id, context_id, source, edge.get('use', 'interpret'),
            edge.get('classification', 'internal')) == 'approved'
    except (PolicyError, ValueError, KeyError, TypeError):
        return False


def authorized_typed_provenance(path, reasons, policy, context_id, *, limit=1000):
    """Validate every reached typed cause, including convergent upstream paths."""
    pending = [path]; visited = set(); seen_edges = set()
    while pending:
        node = pending.pop()
        if node in visited: continue
        visited.add(node)
        if len(visited) > limit or node not in reasons: return False
        for edge in reasons[node]['causes']:
            key = json.dumps({k: v for k, v in edge.items() if k != 'origin'}, sort_keys=True, ensure_ascii=False)
            if key in seen_edges: continue
            seen_edges.add(key)
            if len(seen_edges) > limit or not authorized_pending_edge(edge, policy, context_id): return False
            pending.append(edge['prerequisite'])
    return True


def propagate_pending_dependencies(current, base, pending_fields, policy, context_id, *, limit=1000):
    """Propagate review obligations across currently authorized use edges only.

    A pending interpretation may change its produced fields; it is not a fact
    change. Contextual/navigation and historical relations do not propagate.
    """
    edges = []
    seen_edges = set()
    for graph in (base, current):
        for edge in dependency_edges(graph)[0]:
            key = json.dumps({k: v for k, v in edge.items() if k != 'origin'}, sort_keys=True, ensure_ascii=False)
            if key not in seen_edges:
                seen_edges.add(key); edges.append(edge)
    fields = {path: set(values) for path, values in pending_fields.items()}
    if len(fields) > limit: raise ValueError('dynamic impact closure limit exceeded')
    work = deque(sorted(fields)); reached = {}; denied = set(); steps = 0
    by_source = defaultdict(list)
    for edge in edges:
        if not explicit_current_consumption(edge):
            continue
        by_source[edge['prerequisite']].append(edge)
    while work:
        source = work.popleft()
        for edge in by_source[source]:
            steps += 1
            if steps > limit: raise ValueError('dynamic impact closure limit exceeded')
            consumed = {('body' if f.startswith('section:') else f.removeprefix('field:')) for f in edge['consumed_fields']}
            if '*' not in fields[source] and '*' not in consumed and not (fields[source] & consumed): continue
            target = edge['dependent']
            if 'nodes' in current and target not in current['nodes']: continue
            if not authorized_pending_edge(edge, policy, context_id):
                denied.add(source); continue
            produced = {('body' if f.startswith('section:') else f.removeprefix('field:')) for f in edge['produced_fields']}
            previous = fields.get(target, set()); enlarged = previous | produced
            if '*' in enlarged: enlarged = {'*'}
            causes = reached.setdefault(target, [])
            if edge not in causes: causes.append(edge)
            if enlarged != previous:
                fields[target] = enlarged; work.append(target)
                if len(fields) > limit: raise ValueError('dynamic impact closure limit exceeded')
    return fields, reached, denied


def _information_reach(current, base, changed):
    """Return existing field-sensitive traversal without any content reads."""
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
            # Legacy impact is body-granular: section selectors conservatively
            # consume the body; typed field selectors map to frontmatter fields.
            consumed = {('body' if f.startswith('section:') else f.removeprefix('field:')) for f in edge['consumed_fields']}
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
    return seeds, reasons, adjacency, nonpropagating


def typed_information_reach(current, base, changed):
    """Reach over explicitly declared current consumption only."""
    return _information_reach(typed_consumption_graph(current), typed_consumption_graph(base), changed)[1]


def evaluate_information_impact(current: dict, base: dict, changed: set[str], *, today: dt.date, _typed_reasons=None, _legacy_authority_unavailable=False) -> dict:
    """Propagate global impact while discovering queries from typed reach only.

    Current-use prerequisites are checked separately at execution; this does
    not imply that a review or external verification occurred.
    """
    seeds, reasons, adjacency, nonpropagating = _information_reach(current, base, changed)
    if _typed_reasons is None:
        has_queries = any('query' in edge.get('requirement', {}) for graph in (base, current) for edge in graph['edges'])
        _typed_reasons = typed_information_reach(current, base, changed) if has_queries else {}
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
    # This already-materialized graph has no current context authority to
    # enumerate dynamic members. It must not certify only the anchor edge.
    affected = affected_dynamic_queries(current, base, changed, set(_typed_reasons),
                                        legacy_authority_unavailable=_legacy_authority_unavailable,
                                        include_preserved=True)
    preserved = [row for row in affected if row.get('reason') == 'historical_query_preserved_unverified']
    pending.extend({'path': row['path'], 'seed': row['path'], 'fields': ['*'], 'causes': [], 'chain': [],
                    'state': 'review_pending', 'reason': row['reason'], 'priority': 'on_demand',
                    'verification_performed': False} for row in preserved)
    dynamic_blockers = [{'path':row['path'],'reason':'dynamic_query_requires_authorized_revalidation'}
                        for row in affected if row.get('reason') != 'historical_query_preserved_unverified']
    # A manifest change can revoke or remove an inherited normative input even
    # when neither its body nor its consumer changed. The global caller-trust
    # audit cannot prove the new authority; preserve a visible review obligation.
    from wiki_core.context_policy import is_context_instruction
    if any(path == 'context.yaml' or path.endswith('/context.yaml') or is_context_instruction(path) for path in changed):
        normative_consumers = {edge['source'] for edge in current['edges']
            if edge.get('type') == 'operational_prerequisite'
            and edge.get('field') == 'information_requirements'
            and edge.get('requirement', {}).get('source_kind') == 'mandatory'}
        for path in sorted(normative_consumers):
            pending.append({'path': path, 'seed': path, 'fields': ['*'], 'causes': [], 'chain': [],
                'state': 'review_pending', 'reason': 'normative_policy_requalification_required',
                'priority': 'on_demand', 'verification_performed': False})
    missing = set(current.get('missing_evidence', set()))
    missing_used = sorted({edge['prerequisite'] for edges in adjacency.values() for edge in edges
                           if edge['origin'] == 'current' and edge['prerequisite'] in missing})
    return {'schema_version': 'wiki_information_impact.v1', 'seeds': sorted(seeds),
            'included': [reasons[p] for p in sorted(reasons)], 'pending_reviews': pending,
            'integrity_blockers': [{'path': p, 'reason': 'missing_evidence'} for p in missing_used] + dynamic_blockers,
            'relation_errors': current['errors'], 'nonpropagating_relations': nonpropagating,
            'ok': not missing_used and not dynamic_blockers and not current['errors']}
