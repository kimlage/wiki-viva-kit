"""Public synthetic claims; normal graph, projector, review and impact paths."""
import copy
import datetime as dt
import json
from pathlib import Path

import pytest

from wiki_core.config import load_config
from wiki_core.document_records import digest, edge_digest, node_id, project_records
from wiki_core.document_record_review import review_records
from wiki_core.document_view_selectors import body_span, frontmatter_span, partition_view
from wiki_core.freshness_impact import authored_graph, evaluate_impact
from test_freshness_impact import repo


VIEW = "memories/views/source-register.md"
A = "memories/consumers/a-fields.md"
WHOLE = "memories/consumers/register-whole.md"
RULE = "memories/system/observation-rule.md"
CHANGED = {VIEW, "memories/sources/c.md"}


@pytest.fixture
def example(repo):
    data = json.loads((Path(__file__).parent / "fixtures/document-view/mixed-example.json").read_text())
    graphs = {}
    for origin, documents in data["documents"].items():
        for path in repo.glob("memories/**/*.md"):
            path.unlink()
        for path, text in documents.items():
            target = repo / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(text.encode())
        graphs[origin] = authored_graph(repo, load_config(repo))
        assert not graphs[origin]["errors"]
    inputs = {(a["origin"], a["id"]): data["artifact_files"][a["path"]].encode()
              for a in data["contract"]["artifacts"]}
    return graphs["current"], graphs["base"], data["contract"], inputs


def project(example, changed=CHANGED, trace=None):
    current, base, contract, inputs = example
    return project_records(current, base, changed, contract, artifact_inputs=inputs, review_trace=trace)


def impact(example, changed=CHANGED):
    current, base, seeds, _ = project(example, changed)
    return evaluate_impact(current, base, seeds, today=dt.date(2026, 10, 2))


def test_mixed_example_preserves_raw_seed_whole_and_required_upstream(example):
    current, base, seeds, coverage = project(example)
    assert CHANGED <= seeds
    assert seeds == CHANGED | {node_id(VIEW, r) for r in ("entry-c", "publication", "membership")}
    assert coverage[0]["complete_delta_covered"]
    result = impact(example)
    included = {r["path"] for r in result["included"]}
    assert WHOLE in included and A not in included
    assert {VIEW, RULE} | {node_id(VIEW, r) for r in ("entry-a", "entry-b", "entry-c", "reading-rule", "remainder")} <= included
    assert "memories/sources/a.md" not in included
    assert "memories/sources/b.md" not in included
    for g in (base, current):
        assert any(e["source"] == WHOLE and e["target"] == VIEW for e in g["edges"])
        assert any(e["source"] == VIEW and e["target"] == node_id(VIEW, "entry-a")
                   and e["type"] == "source_ref" for e in g["edges"])


def test_review_uses_same_projection_and_keeps_raw_nodes_and_zero_counts(example):
    trace = []
    assert project(example) == project(example, trace=trace)
    current, base, contract, inputs = example
    packet = review_records(current, base, CHANGED, contract, targets=[VIEW], artifact_inputs=inputs)
    assert packet == review_records(current, base, CHANGED, contract, targets=[VIEW], artifact_inputs=inputs)
    assert packet["changed_record_seeds"] == sorted(project(example)[2])
    assert VIEW in packet["nodes"]["base"]
    assert node_id(VIEW, "publication") in packet["nodes"]["current"]
    assert any(r["raw"]["field"] == "document_components" for r in packet["occurrences"])
    assert len(trace) == packet["projected_variant_count"]


