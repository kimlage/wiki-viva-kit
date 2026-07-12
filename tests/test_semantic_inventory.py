"""Independent authored-vs-read-model semantic inventory contract."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from wiki_core.config import WikiConfig
from wiki_core.semantic_inventory import (
    build_semantic_inventory,
    load_snapshot_payloads,
    render_markdown,
)
from wiki_core.web.snapshot import build_snapshot


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _page(
    page_id: str,
    page_type: str,
    title: str,
    *,
    extra: str = "",
) -> str:
    return (
        "---\n"
        f"page_id: {page_id}\n"
        f"page_type: {page_type}\n"
        f"title: {title}\n"
        "context: example\n"
        "visibility: private_self\n"
        "updated_at: 2026-07-11\n"
        "stale_after_days: 30\n"
        f"{extra}"
        "---\n\n"
        f"# {title}\n"
    )


def _fixture(tmp_path: Path) -> tuple[WikiConfig, dict[str, dict[str, object]]]:
    config = WikiConfig(
        repo_id="semantic-secret-repo",
        contexts=("example",),
        default_context="example",
        root_entity={"page": "memories/index.md"},
    )
    _write(
        tmp_path / "memories/index.md",
        _page("root-secret", "root_index", "Private root"),
    )
    _write(
        tmp_path / "memories/sources/source.md",
        _page(
            "source-secret",
            "source",
            "Private source",
            extra="moc_parent: root-secret\n",
        ),
    )
    _write(
        tmp_path / "memories/example/note.md",
        _page(
            "note-secret",
            "context_note",
            "Private note",
            extra=(
                "moc_parent: root-secret\n"
                "source_refs:\n"
                "- memories/sources/source.md\n"
            ),
        ),
    )
    _write(
        tmp_path / "memories/system/ingestion/events/event.md",
        _page(
            "event-secret",
            "ingestion_event",
            "Private event",
            extra=(
                "event_id: evt-secret\n"
                "moc_parent: source-secret\n"
                "source_refs:\n"
                "- memories/sources/source.md\n"
                "consolidated_into:\n"
                "- note-secret\n"
                "captured_at: 2026-07-10\n"
            ),
        )
        + "\n## Source\n\n- Synthetic source.\n\n"
        "## Quadrants\n\n- Synthetic quadrants.\n",
    )
    snapshot = build_snapshot(
        tmp_path,
        config,
        generated_at="2026-07-11T12:00:00Z",
    )
    return config, snapshot


def test_semantic_inventory_valid_case_matches_all_surfaces_and_relations(
    tmp_path: Path,
) -> None:
    config, snapshot = _fixture(tmp_path)

    report = build_semantic_inventory(tmp_path, config, snapshot)

    assert report["schema_version"] == "wiki_semantic_inventory.v1"
    assert report["status"] == "pass"
    assert report["summary"] == {
        "error_count": 0,
        "event_error_count": 0,
        "relation_error_count": 0,
    }
    assert report["events"]["authored"]["count"] == 1
    assert report["events"]["authored_closed"]["count"] == 1
    assert {
        name: summary["count"]
        for name, summary in report["events"]["surfaces"].items()
    } == {"closure": 1, "closure_closed": 1, "temporal": 1, "graph": 1}
    assert report["relations"]["expected"]["count"] == 7
    assert report["relations"]["actual"]["count"] == 7
    assert report["relations"]["comparison"]["status"] == "pass"
    assert report["relations"]["unresolved"]["count"] == 0


def test_semantic_inventory_detects_removed_explicit_edge(tmp_path: Path) -> None:
    config, snapshot = _fixture(tmp_path)
    tampered = copy.deepcopy(snapshot)
    tampered["graph.json"]["edges"] = [
        edge
        for edge in tampered["graph.json"]["edges"]
        if not (
            edge["source"] == "note-secret"
            and edge["target"] == "source-secret"
            and edge["type"] == "source_ref"
        )
    ]

    report = build_semantic_inventory(tmp_path, config, tampered)

    assert report["status"] == "fail"
    assert report["summary"]["relation_error_count"] == 1
    assert report["relations"]["comparison"]["missing"]["count"] == 1
    assert report["relations"]["comparison"]["extra"]["count"] == 0


def test_semantic_inventory_detects_removed_temporal_event(tmp_path: Path) -> None:
    config, snapshot = _fixture(tmp_path)
    tampered = copy.deepcopy(snapshot)
    tampered["temporal_graph.json"]["events"] = [
        event
        for event in tampered["temporal_graph.json"]["events"]
        if event["kind"] != "ingestion_recorded"
    ]

    report = build_semantic_inventory(tmp_path, config, tampered)

    assert report["status"] == "fail"
    assert report["summary"]["event_error_count"] == 1
    assert report["events"]["comparisons"]["temporal"]["missing"]["count"] == 1
    assert report["events"]["comparisons"]["temporal"]["extra"]["count"] == 0


def test_snapshot_directory_loader_and_renderers_keep_output_sanitized(
    tmp_path: Path,
) -> None:
    config, snapshot = _fixture(tmp_path)
    snapshot_dir = tmp_path / "snapshot"
    snapshot_dir.mkdir()
    for name in (
        "manifest.json",
        "ingestion.json",
        "temporal_graph.json",
        "graph.json",
    ):
        (snapshot_dir / name).write_text(
            json.dumps(snapshot[name]), encoding="utf-8"
        )

    loaded = load_snapshot_payloads(snapshot_dir)
    report = build_semantic_inventory(tmp_path, config, loaded)
    rendered = json.dumps(report, sort_keys=True) + render_markdown(report)

    assert report["status"] == "pass"
    for private_value in (
        "semantic-secret-repo",
        "root-secret",
        "source-secret",
        "note-secret",
        "event-secret",
        "Private root",
        "memories/",
    ):
        assert private_value not in rendered
