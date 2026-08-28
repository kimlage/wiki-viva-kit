#!/usr/bin/env python3
"""Read-only quadrant projection inventory.

The report is intentionally conservative: it writes only the requested output
file, never edits wiki pages, and surfaces inferred/defaulted placements so a
human can decide where explicit ``parent_projection`` or ``subject_role`` should
be added.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

try:
    from _common import ROOT
except ImportError:  # pragma: no cover - used when imported from tests
    ROOT = Path(__file__).resolve().parents[1]
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

from wiki_core.config import load_config
from wiki_core.template_blocks import (
    ANCHOR_TYPE_PARENT_PROJECTION,
    ROOT_ENTITY_TYPE_PARENT_PROJECTION,
    build_block_stacks_payload,
    load_block_world,
)


def _as_rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _projection_summary(entries: list[dict[str, Any]]) -> dict[str, Any]:
    quadrants = Counter(str(item.get("quadrant") or "q0") for item in entries)
    bases = Counter(str(item.get("basis") or "unknown") for item in entries)
    return {
        "total": len(entries),
        "by_quadrant": dict(sorted(quadrants.items())),
        "by_basis": dict(sorted(bases.items())),
    }


def _anchor_projection_values(page: dict[str, Any]) -> dict[str, Any]:
    raw = page["values"].get("parent_projection")
    if isinstance(raw, dict):
        return {
            "quadrant": str(raw.get("quadrant") or raw.get("facet") or ""),
            "sub_lens": str(raw.get("sub_lens") or raw.get("lens") or ""),
            "reason": str(raw.get("reason") or ""),
            "explicit": True,
        }
    return {"quadrant": "", "sub_lens": "", "reason": "", "explicit": False}


def _has_contract_default(page: dict[str, Any]) -> bool:
    """Whether core defines an intentional parent projection for this anchor.

    Source, holon and project anchors (plus typed nested roots) already have a
    deterministic contract default. Reporting each of those as an actionable
    inference buried real downstream ambiguities in dozens of false warnings.
    """
    if page["page_type"] in ANCHOR_TYPE_PARENT_PROJECTION:
        return True
    if page["page_type"] == "root_entity":
        entity_type = str(page["values"].get("root_entity_type") or "").strip()
        return entity_type in ROOT_ENTITY_TYPE_PARENT_PROJECTION
    return False


def build_report(root: Path = ROOT, *, q0_warn_threshold: int = 8) -> dict[str, Any]:
    config = load_config(root)
    world = load_block_world(root, config)
    payload = build_block_stacks_payload(world)
    tree = payload.get("anchor_tree") or {"roots": [], "nodes": {}}
    anchors_payload = payload.get("anchors") or {}
    warnings: list[dict[str, Any]] = []
    anchors: dict[str, Any] = {}
    page_centers: dict[str, list[dict[str, str]]] = defaultdict(list)

    for anchor_id, tree_node in sorted((tree.get("nodes") or {}).items()):
        page = world.by_id.get(anchor_id)
        if not page:
            continue
        record = anchors_payload.get(anchor_id) or {}
        derived = record.get("derived") or {}
        assignments = derived.get("quadrant_assignments") or {}
        projections_by_page = derived.get("quadrant_projections") or {}
        flat_projections = [
            projection
            for entries in projections_by_page.values()
            if isinstance(entries, list)
            for projection in entries
            if isinstance(projection, dict)
        ]
        q0_pages = list(assignments.get("q0_core") or [])
        parent_projection = _anchor_projection_values(page)
        parent_id = str(tree_node.get("parent") or "")
        contract_default = bool(parent_id and not parent_projection["explicit"] and _has_contract_default(page))
        inferred_parent = bool(parent_id and not parent_projection["explicit"] and not contract_default)
        if inferred_parent:
            warnings.append(
                {
                    "kind": "inferred_parent_projection",
                    "anchor": anchor_id,
                    "parent": parent_id,
                    "path": page["path"],
                    "message": "Nested center has no explicit parent_projection; defaults or type fallback will be used.",
                }
            )
        if len(q0_pages) > q0_warn_threshold:
            warnings.append(
                {
                    "kind": "q0_overload",
                    "anchor": anchor_id,
                    "path": page["path"],
                    "count": len(q0_pages),
                    "message": "Too many scoped pages lack quadrant projection basis.",
                }
            )
        for projection in flat_projections:
            page_centers[str(projection.get("page") or "")].append(
                {
                    "center": anchor_id,
                    "quadrant": str(projection.get("quadrant") or ""),
                    "basis": str(projection.get("basis") or ""),
                    "subject_center": str(projection.get("subject_center") or ""),
                }
            )
        anchors[anchor_id] = {
            "id": anchor_id,
            "title": page["title"],
            "path": page["path"],
            "page_type": page["page_type"],
            "root_entity_type": str(page["values"].get("root_entity_type") or ""),
            "parent": parent_id,
            "children": list(tree_node.get("children") or []),
            "parent_projection": parent_projection,
            "nested_mode": str(derived.get("quadrant_nested_mode") or ""),
            "assignments": {key: list(value or []) for key, value in sorted(assignments.items())},
            "projection_summary": _projection_summary(flat_projections),
            "q0_core_count": len(q0_pages),
            "inferred_parent_projection": bool(inferred_parent),
            "parent_projection_source": (
                "explicit" if parent_projection["explicit"] else "contract_default" if contract_default else "none"
            ),
        }

    multi_quadrant_pages: list[dict[str, Any]] = []
    for page_id, center_entries in sorted(page_centers.items()):
        quadrants = {entry["quadrant"] for entry in center_entries if entry["quadrant"]}
        if len(quadrants) <= 1:
            continue
        page = world.by_id.get(page_id)
        multi_quadrant_pages.append(
            {
                "page": page_id,
                "path": page["path"] if page else "",
                "title": page["title"] if page else page_id,
                "centers": center_entries,
            }
        )

    return {
        "schema_version": "wiki_quadrant_projection_report.v1",
        "repo_id": config.repo_id,
        "root": _as_rel(root, root),
        "anchor_count": len(anchors),
        "page_count": len(world.pages),
        "anchors": dict(sorted(anchors.items())),
        "multi_quadrant_pages": multi_quadrant_pages,
        "warnings": warnings,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Quadrant Projection Report",
        "",
        f"- Schema: `{report['schema_version']}`",
        f"- Repo: `{report['repo_id']}`",
        f"- Anchors: {report['anchor_count']}",
        f"- Pages: {report['page_count']}",
        f"- Warnings: {len(report['warnings'])}",
        "",
        "## Anchors",
        "",
        "| Anchor | Type | Parent | Mode | Projections | Q0 |",
        "| --- | --- | --- | --- | ---: | ---: |",
    ]
    for anchor in report["anchors"].values():
        summary = anchor["projection_summary"]
        lines.append(
            "| "
            f"`{anchor['id']}` | `{anchor['page_type']}` | `{anchor['parent'] or '-'}` | "
            f"`{anchor['nested_mode'] or '-'}` | {summary['total']} | {anchor['q0_core_count']} |"
        )
    if report["multi_quadrant_pages"]:
        lines.extend(["", "## Multi-Projection Pages", ""])
        for item in report["multi_quadrant_pages"]:
            centers = ", ".join(f"{entry['center']}:{entry['quadrant']}" for entry in item["centers"])
            lines.append(f"- `{item['page']}` ({item['path']}): {centers}")
    if report["warnings"]:
        lines.extend(["", "## Warnings", ""])
        for warning in report["warnings"]:
            lines.append(f"- `{warning['kind']}` `{warning.get('anchor', '')}`: {warning['message']}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="Path to write the JSON report.")
    parser.add_argument("--markdown-out", help="Optional Markdown report path.")
    parser.add_argument("--q0-warn-threshold", type=int, default=8)
    args = parser.parse_args(argv)

    report = build_report(ROOT, q0_warn_threshold=args.q0_warn_threshold)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.markdown_out:
        md_out = Path(args.markdown_out)
        md_out.parent.mkdir(parents=True, exist_ok=True)
        md_out.write_text(render_markdown(report), encoding="utf-8")
    print(f"quadrant projection report: {report['anchor_count']} anchors, {len(report['warnings'])} warning(s) -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
