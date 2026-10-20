"""Public synthetic authoring census, with no alternative freshness rules."""
import copy
import datetime as dt
import json
import os
import subprocess
import sys

import pytest
import yaml

from wiki_core.document_record_review import review_records
from wiki_core.document_records import digest, edge_digest, project_records
from wiki_core.document_records import structured_digest
from test_document_records import (
    add_binding, declaration, graph, setup_increment,
)
from test_freshness_impact import page, repo, commit, git, TODAY


@pytest.mark.parametrize("kind", ["record_evidence", "occurrence_evidence"])
def test_structured_evidence_includes_unlinked_parent_text_per_origin(repo, kind):
    event = dict(event_id="dated-result", text="Assisted historical result.")
    parent = page(repo, "archive", action_dialogue=[event],
                  body="# Archive\n\nBASE context and limitations.\n")
    page(repo, "source")
    link = "[Source](source.md)." if kind == "occurrence_evidence" else "No citation."
    log = page(repo, "log", body="# Log\n\n## New record\n" + link + "\n")
    base = graph(repo)
    parent.write_text(parent.read_text().replace("BASE context", "CURRENT context"))
    log.write_text(log.read_text() + "Additional dated observation.\n")
    current = graph(repo)
    contract = declaration(base, current)
    contract["artifacts"] = [dict(origin=origin, id="dated-result",
        document="memories/archive.md", field="action_dialogue",
        match_key="event_id", match_value="dated-result", sha256=structured_digest(event))
        for origin in ("base", "current")]
    for origin, authored in (("base", base), ("current", current)):
        if kind == "record_evidence":
            contract["documents"][0]["records"][0][origin + "_evidence"] = ["dated-result"]
        else:
            raw = next(e for e in authored["edges"] if e["source"] == "memories/log.md")
            contract["bindings"].append(dict(origin=origin, edge_sha256=edge_digest(raw),
                consumer_record="entry-0", role="provenance", evidence=["dated-result"],
                prerequisite_document_sha256=digest(authored["documents"]["memories/source.md"]),
                rationale="The isolated event supplies historical evidence only."))
    before = copy.deepcopy((base, current, contract))
    result = review_records(current, base, {"memories/log.md"}, contract,
                            targets={"memories/log.md"})
    for origin, authored in (("base", base), ("current", current)):
        # No raw relation or requested target otherwise selects the archive.
        assert not any("memories/archive.md" in (e["source"], e["target"])
                       for e in authored["edges"])
        assert result["documents"][origin]["memories/archive.md"] == dict(
            text=authored["documents"]["memories/archive.md"],
            sha256=digest(authored["documents"]["memories/archive.md"]))
        assert any(n.get("evidence_source", {}).get("document") == "memories/archive.md"
                   for n in result["nodes"][origin].values())
    assert (base, current, contract) == before


@pytest.mark.parametrize("metadata", [None, "ordinary annotation",
                                      {"document": "memories/unrelated.md"}])
@pytest.mark.parametrize("marker", [False, True])
def test_ordinary_frontmatter_cannot_impersonate_evidence_context(repo, metadata, marker):
    page(repo, "source", evidence_source=metadata, immutable_evidence=marker)
    page(repo, "unrelated", body="Unrelated context must not be imported.")
    log = page(repo, "log", body="# Log\n\n## Old\nPrior.\n\n")
    base = graph(repo)
    log.write_text(log.read_text() + "## New record\n[Source](source.md).\n")
    current = graph(repo)
    contract = declaration(base, current)
    result = review_records(current, base, {"memories/log.md"}, contract,
                            targets={"memories/log.md"})
    assert "memories/source.md" in result["documents"]["current"]
    assert "memories/unrelated.md" not in result["documents"]["current"]


