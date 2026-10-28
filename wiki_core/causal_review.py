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
                     locator_record_documents=g.get("verified_locator_record_documents", {}),
                     **({"record_observations": g["verified_record_observations"]}
                        if "verified_record_observations" in g else {}),
                     **({"record_reviews": g["verified_record_reviews"]}
                        if "verified_record_reviews" in g else {}))
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


def _review_receipt(plan, contract, artifact_inputs):
    """Verify the immutable review binding before deriving any proof."""
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
    return evidence, candidates[0]["sha256"], receipt


def verify(current, base, changed, contract, artifact_inputs, *, complete_component_deltas=frozenset()):
    plan = contract.get("causal_review")
    if plan is None:
        return None
    if contract.get("schema_version") != "document_record.v2":
        raise ValueError("causal review requires document_record.v2")
    required = {"schema_version", "author", "pair_sha256", "census_sha256", "dispositions", "review_evidence"}
    if (not isinstance(plan, dict) or not required <= set(plan)
            or set(plan) - required - {"base_authority_citations", "normative_revalidations", "documentary_edits"}
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
    evidence, review_sha, receipt = _review_receipt(plan, contract, artifact_inputs)
    decisions = {}
    unchanged_interpretations = {}
    reconciled_interpretations = {}
    from wiki_core.causal_authority import citation_qualifications, reviewed_citation_extension
    citations = citation_qualifications(plan, contract, artifact_inputs, inventory, base, current)
    used_citations = set()
    from wiki_core.causal_revalidation import normative_revalidations
    revalidations = normative_revalidations(plan, contract, artifact_inputs, base, current)
    used_revalidations = set()
    from wiki_core.documentary_edits import qualifications
    documentary_edits = qualifications(plan, contract, artifact_inputs, base, current, inventory['seeds'],
                                        complete_component_deltas=complete_component_deltas)
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
                # The projector can prove an entire H2 was introduced/removed
                # inside an otherwise preserved document. An independently
                # reviewed `updated` arrival propagates that exact delta; it
                # is never an unchanged cut, freshness proof or WHOLE waiver.
                present = current if consumer in current["nodes"] else base
                path = present.get("verified_record_documents", {}).get(consumer)
                if (item["disposition"] != "updated" or consumer not in complete_component_deltas
                        or path not in base["documents"] or path not in current["documents"]
                        or consumer in base["documents"] or consumer in current["documents"]):
                    raise ValueError("removed/added consumer needs explicit supported reconciliation")
            else:
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
    from wiki_core.causal_reconciliation import (
        repaired_boundary, reachable_repaired_frontiers, upstream_closure, updated_paths,
    )
    from functools import lru_cache
    @lru_cache(maxsize=None)
    def is_repaired(node):
        return repaired_boundary(base, current, node)
    paths = updated_paths(inventory, decisions)
    frontiers = reachable_repaired_frontiers(inventory, decisions, base, current, is_repaired, paths=paths)
    arrival_upstream = upstream_closure(inventory)
    requests, direct_seeds = {}, {}
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
        requests[oid], direct_seeds[oid] = requested, direct_seed

    # Complete interpretation belongs to the consumer, while support belongs
    # to each seed/occurrence. Compose only explicit, locally proved requests
    # that actually arrive here through updated paths. Potential dispositions
    # beyond another cut cannot manufacture support.
    eligible = defaultdict(set)
    for oid, obligation in inventory['obligations'].items():
        edge = inventory['edges'][obligation['edge_id']]
        if edge['prerequisite'] in paths[obligation['seed']]:
            eligible[edge['consumer']].add(oid)
    compositions = {}

    @lru_cache(maxsize=None)
    def exact_interpretation_equal(node):
        return _interpretation(base, node) == _interpretation(current, node)

    @lru_cache(maxsize=None)
    def interpretation_equal(consumer, stops):
        return (_interpretation_state(base, consumer, stop_at=stops, append_equivalence=True)
                == _interpretation_state(current, consumer, stop_at=stops, append_equivalence=True))

    @lru_cache(maxsize=None)
    def joint_interpretation_equal(consumer, stops, authority_ids):
        if not authority_ids:
            return interpretation_equal(consumer, stops)
        matched = reviewed_citation_extension(base, current, consumer,
            {key: citations[key] for key in authority_ids},
            stop_at=stops, append_equivalence=True)
        return matched is not None and matched == set(authority_ids)

    @lru_cache(maxsize=None)
    def same_complete_unit(node):
        if node not in base['nodes'] or node not in current['nodes']:
            return False
        try:
            before, after = _document(base, node), _document(current, node)
        except ValueError:
            return False
        if before != after:
            return False
        if node in current['documents']:
            return base['documents'][before] == current['documents'][after]
        old = base['nodes'][node].get('record_sha256')
        return old is not None and old == current['nodes'][node].get('record_sha256')

    @lru_cache(maxsize=None)
    def native_prerequisite_qualification(node):
        if not same_complete_unit(node):
            return None
        if exact_interpretation_equal(node):
            return dict(prerequisite=node, base_authority_citations=[])
        matched = reviewed_citation_extension(base, current, node, citations) if citations else None
        return (dict(prerequisite=node, base_authority_citations=sorted(matched))
                if matched is not None else None)

    def input_evidence(proof):
        # Supports are already aggregated. Keep their exact identities without
        # recursively embedding the same prerequisite proof down every path.
        return {key: value for key, value in proof.items() if key != 'prerequisite_qualifications'}

    @lru_cache(maxsize=1)
    def component_qualifications():
        """Ground intact cycles jointly; a visiting member is never evidence.

        All supports come from actual reviewed arrivals or already established
        input proofs. Flatten repaired frontiers instead of stopping traversal
        at an intact member, which would hide its factual dependencies.
        """
        from wiki_core.causal_reconciliation import preserved_components
        nodes = frozenset(base['nodes']) | frozenset(current['nodes'])
        intact = {node for node in nodes if same_complete_unit(node)
                  and interpretation_equal(node, nodes)}
        incoming = defaultdict(set)
        for edge in inventory['edges'].values():
            incoming[edge['consumer']].add(edge['prerequisite'])
        groups = preserved_components({node: incoming[node] & intact for node in intact})
        proved = {}
        # Kosaraju order follows consumer -> prerequisite. Reverse it so only
        # fully completed prerequisite components can supply a foundation.
        for members in reversed(groups):
            required = set().union(*(eligible[node] for node in members))
            if any(oid not in requests for oid in required):
                continue
            # An intact intermediary beyond a reviewed cut has no actual
            # arrival to approve. It can carry only proofs established for
            # all its inputs below; it cannot introduce its own repair.
            repairs = set().union(*(requests[oid] for oid in required))
            authorities, supports, input_proofs = set(), set(required), {}
            valid = True
            for node in members:
                for parent in incoming[node] - members:
                    proof = native_prerequisite_qualification(parent) or proved.get(parent)
                    arrivals = {oid for oid in eligible[node]
                                if inventory['edges'][inventory['obligations'][oid]['edge_id']]['prerequisite'] == parent}
                    if proof is None:
                        # No other seed/member can cover an empty or absent
                        # declaration for this changed external input.
                        if not arrivals or any(not requests[oid] for oid in arrivals):
                            valid = False
                            break
                    else:
                        repairs.update(proof.get('upstream_repairs', []))
                        authorities.update(proof['base_authority_citations'])
                        supports.update(proof.get('arrivals', []))
                        input_proofs[parent] = input_evidence(proof)
                if not valid:
                    break
            if not valid:
                continue
            stops, authority_ids = frozenset(repairs), frozenset(authorities)
            if not all(joint_interpretation_equal(node, stops, authority_ids) for node in members):
                continue
            proof = dict(members=sorted(members), arrivals=sorted(supports),
                         upstream_repairs=sorted(repairs), base_authority_citations=sorted(authorities),
                         prerequisite_qualifications=input_proofs)
            for node in members:
                proved[node] = dict(proof, prerequisite=node)
        return proved

    @lru_cache(maxsize=None)
    def prerequisite_qualification(node):
        return native_prerequisite_qualification(node) or component_qualifications().get(node)

    @lru_cache(maxsize=None)
    def composed_requests(consumer):
        combined = set()
        participants = []
        intact_inputs = {}
        for other in sorted(eligible[consumer]):
            if other not in requests:  # Missing, blocked or updated is not an unchanged arrival.
                return None
            local = requests[other]
            if local:
                combined.update(local)
                participants.append(other)
            else:
                incoming = inventory['edges'][inventory['obligations'][other]['edge_id']]['prerequisite']
                proof = prerequisite_qualification(incoming)
                if proof is None:
                    # An empty request must prove its own complete input is
                    # unchanged or use the existing sealed authority proof;
                    # it cannot borrow another seed's substantive repair.
                    return None
                participants.append(other)
                intact_inputs[other] = input_evidence(proof)
                combined.update(proof.get('upstream_repairs', []))
        return frozenset(combined), participants, intact_inputs

    for oid, requested in requests.items():
        item = decisions[oid]
        obligation = inventory['obligations'][oid]
        edge = inventory['edges'][obligation['edge_id']]
        seed, consumer = obligation['seed'], edge['consumer']
        direct_seed = direct_seeds[oid]
        candidates = requested
        key = (seed, consumer, edge['prerequisite'], tuple(sorted(candidates)),
               direct_seed, oid in eligible[consumer])
        if key not in unchanged_interpretations:
            same_content = same_complete_unit(consumer)
            equivalent = exact_interpretation_equal(consumer)
            qualification = {}
            if same_content and not equivalent and citations:
                matched = reviewed_citation_extension(base, current, consumer, citations)
                equivalent = matched is not None
                if matched is not None:
                    used_citations.update(matched)
            if same_content and not equivalent:
                equivalent = interpretation_equal(consumer, frozenset(candidates))
                composition = None
                authority_ids = frozenset()
                if (not equivalent and oid in eligible[consumer]
                        and (requested or prerequisite_qualification(edge['prerequisite']) is not None)):
                    group = composed_requests(consumer)
                    if group is not None:
                        combined, participants, intact_inputs = group
                        qualified_authorities = frozenset(key for proof in intact_inputs.values()
                                                          for key in proof['base_authority_citations'])
                        if joint_interpretation_equal(consumer, combined, qualified_authorities):
                            candidates = set(combined)
                            authority_ids = qualified_authorities
                            equivalent = True
                            composition = dict(arrivals=participants, upstream_repairs=sorted(combined),
                                               prerequisite_qualifications=intact_inputs)
                if not equivalent:
                    proof = component_qualifications().get(consumer)
                    if proof is not None:
                        candidates = set(proof['upstream_repairs'])
                        authority_ids = frozenset(proof['base_authority_citations'])
                        if not requested <= candidates:
                            raise ValueError('reviewed upstream repair declaration is unused')
                        equivalent = True
                        composition = proof
                if equivalent:
                    states = [_interpretation_state(g, consumer, stop_at=candidates, append_equivalence=True)
                              for g in (base, current)]
                    reached = set(states[0]['scopes']) | set(states[1]['scopes'])
                    used = sorted(candidates & reached)
                    if set(used) != candidates:
                        raise ValueError('reviewed upstream repair declaration is unused')
                    # Reachability alone is not use. Every named frontier
                    # must be necessary for this arrival's equivalence.
                    for node in used:
                        without = candidates - {node}
                        if joint_interpretation_equal(consumer, frozenset(without), authority_ids):
                            raise ValueError('reviewed upstream repair declaration is unused')
                    qualification = dict(upstream_repairs={node: frontiers[seed].get(node, []) for node in sorted(requested)},
                        direct_repaired_seed=seed if direct_seed and seed in requested else None,
                        append_only_remainders=sorted(reached & set(current.get('verified_append_only_partitions', {}))))
                    if composition is not None:
                        compositions[consumer] = composition
                        qualification['composed_consumer'] = consumer
                        for proof in composition['prerequisite_qualifications'].values():
                            used_citations.update(proof['base_authority_citations'])
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
    # This binds semantic evidence, not authenticated reviewer identity. The
    # existing final-HEAD independent PR promotion gate remains mandatory.
    verified = dict(pair_sha256=pair, census_sha256=structured_digest(inventory),
                census=inventory, dispositions=decisions, review_evidence=evidence,
                review_sha256=review_sha, plan_sha256=receipt["plan_sha256"],
                normative_revalidations=revalidations, reconciled_interpretations=reconciled_interpretations,
                composed_interpretations=compositions, documentary_edits=documentary_edits)
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
    factual_demands = set()
    while queue:
        seed, parent = queue.popleft()
        for eid, edge in downstream[parent]:
            target = edge["dependent"]
            # A projector-owned component -> raw edge is representational.
            # Any other causal arrival still imposes a real raw obligation.
            if not (edge.get("basis") == "document_record.v2"
                    and edge.get("field") == "document_components"
                    and edge.get("path") == target
                    and (base if edge['origin'] == 'base' else current)
                        .get("verified_record_documents", {}).get(parent) == target):
                factual_raw_arrivals.add((seed, target))
                factual_demands.add(target)
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

    def require_input(seed, parent, edge):
        target = edge['prerequisite']
        factual_demands.add(target)
        reason = dict(reason='required_dependency', seed=seed, via=parent,
                      chain=[*witnesses[seed, parent]['chain'], edge])
        reasons.setdefault(target, reason)
        witnesses.setdefault((seed, target), reason)
        if (seed, target) not in seen:
            seen.add((seed, target)); queue.append((seed, target))

    for seed, parent in list(witnesses):
        if parent in carriers and (seed, parent) not in factual_raw_arrivals:
            # Its retirement evidence is an input to the operation, even when
            # the removed record is absent. Do not mark the carrier visited:
            # a later factual WHOLE arrival must still traverse every sibling.
            for _, edge in upstream[parent]:
                if (edge['origin'] == 'current' and edge.get('basis') == 'document_record.v2'
                        and edge.get('field') == 'removed_record_evidence'):
                    require_input(seed, parent, edge)
    while queue:
        seed, parent = queue.popleft()
        for eid, edge in upstream[parent]:
            require_input(seed, parent, edge)
    included = [dict(path=p, state=original_rows[p]["state"], **reasons[p]) for p in sorted(reasons)]
    from datetime import date
    satisfied, pending_edits = [], []
    for row in included:
        proof = review['documentary_edits'].get(row['path'])
        if proof and proof.get('retired') and date.fromisoformat(proof['reviewed_on']) > today:
            # A missing CURRENT node has state `removed`, so freshness cannot
            # enforce the review's time boundary on its behalf.
            pending_edits.append(dict(row, reason='documentary_review_in_future'))
        if (proof and row['reason'] == 'changed_page' and row['state'] == 'stale'
                and row['path'] not in factual_demands
                and date.fromisoformat(proof['reviewed_on']) <= today):
            row['documentary_edit_satisfied'] = proof
            satisfied.append(row['path'])
        if (row['path'] in carriers and row['path'] not in factual_demands
                and row['reason'] == 'changed_page'):
            # The complete changed components still have their own obligations.
            # A later WHOLE/context arrival removes this representation-only
            # status; it cannot borrow a sibling's edit or observation proof.
            row['precise_representation_components'] = carriers[row['path']]
    stale = [r for r in included if r["state"] in {"stale", "unknown"}
             and 'documentary_edit_satisfied' not in r and 'precise_representation_components' not in r]
    beyond = [dict(r, reason="beyond_reviewed_causal_boundary") for r in original["included"] if r["path"] not in reasons]
    result = dict(original, included=included, blockers=[*stale, *unresolved.values(), *pending_edits],
                  unrelated_debt=[*original["unrelated_debt"], *(r for r in beyond if r["state"] in {"stale", "unknown"})])
    result["causal_review"] = dict(pair_sha256=review["pair_sha256"], census_sha256=review["census_sha256"],
        potential_obligations=len(inventory["obligations"]), considered_arrivals=len(arrivals),
        approved_boundaries=list(boundaries.values()), unresolved=list(unresolved.values()),
        beyond_boundaries=beyond, review_evidence=review["review_evidence"], review_sha256=review["review_sha256"],
        factual_relations_preserved=True, final_head_independent_promotion_review_still_required=True)
    result["causal_review"]["precise_representation_carriers"] = sorted(carriers)
    result["causal_review"]["documentary_edits_satisfied"] = satisfied
    result["causal_review"]["documentary_edit_factual_demands"] = sorted(set(review['documentary_edits']) & factual_demands)
    result["ok"] = not result["blockers"] and not result["relation_errors"]
    return result
