"""Pair-bound causal review of documentary changes.

Semantic dispositions are authored and independently reviewed, never inferred
from dates or equal bytes. These guards bind that review to the exact graph.
They grant no account, session, tool or publication authority.
"""
from __future__ import annotations

import copy
import json
from collections import defaultdict, deque

from wiki_core.document_records import digest, structured_digest, substantive_digest
from wiki_core.freshness import freshness_state, is_stale_exempt


def factual_edges(current, base):
    from wiki_core.freshness_impact import STRUCTURAL, ASSOCIATION, REFERENCE
    result = {}
    for origin, graph in (("base", base), ("current", current)):
        for raw in graph["edges"]:
            if raw["type"] in STRUCTURAL | ASSOCIATION:
                continue
            a, b = raw["source"], raw["target"]
            prerequisite, consumer = (b, a) if raw["type"] in REFERENCE else (a, b)
            row = dict(origin=origin, edge=raw, prerequisite=prerequisite, consumer=consumer)
            key = structured_digest(row)
            result[key] = row
    return result


def census(current, base, changed):
    """Finite union of every seed/occurrence before any proposed cut."""
    from wiki_core.freshness_impact import factual_changes
    changed, _comments = factual_changes(current, base, changed)
    nodes = set(current["nodes"]) | set(base["nodes"])
    seeds = sorted((set(changed) & nodes) | (set(base["nodes"]) - set(current["nodes"])))
    edges = factual_edges(current, base)
    downstream = defaultdict(list)
    for eid, edge in edges.items():
        downstream[edge["prerequisite"]].append(eid)
    obligations = {}
    for seed in seeds:
        queue, seen = deque([seed]), {seed}
        while queue:
            parent = queue.popleft()
            for eid in sorted(downstream[parent]):
                row = dict(seed=seed, edge_id=eid)
                obligations[structured_digest(row)] = row
                consumer = edges[eid]["consumer"]
                if consumer not in seen:
                    seen.add(consumer)
                    queue.append(consumer)
    return dict(seeds=seeds, edges=edges, obligations=obligations)


def pair_digest(current, base, changed):
    def relevant_evidence(graph):
        linked = {p for edge in graph["edges"] for p in (edge["source"], edge["target"])}
        return sorted(p for p in graph.get("verified_evidence_nodes", []) if p in linked or p in changed)
    return structured_digest(dict(changed=sorted(changed), graphs={
        origin: dict(documents={p: digest(t) for p, t in g["documents"].items()},
                     nodes={p: n for p, n in g["nodes"].items() if p not in g.get("verified_evidence_nodes", [])
                            or p in relevant_evidence(g)},
                     edges=g["edges"], errors=g["errors"],
                     verified_evidence_nodes=relevant_evidence(g),
                     record_documents=g.get("verified_record_documents", {}),
                     record_shapes=g.get("verified_record_shapes", {}),
                     record_substantive_sha256=g.get("verified_record_substantive_sha256", {}),
                     precise_component_seeds=g.get("verified_precise_component_seeds", {}),
                     append_only_partitions=g.get("verified_append_only_partitions", {}),
                     locator_changes=g.get("verified_locator_changes", {}),
                     locator_record_documents=g.get("verified_locator_record_documents", {}))
        for origin, g in (("base", base), ("current", current))}))


def _document(graph, node):
    # A raw document identity always dominates synthetic-looking frontmatter.
    if node in graph["documents"]:
        return node
    path = graph.get("verified_record_documents", {}).get(node)
    if path not in graph["documents"]:
        raise ValueError("causal review requires verified documentary identity")
    return path


def _normalized_interpretation_edge(raw):
    edge = copy.deepcopy(raw)
    for key in ("body_line", "body_offset"):
        edge.pop(key, None)
    for field in ("consumption_binding", "locator_review"):
        binding = edge.get(field)
        if isinstance(binding, dict):
            for key in ("origin", "consumed_sha256", "prerequisite_document_sha256", "rationale"):
                binding.pop(key, None)
            if field == "consumption_binding":
                binding.pop("edge_sha256", None)
    return edge


