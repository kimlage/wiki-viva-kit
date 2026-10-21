"""Synthetic custody edits through the normal projector, review and evaluator."""
import copy
import datetime as dt
import hashlib
import json

import pytest

from wiki_core.config import load_config
from wiki_core.document_records import digest, edge_digest, node_id, project_records, sections
from wiki_core.document_record_review import repository_review, review_records
from wiki_core.freshness_impact import authored_graph, evaluate_impact, repository_report
from test_freshness_impact import commit, page, repo

SOURCE = "memories/source.md"
CONSUMER = "memories/consumer.md"
RULE = "memories/rule.md"
OLD = "[Preserved banner](../assets/banner.png)"
NEW = "[Preserved banner](https://files.example.invalid/banner)"
TODAY = dt.date(2026, 10, 18)
ASSET = b"banner!"
ASSET_SHA = hashlib.sha256(ASSET).hexdigest()


@pytest.fixture
def migration(repo):
    graphs = {}
    for origin, link in (("base", OLD), ("current", NEW)):
        page(repo, "source", stale=True, source_refs=["rule"],
             body="## Historical observation\n\nCaptured in January: " + link + "\n")
        page(repo, "consumer", body="A dated observation: [the source](source.md).\n")
        page(repo, "rule", body="Current publication requires current factual readback.\n")
        graphs[origin] = authored_graph(repo, load_config(repo))
    receipt = json.dumps(dict(source_path="assets/banner.png", sha256=ASSET_SHA,
                              size_bytes=7, view_url="https://files.example.invalid/banner",
                              verified_at="2026-10-18T00:00:00+00:00")).encode()
    contract = dict(schema_version="document_record.v1", documents=[dict(
        path=SOURCE, records=[dict(id="historical", heading="Historical observation",
            independent=True, recorded_on="2026-01-01", epistemic_status="observation",
            context_records=[], rationale="The dated observation is distinct from current profile claims.",
            **{f"{o}_sha256": digest(sections(g["documents"][SOURCE])[1]["Historical observation"][2])
               for o, g in graphs.items()})])], bindings=[], artifacts=[dict(
        origin="current", id="custody", path="proofs/custody.json",
        sha256=hashlib.sha256(receipt).hexdigest())], locator_changes=[dict(
        id="banner-custody", path=SOURCE,
        rationale="Only the private custody address changes; this asserts no present profile state.",
        replacements=[dict(base_markdown=OLD, current_markdown=NEW,
                           locator_use="historical_artifact_address", artifact_sha256=ASSET_SHA,
                           size_bytes=7, custody_evidence="custody")])])
    for origin, graph in graphs.items():
        contract[f"{origin}_documents_sha256"] = {p: digest(t) for p, t in graph["documents"].items()}
        edge = next(e for e in graph["edges"] if e["source"] == CONSUMER and e["target"] == SOURCE)
        contract["bindings"].append(dict(origin=origin, edge_sha256=edge_digest(edge),
            target_record="historical", consumed_sha256=contract["documents"][0]["records"][0][f"{origin}_sha256"],
            rationale="This consumer preserves the dated observation, not the asset URL or present profile.",
            locator_review=dict(change_id="banner-custody",
                                consumption="historical_observation_without_locator",
                                rationale="The January observation is unchanged; no current publication or access is asserted.")))
    return graphs["current"], graphs["base"], contract, {("current", "custody"): receipt}


def projected(case, changed=None):
    current, base, contract, inputs = case
    return project_records(current, base, changed or {SOURCE}, contract, artifact_inputs=inputs)


def result(case, changed=None):
    current, base, seeds, _ = projected(case, changed)
    return evaluate_impact(current, base, seeds, today=TODAY)


