"""Synthetic semantics and adversarial coverage for documentary increments."""
import copy
import datetime as dt
import json

import pytest

from wiki_core.document_records import digest, edge_digest, node_id, project_records, sections, structured_digest
from wiki_core.freshness_impact import authored_graph, evaluate_impact, repository_report
from wiki_core.config import load_config
from test_freshness_impact import page, git, commit, repo  # shared synthetic Git fixture


TODAY = dt.date(2026, 10, 18)


def graph(root):
    return authored_graph(root, load_config(root))


def declaration(base, current, path="memories/log.md", headings=("New record",)):
    records = []
    for i, heading in enumerate(headings):
        records.append(dict(id=f"entry-{i}", heading=heading, independent=True,
            rationale="Independent dated observation; no change to sibling assertions.",
            epistemic_status="observation", recorded_on="2026-10-18", context_records=[],
            **{f"{origin}_sha256": digest(sections(g["documents"][path])[1][heading][2])
               if heading in sections(g["documents"][path])[1] else None
               for origin, g in (("base", base), ("current", current))}))
    return dict(schema_version="document_record.v1",
        base_documents_sha256={p: digest(t) for p, t in base["documents"].items()},
        current_documents_sha256={p: digest(t) for p, t in current["documents"].items()},
        documents=[dict(path=path, records=records)], bindings=[])


def evaluate(current, base, changed, contract):
    current, base, changed, evidence = project_records(current, base, changed, contract)
    result = evaluate_impact(current, base, changed, today=TODAY)
    result["record_evidence"] = evidence
    return result


def add_binding(contract, g, origin, source="memories/consumer.md", target_record="remainder"):
    edges = [e for e in g["edges"] if e["source"] == source and e["target"] == "memories/log.md"]
    assert len(edges) == 1
    record = contract["documents"][0]["records"][0]
    text = g["documents"]["memories/log.md"]
    available = sections(text)[1]
    if target_record == "remainder":
        content = text.replace(available[record["heading"]][2], "", 1) if record["heading"] in available else text
    else:
        content = available[record["heading"]][2]
    contract["bindings"].append(dict(origin=origin, edge_sha256=edge_digest(edges[0]),
        target_record=target_record, consumed_sha256=digest(content),
        rationale="This dated assertion consumes only the unchanged historical entry."))


def setup_increment(repo, consumer=False):
    page(repo, "old-source", stale=True)
    page(repo, "new-source")
    p = page(repo, "log", body="# Log\n\n## Old record\n\nOld [evidence](old-source.md).\n\n")
    if consumer:
        page(repo, "consumer", body="The historical result follows [log](log.md).")
    base = graph(repo)
    p.write_text(p.read_text() + "## New record\n\nNew [evidence](new-source.md).\n")
    current = graph(repo)
    return base, current, declaration(base, current)


def test_independent_addition_does_not_consume_old_siblings(repo):
    base, current, contract = setup_increment(repo)
    result = evaluate(current, base, {"memories/log.md"}, contract)
    assert result["ok"]
    assert result["seeds"] == [node_id("memories/log.md", "entry-0")]
    assert "memories/old-source.md" in {r["path"] for r in result["unrelated_debt"]}


@pytest.mark.parametrize("common_intro", [False, True])
def test_repeated_h2_siblings_keep_their_boundaries(repo, common_intro):
    page(repo, "old-source", stale=True)
    page(repo, "new-source")
    intro = "Common [premise](old-source.md).\n\n" if common_intro else ""
    p = page(repo, "log", body="# Log\n\n" + intro
             + "## Repeated\n\nOld [evidence](old-source.md).\n\n"
             + "## Repeated\n\nAnother [assertion](old-source.md).\n\n")
    base = graph(repo)
    p.write_text(p.read_text() + "## New record\n\nNew [evidence](new-source.md).\n")
    current = graph(repo)
    contract = declaration(base, current)
    result = evaluate(current, base, {"memories/log.md"}, contract)
    assert result["ok"] is not common_intro
    assert "Repeated" not in sections(current["documents"]["memories/log.md"])[1]
    if not common_intro:
        assert "memories/old-source.md" in {r["path"] for r in result["unrelated_debt"]}


