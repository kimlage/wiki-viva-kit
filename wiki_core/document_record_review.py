"""Read-only occurrence census for authoring an existing document_record.v1.

This does not infer intent, propose bindings, evaluate freshness or approve a
transaction. The projector supplies every variant and its actual output.
"""
from __future__ import annotations

import copy
import datetime as dt

from wiki_core.document_records import digest, edge_digest, project_records
from wiki_core.freshness_impact import ASSOCIATION, REFERENCE, STRUCTURAL


def _metadata(value):
    """Preserve YAML dates in JSON without mutating the projected nodes."""
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _metadata(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_metadata(v) for v in value]
    return copy.deepcopy(value)


def review_records(current, base, changed, contract, *, targets, artifact_inputs=None):
    """Inspect all incoming occurrences and own premises of target documents.

    Callers supply the exact authored graphs, not selected witness chains. Both
    origins and every inherited consumer variant are retained. Whole-document
    consumers remain whole; a missing binding is not an invalid binding.
    """
    targets = set(targets)
    if not targets or not targets <= (set(current["documents"]) | set(base["documents"])):
        raise ValueError("review targets must name existing authored documents")
    if current["errors"] or base["errors"]:
        raise ValueError("authored graph diagnostics must be resolved before review")
    # Never omit another authored page changed by the same transaction merely
    # because a caller requested the first source in a reported witness.
    targets.update(set(changed) & (set(current["documents"]) | set(base["documents"])))
    trace = []
    projected_current, projected_base, seeds, coverage = project_records(
        current, base, changed, contract, artifact_inputs=artifact_inputs,
        review_trace=trace)
    graphs = {"base": projected_base, "current": projected_current}
    originals = {"base": base, "current": current}

    def document(graph, endpoint):
        return graph["nodes"].get(endpoint, {}).get("document_path", endpoint)

    rows, documents = [], {"base": {}, "current": {}}
    nodes = {"base": {}, "current": {}}
    presence = {path: {} for path in sorted(targets)}
    for origin, graph in graphs.items():
        for path in sorted(targets):
            text = originals[origin]["documents"].get(path)
            presence[path][origin] = dict(exists=text is not None, incoming_variants=0,
                                          own_premise_variants=0)
            if text is not None:
                documents[origin][path] = dict(sha256=digest(text), text=text)
        for endpoint, values in sorted(graph["nodes"].items()):
            if document(graph, endpoint) in targets:
                nodes[origin][endpoint] = _metadata(values)
    for item in trace:
        origin = item["origin"]
        graph, edge = graphs[origin], item["before"]
        prerequisite_key, dependent_key = (("target", "source")
            if edge["type"] in REFERENCE else ("source", "target"))
        prerequisite, dependent = edge[prerequisite_key], edge[dependent_key]
        incoming = document(graph, prerequisite) in targets
        premise = document(graph, dependent) in targets
        if not (incoming or premise):
            continue
        row = copy.deepcopy(item)
        row.update(incoming=incoming, own_premise=premise,
                   prerequisite=prerequisite, dependent=dependent,
                   factual_before_binding=edge["type"] not in STRUCTURAL | ASSOCIATION)
        rows.append(row)
        if incoming:
            presence[document(graph, prerequisite)][origin]["incoming_variants"] += 1
        if premise:
            presence[document(graph, dependent)][origin]["own_premise_variants"] += 1
        for relation in [item["raw"], item["before"], *item["projected"]]:
            for key in ("source", "target"):
                endpoint = relation[key]
                if endpoint in graph["nodes"]:
                    nodes[origin][endpoint] = _metadata(graph["nodes"][endpoint])
        # Full author/source context remains available for focal reading; the
        # line/section/field in each occurrence identifies the assertion. A hash
        # or local snippet alone cannot approve its semantics.
        for path in sorted({item["raw"]["path"], document(graph, prerequisite),
                            document(graph, dependent)}):
            text = originals[origin]["documents"].get(path)
            if text is not None:
                documents[origin][path] = dict(sha256=digest(text), text=text)
    identities = [(r["origin"], r["raw_index"], r["variant_index"]) for r in rows]
    if len(set(identities)) != len(identities):
        raise ValueError("duplicate projection review identity")
    # Bind the entire input pair, not only the printed frontier. This is a
    # completeness checksum, not a semantic qualification or a freshness gate.
    input_hashes = {o: {p: digest(t) for p, t in sorted(g["documents"].items())}
                   for o, g in originals.items()}
    return dict(schema="document_record_review.v1", targets=sorted(targets),
        purpose="Authoring aid only; no inferred bindings, approval or freshness result",
        contract_sha256=edge_digest(contract), input_documents_sha256=input_hashes,
        projected_variant_count=len(trace), selected_variant_count=len(rows),
        occurrence_set_sha256=edge_digest(rows), occurrences=rows,
        documents=documents, nodes=nodes, target_presence=presence,
        record_declarations=[copy.deepcopy(d) for d in contract["documents"]
            if any(d["path"] in documents[o] for o in originals)],
        changed_record_seeds=sorted(seeds), record_coverage=coverage)