def test_locator_only_keeps_raw_seed_verdict_and_debt_without_factual_renewal(migration):
    assert {binding["origin"] for binding in migration[2]["bindings"]} == {"base", "current"}
    report = result(migration)
    assert report["ok"]
    assert SOURCE in report["seeds"]
    included = {r["path"]: r for r in report["included"]}
    for path in (SOURCE, node_id(SOURCE, "historical")):
        assert included[path]["state"] == "stale"
        assert included[path]["review_requirements"]["factual"] is False
    assert {r["path"] for r in report["preserved_content_debt"]} >= {SOURCE, node_id(SOURCE, "historical")}
    assert RULE in included  # Own normative prerequisites were not pruned.
    assert migration[0]["nodes"][SOURCE]["updated_at"] == "2026-01-01"


def test_unknown_whole_competing_route_restores_factual_requirement(migration):
    current, base, contract, _ = migration
    for origin, graph in (("base", base), ("current", current)):
        graph["edges"].append(dict(source=CONSUMER, target=SOURCE, type="source_ref",
            direction="directed", basis="frontmatter", path=CONSUMER, field="unknown_whole"))
    report = result(migration)
    assert not report["ok"]
    row = next(r for r in report["included"] if r["path"] == node_id(SOURCE, "historical"))
    assert row["review_requirements"]["factual"] is True
    assert row["review_requirements"]["representation"]
    for graph in (current, base):
        graph["edges"].reverse()
    again = result(migration)
    assert {(r["path"], r["state"]) for r in report["blockers"]} == {
        (r["path"], r["state"]) for r in again["blockers"]}


def test_current_only_qualification_does_not_hide_base(migration):
    migration[2]["bindings"][0].pop("locator_review")
    assert not result(migration)["ok"]


def test_existing_custody_manifest_entry_is_pinned_without_a_new_store(migration):
    contract, inputs = migration[2:]
    entry = json.loads(inputs[("current", "custody")])
    raw = json.dumps({"files": {"banner.png": entry}}).encode()
    inputs[("current", "custody")] = raw
    contract["artifacts"][0]["sha256"] = hashlib.sha256(raw).hexdigest()
    contract["locator_changes"][0]["replacements"][0]["custody_entry"] = "banner.png"
    assert result(migration)["ok"]


def test_verified_input_pair_cannot_change_between_projection_and_evaluation(migration):
    current, base, seeds, _ = projected(migration)
    current["documents"][SOURCE] += "\nA new present-tense claim.\n"
    with pytest.raises(ValueError, match="input pair changed"):
        evaluate_impact(current, base, seeds, today=TODAY)


def test_own_unqualified_normative_premise_remains_blocking(migration):
    for graph in migration[:2]:
        graph["nodes"][RULE]["updated_at"] = "2020-01-01"
    report = result(migration)
    assert not report["ok"]
    assert any(r["path"] == RULE for r in report["blockers"])


@pytest.mark.parametrize("fault", ["null", "missing", "bad-id", "receipt-size", "receipt-url", "duplicate-key", "naive-time"])
def test_malformed_present_inputs_fail_as_contract_errors(migration, fault):
    contract, inputs = migration[2:]
    if fault == "null":
        contract["locator_changes"] = None
    elif fault == "missing":
        contract["locator_changes"][0].pop("rationale")
    elif fault == "bad-id":
        contract["bindings"][0]["locator_review"]["change_id"] = []
    else:
        receipt = json.loads(inputs[("current", "custody")])
        if fault == "receipt-size":
            receipt["size_bytes"] = 7.0
        elif fault == "receipt-url":
            receipt["view_url"] = "https://files.example.invalid/another-original"
        elif fault == "naive-time":
            receipt["verified_at"] = "2026-10-18T00:00:00"
        raw = json.dumps(receipt).encode()
        if fault == "duplicate-key":
            raw = raw[:-1] + b',"sha256":"' + ASSET_SHA.encode() + b'"}'
        inputs[("current", "custody")] = raw
        contract["artifacts"][0]["sha256"] = hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError):
        projected(migration)


def test_mixed_real_normative_change_dominates_custody_even_with_equal_output(migration):
    current, base, contract, _ = migration
    current["documents"][RULE] += "\nNew authority and a stricter publication requirement.\n"
    contract["current_documents_sha256"][RULE] = digest(current["documents"][RULE])
    report = result(migration, {SOURCE, RULE})
    assert not report["ok"]
    assert any(r["path"] == node_id(SOURCE, "historical") for r in report["blockers"])