def test_repeated_h2_remains_ambiguous_for_record_selection(repo):
    page(repo, "old-source", stale=True)
    p = page(repo, "log", body="# Log\n\n## Repeated\n\nFirst.\n\n")
    base = graph(repo)
    p.write_text(p.read_text() + "## Repeated\n\nSecond [assertion](old-source.md).\n"
                 "\n## New record\n\nAdded.\n")
    current = graph(repo)
    contract = declaration(base, current, headings=("Repeated",))
    with pytest.raises(ValueError, match="absent record exists or is ambiguous"):
        evaluate(current, base, {"memories/log.md"}, contract)


def test_whole_document_consumer_receives_addition_and_old_prerequisites(repo):
    base, current, contract = setup_increment(repo, consumer=True)
    result = evaluate(current, base, {"memories/log.md"}, contract)
    assert not result["ok"]
    assert "memories/consumer.md" in {r["path"] for r in result["included"]}
    assert "memories/old-source.md" in {r["path"] for r in result["blockers"]}


def test_explicit_both_version_bindings_preserve_unchanged_consumption(repo):
    base, current, contract = setup_increment(repo, consumer=True)
    for origin, g in (("base", base), ("current", current)):
        add_binding(contract, g, origin)
    result = evaluate(current, base, {"memories/log.md"}, contract)
    assert result["ok"]
    assert "memories/consumer.md" not in {r["path"] for r in result["included"]}


def test_base_binding_is_not_inferred_from_current(repo):
    base, current, contract = setup_increment(repo, consumer=True)
    # Editing a record that was formerly consumed as whole must retain that
    # historical dependency even if the current consumer is narrowed.
    old_text = current["documents"]["memories/log.md"]
    base["documents"]["memories/log.md"] = old_text.replace("New [evidence]", "Earlier [evidence]")
    base["edges"] = copy.deepcopy(current["edges"])
    contract = declaration(base, current)
    add_binding(contract, current, "current")
    result = evaluate(current, base, {"memories/log.md"}, contract)
    assert not result["ok"]
    assert "memories/consumer.md" in {r["path"] for r in result["included"]}


@pytest.mark.parametrize("kind", ["body", "metadata", "other-page"])
def test_uncovered_delta_remains_conservative(repo, kind):
    base, current, _ = setup_increment(repo)
    changed = {"memories/log.md"}
    if kind == "body":
        p = repo / "memories/log.md"
        p.write_text(p.read_text().replace("Old [evidence]", "Reinterpreted [evidence]"))
    elif kind == "metadata":
        p = repo / "memories/log.md"
        p.write_text(p.read_text().replace("stale_after_days: 30", "stale_after_days: 31"))
    else:
        page(repo, "other", stale=True)
        changed.add("memories/other.md")
    current = graph(repo)
    contract = declaration(base, current)
    result = evaluate(current, base, changed, contract)
    assert not result["ok"]
    if kind != "other-page":
        assert "memories/log.md" in result["seeds"]


@pytest.mark.parametrize("kind", ["metadata", "intro", "explicit-context"])
def test_common_premises_cannot_be_shed_by_partitioning(repo, kind):
    base, current, contract = setup_increment(repo)
    if kind == "explicit-context":
        contract["documents"][0]["records"][0]["context_records"] = ["remainder"]
    else:
        for g in (base, current):
            if kind == "metadata":
                g["edges"].append(dict(source="memories/log.md", target="memories/old-source.md",
                    type="source_ref", basis="frontmatter", path="memories/log.md",
                    field="source_refs", direction="directed"))
            else:
                # The actual fixture puts a citation in the H1 introduction.
                text = g["documents"]["memories/log.md"].replace("# Log\n", "# Log\n\nUses [common](old-source.md).\n")
                (repo / "memories/log.md").write_text(text)
                projected = graph(repo)
                g["documents"] = projected["documents"]
                g["edges"] = projected["edges"]
        contract = declaration(base, current)
    assert not evaluate(current, base, {"memories/log.md"}, contract)["ok"]


