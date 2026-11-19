from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

import scripts.wiki_new as wiki_new
from wiki_core.config import load_config
from wiki_core.frontmatter import parse_frontmatter, parse_frontmatter_flat_with_errors
from wiki_core.graph.page_graph import build_page_graph


KIT_ROOT = Path(__file__).resolve().parents[1]


def _authoring_repo(tmp_path: Path, page_type: str = "source") -> Path:
    root = tmp_path / "wiki"
    (root / "docs/references/templates/wiki").mkdir(parents=True)
    shutil.copy2(KIT_ROOT / "wiki.page-types.yaml", root / "wiki.page-types.yaml")
    shutil.copy2(
        KIT_ROOT / f"docs/references/templates/wiki/{page_type}.md",
        root / f"docs/references/templates/wiki/{page_type}.md",
    )
    (root / "wiki.config.yaml").write_text(
        'repo_id: source-authoring-test\n'
        'owner_label: "Synthetic Owner"\n'
        'contexts: system\n',
        encoding="utf-8",
    )
    return root


@pytest.mark.parametrize("dry_run", [False, True])
def test_wiki_new_source_produces_contract_valid_initial_lifecycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    dry_run: bool,
) -> None:
    root = _authoring_repo(tmp_path)
    output = "memories/sources/synthetic-calendar-feed.md"
    argv = [
        "wiki_new.py",
        "--type",
        "source",
        "--title",
        "Synthetic calendar feed",
        "--context",
        "system",
        "--output",
        output,
    ]
    if dry_run:
        argv.append("--dry-run")
    monkeypatch.setattr(wiki_new, "ROOT", root)
    monkeypatch.setattr(sys, "argv", argv)

    assert wiki_new.main() == 0
    rendered = capsys.readouterr().out
    if dry_run:
        assert not (root / output).exists()
    else:
        assert rendered.strip() == output
        rendered = (root / output).read_text(encoding="utf-8")

    values, _body = parse_frontmatter(rendered)
    assert values["owner"] == "synthetic-owner"
    assert values["sync"]["last_status"] == "never"
    assert values["ingestion_state"] == "unread"
    assert values["last_ingested_at"] == ""
    assert values["source_lifecycle"] == {
        "state": "configured",
        "freshness_state": "never_synced",
        "last_attempt_state": "never",
        "pipeline_stage": "configured",
        "pipeline_stage_timestamps": {},
        "adoption_state": "pending",
        "blocked_reason": "",
        "emitted_page_ids": [],
        "emitted_action_ids": [],
        "proposal_ids": [],
        "accepted_ref": "",
        "reviewed_no_change_receipt": "",
        "secret_safe_log_refs": [],
    }


@pytest.mark.parametrize("dry_run", [False, True])
def test_wiki_new_meeting_accepts_template_inline_list_comments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    dry_run: bool,
) -> None:
    root = _authoring_repo(tmp_path, "meeting")
    output = "memories/meetings/synthetic-planning.md"
    argv = [
        "wiki_new.py",
        "--type", "meeting",
        "--title", "Synthetic planning #1",
        "--context", "system",
        "--output", output,
    ]
    if dry_run:
        argv.append("--dry-run")
    monkeypatch.setattr(wiki_new, "ROOT", root)
    monkeypatch.setattr(sys, "argv", argv)

    assert wiki_new.main() == 0
    rendered = capsys.readouterr().out
    if dry_run:
        assert not (root / output).exists()
    else:
        assert rendered.strip() == output
        rendered = (root / output).read_text(encoding="utf-8")

    flat, errors = parse_frontmatter_flat_with_errors(rendered)
    structured, _body = parse_frontmatter(rendered)
    assert errors == []
    assert flat["title"] == structured["title"] == "Synthetic planning #1"
    assert flat["page_type"] == "meeting"
    for field in ("participants", "source_refs", "decisions", "actions"):
        assert flat[field] == structured[field] == []
    assert flat["stale_after_days"] == str(structured["stale_after_days"])


@pytest.fixture
def initiative_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = _authoring_repo(tmp_path, "initiative")
    with (root / "wiki.page-types.yaml").open("a", encoding="utf-8") as registry:
        registry.write(
            "\n  initiative:\n"
            "    template: docs/references/templates/wiki/initiative.md\n"
            "    allowed_dirs: [memories/initiatives]\n"
            "    required_frontmatter: *relation_required\n"
            "    field_types: *relation_field_types\n"
        )
    parent = root / "memories/projects/{{title}} parent #1.md"
    parent.parent.mkdir(parents=True)
    parent.write_text("---\npage_id: project-synthetic\n---\n# Synthetic parent\n", encoding="utf-8")
    (root / "outside.md").write_text("---\npage_id: outside-synthetic\n---\n# Outside memory\n", encoding="utf-8")
    monkeypatch.setattr(wiki_new, "ROOT", root)
    return root


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("parent", ["project-synthetic", "memories/projects/{{title}} parent #1.md"])
def test_wiki_new_initiative_accepts_a_relation_parent(
    initiative_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    dry_run: bool,
    parent: str,
) -> None:
    output = initiative_repo / "memories/initiatives/synthetic-example.md"
    argv = ["wiki_new.py", "--type", "initiative", "--title", "Synthetic example",
            "--context", "system", "--moc-parent", parent]
    if dry_run:
        argv.append("--dry-run")
    monkeypatch.setattr(sys, "argv", argv)

    assert wiki_new.main() == 0
    if dry_run:
        rendered = capsys.readouterr().out
        assert not output.exists()
    else:
        rendered = output.read_text(encoding="utf-8")
        graph = build_page_graph(initiative_repo, load_config(initiative_repo))
        node = graph.nodes[output.relative_to(initiative_repo).as_posix()]
        assert node.outbound_frontmatter_refs == ("memories/projects/{{title}} parent #1.md",)
    flat, errors = parse_frontmatter_flat_with_errors(rendered)
    structured, _body = parse_frontmatter(rendered)
    assert errors == []
    assert flat["moc_parent"] == structured["moc_parent"] == parent
    assert flat["page_type"] == structured["page_type"] == "initiative"


@pytest.mark.parametrize("parent", [
    None,
    "  ",
    "project-synthetic\nvisibility: public",
    "no-such-page",
    "../../../etc/hosts",
    "/etc/hosts",
    "memories/projects/missing.md",
    "outside.md",
    "outside-synthetic",
    r"C:\synthetic\parent.md",
])
def test_wiki_new_initiative_refuses_an_invalid_relation_parent(
    initiative_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    parent: str | None,
) -> None:
    argv = ["wiki_new.py", "--type", "initiative", "--title", "Synthetic example", "--context", "system"]
    if parent is not None:
        argv.extend(["--moc-parent", parent])
    monkeypatch.setattr(sys, "argv", argv)

    status = wiki_new.main()
    assert (status, (initiative_repo / "memories/initiatives/synthetic-example.md").exists()) == (2, False)
    report = capsys.readouterr()
    assert "moc_parent" in report.err
    assert not (initiative_repo / "memories/initiatives").exists()
