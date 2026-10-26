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


def _interpretation(graph, node):
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
        for prerequisite, raw in upstream[parent]:
            edge = copy.deepcopy(raw)
            # Coordinates identify the exact occurrence in the pair/census,
            # but a reviewed text insertion may move the same semantic use.
            # Keep section, role, target, scope and occurrence multiplicity.
            for key in ("body_line", "body_offset"):
                edge.pop(key, None)
            for field in ("consumption_binding", "locator_review"):
                binding = edge.get(field)
                if isinstance(binding, dict):
                    for key in ("origin", "consumed_sha256", "prerequisite_document_sha256", "rationale"):
                        binding.pop(key, None)
                    if field == "consumption_binding":
                        binding.pop("edge_sha256", None)
            related.append(edge)
            if prerequisite not in seen:
                seen.add(prerequisite); queue.append(prerequisite)
    return structured_digest(dict(record_sha256=graph["nodes"][node].get("record_sha256"),
        scopes=scopes, dependencies=sorted(related, key=structured_digest)))


def verify(current, base, changed, contract, artifact_inputs):
    plan = contract.get("causal_review")
    if plan is None:
        return None
    if contract.get("schema_version") != "document_record.v2":
        raise ValueError("causal review requires document_record.v2")
    required = {"schema_version", "author", "pair_sha256", "census_sha256", "dispositions", "review_evidence"}
    if not isinstance(plan, dict) or set(plan) != required or plan["schema_version"] != "wiki_causal_review.v1":
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
    for item in plan["dispositions"]:
        if (not isinstance(item, dict) or set(item) != {"obligation_id", "disposition", "reason"}
                or not isinstance(item["obligation_id"], str) or not isinstance(item["disposition"], str)
                or item["obligation_id"] not in inventory["obligations"]
                or item["obligation_id"] in decisions or item["disposition"] not in {"updated", "no_change", "blocked"}
                or not isinstance(item["reason"], str) or not item["reason"].strip()):
            raise ValueError("invalid/duplicate/unknown causal disposition")
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
            if item["disposition"] == "no_change":
                if consumer not in unchanged_interpretations:
                    unchanged_interpretations[consumer] = (
                        before == after and _interpretation(base, consumer) == _interpretation(current, consumer))
                if not unchanged_interpretations[consumer]:
                    raise ValueError("no_change requires identical full consumer and interpretation")
            else:
                if substantive_digest(before) == substantive_digest(after):
                    raise ValueError("updated requires substantive consumer repair")
                if consumer not in current["documents"]:
                    before_part = base.get("verified_record_substantive_sha256", {}).get(consumer)
                    after_part = current.get("verified_record_substantive_sha256", {}).get(consumer)
                    if before_part is None or after_part is None or before_part == after_part:
                        raise ValueError("updated requires substantive repair in the affected record")
        decisions[item["obligation_id"]] = copy.deepcopy(item)
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
                review_sha256=candidates[0]["sha256"], plan_sha256=receipt["plan_sha256"])
    verified["payload_sha256"] = structured_digest(verified)
    return verified


def decision(review, seed, edge, current, today):
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
        values = current["nodes"].get(edge["dependent"], {})
        if freshness_state(values.get("updated_at"), values.get("stale_after_days"), today,
                           stale_exempt=is_stale_exempt(values.get("stale_exempt"))) != "fresh":
            state = "no_change_consumer_not_fresh"
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
    while queue:
        seed, parent = queue.popleft()
        for eid, edge in downstream[parent]:
            target = edge["dependent"]
            oid, status = decision(review, seed, edge, current, today)
            reason = dict(reason="affected_dependent", seed=seed, via=parent,
                          chain=[*witnesses[seed, parent]["chain"], edge])
            arrivals[oid] = dict(seed=seed, consumer=target, edge_id=eid, disposition=status)
            reasons.setdefault(target, reason)
            witnesses.setdefault((seed, target), reason)
            if status == "no_change":
                boundaries[oid] = arrivals[oid]
                continue
            if status != "updated":
                unresolved[oid] = dict(path=target, state=original_rows[target]["state"],
                    reason="causal_" + status, seed=seed, via=parent, chain=reason["chain"], obligation_id=oid)
            if (seed, target) not in visited:
                visited.add((seed, target)); queue.append((seed, target))
    # All real prerequisites of every included consumer remain checked. Never
    # cut this phase or start a fresh downstream fan-out from shared sources.
    queue = deque(witnesses)
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
    result["ok"] = not result["blockers"] and not result["relation_errors"]
    return result