@pytest.mark.parametrize("operation", ["retarget", "remove"])
def test_record_edit_and_removal_preserve_old_source(repo, operation):
    page(repo, "old-source", stale=True)
    page(repo, "new-source")
    p = page(repo, "log", body="# Log\n\n## New record\n\n[evidence](old-source.md)\n")
    base = graph(repo)
    p.write_text(p.read_text().replace("old-source.md", "new-source.md") if operation == "retarget"
                 else p.read_text().split("## New record")[0])
    current = graph(repo)
    contract = declaration(base, current)
    result = evaluate(current, base, {"memories/log.md"}, contract)
    assert "memories/old-source.md" in {r["path"] for r in result["blockers"]}


def test_record_date_does_not_freshen_page(repo):
    base, current, contract = setup_increment(repo)
    current["nodes"]["memories/log.md"]["updated_at"] = "2026-01-01"
    result = evaluate(current, base, {"memories/log.md"}, contract)
    assert not result["ok"]
    assert result["blockers"][0]["path"] == node_id("memories/log.md", "entry-0")


@pytest.mark.parametrize("fault", ["snapshot", "hash", "independence", "binding", "duplicate", "absent"])
def test_invalid_contract_fails_closed(repo, fault):
    base, current, contract = setup_increment(repo)
    record = contract["documents"][0]["records"][0]
    if fault == "snapshot":
        contract["base_documents_sha256"] = {}
    elif fault == "hash":
        record["current_sha256"] = "0" * 64
    elif fault == "independence":
        record["independent"] = False
    elif fault == "binding":
        contract["bindings"] = [dict(origin="base", edge_sha256="absent", rationale="claimed")]
    elif fault == "duplicate":
        contract["documents"][0]["records"].append(copy.deepcopy(record))
    else:
        record["current_sha256"] = None
    with pytest.raises(ValueError):
        evaluate(current, base, {"memories/log.md"}, contract)


def test_commonmark_selectors_reject_nested_fenced_and_duplicate_headings():
    text = "# Title\n\n```\n## Fake\n```\n\n> ## Nested\n\n## Real\nbody\n### Child\nchild\n## Real\nsecond\n"
    assert sections(text)[1] == {}
    text = "# Title\r\n\r\n## Real\r\nbody\r\n### Child\r\nchild\r\n# End\r\n"
    section = sections(text)[1]["Real"][2]
    assert section == "## Real\r\nbody\r\n### Child\r\nchild\r\n"


def test_git_gate_uses_complete_diff_and_records_contract_hash(repo):
    page(repo, "old-source", stale=True)
    p = page(repo, "log", body="# Log\n\n## Old\n[evidence](old-source.md)\n\n")
    sha = commit(repo)
    base = graph(repo)
    p.write_text(p.read_text() + "## New record\n\nIndependent observation.\n")
    current = graph(repo)
    contract = declaration(base, current)
    (repo / "records.json").write_text(json.dumps(contract))
    (repo / "wiki.config.yaml").write_text("audit:\n  freshness_scope: impact\n  freshness_records: records.json\n")
    result = repository_report(repo, load_config(repo), sha, today=TODAY)
    assert result["ok"]
    assert "records.json" in result["changed_paths"]
    assert "wiki.config.yaml" in result["changed_paths"]
    assert result["record_contract_sha256"] == digest((repo / "records.json").read_text())
    page(repo, "hidden", stale=True)
    with pytest.raises(ValueError, match="snapshot"):
        repository_report(repo, load_config(repo), sha, today=TODAY)