@pytest.mark.parametrize("foreign_origin", [None, "base", "current", "both"])
def test_locator_review_cannot_qualify_another_documents_stale_observation(migration, repo, foreign_origin):
    current, base, contract, inputs = migration
    heading = "Independent historical observation"
    other_sha = None
    for origin, graph in (("base", base), ("current", current)):
        for path, text in graph["documents"].items():
            (repo / path).write_text(text)
        page(repo, "rule", stale=True, body=f"## {heading}\n\nA separate event recorded in January.\n")
        authored = authored_graph(repo, load_config(repo))
        other_sha = digest(sections(authored["documents"][RULE])[1][heading][2])
        contract[f"{origin}_documents_sha256"] = {p: digest(t) for p, t in authored["documents"].items()}
        edge = next(e for e in authored["edges"] if e["source"] == SOURCE and e["target"] == RULE)
        for consumer in ("historical", "remainder"):
            binding = dict(origin=origin, edge_sha256=edge_digest(edge),
                consumer_record=consumer, target_record="other-observation", consumed_sha256=other_sha,
                rationale="A separate historical observation is the explicit prerequisite.")
            if foreign_origin in {origin, "both"}:
                binding["locator_review"] = dict(change_id="banner-custody",
                    consumption="historical_observation_without_locator",
                    rationale="This deliberately names the other document's locator change.")
            contract["bindings"].append(binding)
        if origin == "base":
            baseline = commit(repo)
    contract["documents"].append(dict(path=RULE, records=[dict(id="other-observation", heading=heading,
        independent=True, recorded_on="2026-01-01", epistemic_status="observation", context_records=[],
        rationale="A distinct dated event, with no custody change in this operation.",
        base_sha256=other_sha, current_sha256=other_sha)]))
    proof = repo / "proofs/custody.json"
    proof.parent.mkdir()
    proof.write_bytes(inputs[("current", "custody")])
    (repo / "records.json").write_text(json.dumps(contract))
    (repo / "wiki.config.yaml").write_text(
        f"audit:\n  freshness_scope: impact\n  freshness_base: {baseline}\n  freshness_records: records.json\n")
    if foreign_origin:
        with pytest.raises(ValueError, match="same changed document"):
            report = repository_report(repo, load_config(repo), baseline, today=TODAY)
            print(json.dumps(dict(incorrectly_accepted=report["ok"],
                other_observation=next(r for r in report["included"]
                                      if r["path"] == node_id(RULE, "other-observation")))))
    else:
        report = repository_report(repo, load_config(repo), baseline, today=TODAY)
        row = next(r for r in report["included"] if r["path"] == node_id(RULE, "other-observation"))
        assert row["state"] == "stale" and row["review_requirements"]["factual"]
        assert not report["ok"] and row in report["blockers"]


@pytest.mark.parametrize("component_markers", [False, True])
def test_raw_factual_page_cannot_borrow_locator_identity_from_frontmatter(migration, repo, component_markers):
    current, base, contract, inputs = migration
    forged = dict(document_path=SOURCE)
    if component_markers:
        forged.update(document_record_id="historical", record_sha256="0" * 64,
                      verified_locator_record_documents={"memories/unrelated.md": SOURCE})
    for origin, graph in (("base", base), ("current", current)):
        page(repo, "unrelated", stale=True,
             body="Previous factual claim.\n" if origin == "base" else "A different factual claim.\n",
             **forged)
        for path, text in graph["documents"].items():
            (repo / path).write_text(text)
        authored = authored_graph(repo, load_config(repo))
        contract[f"{origin}_documents_sha256"] = {p: digest(t) for p, t in authored["documents"].items()}
        if origin == "base":
            baseline = commit(repo)
    proof = repo / "proofs/custody.json"
    proof.parent.mkdir()
    proof.write_bytes(inputs[("current", "custody")])
    (repo / "records.json").write_text(json.dumps(contract))
    (repo / "wiki.config.yaml").write_text(
        f"audit:\n  freshness_scope: impact\n  freshness_base: {baseline}\n  freshness_records: records.json\n")
    report = repository_report(repo, load_config(repo), baseline, today=TODAY)
    row = next(r for r in report["included"] if r["path"] == "memories/unrelated.md")
    assert row["state"] == "stale"
    assert row["review_requirements"]["factual"] is True
    assert not row["review_requirements"]["representation"]
    assert not report["ok"] and row in report["blockers"]