@pytest.mark.parametrize("fault", ["missing-mode", "unknown-mode", "bad-hash", "false-absence", "overlap", "template", "evidence"])
def test_bad_v2_contract_fails_closed(example, fault):
    current, base, contract, inputs = example
    declaration = contract["documents"][0]
    if fault == "missing-mode":
        del contract["document_modes"][VIEW]
    elif fault == "unknown-mode":
        contract["document_modes"][VIEW] = "automatic"
    elif fault == "bad-hash":
        declaration["records"][0]["current_sha256"] = "0" * 64
    elif fault == "false-absence":
        declaration["records"][0]["selectors"]["base"] = None
        declaration["records"][0]["base_sha256"] = None
    elif fault == "overlap":
        duplicate = copy.deepcopy(declaration["records"][0])
        duplicate["id"] = "overlap"
        declaration["records"].append(duplicate)
    elif fault == "template":
        declaration["envelope"][0]["selectors"]["current"]["path"] = ["stale_after_days"]
    else:
        inputs[next(iter(inputs))] = b"wrong capture"
    with pytest.raises(ValueError):
        project(example)


def test_current_only_binding_does_not_narrow_base(example):
    example[2]["bindings"] = [b for b in example[2]["bindings"]
                              if not (b["origin"] == "base" and b.get("role") == "consumption"
                                      and b.get("target_record") == "entry-a")]
    assert A in {r["path"] for r in impact(example)["included"]}


@pytest.mark.parametrize("age", ["stale", "unknown"])
def test_upstream_unchanged_component_still_blocks(example, age):
    for graph in example[:2]:
        if age == "stale":
            graph["nodes"][VIEW]["updated_at"] = "2020-01-01"
        else:
            graph["nodes"][VIEW].pop("updated_at", None)
    result = impact(example)
    assert not result["ok"]
    assert any(r["path"] == node_id(VIEW, "entry-a") for r in result["blockers"])
    assert A not in {r["path"] for r in result["included"]}


def test_policy_raw_seed_reaches_row_and_consumer_even_when_row_bytes_equal(example):
    result = impact(example, {RULE})
    assert A in {r["path"] for r in result["included"]}
    assert result["seeds"] == [RULE]


def test_unqualified_factual_source_seed_remains_when_rendered_row_equal(example):
    result = impact(example, {"memories/sources/a.md"})
    included = {r["path"] for r in result["included"]}
    assert "memories/consumers/live-a.md" in included
    assert A not in included


def test_legacy_subprojection_is_identical_in_mixed_contract(example):
    current, base, contract, inputs = example
    legacy = copy.deepcopy(contract)
    legacy["schema_version"] = "document_record.v1"
    legacy.pop("document_modes")
    legacy["documents"] = [legacy["documents"][1]]
    legacy["bindings"] = [b for b in legacy["bindings"] if b.get("target_record") == "approved-note"]
    legacy.pop("artifacts")
    mixed = project(example)
    original = project_records(current, base, set(), legacy)
    for g1, g2 in zip(mixed[:2], original[:2]):
        prefix = "memories/log/history.md"
        assert {k: v for k, v in g1["nodes"].items() if k.startswith(prefix)} == {
            k: v for k, v in g2["nodes"].items() if k.startswith(prefix)}
        assert [e for e in g1["edges"] if e["path"] in {prefix, "memories/consumers/history.md"}] == [
            e for e in g2["edges"] if e["path"] in {prefix, "memories/consumers/history.md"}]


def table_selector(text, *, key="a.md"):
    lines = text.splitlines(keepends=True)
    start = next(i for i, line in enumerate(lines) if line.startswith("| Source"))
    return dict(kind="table_row", container_heading_path=["Register"],
                header_sha256=digest("".join(lines[start:start + 2])), key_column=0,
                key=dict(kind="link_destination", value=key), required_match_count=1)


@pytest.mark.parametrize("eol", ["\n", "\r\n"])
def test_table_ast_uses_complete_row_bytes_including_escaped_pipe(eol):
    text = "# Register\n\n| Source | Value |\n| --- | --- |\n| [A](a.md) | a \\| b |\n".replace("\n", eol)
    assert body_span(text, table_selector(text)) == (4, 5)
    assert digest("".join(text.splitlines(keepends=True)[4:5])) != digest("[A](a.md)")


