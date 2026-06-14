#!/usr/bin/env python3
"""Inventory legacy wiki pages and suggest v6.2 frontmatter metadata."""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys

try:  # importing _common bootstraps sys.path so wiki_core resolves
    from scripts._common import ROOT  # package/spec-loader import
except ModuleNotFoundError:
    from _common import ROOT  # direct run: scripts/ on sys.path

from wiki_core.config import load_config
from wiki_core.migration import frontmatter_block_for_suggestion, migration_inventory
from wiki_core.page_types import load_page_type_registry


def _markdown(rows: list[object]) -> str:
    lines = [
        "# Wiki migration inventory",
        "",
        "| Path | Issue | Suggested type | Context | Page ID | Reason |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        rel = getattr(row, "rel")
        lines.append(
            "| "
            + " | ".join(
                [
                    rel,
                    getattr(row, "issue"),
                    getattr(row, "page_type"),
                    getattr(row, "context"),
                    getattr(row, "page_id"),
                    getattr(row, "reason"),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument(
        "--show-frontmatter",
        action="store_true",
        help="include suggested frontmatter blocks after the inventory",
    )
    args = parser.parse_args()

    config = load_config(ROOT)
    registry = load_page_type_registry(ROOT)
    rows = migration_inventory(ROOT, config, registry)

    if args.format == "json":
        print(json.dumps([dataclasses.asdict(row) for row in rows], indent=2, ensure_ascii=False))
    else:
        print(_markdown(rows), end="")
        if args.show_frontmatter and rows:
            print("\n## Suggested frontmatter blocks\n")
            gate = str(config.approval.get("gate") or "github_pr")
            for row in rows:
                print(f"### {row.rel}\n")
                print("```yaml")
                print(frontmatter_block_for_suggestion(row, visibility=config.default_visibility, gate=gate))
                print("```\n")

    if rows:
        print(f"wiki_migration_inventory: {len(rows)} legacy page(s)", file=sys.stderr)
    else:
        print("wiki_migration_inventory: no legacy pages", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
