#!/usr/bin/env python3
"""Create a new typed wiki page from the page-type registry template."""

from __future__ import annotations

import argparse
import sys

try:  # importing _common bootstraps sys.path so wiki_core resolves
    from scripts._common import ROOT  # package/spec-loader import
except ModuleNotFoundError:
    from _common import ROOT  # direct run: scripts/ on sys.path

from wiki_core.page_creation import create_page, prepare_page
from wiki_core.experience_packs import PackError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--type", required=True, dest="page_type")
    parser.add_argument("--title", required=True)
    parser.add_argument("--context")
    parser.add_argument(
        "--output",
        help="repo-relative destination; defaults to first allowed_dir/<slug>.md",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="print the page without writing"
    )
    args = parser.parse_args()

    try:
        output, text = prepare_page(ROOT, args.page_type, args.title, args.context, args.output)
    except (FileNotFoundError, OSError, PackError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(text)
        return 0

    try:
        create_page(ROOT, output, text)
    except FileExistsError:
        print(f"ERROR: destination exists: {output}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"ERROR: could not safely create destination: {exc}", file=sys.stderr)
        return 2
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
