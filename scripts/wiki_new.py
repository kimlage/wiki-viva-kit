#!/usr/bin/env python3
"""Create a new typed wiki page from the page-type registry template."""

from __future__ import annotations

import argparse
import sys

try:  # importing _common bootstraps sys.path so wiki_core resolves
    from scripts._common import ROOT  # package/spec-loader import
except ModuleNotFoundError:
    from _common import ROOT  # direct run: scripts/ on sys.path

from wiki_core.config import load_config
from wiki_core.page_types import load_page_type_registry
from wiki_core.templates import default_output_path, instantiate_template, resolve_template


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--type", required=True, dest="page_type")
    parser.add_argument("--title", required=True)
    parser.add_argument("--context")
    parser.add_argument("--output", help="repo-relative destination; defaults to first allowed_dir/<slug>.md")
    parser.add_argument("--dry-run", action="store_true", help="print the page without writing")
    args = parser.parse_args()

    config = load_config(ROOT)
    registry = load_page_type_registry(ROOT)
    if registry is None:
        print("ERROR: wiki.page-types.yaml not found", file=sys.stderr)
        return 2
    try:
        resolved = resolve_template(ROOT, config, registry, args.page_type)
        text = instantiate_template(
            resolved,
            title=args.title,
            context=args.context or config.default_context,
            config=config,
        )
        output = args.output or default_output_path(registry, args.page_type, args.title)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(text)
        return 0

    out = ROOT / output
    if out.exists():
        print(f"ERROR: destination exists: {output}", file=sys.stderr)
        return 2
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