def test_second_h1_introduction_is_inherited(repo):
    page(repo, "old-source", stale=True)
    p = page(repo, "log", body="# A\n\n## Old\nOld assertion.\n\n# B\n\nUses [common](old-source.md).\n\n")
    base = graph(repo)
    p.write_text(p.read_text() + "## New record\n\nNew assertion.\n")
    current = graph(repo)
    result = evaluate(current, base, {"memories/log.md"}, declaration(base, current))
    assert not result["ok"]
    assert "memories/old-source.md" in {r["path"] for r in result["blockers"]}


def test_git_projection_preserves_crlf_blob_bytes(repo):
    from scripts.wiki_page_graph import project_memory_at_commit
    p = page(repo, "log", body="# Log\n\n## Old\nPrevious.\n\n")
    p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))
    original = p.read_bytes()
    git(repo, "config", "core.autocrlf", "false")
    sha = commit(repo)
    base = project_memory_at_commit(sha, authored_graph, root=repo)
    assert base["documents"]["memories/log.md"].encode("utf-8") == original
    p.write_bytes(original + b"## New record\r\n\r\nIndependent.\r\n")
    current = graph(repo)
    contract = declaration(base, current)
    (repo / "records.json").write_text(json.dumps(contract))
    (repo / "wiki.config.yaml").write_text("audit:\n  freshness_scope: impact\n  freshness_records: records.json\n")
    result = repository_report(repo, load_config(repo), sha, today=TODAY)
    assert result["ok"]
    assert result["seeds"] == [node_id("memories/log.md", "entry-0")]


def test_shared_metadata_binding_only_qualifies_named_consumer_record(repo):
    page(repo, "old-source", stale=True)
    page(repo, "log", body="# Log\n\n## Old\n[old](old-source.md).\n\n## New record\nFresh.\n")
    p = page(repo, "consumer", source_refs=["log"], body="# Consumer\n\n## Old\nPrevious.\n\n")
    base = graph(repo)
    p.write_text(p.read_text() + "## New record\nCurrent.\n")
    current = graph(repo)
    contract = declaration(base, current)
    contract["documents"] += declaration(base, current, "memories/consumer.md")["documents"]
    raw = next(e for e in current["edges"] if e["path"] == "memories/consumer.md" and e["field"] == "source_refs")
    contract["bindings"].append(dict(origin="current", edge_sha256=edge_digest(raw),
        consumer_record="entry-0", target_record="entry-0",
        consumed_sha256=contract["documents"][0]["records"][0]["current_sha256"],
        rationale="New consumer assertion depends on the current source record only."))
    projected, _, _, _ = project_records(current, base, {"memories/consumer.md"}, contract)
    new_edges = [e for e in projected["edges"] if e["source"] == node_id("memories/consumer.md", "entry-0")]
    old_edges = [e for e in projected["edges"] if e["source"] == node_id("memories/consumer.md", "remainder")]
    assert {e["target"] for e in new_edges} == {node_id("memories/log.md", "entry-0")}
    assert node_id("memories/log.md", "remainder") in {e["target"] for e in old_edges}
    assert evaluate(current, base, {"memories/consumer.md"}, contract)["ok"]


def test_new_reference_definition_cannot_change_old_rendering_unnoticed(repo):
    page(repo, "old-source", stale=True)
    p = page(repo, "log", body="# Log\n\n## Old\nUses [fact][new-definition].\n\n")
    base = graph(repo)
    p.write_text(p.read_text() + "## New record\n\nIndependent?\n\n[new-definition]: old-source.md\n")
    current = graph(repo)
    result = evaluate(current, base, {"memories/log.md"}, declaration(base, current))
    assert "memories/log.md" in result["seeds"]
    assert "memories/old-source.md" in {r["path"] for r in result["blockers"]}