def test_trace_is_an_observer_and_does_not_mutate_inputs(repo):
    base, current, contract = setup_increment(repo, consumer=True)
    before = copy.deepcopy((current, base, contract))
    expected = project_records(current, base, {"memories/log.md"}, contract)
    trace = []
    actual = project_records(current, base, {"memories/log.md"}, contract, review_trace=trace)
    assert actual == expected
    assert (current, base, contract) == before
    assert trace and {r["origin"] for r in trace} == {"base", "current"}
    assert all(r["edge_sha256"] == edge_digest(r["raw"]) for r in trace)
    assert sum(len(r["projected"]) for r in trace) == sum(len(g["edges"]) for g in actual[:2])


def test_census_keeps_second_link_and_inherited_frontmatter_variants(repo):
    page(repo, "old-source", stale=True)
    page(repo, "new-source")
    p = page(repo, "log", body="# Log\n\n## Old\nOld [source](old-source.md).\n\n")
    page(repo, "consumer", source_refs=["log"],
         body="# Consumer\n\n## Old\n[one](log.md).\n\n## New record\n[two](log.md).\n")
    base = graph(repo)
    p.write_text(p.read_text() + "## New record\nNew [source](new-source.md).\n")
    current = graph(repo)
    contract = declaration(base, current)
    contract["documents"] += declaration(base, current, "memories/consumer.md")["documents"]
    result = review_records(current, base, {"memories/log.md"}, contract,
                            targets={"memories/log.md"})
    for origin in ("base", "current"):
        rows = [r for r in result["occurrences"] if r["origin"] == origin
                and r["incoming"] and r["raw"]["path"] == "memories/consumer.md"]
        assert len(rows) == 4  # two body links and two inherited metadata variants
        assert len({r["edge_sha256"] for r in rows}) == 3
        metadata = [r for r in rows if r["raw"]["field"] == "source_refs"]
        assert {r["consumer_record"] for r in metadata} == {"entry-0", "remainder"}
        assert all(r["before"]["inherited_document_context"] for r in metadata)
        assert all(r["binding"] is None for r in rows)
    assert result["occurrence_set_sha256"] == edge_digest(result["occurrences"])


def test_qualified_historical_link_does_not_hide_a_second_live_link(repo):
    base, current, contract = setup_increment(repo, consumer=True)
    for origin, g in (("base", base), ("current", current)):
        add_binding(contract, g, origin)
        raw = next(e for e in g["edges"] if e["path"] == "memories/consumer.md")
        # Another factual occurrence has a separate identity; it stays WHOLE.
        g["edges"].append({**raw, "body_offset": 999, "body_line": 99})
    result = review_records(current, base, {"memories/log.md"}, contract,
                            targets={"memories/log.md"})
    rows = [r for r in result["occurrences"] if r["incoming"]
            and r["raw"]["path"] == "memories/consumer.md"]
    assert len(rows) == 4
    assert all(any(e.get("whole_document_consumption") for e in r["projected"])
               for r in rows if r["binding"] is None)
    assert all(not any(e.get("whole_document_consumption") for e in r["projected"])
               for r in rows if r["binding"] is not None)


def test_external_authored_relation_is_not_lost_at_consumer_partition(repo):
    page(repo, "old-source", stale=True)
    page(repo, "new-source")
    p = page(repo, "log", body="# Log\n\n## Old\nPrior.\n\n")
    page(repo, "consumer", body="# Consumer\n\n## Old\nPrior.\n\n## New record\nCurrent.\n")
    base = graph(repo)
    p.write_text(p.read_text() + "## New record\nNew.\n")
    current = graph(repo)
    contract = declaration(base, current)
    contract["documents"] += declaration(base, current, "memories/consumer.md")["documents"]
    for g in (base, current):
        g["edges"].append(dict(source="memories/log.md", target="memories/consumer.md",
            type="impact", direction="directed", basis="frontmatter",
            path="memories/log.md", field="consolidated_into"))
    result = review_records(current, base, {"memories/log.md"}, contract,
                            targets={"memories/log.md"})
    rows = [r for r in result["occurrences"] if r["raw"]["field"] == "consolidated_into"]
    assert len(rows) == 4
    assert all(r["incoming"] and r["raw"]["path"] == "memories/log.md"
               and r["before"]["inherited_document_context"] for r in rows)
    assert {r["consumer_record"] for r in rows} == {"entry-0", "remainder"}