@pytest.mark.parametrize("wrapped", [False, True])
def test_complete_git_migration_normative_and_whole_routes_use_normal_callers(migration, repo, wrapped):
    if wrapped:
        migration = _wrapped_locator_case(migration,
            "- Old historical context\n  before {link}\n  with unchanged trailing prose.\n")
    current, base, contract, inputs = migration
    for path, text in base["documents"].items():
        (repo / path).write_text(text)
    original = repo / "assets/banner.png"
    original.parent.mkdir()
    original.write_bytes(ASSET)
    baseline = commit(repo)
    original.unlink()
    for path, text in current["documents"].items():
        (repo / path).write_text(text)
    proof = repo / "proofs/custody.json"
    proof.parent.mkdir()
    proof.write_bytes(inputs[("current", "custody")])
    records = repo / "records.json"
    records.write_text(json.dumps(contract))
    (repo / "wiki.config.yaml").write_text(
        f"audit:\n  freshness_scope: impact\n  freshness_base: {baseline}\n  freshness_records: records.json\n")
    clean = repository_report(repo, load_config(repo), baseline, today=TODAY)
    assert clean["ok"] and SOURCE in clean["seeds"]
    packet = repository_review(repo, [SOURCE])
    assert packet["locator_changes"][0]["id"] == "banner-custody"
    # Real normative change and an additional WHOLE occurrence coexist with
    # the valid custody edit. Rebuild through the actual authored graph.
    (repo / RULE).write_text(current["documents"][RULE] + "\nNew current publication authority.\n")
    (repo / CONSUMER).write_text(current["documents"][CONSUMER] + "\nCurrent whole premise: [source](source.md).\n")
    graph = authored_graph(repo, load_config(repo))
    contract["current_documents_sha256"] = {p: digest(t) for p, t in graph["documents"].items()}
    records.write_text(json.dumps(contract))
    blocked = repository_report(repo, load_config(repo), baseline, today=TODAY)
    assert not blocked["ok"]
    historical = next(r for r in blocked["included"] if r["path"] == node_id(SOURCE, "historical"))
    assert historical["state"] == "stale" and historical["review_requirements"]["factual"]


@pytest.mark.parametrize("case", ["shared-reference", "partial-occurrences", "unknown-field", "bad-claim", "whole-remainder"])
def test_ambiguous_or_unknown_semantics_never_abstain_silently(migration, case):
    current, base, contract, _ = migration
    change = contract["locator_changes"][0]
    if case == "unknown-field":
        change["automatic_independence"] = True
    elif case == "bad-claim":
        contract["bindings"][0]["locator_review"]["consumption"] = "live_policy_or_hash"
    elif case == "whole-remainder":
        for binding in contract["bindings"]:
            binding["target_record"] = "remainder"
            text = (base if binding["origin"] == "base" else current)["documents"][SOURCE]
            body, _ = sections(text)
            binding["consumed_sha256"] = digest(text[:-len(body)])
    else:
        for origin, graph, link in (("base", base, OLD), ("current", current, NEW)):
            if case == "shared-reference":
                href = "../assets/banner.png" if origin == "base" else "https://files.example.invalid/banner"
                text = graph["documents"][SOURCE].replace(link, "[Preserved banner][asset]") + f"\n[asset]: {href}\n"
            else:
                text = graph["documents"][SOURCE] + "\n" + link.replace("Preserved banner", "Second occurrence") + "\n"
            graph["documents"][SOURCE] = text
            contract[f"{origin}_documents_sha256"][SOURCE] = digest(text)
            contract["documents"][0]["records"][0][f"{origin}_sha256"] = digest(
                sections(text)[1]["Historical observation"][2])
        for binding in contract["bindings"]:
            binding["consumed_sha256"] = contract["documents"][0]["records"][0][f"{binding['origin']}_sha256"]
    with pytest.raises(ValueError):
        projected(migration)


