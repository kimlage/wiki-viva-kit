"""Synthetic canonical-registry cases shared by legacy and explicit views."""
import datetime as dt
from types import SimpleNamespace

import pytest

from scripts import wiki_source_registry as registry
from wiki_core.config import load_config
from wiki_core.document_records import digest, edge_digest, node_id, project_records
from wiki_core.document_view_selectors import body_span, frontmatter_span
from wiki_core.frontmatter import FRONTMATTER_RE
from wiki_core.freshness_impact import authored_graph, evaluate_impact
from wiki_core.paths import WikiPaths
from test_freshness_impact import TODAY, page, repo


@pytest.fixture
def registry_case(repo, monkeypatch):
    """Use the real source collector/renderer and existing graph fixture."""
    monkeypatch.setattr(registry, "ROOT", repo)
    cfg = load_config(repo)
    paths = WikiPaths(repo, cfg)
    page(repo, "index", body="# Wiki\n")
    policy = page(repo, "system/reading-rule", body="# Reading rule\n\n"
                  "Recorded ingestion metadata is not current external progress.\n")

    def source(key):
        path = page(repo, "sources/" + key, title="Source " + key.upper(),
                    ingestion_state="partial", source_type="live",
                    source_refs=["system/reading-rule"],
                    body="# Source " + key.upper() + "\n\nExternal facts require their own support.\n")
        path.write_text(path.read_text().replace("page_type: project", "page_type: source", 1))
        return path

    a, b = source("a"), source("b")
    entry = page(repo, "consumers/entry-a", body="# A fields\n\n"
                 "The [register](../system/source-registry.md) reports A's recorded state "
                 "and next review, subject to the [reading rule](../system/reading-rule.md).\n")
    whole = page(repo, "consumers/whole", body="# Whole register\n\n"
                 "The [register](../system/source-registry.md) supplies its complete membership, "
                 "publication date and current recorded rows.\n")
    target = paths.source_registry_page
    assert target.relative_to(repo).as_posix() == "memories/system/source-registry.md"
    target.parent.mkdir(parents=True, exist_ok=True)

    def render(as_of=TODAY):
        text = registry.build_registry(paths, cfg, as_of.isoformat())
        target.write_text(text)
        return text

    def graph():
        result = authored_graph(repo, cfg)
        assert not result["errors"]
        return result

    def row(text, key="a"):
        found = [line for line in text.splitlines(keepends=True)
                 if f"](../sources/{key}.md)" in line]
        assert len(found) == 1
        return found[0]

    render()
    return SimpleNamespace(root=repo, a=a, b=b, policy=policy, entry=entry, whole=whole,
                           target=target, source=source, render=render, graph=graph, row=row)


def test_legacy_registry_addition_preserves_raw_seeds_and_whole_consumption(registry_case):
    case = registry_case
    old_text = case.target.read_text()
    base = case.graph()
    case.source("c")
    new_text = case.render()
    current = case.graph()
    assert case.row(old_text) == case.row(new_text)
    assert old_text != new_text
    changed = {"memories/sources/c.md", "memories/system/source-registry.md"}
    result = evaluate_impact(current, base, changed, today=TODAY)
    assert changed <= set(result["seeds"])
    included = {item["path"] for item in result["included"]}
    assert {"memories/consumers/entry-a.md", "memories/consumers/whole.md",
            "memories/sources/a.md", "memories/sources/b.md"} <= included
    # The legacy citation is WHOLE. Equality of A's rendered line does not
    # constitute a declaration that the current engine can select that line.
    assert any(edge["path"] == "memories/consumers/entry-a.md"
               for item in result["included"] for edge in item["chain"])


