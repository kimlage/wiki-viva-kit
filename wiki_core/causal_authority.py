"""Reviewed documentary applicability, never execution or account authority.

The existing independent causal review decides meaning. This module only seals
the explicit BASE evidence and rejects scope loss or unqualified new citations.
"""
from __future__ import annotations

from collections import Counter, defaultdict, deque
import json
import re

from wiki_core.document_records import digest, structured_digest


def _unit_hash(graph, node):
    from wiki_core.causal_review import _document
    _document(graph, node)  # Verify lineage; authored node attributes are not identity.
    return (digest(graph["documents"][node]) if node in graph["documents"]
            else graph["nodes"][node]["record_sha256"])


def _upstream_nodes(graph, node):
    from wiki_core.freshness_impact import REFERENCE, STRUCTURAL, ASSOCIATION
    edges = defaultdict(list)
    for raw in graph["edges"]:
        if raw["type"] in STRUCTURAL | ASSOCIATION:
            continue
        consumer, prerequisite = ((raw["source"], raw["target"]) if raw["type"] in REFERENCE
                                  else (raw["target"], raw["source"]))
        edges[consumer].append(prerequisite)
    queue, seen = deque([node]), {node}
    while queue:
        for target in edges[queue.popleft()]:
            if target not in seen:
                seen.add(target); queue.append(target)
    return seen


def _unique_json(data):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate BASE applicability evidence key")
            value[key] = item
        return value
    return json.loads(data, object_pairs_hook=unique)


def citation_qualifications(plan, contract, artifact_inputs, inventory, base, current):
    """Validate every authored claim, without adding a relation to BASE."""
    from wiki_core.causal_review import _document, _normalized_interpretation_edge
    items = plan.get("base_authority_citations", [])
    if not isinstance(items, list):
        raise ValueError("invalid BASE authority citation qualifications")
    result = {}
    for item in items:
        fields = {"edge_id", "evidence_id", "evidence_sha256", "reason"}
        if (not isinstance(item, dict) or set(item) != fields
                or any(not isinstance(item[k], str) or not item[k].strip() for k in fields)
                or not re.fullmatch(r"[a-f0-9]{64}", item["evidence_sha256"])
                or item["edge_id"] in result):
            raise ValueError("invalid/duplicate BASE authority citation qualification")
        row = inventory["edges"].get(item["edge_id"])
        if (not row or row["origin"] != "current" or row["edge"]["type"] != "markdown_link"
                or row["edge"].get("basis") != "markdown_body"
                or row["edge"].get("field") != "body"):
            raise ValueError("BASE authority qualification requires an exact CURRENT body citation")
        unit, authority = row["consumer"], row["prerequisite"]
        if any(n not in g["nodes"] for g in (base, current) for n in (unit, authority)):
            raise ValueError("BASE authority and affected unit must preexist")
        source = _document(base, authority)
        # A previously non-factual occurrence is not a new citation. Without a
        # separate occurrence-remapping proof, even another citation in that
        # same unit/section would be ambiguous; retain conservative behavior.
        unit_document = _document(base, unit)
        for prior in base["edges"]:
            prior_document = base.get("verified_record_documents", {}).get(prior["source"], prior["source"])
            if (prior_document == unit_document and prior.get("basis") == "markdown_body"
                    and prior.get("field") == "body"
                    and prior.get("section") == row["edge"].get("section")
                    and prior["type"] in {"record_context_reference", "navigation_link"}
                    and (prior["target"] == source
                         or base.get("verified_record_documents", {}).get(prior["target"]) == source)):
                raise ValueError("BASE role reclassification is not a new authority citation")
        if (_document(current, authority) != source
                or base["documents"][source] != current["documents"][source]
                or _unit_hash(base, authority) != _unit_hash(current, authority)):
            raise ValueError("BASE cited authority must remain completely intact")
        aid = item["evidence_id"]
        declarations = [a for a in contract.get("artifacts", [])
                        if a.get("origin") == "base" and a.get("id") == aid and "path" in a]
        data = artifact_inputs.get(("base", aid))
        if (len(declarations) != 1 or data is None
                or declarations[0]["sha256"] != item["evidence_sha256"]
                or digest(data.decode()) != item["evidence_sha256"]):
            raise ValueError("BASE applicability requires sealed immutable evidence")
        proof = _unique_json(data)
        expected = {"schema_version", "unit", "unit_base_sha256", "authority", "authority_base_sha256",
                    "authority_document", "authority_document_sha256", "supporting_units", "applicability_reason"}
        if (not isinstance(proof, dict) or set(proof) != expected
                or proof["schema_version"] != "wiki_base_authority_applicability.v1"
                or proof["unit"] != unit or proof["authority"] != authority
                or proof["unit_base_sha256"] != _unit_hash(base, unit)
                or proof["authority_base_sha256"] != _unit_hash(base, authority)
                or proof["authority_document"] != source
                or proof["authority_document_sha256"] != digest(base["documents"][source])
                or not isinstance(proof["applicability_reason"], str) or not proof["applicability_reason"].strip()
                or not isinstance(proof["supporting_units"], list) or not proof["supporting_units"]):
            raise ValueError("BASE applicability proof does not match the exact prior units")
        reachable, seen = _upstream_nodes(base, authority), set()
        for support in proof["supporting_units"]:
            if (not isinstance(support, dict) or set(support) != {"node", "sha256", "complete_text"}
                    or not isinstance(support["node"], str) or support["node"] in seen
                    or support["node"] not in reachable or support["node"] not in base["nodes"]
                    or _document(base, support["node"]) != source
                    or support["sha256"] != _unit_hash(base, support["node"])
                    or not isinstance(support["complete_text"], str) or not support["complete_text"]
                    or digest(support["complete_text"]) != support["sha256"]
                    or support["complete_text"] not in base["documents"][source]):
                raise ValueError("BASE applicability requires complete supporting authority units")
            seen.add(support["node"])
        required_support = {n for n in reachable if n == source
                            or base.get("verified_record_documents", {}).get(n) == source}
        if seen != required_support:
            raise ValueError("BASE applicability evidence omits complete authority context")
        result[item["edge_id"]] = dict(row=row,
            normalized=structured_digest(_normalized_interpretation_edge(row["edge"])))
    return result


def reviewed_citation_extension(base, current, consumer, qualifications):
    """Return exact used claims only for a non-narrowing reviewed extension.

    Prior reachability through a different branch is not inferred to prove
    applicability: each added occurrence needs the independently reviewed BASE
    evidence validated above. The complete graph/census remain unchanged.
    """
    from wiki_core.causal_review import _interpretation_state
    old, new = _interpretation_state(base, consumer), _interpretation_state(current, consumer)
    if old["record_sha256"] != new["record_sha256"] or old["scopes"] != new["scopes"]:
        return None
    before, after = (Counter(map(structured_digest, state["dependencies"])) for state in (old, new))
    if before - after:
        return None
    additions = after - before
    if not additions:
        return None
    # Coordinates move after editing; an old and a new occurrence sharing one
    # normalized signature cannot be matched uniquely by this narrow proof.
    if set(additions) & set(before):
        return None
    covered, used = Counter(), set()
    for eid, item in qualifications.items():
        row = item["row"]
        if row["consumer"] not in old["scopes"] or item["normalized"] not in additions:
            continue
        # Direct consumer interpretation must remain exact. Only a citation
        # inside an already-consumed premise can use this reviewed proof.
        if row["consumer"] == consumer:
            return None
        covered[item["normalized"]] += 1
        used.add(eid)
    return used if covered == additions else None
