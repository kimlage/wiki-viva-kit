"""Synthetic Git-backed proofs of scoped freshness; no consumer/private fixtures."""
from __future__ import annotations

import datetime as dt
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


@pytest.mark.parametrize("field,kind", [("moc_parent", "project"), ("owner_ref", "action"), ("collection_refs", "project")])
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
