#!/usr/bin/env python3
"""Build or inspect the local SQLite chunk index."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wiki_core.config import load_config
from wiki_core.index import build_index, check_index
from wiki_core.paths import WikiPaths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()
    paths = WikiPaths(ROOT, load_config(ROOT))
    paths.ensure()
    db_path = paths.indexes / "wiki.sqlite"
    if args.rebuild:
        print(json.dumps(build_index(paths.chunks, db_path), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    result = check_index(db_path)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if args.check and not result["exists"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