@pytest.mark.parametrize("change", ["removed", "retargeted"])
def test_old_dependency_survives_removed_or_retargeted_occurrence(repo, change):
    base, current, contract = setup_increment(repo, consumer=True)
    if change == "removed":
        current["edges"] = [e for e in current["edges"] if e["path"] != "memories/consumer.md"]
    else:
        for edge in current["edges"]:
            if edge["path"] == "memories/consumer.md":
                edge["target"] = "memories/new-source.md"
    result = review_records(current, base, {"memories/log.md", "memories/consumer.md"},
                            contract, targets={"memories/log.md"})
    assert "memories/consumer.md" in result["targets"]
    assert any(r["origin"] == "base" and r["raw"]["path"] == "memories/consumer.md"
               and r["prerequisite"] == "memories/log.md" for r in result["occurrences"])
    if change == "retargeted":
        assert any(r["origin"] == "current" and r["prerequisite"] == "memories/new-source.md"
                   for r in result["occurrences"])


def test_invalid_binding_never_publishes_a_partial_success_trace(repo):
    base, current, contract = setup_increment(repo, consumer=True)
    add_binding(contract, current, "current")
    contract["bindings"][0]["consumed_sha256"] = "wrong"
    trace = []
    with pytest.raises(ValueError, match="hash mismatch"):
        project_records(current, base, {"memories/log.md"}, contract, review_trace=trace)
    assert trace == []
    with pytest.raises(ValueError):
        review_records(current, base, {"memories/log.md"}, contract,
                       targets={"memories/log.md"})


def test_zero_edge_targets_include_text_declarations_and_freshness_nodes(repo):
    p = page(repo, "log", body="# Log\n\n## Old\nPrior.\n\n", observed_on=dt.date(2026, 10, 18))
    base = graph(repo)
    p.write_text(p.read_text() + "## New record\nNo citations or incoming links.\n")
    current = graph(repo)
    contract = declaration(base, current)
    result = review_records(current, base, {"memories/log.md"}, contract,
                            targets={"memories/log.md"})
    for origin in ("base", "current"):
        assert result["documents"][origin]["memories/log.md"]["text"] == (
            {"base": base, "current": current}[origin]["documents"]["memories/log.md"])
        assert result["target_presence"]["memories/log.md"][origin] == dict(
            exists=True, incoming_variants=0, own_premise_variants=0)
    node = result["nodes"]["current"]["memories/log.md::record:entry-0"]
    assert node["updated_at"] == "2026-10-18" and node["stale_after_days"] == 30
    assert node["record_sha256"] == contract["documents"][0]["records"][0]["current_sha256"]
    assert result["record_declarations"] == contract["documents"]
    assert node["observed_on"] == "2026-10-18"
    json.dumps(result, sort_keys=True)


def test_review_refuses_incomplete_snapshot_or_unmatched_binding(repo):
    base, current, contract = setup_increment(repo)
    contract["current_documents_sha256"].pop("memories/log.md")
    with pytest.raises(ValueError, match="snapshot"):
        review_records(current, base, {"memories/log.md"}, contract,
                       targets={"memories/log.md"})


def transaction(repo):
    """A new explicit v1 pair, with unrelated old debt retained verbatim."""
    page(repo, "unrelated", stale=True)
    p = page(repo, "log", body="# Log\n\n## Old\nPrior observation.\n\n")
    page(repo, "consumer", body="Historical [log](log.md).")
    parent = commit(repo)
    base = graph(repo)
    p.write_text(p.read_text() + "## New record\nNew observation.\n")
    current = graph(repo)
    contract = declaration(base, current)
    (repo / "records.json").write_text(json.dumps(contract))
    (repo / "wiki.config.yaml").write_text(yaml.safe_dump({"audit": {
        "freshness_scope": "impact", "freshness_base": parent,
        "freshness_records": "records.json"}}))
    return parent


