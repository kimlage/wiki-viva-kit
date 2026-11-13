"""The legacy impact gate reads canonical typed semantics, not freshness verdicts."""
from __future__ import annotations

import json

import pytest
import yaml

from scripts import wiki_audit as audit
from wiki_core.config import load_config
from wiki_core.freshness_impact import authored_graph, repository_report
from test_freshness_impact import repo, page, commit, git
from test_document_records import declaration, add_binding


def scenario(root, *, bound=True, contract=True, mixed=False, ack=False, consumer_append=False, new_stale=False):
    page(root, "old-source", stale=True)
    page(root, "new-source", stale=new_stale)
    source = page(root, "log", body="# Log\n\n## Old record\nOld [fact](old-source.md).\n")
    consumer = page(root, "consumer", body="# Consumer\n\nThe retained claim consumes [log](log.md).\n")
    if ack:
        ledger = root / "notes/acks.md"; ledger.parent.mkdir()
        ledger.write_text("- affected: memories/consumer.md; reason: historical review already completed.\n")
    base_graph = authored_graph(root, load_config(root)); base = commit(root)
    source.write_text(source.read_text() + "## New record\nA new [fact](new-source.md).\n")
    if mixed:
        source.write_text(source.read_text().replace("2026-10-18", "2026-10-19"))
    if consumer_append:
        consumer.write_text(consumer.read_text() + "## New record\nIndependent unrelated consumer appendix.\n")
    current = authored_graph(root, load_config(root))
    records = declaration(base_graph, current)
    if consumer_append:
        records["documents"] += declaration(base_graph, current, "memories/consumer.md")["documents"]
    if bound:
        for origin, graph in (("base", base_graph), ("current", current)):
            add_binding(records, graph, origin)
    config = yaml.safe_load((root / "wiki.config.yaml").read_text())
    config["audit"].update(impact_check=True, freshness_base=base)
    if ack: config["paths"] = {"impact_acks_page": "notes/acks.md"}
    if contract:
        config["audit"]["freshness_records"] = "records.json"
        (root / "records.json").write_text(json.dumps(records))
    (root / "wiki.config.yaml").write_text(yaml.safe_dump(config))
    return base, records


def errors(root, monkeypatch):
    monkeypatch.setattr(audit, "ROOT", root)
    found = []
    audit.audit_impact(found, load_config(root))
    return found


def test_unchanged_typed_consumption_does_not_create_an_ack_obligation(repo, monkeypatch):
    base, _ = scenario(repo, new_stale=True)
    assert errors(repo, monkeypatch) == []
    report = repository_report(repo, load_config(repo), base)
    assert not report["ok"]  # the new record's actual prerequisite is stale
    # Impact is not inferred from ok/blockers; only downstream changed meaning.
    assert not any(r["document_path"] == "memories/consumer.md" for r in report["affected_dependents"])


@pytest.mark.parametrize("with_contract", [False, True])
def test_whole_document_factual_consumer_remains_obligated(repo, monkeypatch, with_contract):
    scenario(repo, bound=False, contract=with_contract)
    found = errors(repo, monkeypatch)
    assert any("memories/consumer.md: impacted" in e for e in found), found
    assert not any("memories/old-source.md: impacted" in e for e in found)  # prerequisite, not dependent


def test_mixed_frontmatter_and_body_remains_a_whole_document_seed(repo, monkeypatch):
    scenario(repo, mixed=True)
    found = errors(repo, monkeypatch)
    assert any("memories/consumer.md: impacted" in e for e in found), found


def test_changing_another_consumer_record_does_not_satisfy_the_affected_assertion(repo, monkeypatch):
    scenario(repo, bound=False, consumer_append=True)
    found = errors(repo, monkeypatch)
    assert any("memories/consumer.md: impacted" in e and "::record:remainder" in e for e in found), found


@pytest.mark.parametrize("fault", ["snapshot", "binding", "artifact", "missing-file", "base"])
def test_invalid_or_unknown_contract_fails_even_when_only_impact_runs(repo, monkeypatch, fault):
    _, records = scenario(repo)
    if fault == "snapshot": records["current_documents_sha256"] = {}
    elif fault == "binding": records["bindings"][0]["edge_sha256"] = "0" * 64
    elif fault == "artifact": records["artifacts"] = [{"origin": "current", "id": "missing", "path": "missing.bin", "sha256": "0" * 64}]
    if fault == "missing-file": (repo / "records.json").unlink()
    else: (repo / "records.json").write_text(json.dumps(records))
    if fault == "base":
        p = repo / "wiki.config.yaml"; config = yaml.safe_load(p.read_text()); config["audit"]["freshness_base"] = "unavailable-ref"; p.write_text(yaml.safe_dump(config))
    found = errors(repo, monkeypatch)
    assert any("typed impact evidence unavailable" in e for e in found), found


def test_ack_must_be_new_in_the_exact_base_delta(repo, monkeypatch):
    base, _ = scenario(repo, bound=False, contract=False, ack=True)
    # An older origin/main must not make an ACK already present at `base` new.
    git(repo, "update-ref", "refs/remotes/origin/main", base)
    assert any("memories/consumer.md: impacted" in e for e in errors(repo, monkeypatch))
    with (repo / "notes/acks.md").open("a") as stream:
        stream.write("- affected: memories/consumer.md; reason: reviewed the actual new assertion in this exact delta.\n")
    assert errors(repo, monkeypatch) == []


def test_typed_input_mutation_is_not_reported_as_no_impact(repo, monkeypatch):
    scenario(repo)
    original = audit.build_page_graph
    def graph(*args):
        result = original(*args)
        p = repo / "memories/consumer.md"; p.write_text(p.read_text() + "\nConcurrent mutation.\n")
        return result
    monkeypatch.setattr(audit, "build_page_graph", graph)
    assert any("typed impact inputs changed" in e for e in errors(repo, monkeypatch))


def test_global_profile_keeps_legacy_impact_route(repo, monkeypatch):
    scenario(repo, bound=False, contract=False)
    p = repo / "wiki.config.yaml"; config = yaml.safe_load(p.read_text()); config["audit"]["freshness_scope"] = "global"; p.write_text(yaml.safe_dump(config))
    monkeypatch.setattr(audit, "_impact_relevant_changed_paths", lambda: {"memories/log.md"})
    monkeypatch.setattr(audit, "changed_paths_for_audit", lambda: {"memories/log.md"})
    assert any("memories/consumer.md: impacted by changed page(s)" in e for e in errors(repo, monkeypatch))