@pytest.mark.parametrize("fault", ["duplicate-row", "duplicate-table", "fenced", "html", "duplicate-heading", "code-key"])
def test_table_selector_rejects_fake_or_ambiguous_location(fault):
    table = "| Source | Value |\n| --- | --- |\n| [A](a.md) | partial |\n"
    text = "# Register\n\n" + table
    selector = table_selector(text)
    if fault == "duplicate-row":
        text += "| [Other label](a.md) | another |\n"
    elif fault == "duplicate-table":
        text += "\n" + table
    elif fault == "fenced":
        text = "# Register\n\n```\n" + table + "```\n"
    elif fault == "html":
        text = "# Register\n\n<div>\n" + table + "</div>\n"
    elif fault == "duplicate-heading":
        text += "\n# Register\n"
    else:
        text = text.replace("[A](a.md)", "`[A](a.md)`")
        assert body_span(text, selector) is None
        return
    with pytest.raises(ValueError):
        body_span(text, selector)


@pytest.mark.parametrize("fault", ["duplicate", "alias", "comment", "prose", "duplicate-members"])
def test_envelope_cannot_hide_norms_or_uncertain_yaml(fault):
    raw = "updated_at: 2026-10-01\nmembers: [a, b]\n"
    selector, shape = dict(kind="frontmatter_field", path=["updated_at"]), "canonical_iso_date"
    if fault == "duplicate":
        raw += "updated_at: 2026-10-02\n"
    elif fault == "alias":
        raw = "updated_at: &date 2026-10-01\nother: *date\n"
    elif fault == "comment":
        raw = raw.replace("2026-10-01", "2026-10-01 # authoritative norm")
    elif fault == "prose":
        raw = raw.replace("2026-10-01", "Current authority approved 2026-10-01")
    else:
        raw = raw.replace("[a, b]", "[a, a]")
        selector, shape = dict(kind="frontmatter_field", path=["members"]), "unique_string_sequence"
    with pytest.raises(ValueError):
        frontmatter_span("---\n" + raw + "---\n# View\n", selector, shape)


def test_generation_paragraph_requires_complete_literal_timestamp():
    selector = dict(kind="markdown_generation_paragraph", container_heading_path=["Register"],
                    required_match_count=1,
                    template=dict(prefix="Updated at: ", suffix=".", value_format="iso_date"))
    assert body_span("# Register\n\nUpdated at: 2026-10-01.\n", selector) == (2, 3)
    for extra in (" New authority applies.", " [rule](rule.md)", "\ncontinuation"):
        with pytest.raises(ValueError):
            body_span("# Register\n\nUpdated at: 2026-10-01." + extra + "\n", selector)


def revise_current_view(example, edit, repo):
    """Author a fresh synthetic CURRENT; retain the literal independent BASE."""
    current, base, contract, inputs = example
    old_edges = current["edges"]
    text = edit(current["documents"][VIEW])
    (repo / VIEW).write_bytes(text.encode())
    replacement = authored_graph(repo, load_config(repo))
    assert not replacement["errors"]
    current.clear()
    current.update(replacement)
    contract["current_documents_sha256"] = {p: digest(t) for p, t in current["documents"].items()}
    entries = contract["documents"][0]["records"] + contract["documents"][0]["envelope"]
    for record in entries:
        selector = record["selectors"]["current"]
        if selector["kind"] == "frontmatter_field":
            a, b = frontmatter_span(text, selector, record["value_shape"])
            content = "".join(text.splitlines(keepends=True)[a:b])
        else:
            _, body = text.split("---\n", 2)[1:]
            if selector["kind"] == "table_row":
                lines = body.splitlines(keepends=True)
                start = next(i for i, line in enumerate(lines) if line.startswith("| Source"))
                selector["header_sha256"] = digest("".join(lines[start:start + 2]))
            span = body_span(text, selector)
            if span is None:
                record["selectors"]["current"] = None
                record["current_sha256"] = None
                continue
            a, b = span
            content = "".join(body.splitlines(keepends=True)[a:b])
        record["current_sha256"] = digest(content)
    for binding in list(contract["bindings"]):
        if binding["origin"] != "current":
            continue
        raw = next(e for e in old_edges if edge_digest(e) == binding["edge_sha256"])
        candidates = [e for e in current["edges"] if all(e.get(k) == raw.get(k)
                      for k in ("source", "target", "type", "basis", "field"))]
        if not candidates:
            contract["bindings"].remove(binding)
            continue
        binding["edge_sha256"] = edge_digest(candidates[0])
        if binding.get("role") == "consumption" and binding.get("target_record") == "entry-a":
            binding["consumed_sha256"] = entries[0]["current_sha256"]