def test_repository_tool_uses_configured_transaction_pair_without_writes(repo):
    from wiki_core.document_record_review import repository_review
    parent = transaction(repo)
    before = git(repo, "status", "--porcelain")
    result = repository_review(repo, ["memories/log.md"])
    assert result["base_sha"] == result["head_sha"] == parent
    assert result["changed_record_seeds"] == ["memories/log.md::record:entry-0"]
    assert result["input_documents_sha256"]["base"]["memories/unrelated.md"] == digest(
        (repo / "memories/unrelated.md").read_text())
    assert result["documents"]["current"]["memories/consumer.md"]["text"].endswith(
        "Historical [log](log.md).")
    assert git(repo, "status", "--porcelain") == before
    assert "ok" not in result  # no claim of semantic approval/freshness PASS


@pytest.mark.parametrize("mutation", ["existing", "new-page", "config"])
def test_repository_tool_refuses_concurrent_inputs(repo, monkeypatch, mutation):
    from scripts import wiki_page_graph as cli
    transaction(repo)
    from wiki_core import document_record_review as review
    original = review.review_records
    def concurrent(*args, **kwargs):
        result = original(*args, **kwargs)
        if mutation == "new-page":
            page(repo, "newly-discovered")
        elif mutation == "config":
            with (repo / "wiki.config.yaml").open("a") as stream:
                stream.write("\n# changed\n")
        else:
            with (repo / "memories/consumer.md").open("a") as stream:
                stream.write("\nChanged.\n")
        return result
    monkeypatch.setattr(review, "review_records", concurrent)
    with pytest.raises(ValueError, match="inputs changed"):
        review.repository_review(repo, ["memories/log.md"])


def test_cli_never_overwrites_evidence(repo, monkeypatch):
    from scripts import wiki_page_graph as cli
    transaction(repo)
    out = repo / "existing.json"
    out.write_text("Retained evidence")
    monkeypatch.setattr(cli, "ROOT", repo)
    with pytest.raises(SystemExit) as exc:
        cli.main(["--record-review", "--target", "memories/log.md", "--out", str(out)])
    assert exc.value.code == 1
    assert out.read_text() == "Retained evidence"


@pytest.mark.parametrize("extra", [["--impact"], ["--base", "HEAD"], ["--write"],
                                   ["--check"]])
def test_record_review_rejects_other_modes_before_execution(monkeypatch, extra):
    from scripts import wiki_page_graph as cli
    from wiki_core import document_record_review as review
    def forbidden(*args, **kwargs):
        raise AssertionError("must reject before any execution")
    monkeypatch.setattr(cli, "build_page_graph", forbidden)
    monkeypatch.setattr(review, "repository_review", forbidden)
    with pytest.raises(SystemExit) as exc:
        cli.main(["--record-review", "--target", "memories/log.md", *extra])
    assert exc.value.code == 2


def test_record_review_dispatch_never_runs_normal_graph_checks(repo, monkeypatch, capsys):
    from scripts import wiki_page_graph as cli
    from wiki_core import freshness_impact
    transaction(repo)
    def forbidden(*args, **kwargs):
        raise AssertionError("normal graph validation must not run")
    monkeypatch.setattr(cli, "ROOT", repo)
    monkeypatch.setattr(cli, "build_page_graph", forbidden)
    monkeypatch.setattr(cli, "compute_impact", forbidden)
    monkeypatch.setattr(cli, "orphan_pages", forbidden)
    monkeypatch.setattr(freshness_impact, "evaluate_impact", forbidden)
    assert cli.main(["--record-review", "--target", "memories/log.md"]) == 0
    assert json.loads(capsys.readouterr().out)["schema"] == "document_record_review.v1"


@pytest.mark.parametrize("args", [["--record-review"], ["--target", "memories/log.md"],
                                  ["--out", "new.json"]])
def test_review_flags_require_explicit_mode_and_target(args):
    from scripts import wiki_page_graph as cli
    with pytest.raises(SystemExit) as exc:
        cli.main(args)
    assert exc.value.code == 2


