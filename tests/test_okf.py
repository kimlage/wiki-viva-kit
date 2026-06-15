from __future__ import annotations

import json
from pathlib import Path

from wiki_core.okf import (
    OKF_VERSION,
    check_okf_bundle,
    export_okf_bundle,
    generate_okf_visualization,
    import_preview_to_dict,
    preview_okf_import,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _page(page_id: str, page_type: str, title: str, body: str, extra: str = "") -> str:
    return f"""---
page_id: {page_id}
page_type: {page_type}
title: "{title}"
tags:
  - wiki/test
context: system
visibility: private_self
updated_at: 2026-06-15
stale_after_days: 30
sources_policy: test
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
{extra}---

# {title}

{body}
"""


def _fixture_repo(root: Path) -> None:
    _write(
        root / "memories/index.md",
        _page(
            "root",
            "root_index",
            "Root Hub",
            "- [Project hub](projects/index.md)\n- [Project note](projects/note.md)\n",
            extra='purpose: "Root entry point for the rich living wiki."\n',
        ),
    )
    _write(
        root / "memories/projects/index.md",
        _page(
            "projects",
            "context_hub",
            "Projects Hub",
            "- [Root](../index.md)\n- [Note](note.md)\n",
        ),
    )
    _write(
        root / "memories/projects/note.md",
        _page(
            "project-note",
            "project",
            "Project Note",
            "This project note links back to the [root hub](../index.md) and keeps tables.\n\n"
            "| Field | Value |\n| --- | --- |\n| State | active |\n",
            extra='resource: "https://example.com/project"\n',
        ),
    )
    _write(
        root / "memories/system/log.md",
        _page("system-log", "system_log", "Memory Log", "## 2026-06-15\n\n* Update: fixture.\n"),
    )


def test_export_rewrites_reserved_pages_and_checks_conformant_bundle(tmp_path: Path) -> None:
    _fixture_repo(tmp_path)
    out = tmp_path / "tmp" / "okf"

    result = export_okf_bundle(root=tmp_path, source_root="memories", bundle_root=out, clean=True)

    assert result.okf_version == OKF_VERSION
    assert result.concept_count == 4
    assert result.reserved_concept_count == 3
    assert (out / "index.md").exists()
    assert (out / "_wiki_viva_reserved/root-index.md").exists()
    assert (out / "_wiki_viva_reserved/projects-index.md").exists()
    assert (out / "_wiki_viva_reserved/system-log.md").exists()

    root_index = (out / "index.md").read_text(encoding="utf-8")
    assert 'okf_version: "0.1"' in root_index
    assert "page_id:" not in root_index

    note = (out / "projects/note.md").read_text(encoding="utf-8")
    assert "type: project" in note
    assert "x_wiki_viva_source_path: projects/note.md" in note
    assert "../_wiki_viva_reserved/root-index.md" in note
    assert "| State | active |" in note

    checked = check_okf_bundle(out)
    assert checked.errors == []
    assert checked.concept_count == 4
    assert checked.broken_links == 0


def test_okf_check_rejects_missing_type_on_concepts(tmp_path: Path) -> None:
    _write(tmp_path / "bundle/bad.md", "---\ntitle: Bad\n---\n\n# Bad\n")
    _write(tmp_path / "bundle/index.md", "# Index\n\n## Concepts\n\n* [Bad](bad.md)\n")

    result = check_okf_bundle(tmp_path / "bundle")

    assert not result.ok
    assert "bad.md: missing required OKF `type` frontmatter" in result.errors


def test_import_preview_preserves_wiki_viva_identity(tmp_path: Path) -> None:
    _fixture_repo(tmp_path)
    out = tmp_path / "tmp" / "okf"
    export_okf_bundle(root=tmp_path, source_root="memories", bundle_root=out, clean=True)

    preview = preview_okf_import(
        bundle_root=out,
        context="system",
        memory_root="memories",
        default_visibility="private_self",
        today="2026-06-15",
    )
    data = import_preview_to_dict(preview)

    assert data["schema_version"] == "wiki_okf_import_preview.v1"
    assert data["concept_count"] == 4
    by_source = {row["source_path"]: row for row in data["concepts"]}
    assert by_source["projects/note.md"]["suggested_page_id"] == "project-note"
    assert by_source["projects/note.md"]["suggested_page_type"] == "project"
    assert by_source["projects/note.md"]["suggested_output_path"] == "memories/okf-import/projects/note.md"


def test_visualization_embeds_bundle_without_external_runtime(tmp_path: Path) -> None:
    _fixture_repo(tmp_path)
    out = tmp_path / "tmp" / "okf"
    export_okf_bundle(root=tmp_path, source_root="memories", bundle_root=out, clean=True)
    html_path = out / "viz.html"

    result = generate_okf_visualization(out, html_path, name="Fixture OKF")

    assert result.concepts == 4
    assert result.edges >= 2
    html = html_path.read_text(encoding="utf-8")
    assert "Fixture OKF" in html
    assert "const bundle =" in html
    assert "https://cdn" not in html.lower()
    payload_start = html.index("const bundle = ") + len("const bundle = ")
    payload_end = html.index(";\nconst byId", payload_start)
    payload = json.loads(html[payload_start:payload_end])
    assert len(payload["nodes"]) == 4
