"""Synthetic consumer-owned C3 example, NOT a universal semantic classifier.

Only an explicit reviewed plan can add record declarations and integration-act
provenance. This fixture cannot certify domain facts or relabel factual edges.
No model, source recapture, page date change or extra output file is involved.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path.cwd()))
from wiki_core.action_transition import _parse_document
from wiki_core.config import load_config
from wiki_core.document_records import digest, edge_digest, sections, structured_digest
from wiki_core.freshness_impact import authored_graph


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--contribution-file", type=Path, required=True)
    payload = json.loads(parser.parse_args().contribution_file.read_text())
    request = payload["request"]
    plan = request["consumer_preparation"]["authored_plan"]
    if (set(plan) != {"schema_version", "purpose", "records", "refresh_binding_hashes", "bindings", "added_artifacts"}
        or plan["schema_version"] != "synthetic_integration_act.v1"
        or plan["purpose"] != "Record only the integration act; no domain conclusion."):
        raise ValueError("explicit synthetic integration-act plan required")
    action = request["files"][0]["path"]
    fm, _ = _parse_document(Path(action).read_text())
    entry = fm["action_state_history"][-1]
    if entry["receipt_id"] != payload["action_receipt"]["receipt_id"] or entry["kind"] != "body_integration":
        raise ValueError("generated receipt mismatch")
    graph = authored_graph(Path.cwd(), load_config(Path.cwd()))
    path = Path(payload["derived_paths"][0])
    contract = json.loads(path.read_text())
    for authored in plan["records"]:
        if set(authored) != {"path", "record"} or authored["path"] not in {action, payload["generated_log"]["path"]}:
            raise ValueError("record outside explicit action/log plan")
        record = dict(authored["record"])
        if (record.get("independent") is not True or not record.get("rationale")
            or record.get("epistemic_status") != "observation" or record.get("context_records") != []
            or "base_sha256" in record or "current_sha256" in record):
            raise ValueError("explicit reviewed record meaning required")
        if record["heading"] == "$generated_log_heading":
            record["heading"] = payload["generated_log"]["heading"]
        content = sections(graph["documents"][authored["path"]])[1][record["heading"]][2]
        record.update(base_sha256=None, current_sha256=digest(content))
        declaration = next((d for d in contract["documents"] if d["path"] == authored["path"]), None)
        if declaration is None:
            declaration = {"path": authored["path"], "records": []}
            contract["documents"].append(declaration)
        if any(r["id"] == record["id"] for r in declaration["records"]):
            raise ValueError("record already exists")
        declaration["records"].append(record)
    for artifact in plan["added_artifacts"]:
        if (artifact["document"] != action or artifact["field"] != "action_state_history"
            or artifact["match_key"] != "receipt_id" or artifact["match_value"] != "$receipt_id"
            or artifact["sha256"] != "$receipt_sha256" or artifact["origin"] != "current"):
            raise ValueError("only the actual generated integration receipt may be added")
        contract.setdefault("artifacts", []).append({**artifact, "match_value": entry["receipt_id"], "sha256": structured_digest(entry)})
    for authored in plan["refresh_binding_hashes"]:
        matches = [b for b in contract["bindings"] if b.get("origin") == "current"
                   and b.get("edge_sha256") == authored["edge_sha256"]
                   and b.get("consumer_record", "document") == authored["consumer_record"]]
        target = authored["target_document"]
        edges = [e for e in graph["edges"] if edge_digest(e) == authored["edge_sha256"]]
        if (len(matches) != 1 or len(edges) != 1 or edges[0]["target"] != target
            or matches[0].get("role") not in {"provenance", "navigation"}
            or target not in {action, payload["generated_log"]["path"]}):
            raise ValueError("only explicitly selected existing occurrence roles may refresh their current document hash")
        matches[0]["target_document_sha256"] = digest(graph["documents"][target])
    for authored in plan["bindings"]:
        if (set(authored) != {"edge_match", "consumer_record", "role", "evidence", "rationale"}
            or authored["role"] not in {"provenance", "navigation"}
            or (authored["role"] == "provenance" and not authored["evidence"]) or not authored["rationale"]
            or authored["edge_match"].get("source") != payload["generated_log"]["path"]
            or authored["edge_match"].get("target") not in graph["documents"]
            or (authored["role"] == "provenance" and authored["edge_match"].get("target") != action)):
            raise ValueError("explicit integration-act relation required; factual roles cannot be converted")
        edges = [e for e in graph["edges"] if all(e.get(k) == v for k, v in authored["edge_match"].items())]
        if len(edges) != 1:
            raise ValueError("ambiguous or missing authored edge")
        contract["bindings"].append({k: v for k, v in authored.items() if k != "edge_match"} |
            {"origin": "current", "edge_sha256": edge_digest(edges[0]),
             "target_document_sha256": digest(graph["documents"][authored["edge_match"]["target"]])})
    contract["current_documents_sha256"] = {p: digest(t) for p, t in graph["documents"].items()}
    path.write_text(json.dumps(contract, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


if __name__ == "__main__":
    main()