def _interpretation_state(graph, node, *, stop_at=frozenset(), append_equivalence=False):
    """Scope must be identical; different consumed hashes alone are expected.

    A newly shrunken remainder, changed partitions, contexts or dependency roles
    cannot qualify as unchanged merely because the full Markdown is identical.
    """
    from wiki_core.freshness_impact import REFERENCE, STRUCTURAL, ASSOCIATION
    upstream = defaultdict(list)
    for raw in graph["edges"]:
        if raw["type"] in STRUCTURAL | ASSOCIATION:
            continue
        consumer, prerequisite = ((raw["source"], raw["target"]) if raw["type"] in REFERENCE
                                  else (raw["target"], raw["source"]))
        upstream[consumer].append((prerequisite, raw))
    related, scopes, queue, seen = [], {}, deque([node]), {node}
    while queue:
        parent = queue.popleft()
        scopes[parent] = dict(document=graph.get("verified_record_documents", {}).get(parent, parent),
            selection=graph.get("verified_record_shapes", {}).get(parent, "whole_document"),
            evidence=graph["nodes"][parent].get("evidence_source"))
        if append_equivalence and parent in graph.get('verified_append_only_partitions', {}):
            scopes[parent]['selection'] = graph['verified_append_only_partitions'][parent]['base_shape']
        if parent != node and parent in stop_at:
            continue
        for prerequisite, raw in upstream[parent]:
            # Coordinates identify the exact occurrence in the pair/census,
            # but a reviewed text insertion may move the same semantic use.
            # Keep section, role, target, scope and occurrence multiplicity.
            related.append(_normalized_interpretation_edge(raw))
            if prerequisite not in seen:
                seen.add(prerequisite); queue.append(prerequisite)
    return dict(record_sha256=graph["nodes"][node].get("record_sha256"),
        scopes=scopes, dependencies=sorted(related, key=structured_digest))


def _interpretation(graph, node):
    return structured_digest(_interpretation_state(graph, node))