@pytest.mark.parametrize("edit", [
    lambda t: t.replace("stale_after_days: 90", "stale_after_days: 91"),
    lambda t: t.replace("Recorded canonical fields;", "New canonical restriction. Recorded canonical fields;"),
    lambda t: t.replace("| Source |", "A new current authority restriction applies.\n\n| Source |"),
    lambda t: t.replace("| [A](../sources/a.md) | partial |\n| [B](../sources/b.md) | partial |",
                        "| [B](../sources/b.md) | partial |\n| [A](../sources/a.md) | partial |"),
])
def test_common_delta_and_order_remain_broad(example, repo, edit):
    revise_current_view(example, edit, repo)
    current, base, seeds, coverage = project(example)
    assert VIEW in seeds and node_id(VIEW, "entry-a") in seeds
    assert not coverage[0]["complete_delta_covered"]
    assert A in {r["path"] for r in impact(example)["included"]}


def test_changed_norm_component_seeds_unchanged_row_claim(example, repo):
    revise_current_view(example, lambda t: t.replace("Rows reproduce", "A new restriction applies. Rows reproduce"), repo)
    _, _, seeds, coverage = project(example)
    assert coverage[0]["complete_delta_covered"]
    assert node_id(VIEW, "reading-rule") in seeds
    assert node_id(VIEW, "entry-a") not in seeds
    assert A in {r["path"] for r in impact(example)["included"]}


def test_row_change_seeds_its_consumers(example, repo):
    revise_current_view(example, lambda t: t.replace("[A](../sources/a.md) | partial", "[A](../sources/a.md) | ingested"), repo)
    assert node_id(VIEW, "entry-a") in project(example)[2]
    assert A in {r["path"] for r in impact(example)["included"]}


def test_date_only_slot_affects_whole_but_not_material_row(example, repo):
    # Start with identical full snapshots, then author only a date change.
    current, base, contract, inputs = example
    base.clear()
    base.update(copy.deepcopy(current))
    contract["base_documents_sha256"] = copy.deepcopy(contract["current_documents_sha256"])
    for r in contract["documents"][0]["records"] + contract["documents"][0]["envelope"]:
        r["selectors"]["base"] = copy.deepcopy(r["selectors"]["current"])
        r["base_sha256"] = r["current_sha256"]
    contract["bindings"] = [b for b in contract["bindings"] if b["origin"] == "current"]
    contract["bindings"] += [{**b, "origin": "base"} for b in list(contract["bindings"])]
    contract["artifacts"] = [a for a in contract["artifacts"] if a["origin"] == "current"]
    contract["artifacts"] += [{**a, "origin": "base"} for a in list(contract["artifacts"])]
    for (o, aid), data in list(inputs.items()):
        if o == "current":
            inputs[("base", aid)] = data
    revise_current_view(example, lambda t: t.replace("updated_at: 2026-10-02", "updated_at: 2026-10-03"), repo)
    assert project(example, {VIEW})[2] == {VIEW, node_id(VIEW, "publication")}
    included = {r["path"] for r in impact(example, {VIEW})["included"]}
    assert WHOLE in included and A not in included