@pytest.mark.parametrize("fault", ["date", "label", "image", "prose", "fake-code", "proof", "future-base", "url-identity"])
def test_invalid_or_material_locator_declaration_fails_closed(migration, fault):
    current, base, contract, inputs = migration
    change = contract["locator_changes"][0]
    if fault in {"date", "label", "image", "prose", "fake-code"}:
        text = current["documents"][SOURCE]
        if fault == "date":
            text = text.replace("2026-01-01", "2026-10-18")
        elif fault == "label":
            text = text.replace("Preserved banner", "Newly approved banner")
        elif fault == "image":
            text = text.replace(NEW, "!" + NEW)
        elif fault == "prose":
            text += "\nThe profile is current today.\n"
        else:
            for o, graph in (("base", base), ("current", current)):
                graph["documents"][SOURCE] = graph["documents"][SOURCE].replace(
                    "Captured in January: ", "```markdown\n") + "```\n"
                contract[f"{o}_documents_sha256"][SOURCE] = digest(graph["documents"][SOURCE])
            text = current["documents"][SOURCE]
        current["documents"][SOURCE] = text
        contract["current_documents_sha256"][SOURCE] = digest(text)
        for o, graph in (("base", base), ("current", current)):
            contract["documents"][0]["records"][0][f"{o}_sha256"] = digest(
                sections(graph["documents"][SOURCE])[1]["Historical observation"][2])
        for binding in contract["bindings"]:
            binding["consumed_sha256"] = contract["documents"][0]["records"][0][f"{binding['origin']}_sha256"]
    elif fault == "proof":
        change["replacements"][0]["artifact_sha256"] = "b" * 64
    elif fault == "future-base":
        contract["artifacts"][0]["origin"] = "base"
        inputs[("base", "custody")] = inputs.pop(("current", "custody"))
    else:
        change["replacements"][0]["locator_use"] = "identity_or_permission"
    with pytest.raises(ValueError):
        projected(migration)


def test_absence_retains_existing_contract_and_review_uses_same_projection(migration):
    packet = review_records(migration[0], migration[1], {SOURCE}, migration[2],
                            targets=[SOURCE], artifact_inputs=migration[3])
    assert packet["locator_changes"][0]["id"] == "banner-custody"
    assert SOURCE in packet["changed_record_seeds"]
    original = copy.deepcopy(migration)
    original[2].pop("locator_changes")
    for binding in original[2]["bindings"]:
        binding.pop("locator_review")
    assert not result(original)["ok"]


def _wrapped_locator_case(case, layout, *, current_extra="", current_metadata=False,
                          base_link=OLD, current_link=NEW):
    """Keep the complete input pair and selected-record hashes explicit."""
    current, base, contract, _ = case
    for origin, graph, link in (("base", base, base_link), ("current", current, current_link)):
        text = graph["documents"][SOURCE]
        text = text.replace("Captured in January: " + (OLD if origin == "base" else NEW) + "\n",
                            layout.format(link=link))
        if origin == "current":
            text += current_extra
            if current_metadata:
                text = text.replace("2026-01-01", "2026-10-18")
        graph["documents"][SOURCE] = text
        contract[f"{origin}_documents_sha256"][SOURCE] = digest(text)
        contract["documents"][0]["records"][0][f"{origin}_sha256"] = digest(
            sections(text)[1]["Historical observation"][2])
    for binding in contract["bindings"]:
        binding["consumed_sha256"] = contract["documents"][0]["records"][0][
            f"{binding['origin']}_sha256"]
    return case