def test_record_moved_to_another_parent_is_not_an_empty_delta(repo):
    p = page(repo, "log", body="# A\n\n## New record\nAssertion.\n\n# B\n\n")
    base = graph(repo)
    p.write_text(p.read_text().replace("## New record\nAssertion.\n\n", "") + "## New record\nAssertion.\n\n")
    current = graph(repo)
    result = evaluate(current, base, {"memories/log.md"}, declaration(base, current))
    assert "memories/log.md" in result["seeds"]


def test_explicit_blank_separator_is_hash_bound_not_ignored(repo):
    p = page(repo, "log", body="# Log\n\n## Old\nPrevious.\n")
    base = graph(repo)
    p.write_text(p.read_text() + "\n## New record\nIndependent.\n")
    current = graph(repo)
    contract = declaration(base, current)
    assert "memories/log.md" in evaluate(current, base, {"memories/log.md"}, contract)["seeds"]
    record = contract["documents"][0]["records"][0]
    record["leading_blank_lines"] = 1
    record["current_sha256"] = digest("\n" + sections(current["documents"]["memories/log.md"])[1]["New record"][2])
    assert evaluate(current, base, {"memories/log.md"}, contract)["seeds"] == [node_id("memories/log.md", "entry-0")]


def evidence_fixture(repo):
    event = dict(event_id="local-result", job_id="synthetic-job", actor="operator",
                 at="2026-10-01T12:00:00Z", text="Historical local result, assisted.")
    page(repo, "card", stale=True, action_dialogue=[event])
    p = page(repo, "log", body="# Log\n\n## Old\nOld observation.\n\n")
    base = graph(repo)
    p.write_text(p.read_text() + "## New record\n\nThe [card](card.md) identifies this historical result.\n")
    current = graph(repo)
    contract = declaration(base, current)
    contract["artifacts"] = [dict(origin="current", id="result-event", document="memories/card.md",
        field="action_dialogue", match_key="event_id", match_value="local-result", sha256=structured_digest(event))]
    raw = next(e for e in current["edges"] if e["source"] == "memories/log.md")
    binding = dict(origin="current", edge_sha256=edge_digest(raw), consumer_record="entry-0",
        role="provenance", target_document_sha256=digest(current["documents"]["memories/card.md"]),
        evidence=["result-event"], rationale="Exact event proves job association and assistance, not current operation.")
    contract["bindings"] = [binding]
    return base, current, contract


def test_provenance_retains_verified_event_as_real_historical_dependency(repo):
    base, current, contract = evidence_fixture(repo)
    result = evaluate(current, base, {"memories/log.md"}, contract)
    assert result["ok"]
    historical = [r for r in result["included"] if r["state"] == "historical_evidence"]
    assert len(historical) == 1
    assert "memories/card.md" in {r["path"] for r in result["unrelated_debt"]}
    assert any(e.get("authored_role") == "provenance" for e in result["nonpropagating_relations"])


@pytest.mark.parametrize("fault", ["event-hash", "event-id", "missing-evidence", "no-evidence", "target-hash", "role"])
def test_missing_provenance_proof_fails_closed(repo, fault):
    base, current, contract = evidence_fixture(repo)
    if fault == "event-hash": contract["artifacts"][0]["sha256"] = "0" * 64
    elif fault == "event-id": contract["artifacts"][0]["match_value"] = "missing"
    elif fault == "missing-evidence": contract["bindings"][0]["evidence"] = ["missing"]
    elif fault == "no-evidence": contract["bindings"][0]["evidence"] = []
    elif fault == "target-hash": contract["bindings"][0]["target_document_sha256"] = "0" * 64
    else: contract["bindings"][0]["role"] = "ignore"
    with pytest.raises(ValueError): evaluate(current, base, {"memories/log.md"}, contract)


