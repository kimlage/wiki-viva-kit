"""Installed public consumer: real sync, CLI, writer, auditor and local gates.

GitHub control-plane responses are synthetic; no provider/model/live service.
The old factual-dependency case must fail, not be relabelled as provenance.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import pytest
import yaml

import wiki_core.action_contribution as port
from wiki_core.action_transition import _parse_document, transition_action_page
from wiki_core.config import load_config
from wiki_core.document_records import digest, edge_digest, sections, structured_digest
from wiki_core.freshness_impact import authored_graph, repository_report
from test_action_contribution import git, call, review
from test_action_contribution_strict import remote, reviewed_head


SOURCE = Path(__file__).resolve().parents[1]
ACTION = "memories/actions/synthetic-strict.md"
LOG = "memories/system/log.md"
CONSUMER = "memories/projects/synthetic-historical-act.md"
TODAY = dt.datetime.now(dt.timezone.utc).date().isoformat()


def document(fields, body):
    return "---\n" + yaml.safe_dump(fields, sort_keys=False) + "---\n\n" + body


def invoke(root, *args):
    result = subprocess.run(args, cwd=root, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout[-6000:] + result.stderr[-2000:]
    return result


def installed(root, monkeypatch, *, factual=False):
    monkeypatch.setenv("PATH", str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""))
    subprocess.run(["git", "clone", "--shared", str(SOURCE), str(root)], check=True, capture_output=True)
    git(root, "switch", "-C", "main", git(SOURCE, "rev-parse", "HEAD"))
    git(root, "remote", "remove", "origin")
    git(root, "config", "user.name", "Public Synthetic Consumer")
    git(root, "config", "user.email", "fixture@example.test")
    # The actual supported C1/C2 adoption operation. C3 is then authored by this
    # synthetic consumer in its own committed policy/script, not portable core.
    invoke(SOURCE, sys.executable, "scripts/wiki_sync_from_kit.py", "--kit", str(SOURCE), "--consumer", str(root))
    fields = dict(page_id="synthetic-strict", page_type="action", title="Synthetic strict contribution",
        context="example", visibility="private_self", updated_at="2026-10-01", stale_after_days=30,
        sources_policy="synthetic_only", gate="github_pr", sensitive_data_policy="private_sensitive_allowed",
        source_refs=["sources-synthetic-context"], moc_parent="memories/example/index.md", action_state="open", owner_kind="unassigned",
        created_at="2026-10-01", next_action="Retain a direction", priority="normal", attention_basis="Public synthetic coverage only.",
        actions=[], claims=[], decisions=[], evidence_refs=[], owner=[], related_holons=[], responsibilities=[], roles=[])
    old_body = "# Synthetic strict contribution\n\n## Retained direction\nThe recorded direction is an integration exercise, without a business conclusion.\n"
    (root / "memories/projects").mkdir(parents=True, exist_ok=True)
    context_source = {**fields, "page_id": "sources-synthetic-context", "page_type": "source", "title": "Synthetic fixture context",
                      "updated_at": TODAY, "source_type": "reference", "source_refs": []}
    (root / "memories/sources/synthetic-context.md").write_text(document(context_source,
        "# Synthetic fixture context\n\nA fictional source used only by this test.\n\n## Related\n\n- [Example context](../example/index.md)\n"))
    if factual:
        stale = {**fields, "page_id": "project-synthetic-old-fact", "title": "A retained factual dependency", "page_type": "project", "updated_at": "2020-01-01", "source_refs": ["sources-synthetic-context"]}
        (root / "memories/projects/synthetic-old-fact.md").write_text(document(stale, "# A retained factual dependency\n\nThis fact requires a real source update.\n"))
        old_body += "The factual assertion consumes [this source](../projects/synthetic-old-fact.md).\n"
    (root / ACTION).parent.mkdir(parents=True, exist_ok=True)
    (root / ACTION).write_text(document(fields, old_body))
    transition_action_page(root, ACTION, "open", next_action="Keep the explicit recorded direction",
        expected_sha256=digest((root / ACTION).read_text()), recorded_at="2026-10-01T12:00:00Z")
    old_entry = _parse_document((root / ACTION).read_text())[0]["action_state_history"][-1]
    historical = {**fields, "page_id": "project-synthetic-historical-act", "title": "Historical act reference", "page_type": "project", "updated_at": "2020-01-01", "source_refs": ["sources-synthetic-context"]}
    (root / CONSUMER).write_text(document(historical, "# Historical act reference\n\nThe [recorded action](../actions/synthetic-strict.md) identifies the old direction-recording act, not a domain fact or current execution.\n"))
    log = root / LOG
    fm, body = _parse_document(log.read_text()); fm["updated_at"] = TODAY
    log.write_text(document(fm, body.rstrip("\n") + "\n\n## Retained synthetic record\nA literal retained integration record.\n"))
    hub = root / "memories/example/index.md"
    hub_fm, hub_body = _parse_document(hub.read_text())
    hub_fm["related_pages"] = [*hub_fm.get("related_pages", []), ACTION, CONSUMER]
    hub.write_text(document(hub_fm, hub_body.rstrip() + "\n\n## Navigation\n\n- [Synthetic action](../actions/synthetic-strict.md)\n- [Historical integration act](../projects/synthetic-historical-act.md)\n"))
    private_script = root / "consumer/prepare_records.py"; private_script.parent.mkdir()
    shutil.copyfile(SOURCE / "tests/fixtures/contribution_consumer_prepare.py", private_script)
    config_path = root / "wiki.config.yaml"; config = yaml.safe_load(config_path.read_text())
    config["approval"].update(gate="github_pr", contribution_c3={"argv": ["python3", "consumer/prepare_records.py"], "derived_paths": ["consumer/records.json"]},
        contribution_validation={"mode": "local"}, contribution_gates=[["python3", "scripts/wiki_check_methodology_coverage.py", "--check"]])
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))
    git(root, "add", "."); git(root, "commit", "-m", "Author synthetic consumer and historical reference")
    base = git(root, "rev-parse", "HEAD")
    config.setdefault("audit", {}).update(freshness_scope="impact", freshness_base=base, freshness_records="consumer/records.json")
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))
    graph = authored_graph(root, load_config(root))
    records = []
    for path, heading, rid in [(ACTION, "Retained direction", "retained-direction"), (LOG, "Retained synthetic record", "retained-log")]:
        section_hash = digest(sections(graph["documents"][path])[1][heading][2])
        records.append({"path": path, "records": [{"id": rid, "heading": heading, "independent": True,
            "rationale": "Explicit synthetic independent integration record; no domain conclusion.", "epistemic_status": "observation",
            "recorded_on": "2026-10-01", "context_records": [], "base_sha256": section_hash, "current_sha256": section_hash}]})
    edge = next(e for e in graph["edges"] if e["source"] == CONSUMER and e["target"] == ACTION)
    navigation = min((e for e in graph["edges"] if e["source"] == LOG and e["target"] == "memories/index.md"), key=lambda e: e.get("body_line", 0))
    artifacts = [{"origin": origin, "id": "retained-direction", "document": ACTION, "field": "action_state_history",
        "match_key": "receipt_id", "match_value": old_entry["receipt_id"], "sha256": structured_digest(old_entry)} for origin in ("base", "current")]
    bindings = [{"origin": origin, "edge_sha256": edge_digest(edge), "consumer_record": "document", "role": "provenance",
        "target_document_sha256": digest(graph["documents"][ACTION]), "evidence": ["retained-direction"],
        "rationale": "This citation identifies the old direction-recording act, not truth of a domain fact or current execution."} for origin in ("base", "current")]
    # These two existing public catalog occurrences are authored navigation,
    # not readings of every future assertion in the log. Pin each occurrence;
    # never classify every link to a shared page by endpoint alone.
    catalog_edges = []
    for catalog in ("memories/index.md", "memories/operations.md"):
        matches = [e for e in graph["edges"] if e["source"] == catalog and e["target"] == LOG and e["basis"] == "markdown_body"]
        assert len(matches) == 1
        catalog_edges.extend(matches)
        bindings.extend({"origin": origin, "edge_sha256": edge_digest(matches[0]), "consumer_record": "document",
            "role": "navigation", "target_document_sha256": digest(graph["documents"][LOG]), "evidence": [],
            "rationale": "This exact catalog item opens the log; it does not consume or assert the truth of each log entry."} for origin in ("base", "current"))
    contract = {"schema_version": "document_record.v1", "base_documents_sha256": {p: digest(t) for p, t in graph["documents"].items()},
        "current_documents_sha256": {p: digest(t) for p, t in graph["documents"].items()}, "documents": records, "bindings": bindings, "artifacts": artifacts}
    (root / "consumer/records.json").write_text(json.dumps(contract, sort_keys=True, indent=2) + "\n")
    git(root, "add", "."); git(root, "commit", "-m", "Review exact synthetic record snapshots and roles")
    baseline = invoke(root, sys.executable, "scripts/wiki_audit.py", "--check")
    before = (root / ACTION).read_text()
    text = before + "## Contribution appendix\nA reviewed synthetic integration appendix; no business fact or live execution.\n"
    authored_records = [{"path": path, "record": {"id": rid, "heading": heading, "independent": True,
        "rationale": "Explicit new integration-act record; prior assertions are not refreshed.", "epistemic_status": "observation",
        "recorded_on": TODAY, "context_records": []}} for path, heading, rid in
        [(ACTION, "Contribution appendix", "contribution-appendix"), (LOG, "$generated_log_heading", "integration-act")]]
    plan = {"schema_version": "synthetic_integration_act.v1", "purpose": "Record only the integration act; no domain conclusion.",
        "records": authored_records, "refresh_binding_hashes": [{"edge_sha256": edge_digest(edge), "consumer_record": "document", "target_document": ACTION},
            *[{"edge_sha256": edge_digest(e), "consumer_record": "document", "target_document": LOG} for e in catalog_edges]],
        "added_artifacts": [{"origin": "current", "id": "new-integration-act", "document": ACTION, "field": "action_state_history",
            "match_key": "receipt_id", "match_value": "$receipt_id", "sha256": "$receipt_sha256"}],
        "bindings": [{"edge_match": {"source": LOG, "target": ACTION, "path": LOG, "basis": "markdown_body"},
            "consumer_record": "integration-act", "role": "provenance", "evidence": ["new-integration-act"],
            "rationale": "The generated annotation proves the reviewed integration act only, not execution or domain truth."},
            {"edge_match": {k: navigation[k] for k in ("source", "target", "path", "basis", "body_line")},
             "consumer_record": "integration-act", "role": "navigation", "evidence": [],
             "rationale": "The existing introduction links to the memory index for navigation; it is not a factual premise of the integration annotation."}]}
    request = {"schema_version": port.SCHEMA, "task_ref": {"repo_id": config["repo_id"], "action_id": "synthetic-strict"},
        "run_ref": {"runtime": "synthetic-local", "task_id": "same-synthetic-task", "run_id": "one"},
        "session_ref": {"session_id": "synthetic-author", "coverage": "Synthetic only; no provider/model/native runtime"},
        "effect_key": "synthetic-strict-integration", "files": [{"path": ACTION, "base_commit": git(root, "rev-parse", "HEAD"),
            "base_sha256": digest(before), "sha256": digest(text), "text": text}],
        "consumer_preparation": {"schema_version": "wiki_consumer_preparation.v1", "authored_plan": plan}}
    return request, contract, baseline


@pytest.mark.parametrize("factual", [False, True])
def test_installed_strict_real_writer_fm_and_historical_consumers(tmp_path, monkeypatch, factual):
    root = tmp_path / "consumer"
    request, original_contract, _ = installed(root, monkeypatch, factual=factual)
    before = (root / ACTION).read_bytes()
    request_file = tmp_path / "request.json"; request_file.write_text(json.dumps(request))
    review_file = tmp_path / "review.json"; review_file.write_text(json.dumps(review(request)))
    process = subprocess.run([sys.executable, str(root / "scripts/wiki_contribution.py"), "prepare", "--root", str(root),
        "--request", str(request_file), "--review", str(review_file), "--apply"], text=True, capture_output=True)
    result = json.loads(process.stdout)
    (tmp_path / "prepare-result.json").write_text(json.dumps(result, indent=2) + "\n")
    if factual:
        assert process.returncode != 0 and result["error"].startswith("proposal_gate_failed"), result
        assert any("freshness" in g.get("diagnostic_tail", "").lower() for g in result["gate_receipts"]), result
        assert not git(root, "branch", "--list", "wiki/contribution-*")
    else:
        assert process.returncode == 0 and result["status"] == "prepared", json.dumps(result, indent=2)
        candidate = result["proposal_commit"]
        old_fm, _ = _parse_document(before.decode())
        new_fm, _ = _parse_document(port._blob(root, candidate, ACTION))
        assert old_fm["updated_at"] != new_fm["updated_at"]
        assert new_fm["action_state_history"][:-1] == old_fm["action_state_history"]
        proposed_contract = json.loads(port._blob(root, candidate, "consumer/records.json"))
        assert proposed_contract["artifacts"][:-1] == original_contract["artifacts"]
        # Inspect the real projection on the frozen candidate, without changing
        # the application's checkout. FM remains part of remainder/whole seed.
        with tempfile.TemporaryDirectory(prefix="strict-projection-") as temporary:
            observed = Path(temporary) / "candidate"
            invoke(root, "git", "clone", "--shared", "--no-checkout", str(root), str(observed))
            git(observed, "checkout", "--detach", candidate)
            config = load_config(observed)
            projection = repository_report(observed, config, config.audit["freshness_base"])
            assert projection["ok"], projection["blockers"]
            assert ACTION in projection["seeds"]
            action_record = next(d for d in projection["document_records"] if d["path"] == ACTION)
            assert not action_record["complete_delta_covered"]  # the technical FM change is real
            assert CONSUMER in {r["path"] for r in projection["unrelated_debt"]}
            assert not any(r["path"] == CONSUMER for r in projection["included"])
        pr, effects = remote(root, result, monkeypatch)
        integrated = call(root, "integrate", request, pr=1, head_review=reviewed_head(request, result))
        assert integrated["remote_merged"] and not integrated["canonical_body_adopted"], integrated
        assert not integrated["served_adoption_verified"] and len(effects) == 1
    assert (root / ACTION).read_bytes() == before
    assert json.loads((root / "consumer/records.json").read_text()) == original_contract
