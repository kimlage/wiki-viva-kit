"""Synthetic Git-backed proofs of scoped freshness; no consumer/private fixtures."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
from pathlib import Path

import pytest
import yaml

from scripts import wiki_audit as audit
from scripts.wiki_page_graph import GitCommandError
from wiki_core.config import load_config
from wiki_core.freshness_impact import authored_graph, evaluate_impact, repository_report

TODAY = dt.date(2026, 10, 18)


def page(root: Path, name: str, *, stale=False, body="", **fields):
    path = root / "memories" / f"{name}.md"
    path.parent.mkdir(exist_ok=True, parents=True)
    values = dict(page_id=name, page_type="project", updated_at="2026-01-01" if stale else "2026-10-18",
                  stale_after_days=30, **fields)
    path.write_text("---\n" + yaml.safe_dump(values) + "---\n" + body)
    return path


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "wiki.config.yaml").write_text("audit:\n  freshness_scope: impact\n")
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "fixture@example.invalid")
    git(tmp_path, "config", "user.name", "Synthetic Fixture")
    return tmp_path


def commit(root):
    git(root, "add", ".")
    git(root, "commit", "-qm", "synthetic base")
    return git(root, "rev-parse", "HEAD")


def report(root, base):
    return repository_report(root, load_config(root), base, today=TODAY)


def paths(rows):
    return {r["path"] for r in rows}


def declared_link(label, target, role):
    """Public authored declaration, not a claim about a particular consumer."""
    literal = f"[{label}]({target})"
    digest = hashlib.sha256(literal.encode()).hexdigest()
    return literal + f"<!-- wiki-link-role.v1 {role} sha256:{digest} -->"


def test_authored_navigation_table_does_not_connect_unrelated_fiscal_action(repo):
    page(repo, "catalogue", body="Command reference.")
    page(repo, "meta", body="| Destination | Purpose |\n| --- | --- |\n| "
         + declared_link("Commands", "catalogue.md", "navigation") + " | Open reference |\n")
    page(repo, "index", body="Use the wiki: " + declared_link("Open", "meta.md", "navigation"))
    page(repo, "tax", body="## Related\n- Back to index: "
         + declared_link("Index", "index.md", "navigation"))
    action = page(repo, "tax-action", stale=True, evidence_refs=["tax"])
    action.write_text(action.read_text().replace("page_type: project", "page_type: action", 1))
    base = commit(repo)
    with (repo / "memories/catalogue.md").open("a") as stream:
        stream.write("\nDocument another command.\n")
    result = report(repo, base)
    assert result["ok"]
    assert paths(result["included"]) == {"memories/catalogue.md"}
    # The last edge is genuine evidence, and must still propagate a real change.
    with (repo / "memories/tax.md").open("a") as stream:
        stream.write("\nChanged fiscal evidence.\n")
    assert "memories/tax-action.md" in paths(report(repo, base)["blockers"])


def test_generated_target_column_is_not_consumption_of_target_content(repo):
    from wiki_core.input_stage import render_input_stage_markdown

    page(repo, "index")
    page(repo, "catalogue", body="Command reference.")
    page(repo, "meta", body="| Destination |\n| --- |\n| "
         + declared_link("Commands", "catalogue.md", "navigation") + " |\n")
    page(repo, "source", stale=True)
    cfg = load_config(repo)
    catalog = {"generated_at": "2026-01-01", "sources": [
        {"title": "Synthetic source", "source_path": "memories/source.md",
         "input_status": "integrated", "target_pages": ["memories/meta.md"],
         "resolved_perspectives": {}}]}
    stage = repo / str(cfg.root_entity.get("input_stage_page") or "memories/system/input-stage.md")
    stage.parent.mkdir(parents=True, exist_ok=True)
    stage.write_text(render_input_stage_markdown(catalog, cfg))
    base = commit(repo)
    with (repo / "memories/catalogue.md").open("a") as stream:
        stream.write("\nDocument another command.\n")
    result = report(repo, base)
    assert result["ok"]
    assert stage.relative_to(repo).as_posix() not in paths(result["included"])
    assert any(e.get("authored_role") == "change_target"
               and e["path"] == stage.relative_to(repo).as_posix()
               for e in result["nonpropagating_relations"])
    # Source/status cells still consume their source; only targets are qualified.
    stage.write_text(stage.read_text() + "\nChanged processing guidance.\n")
    assert "memories/source.md" in paths(report(repo, base)["blockers"])


def test_authored_navigation_never_hides_second_factual_occurrence(repo):
    page(repo, "catalogue")
    page(repo, "consumer", stale=True,
         body=declared_link("Open", "catalogue.md", "navigation")
         + "\n\nThis conclusion depends on [the catalogue](catalogue.md).\n")
    base = commit(repo)
    with (repo / "memories/catalogue.md").open("a") as stream:
        stream.write("\nChanged command contract.\n")
    result = report(repo, base)
    assert paths(result["blockers"]) == {"memories/consumer.md"}
    assert any(e.get("authored_role") == "navigation" for e in result["nonpropagating_relations"])


def test_current_only_role_never_relabels_historical_citation(repo):
    page(repo, "catalogue", stale=True)
    page(repo, "consumer", body="[Open](catalogue.md)")
    base = commit(repo)
    page(repo, "consumer", body=declared_link("Open", "catalogue.md", "navigation"))
    assert "memories/catalogue.md" in paths(report(repo, base)["blockers"])


def test_connected_stale_blocks_unrelated_debt_is_reported(repo):
    page(repo, "source", stale=True)
    page(repo, "task", source_refs=["source"])
    page(repo, "elsewhere", stale=True)
    base = commit(repo)
    page(repo, "task", source_refs=["source"], body="New conclusion.")
    result = report(repo, base)
    assert paths(result["blockers"]) == {"memories/source.md"}
    assert paths(result["unrelated_debt"]) == {"memories/elsewhere.md"}
    row = result["blockers"][0]
    assert row["reason"] == "required_dependency"
    assert row["seed"] == "memories/task.md"
    assert row["chain"][0]["field"] == "source_refs"
    assert result == report(repo, base)  # deterministic evidence, no wall-clock fields


def test_two_phase_transitive_closure_does_not_fan_out_to_sibling(repo):
    page(repo, "shared", stale=True)
    page(repo, "first", source_refs=["shared"])
    page(repo, "second", source_refs=["first"])
    page(repo, "third", source_refs=["second"])
    page(repo, "sibling", stale=True, source_refs=["shared"])
    base = commit(repo)
    page(repo, "first", source_refs=["shared"], body="Changed.")
    result = report(repo, base)
    assert paths(result["included"]) == {f"memories/{n}.md" for n in ("first", "second", "third", "shared")}
    assert paths(result["unrelated_debt"]) == {"memories/sibling.md"}
    assert len(next(r for r in result["included"] if r["path"].endswith("third.md"))["chain"]) == 2


@pytest.mark.parametrize("field,kind", [("moc_parent", "project"), ("owner_ref", "action"), ("owner", "project"), ("collection_refs", "project")])
def test_structural_edges_alone_do_not_propagate(repo, field, kind):
    page(repo, "index", stale=True)
    target = page(repo, "item", **{field: ["index"]})
    values = target.read_text().replace("page_type: project", f"page_type: {kind}")
    target.write_text(values)
    base = commit(repo)
    target.write_text(values + "\nA change.")
    result = report(repo, base)
    assert result["ok"]
    assert paths(result["included"]) == {"memories/item.md"}
    assert result["nonpropagating_relations"]


def test_explicit_evidence_is_not_hidden_by_structural_navigation(repo):
    page(repo, "parent", stale=True)
    page(repo, "item", moc_parent="parent", source_refs=["parent"], body="[Parent](parent.md)")
    base = commit(repo)
    page(repo, "item", moc_parent="parent", source_refs=["parent"], body="Changed [Parent](parent.md)")
    assert paths(report(repo, base)["blockers"]) == {"memories/parent.md"}


def test_factual_markdown_citation_to_parent_is_not_assumed_navigation(repo):
    page(repo, "parent", stale=True)
    path = page(repo, "item", moc_parent="parent", body="The baseline follows [parent](parent.md).")
    base = commit(repo)
    path.write_text(path.read_text() + "Updated conclusion.")
    assert paths(report(repo, base)["blockers"]) == {"memories/parent.md"}


def test_duplicate_ids_block_cleanly_and_base_duplicates_can_be_repaired(repo):
    first = page(repo, "first", stale=True)
    second = page(repo, "second")
    second.write_text(second.read_text().replace("page_id: second", "page_id: first"))
    page(repo, "item", source_refs=["first"])
    base = commit(repo)
    duplicate = report(repo, base)
    assert duplicate["relation_errors"] and not duplicate["ok"]
    second.write_text(second.read_text().replace("page_id: first", "page_id: second"))
    repaired = report(repo, base)
    assert not repaired["relation_errors"]
    assert repaired["base_relation_diagnostics"]
    assert "memories/first.md" in paths(repaired["blockers"])


def test_removed_untyped_reference_keeps_all_ambiguous_historical_targets(repo):
    a = page(repo, "a")
    z = page(repo, "z", stale=True)
    for path in (a, z):
        path.write_text(path.read_text().replace(f"page_id: {path.stem}", "page_id: same"))
    page(repo, "item", claims=["same"])
    base = commit(repo)
    a.write_text(a.read_text().replace("page_id: same", "page_id: a"))
    page(repo, "item")
    result = report(repo, base)
    assert not result["relation_errors"]
    assert paths(result["blockers"]) == {"memories/z.md"}
    assert result["blockers"][0]["chain"][0]["origin"] == "base"


def test_removing_or_retargeting_link_does_not_shed_old_dependency(repo):
    page(repo, "old", stale=True)
    page(repo, "new")
    page(repo, "item", body="[Citation](old.md)")
    base = commit(repo)
    page(repo, "item", body="[Citation](new.md)")
    result = report(repo, base)
    assert paths(result["included"]) == {"memories/old.md", "memories/new.md", "memories/item.md"}
    assert result["blockers"][0]["chain"][0]["origin"] == "base"


def test_deleted_or_renamed_page_keeps_dependents(repo):
    old = page(repo, "old")
    page(repo, "dependent", stale=True, source_refs=["old"])
    base = commit(repo)
    old.rename(repo / "memories" / "renamed.md")
    result = report(repo, base)
    assert "memories/old.md" in result["seeds"]
    assert "memories/renamed.md" in result["seeds"]
    assert paths(result["blockers"]) == {"memories/dependent.md"}
    assert next(r for r in result["included"] if r["path"].endswith("old.md"))["state"] == "removed"


def test_metadata_only_and_untracked_pages_are_seeds(repo):
    path = page(repo, "old")
    base = commit(repo)
    path.write_text(path.read_text().replace("2026-10-18", "2026-10-17"))
    page(repo, "new", stale=True)
    result = report(repo, base)
    assert result["seeds"] == ["memories/new.md", "memories/old.md"]
    assert result["untracked_paths"] == ["memories/new.md"]
    assert paths(result["blockers"]) == {"memories/new.md"}


def test_unknown_freshness_and_invalid_unrelated_relation_fail(repo):
    page(repo, "task")
    page(repo, "other", source_refs=["nonexistent"])
    base = commit(repo)
    path = page(repo, "task")
    path.write_text(path.read_text().replace("2026-10-18", "invalid"))
    result = report(repo, base)
    assert result["blockers"][0]["state"] == "unknown"
    assert result["relation_errors"] and not result["ok"]


def test_no_changes_reports_global_debt_without_global_budget(repo):
    page(repo, "old", stale=True)
    base = commit(repo)
    result = report(repo, base)
    assert result["ok"] and result["seeds"] == []
    assert paths(result["unrelated_debt"]) == {"memories/old.md"}


def test_missing_base_fails_closed(repo):
    page(repo, "item")
    commit(repo)
    with pytest.raises(ValueError, match="requires"):
        report(repo, "")
    with pytest.raises(GitCommandError):
        report(repo, "missing-ref")


def test_concurrent_edit_fails_closed(repo, monkeypatch):
    import wiki_core.freshness_impact as module
    path = page(repo, "item")
    base = commit(repo)
    original = module.authored_graph
    def changing(root, config):
        result = original(root, config)
        if root == repo:
            path.write_text(path.read_text() + "Concurrent change.")
        return result
    monkeypatch.setattr(module, "authored_graph", changing)
    with pytest.raises(ValueError, match="inputs changed"):
        report(repo, base)


def test_dialogue_multiline_is_not_a_dependency_or_top_level_field(repo):
    page(repo, "task", action_dialogue=[dict(kind="answer", text="Answer\nsource_refs: [missing]\nupdated_at: invalid")])
    base = commit(repo)
    path = repo / "memories/task.md"
    path.write_text(path.read_text() + "Changed body.")
    result = report(repo, base)
    assert result["ok"] and not result["relation_errors"]
    assert paths(result["included"]) == {"memories/task.md"}


def test_audit_writes_evidence_and_keeps_registry_global_checks(repo, monkeypatch):
    page(repo, "old", stale=True)
    base = commit(repo)
    monkeypatch.setattr(audit, "ROOT", repo)
    out = repo / "report.json"
    errors, warnings = [], []
    audit.audit_freshness_budget(errors, warnings, load_config(repo), base_ref=base, report_path=out)
    assert errors == []
    assert "outside freshness impact" in warnings[0]
    assert json.loads(out.read_text())["base_sha"] == base
    audit.audit_freshness_budget(errors, warnings, load_config(repo), base_ref=base, report_path=out)
    assert "evidence unavailable" in errors[0]  # cannot clobber any existing file
    assert {"secrets", "pii", "relations", "page_type_registry"} <= set(audit.CHECK_NAMES)


def test_audit_enriches_existing_stale_warning_without_hiding_other_debt(repo, monkeypatch):
    old = page(repo, "old", stale=True)
    page(repo, "unknown")
    unknown = repo / "memories/unknown.md"
    unknown.write_text(unknown.read_text().replace("2026-10-18", "invalid"))
    base = commit(repo)
    before = old.read_bytes()
    monkeypatch.setattr(audit, "ROOT", repo)
    errors = []
    warnings = ["memories/old.md: stale page", "memories/old.md: unrelated diagnostic"]
    audit.audit_freshness_budget(errors, warnings, load_config(repo), base_ref=base)
    assert errors == []
    assert warnings == [
        "memories/old.md: stale outside freshness impact (reported, nonblocking)",
        "memories/old.md: unrelated diagnostic",
        "memories/unknown.md: unknown outside freshness impact (reported, nonblocking)",
    ]
    assert old.read_bytes() == before
    # The same old page still blocks when a factual edit brings it into scope.
    old.write_text(old.read_text() + "Changed factual evidence.\n")
    audit.audit_freshness_budget(errors, [], load_config(repo), base_ref=base)
    assert any("memories/old.md: stale in freshness impact" in error for error in errors)


def test_catalogue_associations_do_not_couple_independent_contexts(repo):
    page(repo, "catalogue", related_pages=["books", "tax"],
         body="## Related\n- [Books](books.md)\n- [Tax](tax.md)\n")
    page(repo, "books", related_pages=["catalogue"],
         body="## Related\n- [Catalogue](catalogue.md)\n")
    page(repo, "tax", stale=True, related_pages=["catalogue"])
    base = commit(repo)
    with (repo / "memories/books.md").open("a") as stream:
        stream.write("\nChanged direction.\n")
    result = report(repo, base)
    assert result["ok"]
    assert paths(result["included"]) == {"memories/books.md"}
    assert paths(result["unrelated_debt"]) == {"memories/tax.md"}
    excluded = result["nonpropagating_relations"]
    assert any(e["type"] == "navigation_link" and e["body_line"] == 2 for e in excluded)


def test_factual_dependency_through_same_catalogue_still_blocks(repo):
    page(repo, "catalogue", source_refs=["tax"], related_pages=["books", "tax"],
         body="## Related\n- [Books](books.md)\n- [Tax](tax.md)\n")
    path = page(repo, "books", source_refs=["catalogue"])
    page(repo, "tax", stale=True)
    base = commit(repo)
    path.write_text(path.read_text() + "Changed conclusion.")
    assert paths(report(repo, base)["blockers"]) == {"memories/tax.md"}


@pytest.mark.parametrize("body", [
    "## Related\n- [Parent](parent.md)\n\n## Evidence\nBased on [parent](parent.md).\n",
    "## Related\n- [Parent](parent.md)\n  establishes the baseline.\n",
    "## Related\n### Sources\n- [Parent](parent.md)\n",
    "## Related\n- [Parent](parent.md)\n  - [Parent](parent.md)\n",
    "```md\n## Related\n```\n- [Parent](parent.md)\n",
    "## Related\n- [Parent](parent.md)\nestablishes the factual baseline.\n",
    "## Related\nSources\n-------\n- [Parent](parent.md)\n",
    "## Related\n  ### Sources\n- [Parent](parent.md)\n",
    "## Sources\n- Supporting evidence:\n  ## Related\n- [Parent](parent.md)\n",
    "Sources and\nRelated\n-------\n- [Parent](parent.md)\n",
])
def test_navigation_does_not_hide_factual_or_uncertain_occurrences(repo, body):
    page(repo, "parent", stale=True)
    path = page(repo, "item", related_pages=["parent"], body=body)
    base = commit(repo)
    path.write_text(path.read_text() + "\nChanged.\n")
    result = report(repo, base)
    assert paths(result["blockers"]) == {"memories/parent.md"}
    assert result["blockers"][0]["chain"][0]["type"] == "markdown_link"


def test_navigation_requires_local_typed_declaration(repo):
    page(repo, "parent", stale=True)
    path = page(repo, "item", body="## Related\n- [Parent](parent.md)\n")
    base = commit(repo)
    path.write_text(path.read_text() + "\nChanged.\n")
    assert paths(report(repo, base)["blockers"]) == {"memories/parent.md"}


def test_moving_factual_link_to_navigation_preserves_base_dependency(repo):
    page(repo, "parent", stale=True)
    page(repo, "item", related_pages=["parent"], body="Based on [parent](parent.md).")
    base = commit(repo)
    page(repo, "item", related_pages=["parent"], body="## Related\n- [Parent](parent.md)\n")
    result = report(repo, base)
    assert paths(result["blockers"]) == {"memories/parent.md"}
    assert result["blockers"][0]["chain"][0]["origin"] == "base"


def test_transaction_snapshot_preserves_wip_as_context_not_as_changed_seed(repo, tmp_path):
    import shutil
    from wiki_core.freshness_impact import input_hashes

    page(repo, "unrelated", stale=True)
    page(repo, "source", stale=True)
    page(repo, "proposal", source_refs=["source"])
    commit(repo)
    for name in ("unrelated", "source"):
        path = repo / f"memories/{name}.md"
        path.write_text(path.read_text() + "Existing independent WIP.\n")
    baseline_hashes = input_hashes(repo, load_config(repo))
    baseline_graph = authored_graph(repo, load_config(repo))
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    for name in baseline_hashes:
        destination = candidate / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repo / name, destination)
    path = candidate / "memories/proposal.md"
    path.write_text(path.read_text() + "Only this proposal is submitted.\n")
    candidate_hashes = input_hashes(candidate, load_config(candidate))
    changed = {p for p in baseline_hashes.keys() | candidate_hashes.keys()
               if baseline_hashes.get(p) != candidate_hashes.get(p)}
    result = evaluate_impact(authored_graph(candidate, load_config(candidate)), baseline_graph,
                             changed, today=TODAY)
    assert result["seeds"] == ["memories/proposal.md"]
    assert paths(result["blockers"]) == {"memories/source.md"}
    assert paths(result["unrelated_debt"]) == {"memories/unrelated.md"}
    assert input_hashes(repo, load_config(repo)) == baseline_hashes


def test_holon_context_association_is_not_factual_dependency(repo):
    page(repo, "context", stale=True)
    path = page(repo, "item", related_holons=["context"],
                body="## Related\n- [Context](context.md)\n")
    base = commit(repo)
    path.write_text(path.read_text() + "\nUpdated direction.\n")
    result = report(repo, base)
    assert result["ok"]
    assert paths(result["included"]) == {"memories/item.md"}
    assert paths(result["unrelated_debt"]) == {"memories/context.md"}
    assert any(e["type"] == "related_holon" and e["field"] == "related_holons"
               for e in result["nonpropagating_relations"])


@pytest.mark.parametrize("fields,body", [
    ({"source_refs": ["context"]}, "## Related\n- [Context](context.md)\n"),
    ({"evidence_refs": ["context"]}, "## Related\n- [Context](context.md)\n"),
    ({}, "According to [context](context.md), the requirement applies.\n"),
])
def test_holon_association_never_suppresses_factual_support(repo, fields, body):
    page(repo, "source", stale=True)
    page(repo, "context", source_refs=["source"])
    path = page(repo, "item", related_holons=["context"], body=body, **fields)
    base = commit(repo)
    path.write_text(path.read_text() + "\nUpdated conclusion.\n")
    result = report(repo, base)
    assert paths(result["blockers"]) == {"memories/source.md"}
    assert any(r["type"] == "related_holon" for r in result["nonpropagating_relations"])


@pytest.mark.parametrize("label", ["MOC", "Parent MOC", "MOC pai"])
def test_explicit_body_moc_declaration_is_structural_without_frontmatter_duplicate(repo, label):
    page(repo, "catalogue", stale=True)
    path = page(repo, "item", body=f"## Related\n- {label}: [Catalogue](catalogue.md)\n")
    base = commit(repo)
    path.write_text(path.read_text() + "\nChanged.\n")
    result = report(repo, base)
    assert result["ok"]
    assert paths(result["included"]) == {"memories/item.md"}
    assert any(e.get("classification") == "explicit_body_moc_navigation"
               for e in result["nonpropagating_relations"])


@pytest.mark.parametrize("body", [
    "## Related\n- Evidence: [Catalogue](catalogue.md)\n",
    "## Related\n- MOC: [Catalogue](catalogue.md) establishes the baseline.\n",
    "## Related\n- MOC: [Catalogue](catalogue.md)\n  establishes the baseline.\n",
    "## Related\n- MOC: [Catalogue](catalogue.md)\nestablishes the baseline.\n",
    "## Sources\n- MOC: [Catalogue](catalogue.md)\n",
    "## Related\n- MOC: [Catalogue](catalogue.md)\n\n## Evidence\nBased on [catalogue](catalogue.md).\n",
])
def test_body_labels_never_hide_evidence_or_factual_continuations(repo, body):
    page(repo, "catalogue", stale=True)
    path = page(repo, "item", body=body)
    base = commit(repo)
    path.write_text(path.read_text() + "\nChanged.\n")
    assert paths(report(repo, base)["blockers"]) == {"memories/catalogue.md"}


@pytest.mark.parametrize("body", [
    "## Related\n- MOC evidence: [Catalogue](catalogue.md)\n",
    "## Related\n- Responsibility: [Catalogue](catalogue.md)\n",
    "## Related\n- Evidence:\n  - MOC: [Catalogue](catalogue.md)\n",
    "## Related\n- MOC: [Catalogue](catalogue.md)\n  - [Catalogue](catalogue.md)\n",
])
def test_nearby_labels_and_nested_moc_items_are_conservative(repo, body):
    page(repo, "catalogue", stale=True)
    path = page(repo, "item", body=body)
    base = commit(repo)
    path.write_text(path.read_text() + "\nChanged.\n")
    assert paths(report(repo, base)["blockers"]) == {"memories/catalogue.md"}


def test_moving_citation_to_moc_declaration_preserves_historical_dependency(repo):
    page(repo, "catalogue", stale=True)
    page(repo, "item", body="Based on [catalogue](catalogue.md).")
    base = commit(repo)
    page(repo, "item", body="## Related\n- MOC: [Catalogue](catalogue.md)\n")
    result = report(repo, base)
    assert paths(result["blockers"]) == {"memories/catalogue.md"}
    assert result["blockers"][0]["chain"][0]["origin"] == "base"
    assert any(e.get("body_relation_label") == "MOC:" for e in result["nonpropagating_relations"])


def test_documentary_review_suppresses_only_seed_never_required_evidence(repo):
    source = page(repo, 'source', stale=True)
    consumer = page(repo, 'consumer', source_refs=['source'])
    base = commit(repo)
    source.write_text(source.read_text() + '\nTypographical clarification.\n')
    cfg = load_config(repo)
    declaration = {'memories/source.md': 'Only spelling changed; original verification date retained.'}
    result = repository_report(repo, cfg, base, today=TODAY, documentary_only=declaration)
    assert result['ok'] and not result['seeds']
    assert 'memories/source.md' in paths(result['unrelated_debt'])
    consumer.write_text(consumer.read_text() + '\nA new factual conclusion.\n')
    result = repository_report(repo, cfg, base, today=TODAY, documentary_only=declaration)
    assert not result['ok']
    assert 'memories/source.md' in paths(result['blockers'])


@pytest.mark.parametrize('declaration', [
    {'memories/unchanged.md': 'No changed bytes'}, {'memories/source.md': ''},
    {'../source.md': 'Outside repository'}, {'memories/*.md': 'No blanket exemptions'},
])
def test_documentary_review_refuses_unbounded_or_unexplained_classification(repo, declaration):
    source = page(repo, 'source')
    page(repo, 'unchanged')
    base = commit(repo)
    source.write_text(source.read_text() + '\nEdited.\n')
    with pytest.raises(ValueError, match='documentary-only'):
        repository_report(repo, load_config(repo), base, today=TODAY, documentary_only=declaration)


def test_documentary_edit_cannot_renew_source_date(repo):
    source = page(repo, 'source', stale=True)
    base = commit(repo)
    source.write_text(source.read_text().replace('2026-01-01', '2026-10-18'))
    with pytest.raises(ValueError, match='cannot renew'):
        repository_report(repo, load_config(repo), base, today=TODAY,
                          documentary_only={'memories/source.md': 'Claimed formatting only'})


@pytest.mark.parametrize('exempt', [False, True])
def test_future_verification_is_unknown_even_when_evergreen(exempt):
    from wiki_core.freshness import freshness_state
    assert freshness_state('2099-01-01', 30, TODAY, stale_exempt=exempt) == 'unknown'


@pytest.mark.parametrize('operation', ['edit', 'delete', 'delete_and_unlink'])
def test_tracked_nonmemory_evidence_changes_reach_stale_consumers(repo, operation):
    artifact = repo / 'evidence.txt'
    artifact.write_text('Original captured evidence.\n')
    consumer = page(repo, 'consumer', stale=True, body='Claim based on [evidence](../evidence.txt).')
    base = commit(repo)
    if operation == 'edit':
        artifact.write_text('Changed captured evidence.\n')
    else:
        artifact.unlink()
        if operation == 'delete_and_unlink':
            consumer.write_text(consumer.read_text().replace('[evidence](../evidence.txt)', 'the former capture'))
    result = report(repo, base)
    assert not result['ok']
    assert 'evidence.txt' in result['seeds']
    assert 'memories/consumer.md' in paths(result['blockers'])
    if operation != 'edit':
        assert 'evidence.txt' in paths(result['blockers'])


def test_nonmemory_evidence_symlink_cannot_read_outside_root(repo, tmp_path):
    evidence = repo / 'evidence.txt'
    evidence.write_text('Original capture.')
    page(repo, 'consumer', body='[Evidence](../evidence.txt)')
    base = commit(repo)
    evidence.unlink()
    evidence.symlink_to('/etc/passwd')
    with pytest.raises(ValueError):
        report(repo, base)


def test_unicode_source_filename_is_not_lost_in_git_quoting(repo):
    artifact = repo / 'evidência técnica.txt'
    artifact.write_text('Original capture.')
    page(repo, 'consumer', stale=True, body='[Evidence](../evidência%20técnica.txt)')
    base = commit(repo)
    artifact.write_text('Changed capture.')
    result = report(repo, base)
    assert artifact.name in result['seeds']
    assert artifact.name in result['input_sha256']
    assert 'memories/consumer.md' in paths(result['blockers'])


def test_reviewed_technical_input_suppresses_only_its_seed(repo):
    tool = repo / 'tool.py'
    tool.write_text('print("old")\n')
    manual = page(repo, 'manual', body='Tool [implementation](../tool.py); [source](source.md).')
    page(repo, 'source', stale=True)
    base = commit(repo)
    tool.write_text('print("new implementation")\n')
    assert 'memories/source.md' in paths(report(repo, base)['blockers'])
    reason = {'tool.py': 'Implementation refactor; downstream asserted facts unchanged, reviewed and tested.'}
    result = repository_report(repo, load_config(repo), base, today=TODAY, documentary_only=reason)
    assert result['seeds'] == []
    manual.write_text(manual.read_text() + '\nA new factual assertion.\n')
    result = repository_report(repo, load_config(repo), base, today=TODAY, documentary_only=reason)
    assert 'tool.py' in paths(result['included'])
    assert 'memories/source.md' in paths(result['blockers'])


def test_retired_input_review_requires_no_surviving_citation_and_keeps_old_edges(repo):
    tool = repo / 'old-tool.py'
    tool.write_text('print("historical implementation")\n')
    manual = page(repo, 'manual', body='[Tool](../old-tool.py); [source](source.md).')
    source = page(repo, 'source', stale=True)
    base = commit(repo)
    tool.unlink()
    reason = {'old-tool.py': 'Retired implementation retained at the approved Git revision.'}
    with pytest.raises(ValueError, match='changed existing paths'):
        repository_report(repo, load_config(repo), base, today=TODAY, documentary_only=reason)
    manual.write_text(manual.read_text().replace('[Tool](../old-tool.py)', 'Retired tool; see approved Git history'))
    reason['memories/manual.md'] = 'Replace retired implementation link, no source fact changed.'
    result = repository_report(repo, load_config(repo), base, today=TODAY, documentary_only=reason)
    assert result['seeds'] == []
    source.write_text(source.read_text() + '\nChanged evidence.\n')
    result = repository_report(repo, load_config(repo), base, today=TODAY, documentary_only=reason)
    assert 'old-tool.py' in paths(result['blockers'])
    assert next(r for r in result['included'] if r['path'] == 'old-tool.py')['state'] == 'unknown'


def test_documentary_input_review_refuses_new_unreferenced_or_deleted_memory(repo):
    memory = page(repo, 'manual')
    existing = repo / 'unreferenced.txt'
    existing.write_text('Original')
    base = commit(repo)
    existing.write_text('Changed')
    new = repo / 'new.txt'
    new.write_text('New evidence')
    memory.write_text(memory.read_text() + '\n[New](../new.txt)')
    git(repo, 'add', 'new.txt')
    for path in ('new.txt', 'unreferenced.txt'):
        with pytest.raises(ValueError, match='documentary-only'):
            repository_report(repo, load_config(repo), base, today=TODAY, documentary_only={path: 'Reason'})
    memory.unlink()
    with pytest.raises(ValueError, match='documentary-only'):
        repository_report(repo, load_config(repo), base, today=TODAY, documentary_only={'memories/manual.md': 'Deleted'})


def reviewed_fixture(repo):
    page(repo, 'archive', stale=True, body='Observation at the recorded date.')
    base = commit(repo)
    page(repo, 'review', body='Reviewed [archive](archive.md): the dated observation stands; no current claim.')
    review = {'memories/archive.md': {
        'disposition': 'historical', 'evidence': 'memories/review.md',
        'rationale': 'Dated observation checked against its original evidence.',
        'limits': 'Does not establish current provider state.',
    }}
    return base, review


def test_review_disposes_age_without_changing_dates_graph_or_other_debt(repo):
    base, review = reviewed_fixture(repo)
    cfg = load_config(repo)
    before = repository_report(repo, cfg, base, today=TODAY)
    after = repository_report(repo, cfg, base, today=TODAY, freshness_reviews=review)
    assert after['ok'] and not before['ok']
    assert after['included'] == before['included']
    assert after['input_sha256'] == before['input_sha256']
    assert after['reviewed_findings'][0]['state'] == 'stale'
    assert after['reviewed_findings'][0]['chain'] == before['blockers'][0]['chain']
    # A new proposal cannot inherit the previous review implicitly.
    merged = commit(repo)
    page(repo, 'new-change', body='Uses [archive](archive.md).')
    assert 'memories/archive.md' in paths(repository_report(repo, cfg, merged, today=TODAY)['blockers'])


@pytest.mark.parametrize('disposition', ['historical', 'verified_local', 'verified_live', 'known_gap'])
def test_review_never_removes_unreviewed_prerequisite_or_relation_error(repo, disposition):
    page(repo, 'source', stale=True)
    page(repo, 'archive', stale=True, source_refs=['source'])
    base = commit(repo)
    page(repo, 'review', body='Review of [archive](archive.md).')
    review = {'memories/archive.md': dict(disposition=disposition, evidence='memories/review.md',
        rationale='Explicit scoped review.', limits='Source gap stays unresolved.')}
    result = repository_report(repo, load_config(repo), base, today=TODAY, freshness_reviews=review)
    assert not result['ok']
    assert 'memories/source.md' in paths(result['blockers'])
    assert 'memories/source.md' in paths(result['included'])
    page(repo, 'broken', source_refs=['no-such-page'])
    result = repository_report(repo, load_config(repo), base, today=TODAY, freshness_reviews=review)
    assert result['relation_errors'] and not result['ok']


@pytest.mark.parametrize('mutation', ['future', 'missing_date', 'cadence', 'renewal', 'exemption',
                                     'no_citation', 'stale_evidence', 'unknown_kind', 'no_limits', 'outside'])
def test_invalid_reviews_fail_closed(repo, mutation):
    base, review = reviewed_fixture(repo)
    archive = repo / 'memories/archive.md'
    evidence = repo / 'memories/review.md'
    r = review['memories/archive.md']
    if mutation == 'future':
        archive.write_text(archive.read_text().replace('2026-01-01', '2099-01-01'))
    elif mutation == 'missing_date':
        archive.write_text(archive.read_text().replace("updated_at: '2026-01-01'", 'updated_at: invalid'))
    elif mutation == 'cadence':
        archive.write_text(archive.read_text().replace('stale_after_days: 30', 'stale_after_days: 31'))
    elif mutation == 'renewal':
        archive.write_text(archive.read_text().replace('2026-01-01', '2026-01-02'))
    elif mutation == 'exemption':
        archive.write_text(archive.read_text().replace('stale_after_days: 30', 'stale_after_days: 30\nstale_exempt: true'))
    elif mutation == 'no_citation':
        evidence.write_text(evidence.read_text().replace('[archive](archive.md)', 'archive'))
    elif mutation == 'stale_evidence':
        evidence.write_text(evidence.read_text().replace('2026-10-18', '2026-01-01'))
    elif mutation == 'unknown_kind':
        r['disposition'] = 'ignore'
    elif mutation == 'no_limits':
        r['limits'] = ''
    elif mutation == 'outside':
        review['memories/no-such-page.md'] = review.pop('memories/archive.md')
    with pytest.raises(ValueError, match='freshness review'):
        repository_report(repo, load_config(repo), base, today=TODAY, freshness_reviews=review)


def test_review_requires_evidence_changed_in_this_proposal(repo):
    base, review = reviewed_fixture(repo)
    base = commit(repo)
    page(repo, 'other', body='Uses [archive](archive.md).')
    with pytest.raises(ValueError, match='fresh changed evidence'):
        repository_report(repo, load_config(repo), base, today=TODAY, freshness_reviews=review)


def test_review_preserves_one_age_warning_and_global_rejects_option(repo, monkeypatch):
    base, review = reviewed_fixture(repo)
    monkeypatch.setattr(audit, 'ROOT', repo)
    cfg = load_config(repo)
    errors, warnings = [], ['memories/archive.md: stale page']
    audit.audit_freshness_budget(errors, warnings, cfg, base_ref=base, freshness_reviews=review)
    assert not errors and len(warnings) == 1
    assert 'stale; reviewed historical' in warnings[0]
    cfg.audit['freshness_scope'] = 'global'
    audit.audit_freshness_budget(errors, warnings, cfg, freshness_reviews=review)
    assert any('require audit.freshness_scope: impact' in e for e in errors)


def test_documentary_only_delta_cannot_supply_freshness_review(repo):
    base, review = reviewed_fixture(repo)
    base = commit(repo)
    evidence = repo / 'memories/review.md'
    evidence.write_text(evidence.read_text() + '\nClarify typography only.\n')
    page(repo, 'change', body='Uses [archive](archive.md).')
    with pytest.raises(ValueError, match='fresh changed evidence'):
        repository_report(repo, load_config(repo), base, today=TODAY,
            freshness_reviews=review,
            documentary_only={'memories/review.md': 'Typography clarification; no new factual review.'})


def test_operational_comment_cannot_supply_freshness_review(repo):
    from tests.test_action_transition import _write_action
    from tests.test_operational_comment_freshness import comment
    page(repo, 'archive', stale=True)
    action = _write_action(repo, extra={'updated_at': '2026-10-18', 'source_refs': ['archive']})
    base = commit(repo)
    comment(repo, action)
    page(repo, 'change', body='Uses [archive](archive.md).')
    review = {'memories/archive.md': dict(disposition='historical',
        evidence=action.relative_to(repo).as_posix(), rationale='Dated record.', limits='No current claim.')}
    with pytest.raises(ValueError, match='fresh changed evidence'):
        repository_report(repo, load_config(repo), base, today=TODAY, freshness_reviews=review)
