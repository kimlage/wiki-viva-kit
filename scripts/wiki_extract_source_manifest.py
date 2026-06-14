#!/usr/bin/env python3
"""Create a deterministic source manifest for the wiki pipeline."""

from __future__ import annotations

import argparse
import json
import sys

try:  # importing _common bootstraps sys.path so wiki_core resolves
    from scripts._common import ROOT  # package/spec-loader import
except ModuleNotFoundError:
    from _common import ROOT  # direct run: scripts/ on sys.path

from wiki_core.config import load_config
from wiki_core.paths import WikiPaths
from wiki_core.source_manifest import build_manifest, write_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    paths = WikiPaths(ROOT, load_config(ROOT))
    paths.ensure()
    manifest = build_manifest(args.source, args.context)
    if args.dry_run:
        print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    path = write_manifest(manifest, paths.source_manifests)
    print(path.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