def verify(current, base, changed, contract, artifact_inputs):
    plan = contract.get("causal_review")
    if plan is None:
        return None
    if contract.get("schema_version") != "document_record.v2":
        raise ValueError("causal review requires document_record.v2")
    required = {"schema_version", "author", "pair_sha256", "census_sha256", "dispositions", "review_evidence"}
    if (not isinstance(plan, dict) or not required <= set(plan)
            or set(plan) - required - {"base_authority_citations", "normative_revalidations"}
            or plan["schema_version"] != "wiki_causal_review.v1"):
        raise ValueError("invalid causal review schema")
    if contract.get("locator_changes"):
        raise ValueError("causal review with locator changes is not supported in v1")
    inventory = census(current, base, changed)
    pair = pair_digest(current, base, changed)
    if plan["pair_sha256"] != pair or plan["census_sha256"] != structured_digest(inventory):
        raise ValueError("causal review graph pair/census changed")
    if not isinstance(plan["author"], str) or not plan["author"].strip() or not isinstance(plan["dispositions"], list):
        raise ValueError("invalid causal review author/dispositions")
    decisions = {}
    unchanged_interpretations = {}
    reconciled_interpretations = {}
    from wiki_core.causal_authority import citation_qualifications, reviewed_citation_extension
    citations = citation_qualifications(plan, contract, artifact_inputs, inventory, base, current)
    used_citations = set()
    from wiki_core.causal_revalidation import normative_revalidations
    revalidations = normative_revalidations(plan, contract, artifact_inputs, base, current)
    used_revalidations = set()
    # Validate every proposed repair before deriving any same-seed frontier.
    for item in plan["dispositions"]:
        if (not isinstance(item, dict) or not {"obligation_id", "disposition", "reason"} <= set(item)
                or set(item) - {"obligation_id", "disposition", "reason", "reviewed_upstream_repairs"}
                or not isinstance(item["obligation_id"], str) or not isinstance(item["disposition"], str)
                or item["obligation_id"] not in inventory["obligations"]
                or item["obligation_id"] in decisions or item["disposition"] not in {"updated", "no_change", "revalidated", "blocked"}
                or not isinstance(item["reason"], str) or not item["reason"].strip()):
            raise ValueError("invalid/duplicate/unknown causal disposition")
        requested = item.get('reviewed_upstream_repairs', [])
        if (not isinstance(requested, list) or any(not isinstance(n, str) or not n for n in requested)
                or 'reviewed_upstream_repairs' in item and not requested
                or len(requested) != len(set(requested))
                or requested and item['disposition'] not in {'no_change', 'revalidated'}):
            raise ValueError('invalid reviewed upstream repair declaration')
        obligation = inventory["obligations"][item["obligation_id"]]
        edge = inventory["edges"][obligation["edge_id"]]
        consumer = edge["consumer"]
        if item["disposition"] != "blocked":
            if consumer not in base["nodes"] or consumer not in current["nodes"]:
                raise ValueError("removed/added consumer needs explicit supported reconciliation")
            before_path, after_path = _document(base, consumer), _document(current, consumer)
            before, after = base["documents"][before_path], current["documents"][after_path]
            if before_path != after_path:
                raise ValueError("consumer identity changed")
            if item["disposition"] == "updated":
                if substantive_digest(before) == substantive_digest(after):
                    raise ValueError("updated requires substantive consumer repair")
                if consumer not in current["documents"]:
                    before_part = base.get("verified_record_substantive_sha256", {}).get(consumer)
                    after_part = current.get("verified_record_substantive_sha256", {}).get(consumer)
                    if before_part is None or after_part is None or before_part == after_part:
                        raise ValueError("updated requires substantive repair in the affected record")
        decisions[item["obligation_id"]] = copy.deepcopy(item)
    from wiki_core.causal_reconciliation import repaired_boundary, reachable_repaired_frontiers, upstream_closure
    from functools import lru_cache
    @lru_cache(maxsize=None)
    def is_repaired(node):
        return repaired_boundary(base, current, node)
    frontiers = reachable_repaired_frontiers(inventory, decisions, base, current, is_repaired)
    arrival_upstream = upstream_closure(inventory)
    for oid, item in decisions.items():
        if item['disposition'] not in {'no_change', 'revalidated'}:
            continue
        obligation = inventory['obligations'][oid]
        edge = inventory['edges'][obligation['edge_id']]
        seed, consumer = obligation['seed'], edge['consumer']
        candidates = (set(frontiers[seed]) & arrival_upstream(edge['prerequisite'])) - {consumer}
        direct_seed = (seed == edge['prerequisite'] and seed != consumer
                       and is_repaired(seed))
        if direct_seed:
            candidates.add(seed)
        requested = set(item.get('reviewed_upstream_repairs', []))
        if not requested <= candidates:
            raise ValueError('reviewed upstream repair lacks same-seed substantive support')
        candidates = requested
        key = (seed, consumer, tuple(sorted(candidates)))
        if key not in unchanged_interpretations:
            before_path, after_path = _document(base, consumer), _document(current, consumer)
            same_content = base['documents'][before_path] == current['documents'][after_path]
            if consumer not in current['documents']:
                old_hash = base['nodes'][consumer].get('record_sha256')
                same_content = old_hash is not None and old_hash == current['nodes'][consumer].get('record_sha256')
            equivalent = _interpretation(base, consumer) == _interpretation(current, consumer)
            qualification = {}
            if same_content and not equivalent and citations:
                matched = reviewed_citation_extension(base, current, consumer, citations)
                equivalent = matched is not None
                if matched is not None:
                    used_citations.update(matched)
            if same_content and not equivalent:
                states = [_interpretation_state(g, consumer, stop_at=candidates, append_equivalence=True)
                          for g in (base, current)]
                equivalent = states[0] == states[1]
                if equivalent:
                    reached = set(states[0]['scopes']) | set(states[1]['scopes'])
                    used = sorted(candidates & reached)
                    if set(used) != requested:
                        raise ValueError('reviewed upstream repair declaration is unused')
                    # Reachability alone is not use. Every named frontier
                    # must be necessary for this arrival's equivalence.
                    for node in used:
                        without = candidates - {node}
                        remaining = [_interpretation_state(g, consumer, stop_at=without, append_equivalence=True)
                                     for g in (base, current)]
                        if remaining[0] == remaining[1]:
                            raise ValueError('reviewed upstream repair declaration is unused')
                    qualification = dict(upstream_repairs={node: frontiers[seed].get(node, []) for node in used},
                        direct_repaired_seed=seed if direct_seed and seed in used else None,
                        append_only_remainders=sorted(reached & set(current.get('verified_append_only_partitions', {}))))
            unchanged_interpretations[key] = same_content and equivalent, qualification
        accepted, qualification = unchanged_interpretations[key]
        if not accepted:
            raise ValueError("no_change/revalidated requires identical complete consumer unit and interpretation")
        if requested and not qualification:
            raise ValueError('reviewed upstream repair declaration is unused')
        if qualification:
            reconciled_interpretations[oid] = copy.deepcopy(qualification)
        if item['disposition'] == 'revalidated':
            if consumer not in revalidations:
                raise ValueError("revalidated requires exact normative revalidation evidence")
            used_revalidations.add(consumer)
    if used_citations != set(citations):
        raise ValueError("base authority citation qualification is unused")
    if used_revalidations != set(revalidations):
        raise ValueError("normative revalidation qualification is unused")
    evidence = plan["review_evidence"]
    candidates = [a for a in contract.get("artifacts", []) if a.get("origin") == "current" and a.get("id") == evidence and "path" in a]
    raw = artifact_inputs.get(("current", evidence)) if isinstance(evidence, str) else None
    if len(candidates) != 1 or raw is None or digest(raw.decode()) != candidates[0]["sha256"]:
        raise ValueError("causal review requires immutable current review evidence")
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate causal review receipt key")
            value[key] = item
        return value
    receipt = json.loads(raw, object_pairs_hook=unique)
    expected = {"schema_version", "author", "reviewer", "decision", "plan_sha256", "unresolved_findings"}
    if (not isinstance(receipt, dict) or set(receipt) != expected or receipt["schema_version"] != "wiki_causal_review_receipt.v1"
            or receipt["author"] != plan["author"] or not isinstance(receipt["reviewer"], str)
            or not receipt["reviewer"].strip() or receipt["reviewer"].strip() == plan["author"].strip()
            or receipt["decision"] != "approved" or receipt["unresolved_findings"] != []
            or receipt["plan_sha256"] != structured_digest({k: v for k, v in plan.items() if k != "review_evidence"})):
        raise ValueError("causal disposition review is missing, stale or not independent")
    # This binds semantic evidence, not authenticated reviewer identity. The
    # existing final-HEAD independent PR promotion gate remains mandatory.
    verified = dict(pair_sha256=pair, census_sha256=structured_digest(inventory),
                census=inventory, dispositions=decisions, review_evidence=evidence,
                review_sha256=candidates[0]["sha256"], plan_sha256=receipt["plan_sha256"],
                normative_revalidations=revalidations, reconciled_interpretations=reconciled_interpretations)
    verified["payload_sha256"] = structured_digest(verified)
    return verified


