from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parents[1]


def _report_module():
    spec = importlib.util.spec_from_file_location(
        "wiki_quadrant_projection_report",
        KIT_ROOT / "scripts/wiki_quadrant_projection_report.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _wiki(tmp_path: Path, pages: dict[str, str]) -> Path:
    for name in ("wiki.templates.yaml", "wiki.page-types.yaml"):
        shutil.copy(KIT_ROOT / name, tmp_path / name)
    (tmp_path / "wiki.config.yaml").write_text("repo_id: demo\nlanguage: en\n", encoding="utf-8")
    for rel, text in pages.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def test_projection_report_inventories_centers_warnings_and_multi_projection(tmp_path: Path) -> None:
    root = _wiki(
        tmp_path,
        {
            "memories/index.md": (
                "---\npage_id: root-demo\npage_type: root_entity\ntitle: Root\ncontext: demo\n"
                "visibility: private_self\nupdated_at: 2026-06-01\nstale_after_days: 30\n"
                "blocks:\n  - id: wiki.block.quadrants.v1\n"
                "    config: { nested_mode: project_all }\n---\n# Root\n"
            ),
            "memories/companies/acme.md": (
                "---\npage_id: company-acme\npage_type: root_entity\ntitle: ACME\ncontext: demo\n"
                "visibility: private_self\nupdated_at: 2026-06-01\nstale_after_days: 30\n"
                "moc_parent: memories/index.md\nroot_entity_type: company\n"
                "blocks:\n  - id: wiki.block.quadrants.v1\n---\n# ACME\n"
            ),
            "memories/claims/acme-intent.md": (
                "---\npage_id: claim-acme-intent\npage_type: claim\ntitle: ACME intent\ncontext: demo\n"
                "visibility: private_self\nupdated_at: 2026-06-01\nstale_after_days: 30\n"
                "moc_parent: memories/companies/acme.md\nsubject_ref: company-acme\n"
                "subject_role: perception\nsource_refs: []\n---\n# ACME intent\n"
            ),
            "memories/idx.md": (
                "---\npage_id: idx-demo\npage_type: ontology_index\ntitle: Index\ncontext: demo\n"
                "visibility: private_self\nupdated_at: 2026-06-01\nstale_after_days: 30\n"
                "moc_parent: memories/index.md\n---\n# Index\n"
            ),
        },
    )

    report = _report_module().build_report(root, q0_warn_threshold=0)

    assert report["schema_version"] == "wiki_quadrant_projection_report.v1"
    assert report["anchors"]["root-demo"]["nested_mode"] == "project_all"
    assert report["anchors"]["company-acme"]["inferred_parent_projection"] is True
    assert any(warning["kind"] == "inferred_parent_projection" for warning in report["warnings"])
    assert not any(warning["kind"] == "q0_overload" for warning in report["warnings"])
    assert "idx-demo" in report["anchors"]["root-demo"]["assignments"]["q2"]
    assert report["anchors"]["root-demo"]["assignments"]["q0_core"] == []
    multi = {entry["page"]: entry for entry in report["multi_quadrant_pages"]}
    assert "claim-acme-intent" in multi
    centers = {entry["center"]: entry["quadrant"] for entry in multi["claim-acme-intent"]["centers"]}
    assert centers == {"root-demo": "q4", "company-acme": "q1"}