def test_evidence_does_not_replace_other_factual_dependencies(repo):
    base, current, contract = evidence_fixture(repo)
    # A separate factual edge to the same stale card still blocks.
    current["edges"].append(dict(source="memories/log.md", target="memories/card.md",
        type="source_ref", basis="frontmatter", path="memories/log.md", field="source_refs", direction="directed"))
    assert not evaluate(current, base, {"memories/log.md"}, contract)["ok"]


def test_authored_page_cannot_self_declare_verified_immutable_evidence(repo):
    page(repo, "item", stale=True, immutable_evidence=True)
    current = graph(repo)
    assert not evaluate_impact(current, current, {"memories/item.md"}, today=TODAY)["ok"]


@pytest.mark.parametrize("role", ["navigation", "change_target"])
def test_exact_occurrence_role_does_not_narrow_same_target_sibling(repo, role):
    base, current, contract = setup_increment(repo, consumer=True)
    # A second factual citation on another line cannot inherit the role.
    raw = next(e for e in current["edges"] if e["source"] == "memories/consumer.md")
    current["edges"].append({**raw, "body_offset": 999, "body_line": 99})
    contract["bindings"].append(dict(origin="current", edge_sha256=edge_digest(raw), role=role,
        target_document_sha256=digest(current["documents"]["memories/log.md"]),
        rationale="This precise occurrence identifies a destination; the other is factual."))
    assert not evaluate(current, base, {"memories/log.md"}, contract)["ok"]


def test_file_evidence_requires_exact_bytes_and_keeps_old_dependencies(repo):
    base, current, contract = setup_increment(repo)
    data = b'{"result":"historical synthetic output"}\n'
    contract["artifacts"] = [dict(origin="current", id="output", path="evidence/output.json", sha256=digest(data.decode()))]
    contract["documents"][0]["records"][0]["current_evidence"] = ["output"]
    with pytest.raises(ValueError, match="missing or changed"):
        project_records(current, base, {"memories/log.md"}, contract)
    with pytest.raises(ValueError, match="missing or changed"):
        project_records(current, base, {"memories/log.md"}, contract, artifact_inputs={("current", "output"): b"changed"})
    projected, historical, changed, _ = project_records(current, base, {"memories/log.md"}, contract,
        artifact_inputs={("current", "output"): data})
    result = evaluate_impact(projected, historical, changed, today=TODAY)
    assert result["ok"]
    assert any(r["state"] == "historical_evidence" for r in result["included"])


def test_artifact_path_cannot_escape_repository(repo):
    from wiki_core.document_records import artifact_paths
    for path in ("../outside.json", "/tmp/outside.json", "folder/../outside.json"):
        with pytest.raises(ValueError): artifact_paths(repo, {"artifacts": [dict(origin="current", id="output", path=path)]})


def test_factual_dependency_authored_on_other_page_is_inherited(repo):
    base, current, contract = setup_increment(repo)
    for g in (base, current):
        g["edges"].append(dict(source="memories/old-source.md", target="memories/log.md",
            type="impact", direction="directed", basis="frontmatter",
            path="memories/old-source.md", field="consolidated_into"))
    result = evaluate(current, base, {"memories/log.md"}, contract)
    assert not result["ok"]
    assert "memories/old-source.md" in {r["path"] for r in result["blockers"]}
    # Qualifying only the new assertion must not narrow the historical remainder.
    raw = current["edges"][-1]
    contract["bindings"].append(dict(origin="current", edge_sha256=edge_digest(raw),
        consumer_record="entry-0", role="change_target",
        prerequisite_document_sha256=digest(current["documents"]["memories/old-source.md"]),
        rationale="This event names the old document as its historical write destination; it did not supply this later record."))
    projected, _, _, _ = project_records(current, base, {"memories/log.md"}, contract)
    assert any(e["type"] == "impact" and e["target"] == node_id("memories/log.md", "remainder") for e in projected["edges"])
    assert evaluate(current, base, {"memories/log.md"}, contract)["ok"]