def test_second_whole_occurrence_is_not_qualified_by_endpoint(example, repo):
    current, base, contract, _ = example
    path = repo / A
    path.write_text(path.read_text() + "\nThe complete current [register](../views/source-register.md) also determines this claim.\n")
    current.clear()
    current.update(authored_graph(repo, load_config(repo)))
    contract["current_documents_sha256"] = {p: digest(t) for p, t in current["documents"].items()}
    result = impact(example)
    assert A in {r["path"] for r in result["included"]}


def test_removed_row_keeps_base_seed_and_binding(example, repo):
    # Remove B (not a narrowed direct consumer), keep its BASE support and seed.
    revise_current_view(example, lambda t: t.replace("| [B](../sources/b.md) | partial |\n", ""), repo)
    current, base, seeds, _ = project(example)
    assert node_id(VIEW, "entry-b") in seeds
    assert node_id(VIEW, "entry-b") in base["nodes"]
    assert node_id(VIEW, "entry-b") not in current["nodes"]


def test_observation_fixture_matches_each_origin_full_parent_and_actual_fields(example):
    current, base, contract, inputs = example
    import yaml
    from wiki_core.frontmatter import FRONTMATTER_RE
    for artifact in contract["artifacts"]:
        graph = {"base": base, "current": current}[artifact["origin"]]
        value = json.loads(inputs[(artifact["origin"], artifact["id"])])
        text = graph["documents"][value["source_document"]]
        assert value["source_document_sha256"] == digest(text)
        fields = yaml.safe_load(FRONTMATTER_RE.match(text).group(1))
        assert value["observed_fields"] == {k: fields[k] for k in value["observed_fields"]}


@pytest.mark.parametrize("title,section,header", [
    ("Operation cockpit", "Actions", "Action | State | Next step"),
    ("Input stage", "Sources", "Source | Channel | State"),
    ("Operational pass", "Complete actions", "Action | Priority | Blocker"),
    ("Actions index", "Inventory", "Action | State | Qualification"),
])
def test_other_producer_layouts_keep_header_norm_and_aggregate_outside_row(title, section, header):
    text = (f"# {title}\n\nNormative interpretation stays common.\n\n## {section}\n\n"
            f"| {header} |\n| --- | --- | --- |\n| [A](a.md) | open | pending |\n"
            "\n## Summary\nCount: 1; ranking and blockers are complete claims.\n")
    lines = text.splitlines(keepends=True)
    start = next(i for i, line in enumerate(lines) if line.startswith("| " + header))
    selector = dict(kind="table_row", container_heading_path=[title, section],
                    header_sha256=digest("".join(lines[start:start + 2])), key_column=0,
                    key=dict(kind="link_destination", value="a.md"), required_match_count=1)
    a, b = body_span(text, selector)
    assert "".join(lines[a:b]) == "| [A](a.md) | open | pending |\n"
    record = dict(id="entry-a", selectors={o: selector for o in ("base", "current")},
                  base_sha256=digest("".join(lines[a:b])), current_sha256=digest("".join(lines[a:b])))
    partition = partition_view(text, [record], "current")
    assert "Normative interpretation" in partition["remainder"]
    assert "ranking and blockers" in partition["remainder"]
    assert header in partition["remainder"]