@pytest.mark.parametrize("change", ["state", "publication", "policy", "fact", "unknown"])
def test_legacy_registry_factual_and_unknown_routes_remain_conservative(registry_case, change):
    case = registry_case
    if change == "unknown":
        case.entry.write_text(case.entry.read_text().replace("updated_at: '2026-10-18'\n", ""))
    old_text = case.target.read_text()
    base = case.graph()
    if change == "state":
        case.a.write_text(case.a.read_text().replace("ingestion_state: partial", "ingestion_state: ingested"))
        changed = {"memories/sources/a.md", "memories/system/source-registry.md"}
        case.render()
        assert case.row(old_text) != case.row(case.target.read_text())
    elif change == "publication":
        case.render(TODAY + dt.timedelta(days=1))
        changed = {"memories/system/source-registry.md"}
        assert case.row(old_text) == case.row(case.target.read_text())
    elif change == "policy":
        case.policy.write_text(case.policy.read_text() + "\nA current normative restriction applies.\n")
        changed = {"memories/system/reading-rule.md"}
        assert case.render() == old_text
    elif change == "fact":
        case.a.write_text(case.a.read_text() + "\nThe external factual premise changed.\n")
        changed = {"memories/sources/a.md"}
        assert case.render() == old_text
    else:
        case.source("c")
        case.render()
        changed = {"memories/sources/c.md", "memories/system/source-registry.md"}
    result = evaluate_impact(case.graph(), base, changed, today=TODAY)
    assert changed <= set(result["seeds"])
    assert "memories/consumers/entry-a.md" in {item["path"] for item in result["included"]}
    if change == "unknown":
        assert any(item["path"] == "memories/consumers/entry-a.md" and item["state"] == "unknown"
                   for item in result["blockers"])


def test_v1_cannot_select_a_canonical_table_row_as_an_h2(registry_case):
    case = registry_case
    base = case.graph()
    old_row = case.row(case.target.read_text())
    case.source("c")
    case.render()
    current = case.graph()
    contract = dict(schema_version="document_record.v1",
        base_documents_sha256={p: digest(t) for p, t in base["documents"].items()},
        current_documents_sha256={p: digest(t) for p, t in current["documents"].items()},
        documents=[dict(path="memories/system/source-registry.md", records=[dict(
            id="entry-a", heading="Source A", independent=True,
            rationale="A recorded source entry would be the desired unit; no H2 exists.",
            epistemic_status="observation", recorded_on=TODAY.isoformat(), context_records=[],
            base_sha256=digest(old_row), current_sha256=digest(old_row))])], bindings=[])
    with pytest.raises(ValueError, match="record selector/hash mismatch"):
        project_records(current, base, {"memories/system/source-registry.md"}, contract)