def decision(review, seed, edge, current, base, today):
    """Resolve one actual arrival, without clearing another path or seed."""
    row = dict(origin=edge["origin"], edge={k: v for k, v in edge.items()
               if k not in {"origin", "prerequisite", "dependent"}},
               prerequisite=edge["prerequisite"], consumer=edge["dependent"])
    oid = structured_digest(dict(seed=seed, edge_id=structured_digest(row)))
    if oid not in review["census"]["obligations"]:
        raise ValueError("causal arrival absent from reviewed full census")
    item = review["dispositions"].get(oid)
    if item is None:
        return oid, "missing"
    state = item["disposition"]
    if state == "no_change":
        # An intact unit cannot borrow a new freshness date from a sibling's
        # substantive repair. Both snapshots must already support this cut.
        for graph in (base, current):
            values = graph["nodes"].get(edge["dependent"], {})
            if freshness_state(values.get("updated_at"), values.get("stale_after_days"), today,
                               stale_exempt=is_stale_exempt(values.get("stale_exempt"))) != "fresh":
                state = "no_change_consumer_not_fresh"
                break
    elif state == "revalidated":
        # This is a reviewed normative revision, not inherited page freshness.
        # Unknown/added units and already-fresh BASE units cannot use this path.
        from datetime import date
        states = [freshness_state(g["nodes"][edge["dependent"]].get("updated_at"),
                    g["nodes"][edge["dependent"]].get("stale_after_days"), today,
                    stale_exempt=is_stale_exempt(g["nodes"][edge["dependent"]].get("stale_exempt")))
                  for g in (base, current)]
        proof = review["normative_revalidations"][edge["dependent"]]
        if states != ["stale", "fresh"] or date.fromisoformat(proof["checked_on"]) > today:
            state = "revalidated_consumer_not_fresh"
    return oid, state