@pytest.mark.parametrize("title,section", [
    ("Operation cockpit", "Actions"), ("Input stage", "Sources"),
    ("Operational pass", "Complete actions"), ("Actions index", "Inventory"),
])
def test_nested_table_header_norm_is_inherited_by_its_rows(repo, title, section):
    from test_freshness_impact import page, TODAY
    page(repo, "norm", body="# Canonical norm\n\nVersion one.\n")
    view = page(repo, "view", body=(f"# {title}\n\n## {section}\n\n"
                "| Item | [Norm](norm.md) |\n| --- | --- |\n| [A](a.md) | partial |\n"
                "\n## Other table\n\n| Item | [Other norm](norm-b.md) |\n| --- | --- |\n"
                "| [B](b.md) | recorded |\n"))
    page(repo, "a", body="# Source A\n")
    page(repo, "b", body="# Source B\n")
    page(repo, "norm-b", body="# Separate norm\n")
    page(repo, "consumer", body="# Consumer\n\nConsumes the recorded A entry of [view](view.md).\n")
    page(repo, "consumer-b", body="# Consumer B\n\nConsumes only the B entry of [view](view.md).\n")
    base = authored_graph(repo, load_config(repo))
    norm = repo / "memories/norm.md"
    norm.write_text(norm.read_text() + "\nA new canonical restriction.\n")
    current = authored_graph(repo, load_config(repo))
    assert not base["errors"] and not current["errors"]
    body = view.read_text().split("---\n", 2)[2]
    lines = body.splitlines(keepends=True)
    start = next(i for i, line in enumerate(lines) if line.startswith("| Item"))
    selector = dict(kind="table_row", container_heading_path=[title, section],
                    header_sha256=digest("".join(lines[start:start + 2])), key_column=0,
                    key=dict(kind="link_destination", value="a.md"), required_match_count=1)
    row_hash = digest("| [A](a.md) | partial |\n")
    record = dict(id="entry-a", selectors={o: selector for o in ("base", "current")},
                  base_sha256=row_hash, current_sha256=row_hash, independent=True,
                  rationale="Complete source row under its actual table header and norm.",
                  epistemic_status="observation", recorded_on=TODAY.isoformat(), context_records=[])
    selector_b = copy.deepcopy(selector)
    selector_b.update(container_heading_path=[title, "Other table"],
                      header_sha256=digest("| Item | [Other norm](norm-b.md) |\n| --- | --- |\n"),
                      key=dict(kind="link_destination", value="b.md"))
    record_b = {**record, "id": "entry-b", "selectors": {o: selector_b for o in ("base", "current")},
                "base_sha256": digest("| [B](b.md) | recorded |\n"),
                "current_sha256": digest("| [B](b.md) | recorded |\n")}
    bindings = []
    for origin, graph in (("base", base), ("current", current)):
        for consumer, entry in (("consumer", record), ("consumer-b", record_b)):
            edge = next(e for e in graph["edges"] if e["source"] == f"memories/{consumer}.md"
                        and e["target"] == "memories/view.md")
            bindings.append(dict(origin=origin, edge_sha256=edge_digest(edge), consumer_record="document",
                                 role="consumption", target_record=entry["id"],
                                 consumed_sha256=entry[origin + "_sha256"],
                                 rationale="Consumes only the complete row and its required interpretation."))
    contract = dict(schema_version="document_record.v2",
                    document_modes={"memories/view.md": "explicit_view_v2"},
                    documents=[dict(path="memories/view.md", records=[record, record_b], envelope=[])], bindings=bindings,
                    **{o + "_documents_sha256": {p: digest(t) for p, t in g["documents"].items()}
                       for o, g in (("base", base), ("current", current))})
    pc, pb, seeds, _ = project_records(current, base, {"memories/norm.md"}, contract)
    row = node_id("memories/view.md", "entry-a")
    for graph in (pb, pc):
        assert any(e["source"] == row and e["target"] == "memories/norm.md"
                   and e.get("inherited_document_context") for e in graph["edges"])
        assert not any(e["source"] == node_id("memories/view.md", "entry-b")
                       and e["target"] == "memories/norm.md" for e in graph["edges"])
    result = evaluate_impact(pc, pb, seeds, today=TODAY)
    assert seeds == {"memories/norm.md"}
    assert "memories/consumer.md" in {r["path"] for r in result["included"]}
    assert "memories/consumer-b.md" not in {r["path"] for r in result["included"]}