def registry_contract(base, current):
    """Explicit synthetic claims against the unmodified real registry renderer.

    The status column uses as_of, so each full row consumes publication-body.
    Source links remain LIVE: this fixture does not author metadata provenance.
    """
    import copy
    path = "memories/system/source-registry.md"
    bodies = {o: t[FRONTMATTER_RE.match(t).end():]
              for o, t in (("base", base["documents"][path]), ("current", current["documents"][path]))}
    heading = next(line[2:] for line in bodies["base"].splitlines() if line.startswith("# "))
    lines = bodies["base"].splitlines(keepends=True)
    start = next(i for i, line in enumerate(lines) if line.startswith("| Source |"))
    header_hash = digest("".join(lines[start:start + 2]))
    records = []
    for key in ("a", "b", "c"):
        selector = dict(kind="table_row", container_heading_path=[heading],
                        header_sha256=header_hash, key_column=0,
                        key=dict(kind="link_destination", value=f"../sources/{key}.md"), required_match_count=1)
        record = dict(id="entry-" + key, selectors={}, independent=True,
                      rationale="Complete recorded row, including temporal status and common interpretation.",
                      epistemic_status="observation", recorded_on=TODAY.isoformat(),
                      context_records=["remainder", "publication-body"])
        for origin, graph in (("base", base), ("current", current)):
            span = body_span(graph["documents"][path], selector)
            record["selectors"][origin] = copy.deepcopy(selector) if span else None
            record[origin + "_sha256"] = digest("".join(bodies[origin].splitlines(keepends=True)[span[0]:span[1]])) if span else None
        if record["base_sha256"] is not None or record["current_sha256"] is not None:
            records.append(record)
    envelope = []
    for rid, selector, shape, claim in (
        ("publication-fm", dict(kind="frontmatter_field", path=["updated_at"]),
         "canonical_iso_date", "artifact_publication_date"),
        ("membership", dict(kind="frontmatter_field", path=["collection", "members"]),
         "unique_string_sequence", "declared_view_membership"),
        ("publication-body", dict(kind="markdown_generation_paragraph", container_heading_path=[heading],
                                  required_match_count=1,
                                  template=dict(prefix="Updated at: ", suffix=".", value_format="iso_date")),
         None, "artifact_publication_date"),
    ):
        slot = dict(id=rid, selectors={o: copy.deepcopy(selector) for o in ("base", "current")},
                    claim=claim, rationale="Explicit generation date or complete composition; no external authority.",
                    context_records=[])
        if shape:
            slot["value_shape"] = shape
        for origin, graph in (("base", base), ("current", current)):
            text = graph["documents"][path]
            if shape:
                a, b = frontmatter_span(text, selector, shape)
            else:
                a, b = body_span(text, selector)
                text = bodies[origin]
            slot[origin + "_sha256"] = digest("".join(text.splitlines(keepends=True)[a:b]))
        envelope.append(slot)
    bindings = []
    for origin, graph in (("base", base), ("current", current)):
        edge = next(e for e in graph["edges"] if e["source"] == "memories/consumers/entry-a.md"
                    and e["target"] == path)
        bindings.append(dict(origin=origin, edge_sha256=edge_digest(edge), role="consumption",
                             consumer_record="document", target_record="entry-a",
                             consumed_sha256=records[0][origin + "_sha256"],
                             rationale="This assertion consumes A recorded fields with their real temporal context."))
    return dict(schema_version="document_record.v2", document_modes={path: "explicit_view_v2"},
                documents=[dict(path=path, records=records, envelope=envelope)], bindings=bindings,
                **{o + "_documents_sha256": {p: digest(t) for p, t in g["documents"].items()}
                   for o, g in (("base", base), ("current", current))})


@pytest.mark.parametrize("change", ["addition", "time", "state", "body", "norm"])
def test_real_registry_view_routes_material_temporal_and_live_premises(registry_case, change):
    case = registry_case
    base = case.graph()
    path = "memories/system/source-registry.md"
    changed = {path}
    if change == "addition":
        case.source("c")
        changed.add("memories/sources/c.md")
    elif change == "state":
        case.a.write_text(case.a.read_text().replace("ingestion_state: partial", "ingestion_state: ingested"))
        changed.add("memories/sources/a.md")
    elif change == "body":
        case.a.write_text(case.a.read_text() + "\nExternal premise changed without changing the rendered row.\n")
        changed = {"memories/sources/a.md"}
    elif change == "norm":
        case.policy.write_text(case.policy.read_text() + "\nNew normative restriction.\n")
        changed = {"memories/system/reading-rule.md"}
    case.render(TODAY + dt.timedelta(days=1) if change == "time" else TODAY)
    current = case.graph()
    contract = registry_contract(base, current)
    pc, pb, seeds, coverage = project_records(current, base, changed, contract)
    result = evaluate_impact(pc, pb, seeds, today=TODAY)
    included = {row["path"] for row in result["included"]}
    assert changed <= seeds
    assert ("memories/consumers/entry-a.md" in included) is (change != "addition")
    if change == "addition":
        assert coverage[0]["complete_delta_covered"]
        assert node_id(path, "entry-a") not in seeds
        assert "memories/consumers/whole.md" in included
        assert {"memories/sources/a.md", "memories/sources/b.md"} <= included