def evaluate(current, base, changed, *, today):
    """Cut only reviewed unchanged arrivals; keep every factual prerequisite.

    Traversal is monotone per seed. Every edge arrival is considered, including
    later alternate paths and cycles; a no_change never clears another cause.
    The full uncut census remains available for independent review.
    """
    from wiki_core.freshness_impact import evaluate_impact
    review = current.get("verified_causal_review")
    if not review or review != base.get("verified_causal_review"):
        raise ValueError("causal review requires the same verified pair")
    if review.get("payload_sha256") != structured_digest({k: v for k, v in review.items() if k != "payload_sha256"}):
        raise ValueError("causal review payload changed after verification")
    if pair_digest(current, base, changed) != review["pair_sha256"]:
        raise ValueError("causal inputs changed after projection")
    inventory = census(current, base, changed)
    if structured_digest(inventory) != review["census_sha256"]:
        raise ValueError("causal census changed after projection")
    original = evaluate_impact({k: v for k, v in current.items() if k != "verified_causal_review"},
                               {k: v for k, v in base.items() if k != "verified_causal_review"}, changed, today=today)
    original_rows = {r["path"]: r for r in original["included"]}
    downstream, upstream = defaultdict(list), defaultdict(list)
    for eid, row in inventory["edges"].items():
        edge = dict(row["edge"], origin=row["origin"], prerequisite=row["prerequisite"], dependent=row["consumer"])
        downstream[row["prerequisite"]].append((eid, edge))
        upstream[row["consumer"]].append((eid, edge))
    reasons = {p: dict(reason="changed_page", seed=p, via=None, chain=[]) for p in inventory["seeds"]}
    witnesses, visited, queue = {}, set(), deque()
    for seed in inventory["seeds"]:
        witnesses[seed, seed] = reasons[seed]
        visited.add((seed, seed)); queue.append((seed, seed))
    arrivals, unresolved, boundaries = {}, {}, {}
    factual_raw_arrivals = set()
    while queue:
        seed, parent = queue.popleft()
        for eid, edge in downstream[parent]:
            target = edge["dependent"]
            # A projector-owned component -> raw edge is representational.
            # Any other causal arrival still imposes a real raw obligation.
            if not (edge.get("basis") == "document_record.v2"
                    and edge.get("field") == "document_components"
                    and edge.get("path") == target
                    and current.get("verified_record_documents", {}).get(parent) == target):
                factual_raw_arrivals.add((seed, target))
            oid, status = decision(review, seed, edge, current, base, today)
            reason = dict(reason="affected_dependent", seed=seed, via=parent,
                          chain=[*witnesses[seed, parent]["chain"], edge])
            arrivals[oid] = dict(seed=seed, consumer=target, edge_id=eid, disposition=status)
            reasons.setdefault(target, reason)
            witnesses.setdefault((seed, target), reason)
            if status in {"no_change", "revalidated"}:
                boundaries[oid] = arrivals[oid]
                continue
            if status != "updated":
                unresolved[oid] = dict(path=target, state=original_rows[target]["state"],
                    reason="causal_" + status, seed=seed, via=parent, chain=reason["chain"], obligation_id=oid)
            if (seed, target) not in visited:
                visited.add((seed, target)); queue.append((seed, target))
    # Start from actual semantic demands, not the redundant raw carrier of an
    # exact independently partitioned edit. Keep raw seeds, all edges, census
    # and downstream arrivals. A WHOLE consumer reaching raw in this phase must
    # enqueue it and traverse ALL its parts, even if a carrier was seen earlier.
    carriers = current.get("verified_precise_component_seeds", {})
    queue = deque(key for key in witnesses
                  if key[1] not in carriers or key in factual_raw_arrivals)
    seen = set(queue)
    while queue:
        seed, parent = queue.popleft()
        for eid, edge in upstream[parent]:
            target = edge["prerequisite"]
            reason = dict(reason="required_dependency", seed=seed, via=parent,
                          chain=[*witnesses[seed, parent]["chain"], edge])
            reasons.setdefault(target, reason)
            witnesses.setdefault((seed, target), reason)
            if (seed, target) not in seen:
                seen.add((seed, target)); queue.append((seed, target))
    included = [dict(path=p, state=original_rows[p]["state"], **reasons[p]) for p in sorted(reasons)]
    stale = [r for r in included if r["state"] in {"stale", "unknown"}]
    beyond = [dict(r, reason="beyond_reviewed_causal_boundary") for r in original["included"] if r["path"] not in reasons]
    result = dict(original, included=included, blockers=[*stale, *unresolved.values()],
                  unrelated_debt=[*original["unrelated_debt"], *(r for r in beyond if r["state"] in {"stale", "unknown"})])
    result["causal_review"] = dict(pair_sha256=review["pair_sha256"], census_sha256=review["census_sha256"],
        potential_obligations=len(inventory["obligations"]), considered_arrivals=len(arrivals),
        approved_boundaries=list(boundaries.values()), unresolved=list(unresolved.values()),
        beyond_boundaries=beyond, review_evidence=review["review_evidence"], review_sha256=review["review_sha256"],
        factual_relations_preserved=True, final_head_independent_promotion_review_still_required=True)
    result["causal_review"]["precise_representation_carriers"] = sorted(carriers)
    result["ok"] = not result["blockers"] and not result["relation_errors"]
    return result
