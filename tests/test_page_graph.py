from __future__ import annotations

from pathlib import Path

from wiki_core.config import WikiConfig
from wiki_core.graph import (
    PAGE_GRAPH_SCHEMA_VERSION,
    build_page_graph,
    compute_impact,
    graph_to_dict,
    orphan_pages,
    unreachable_pages,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _page(page_id: str, page_type: str, title: str, body: str, extra: str = "") -> str:
    return f"""---
page_id: {page_id}
page_type: {page_type}
title: "{title}"
context: system
visibility: private_self
updated_at: 2026-06-11
stale_after_days: 30
sources_policy: test
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
{extra}---

# {title}

{body}
"""


def test_page_graph_builds_links_aliases_and_wanted_pages(tmp_path: Path) -> None:
    _write(
        tmp_path / "memories/index.md",
        _page("root", "root_index", "Root", "- [Project](projects/x.md)\n- [Summary](projects/summary.md)\n"),
    )
    _write(
        tmp_path / "memories/projects/x.md",
        _page(
            "project-x",
            "project",
            "Project X",
            "- Related: [Decision](../decisions/d.md)\n- Missing: [Wanted](../claims/wanted.md)\n",
            extra="aliases:\n  - X\nrelated_pages:\n  - decision-d\n",
        ),
    )
    _write(
        tmp_path / "memories/decisions/d.md",
        _page("decision-d", "decision", "Decision D", "- Back to [root](../index.md)\n"),
    )

    graph = build_page_graph(tmp_path, WikiConfig())

    project = graph.nodes["memories/projects/x.md"]
    assert "memories/decisions/d.md" in project.outbound_body_links
    assert "memories/decisions/d.md" in project.outbound_frontmatter_refs
    assert graph.nodes["memories/decisions/d.md"].inbound_links == ("memories/projects/x.md",)
    assert graph.aliases["project x"] == "memories/projects/x.md"
    assert graph.aliases["x"] == "memories/projects/x.md"
    assert graph.wanted_pages["memories/claims/wanted.md"] == ("memories/projects/x.md",)

    data = graph_to_dict(graph)
    assert data["schema_version"] == PAGE_GRAPH_SCHEMA_VERSION
    assert len(data["pages"]) == 3


def test_orphan_reachability_and_impact(tmp_path: Path) -> None:
    _write(
        tmp_path / "memories/index.md",
        _page("root", "root_index", "Root", "- [Project](projects/x.md)\n- [Summary](projects/summary.md)\n"),
    )
    _write(
        tmp_path / "memories/projects/x.md",
        _page("project-x", "project", "Project X", "- [Root](../index.md)\n"),
    )
    _write(
        tmp_path / "memories/projects/summary.md",
        _page("project-summary", "project", "Summary", "- [Project X](x.md)\n"),
    )
    _write(
        tmp_path / "memories/claims/orphan.md",
        _page("claim-orphan", "claim", "Orphan", "No inbound links.\n"),
    )

    graph = build_page_graph(tmp_path, WikiConfig())

    assert orphan_pages(graph) == ("memories/claims/orphan.md",)
    assert unreachable_pages(graph, "memories/index.md") == ("memories/claims/orphan.md",)

    impact = compute_impact(graph, {"memories/projects/x.md"})
    assert impact.changed_pages == ("memories/projects/x.md",)
    assert impact.affected_pages == ("memories/projects/summary.md",)
    assert impact.references == {"memories/projects/summary.md": ("memories/projects/x.md",)}


def test_assignments_frontmatter_field_becomes_an_edge(tmp_path: Path) -> None:
    _write(
        tmp_path / "memories/index.md",
        _page("root", "root_index", "Root", "- [Role](papeis/steward.md)\n"),
    )
    _write(
        tmp_path / "memories/papeis/steward.md",
        _page(
            "role-steward",
            "role",
            "Role Steward",
            "- [Root](../index.md)\n",
            extra="assignments:\n  - assignment-kim-steward\n",
        ),
    )
    _write(
        tmp_path / "memories/atribuicoes/kim-steward.md",
        _page("assignment-kim-steward", "assignment", "Assignment", "- [Root](../index.md)\n"),
    )

    graph = build_page_graph(tmp_path, WikiConfig())
    role = graph.nodes["memories/papeis/steward.md"]
    assert "memories/atribuicoes/kim-steward.md" in role.outbound_frontmatter_refs
    assert "memories/papeis/steward.md" in graph.nodes[
        "memories/atribuicoes/kim-steward.md"
    ].inbound_links


def test_impact_ignores_changes_to_exempt_operational_pages(tmp_path: Path) -> None:
    _write(
        tmp_path / "memories/index.md",
        _page("root", "root_index", "Root", "- [Log](system/log.md)\n"),
    )
    _write(
        tmp_path / "memories/system/log.md",
        _page("log", "system_log", "Log", "Append-only.\n"),
    )
    _write(
        tmp_path / "memories/projects/x.md",
        _page("project-x", "project", "Project X", "- [Log](../system/log.md)\n"),
    )

    graph = build_page_graph(tmp_path, WikiConfig())
    impact = compute_impact(graph, {"memories/system/log.md"})

    assert impact.changed_pages == ()
    assert impact.affected_pages == ()