def test_cli_json_is_deterministic_across_hash_seeds(repo):
    transaction(repo)
    code = "from pathlib import Path; from scripts import wiki_page_graph as c; c.ROOT=Path(__import__('sys').argv[1]); c.main(['--record-review','--target','memories/log.md'])"
    outputs = [subprocess.check_output([sys.executable, "-c", code, str(repo)],
        env={**os.environ, "PYTHONHASHSEED": seed}) for seed in ("11", "59")]
    assert outputs[0] == outputs[1]


def test_a_revocation_still_reaches_unknown_live_consumers(repo):
    from wiki_core.freshness_impact import evaluate_impact
    p = page(repo, "log", body="# Authority\n\n## Old\nPreviously authorized.\n\n")
    page(repo, "historical", body="At the old cut: [authority](log.md).")
    page(repo, "live", stale=True, body="Currently authorized: [authority](log.md).")
    base = graph(repo)
    p.write_text(p.read_text() + "## New record\nAuthorization revoked.\n")
    current = graph(repo)
    contract = declaration(base, current)
    for origin, g in (("base", base), ("current", current)):
        add_binding(contract, g, origin, source="memories/historical.md")
    result = review_records(current, base, {"memories/log.md"}, contract,
                            targets={"memories/log.md"})
    assert all(r["binding"] is None for r in result["occurrences"]
               if r["raw"]["path"] == "memories/live.md")
    projected, old, seeds, _ = project_records(current, base, {"memories/log.md"}, contract)
    evaluated = evaluate_impact(projected, old, seeds, today=TODAY)
    assert "memories/live.md" in {r["path"] for r in evaluated["blockers"]}
    assert "memories/historical.md" not in {r["path"] for r in evaluated["included"]}


def test_new_v1_transaction_preserves_old_contract_and_real_stale_dependencies(repo):
    from wiki_core.document_record_review import repository_review
    from wiki_core.freshness_impact import evaluate_impact
    page(repo, "debt", stale=True)
    p = page(repo, "log", body="# Log\n\n## Old\nPrior.\n\n")
    initial = commit(repo)
    old_base = graph(repo)
    p.write_text(p.read_text() + "## New record\nApproved first addition.\n")
    approved = graph(repo)
    old_contract = declaration(old_base, approved)
    historical = repo / "historical-records.json"
    historical.write_text(json.dumps(old_contract))
    retained = historical.read_bytes()
    parent = commit(repo)
    p.write_text(p.read_text() + "## Later record\nIndependent later addition.\n")
    current = graph(repo)
    new_contract = declaration(approved, current, headings=("New record", "Later record"))
    assert new_contract["base_documents_sha256"] == old_contract["current_documents_sha256"]
    assert new_contract["documents"][0]["records"][0]["base_sha256"] == (
        old_contract["documents"][0]["records"][0]["current_sha256"])
    (repo / "records.json").write_text(json.dumps(new_contract))
    (repo / "wiki.config.yaml").write_text(yaml.safe_dump({"audit": {
        "freshness_scope": "impact", "freshness_base": parent,
        "freshness_records": "records.json"}}))
    inspected = repository_review(repo, ["memories/log.md"])
    assert inspected["base_sha"] == parent != initial
    assert inspected["changed_record_seeds"] == ["memories/log.md::record:entry-1"]
    projected, old, seeds, _ = project_records(current, approved, {"memories/log.md"}, new_contract)
    evaluated = evaluate_impact(projected, old, seeds, today=TODAY)
    assert evaluated["ok"] and "memories/debt.md" in {r["path"] for r in evaluated["unrelated_debt"]}
    assert historical.read_bytes() == retained
    # A real new prerequisite remains blocking; no filter hides the old debt.
    p.write_text(p.read_text() + "Depends on [debt](debt.md).\n")
    dependent = graph(repo)
    required = declaration(approved, dependent, headings=("New record", "Later record"))
    projected, old, seeds, _ = project_records(dependent, approved, {"memories/log.md"}, required)
    assert "memories/debt.md" in {r["path"] for r in evaluate_impact(projected, old, seeds, today=TODAY)["blockers"]}
    assert historical.read_bytes() == retained