@pytest.mark.parametrize("layout", [
    "- A historical observation wraps\n  before {link}\n  and retains its trailing context.\n",
    "1. An old observation:\n   - Nested context wraps\n     before {link}\n     and retains its trailing context.\n",
    "> - An old observation wraps\n>   before {link}\n>   with unchanged context.\n",
])
def test_locator_literal_maps_wrapped_container_without_normalizing_the_link(migration, layout):
    case = _wrapped_locator_case(migration, layout)
    packet = review_records(case[0], case[1], {SOURCE}, case[2],
                            targets=[SOURCE], artifact_inputs=case[3])
    proof = packet["locator_changes"][0]["replacements"][0]
    for origin, graph in (("base", case[1]), ("current", case[0])):
        start, end = proof[f"{origin}_span"]
        assert graph["documents"][SOURCE][start:end] == (OLD if origin == "base" else NEW)
    report = result(case)
    assert report["ok"]
    assert RULE in {r["path"] for r in report["included"]}
    assert SOURCE in {r["path"] for r in report["preserved_content_debt"]}


def test_locator_wrapped_crlf_pair_keeps_exact_raw_offsets(migration):
    case = _wrapped_locator_case(migration, "- Old context\n  {link}\n  unchanged prose.\n")
    for origin, graph in (("base", case[1]), ("current", case[0])):
        text = graph["documents"][SOURCE].replace("\n", "\r\n")
        graph["documents"][SOURCE] = text
        case[2][f"{origin}_documents_sha256"][SOURCE] = digest(text)
        case[2]["documents"][0]["records"][0][f"{origin}_sha256"] = digest(
            sections(text)[1]["Historical observation"][2])
    for binding in case[2]["bindings"]:
        binding["consumed_sha256"] = case[2]["documents"][0]["records"][0][
            f"{binding['origin']}_sha256"]
    assert result(case)["ok"]


@pytest.mark.parametrize("fault", ["duplicate", "inline-code", "fenced-code", "reference",
                                    "image", "label", "metadata", "prose", "factual"])
def test_wrapped_locator_mapping_keeps_ambiguity_syntax_and_full_pair_fail_closed(migration, fault):
    layout = "- Old context\n  {link}\n  unchanged prose.\n"
    if fault == "duplicate":
        layout = "- Old context\n  {link} and {link}\n  unchanged prose.\n"
    elif fault == "inline-code":
        layout = "- Old context\n  `{link}`\n  unchanged prose.\n"
    elif fault == "fenced-code":
        layout = "```markdown\n- Old context\n  {link}\n```\n"
    elif fault == "reference":
        layout = "- Old context\n  [Preserved banner][banner]\n  unchanged prose.\n\n[banner]: {link}\n"
    elif fault == "image":
        layout = "- Old context\n  !{link}\n  unchanged prose.\n"
    extra = "\nA new factual assertion about present state.\n" if fault == "factual" else ""
    if fault == "prose":
        extra = "\nDifferent context.\n"
    case = _wrapped_locator_case(migration, layout, current_extra=extra,
                                current_metadata=fault == "metadata",
                                base_link="../assets/banner.png" if fault == "reference" else OLD,
                                current_link=("https://files.example.invalid/banner" if fault == "reference"
                                              else NEW.replace("Preserved banner", "Approved banner")
                                              if fault == "label" else NEW))
    if fault == "label":
        case[2]["locator_changes"][0]["replacements"][0]["current_markdown"] = (
            NEW.replace("Preserved banner", "Approved banner"))
    with pytest.raises(ValueError):
        projected(case)


def test_normalized_link_cannot_borrow_literal_from_code_in_wrapped_block(migration):
    # The real AST link spans indented lines and has no contiguous raw literal.
    # A matching spelling in code must never be used as that link's raw span.
    case = _wrapped_locator_case(migration,
        "- Old context [Preserved\n  banner]({link})\n  with code `[Preserved\nbanner]({link})`.\n",
        base_link="../assets/banner.png", current_link="https://files.example.invalid/banner")
    for origin in ("base", "current"):
        case[2]["locator_changes"][0]["replacements"][0][f"{origin}_markdown"] = (
            "[Preserved\nbanner](" + ("../assets/banner.png" if origin == "base"
                                       else "https://files.example.invalid/banner") + ")")
    with pytest.raises(ValueError):
        projected(case)
