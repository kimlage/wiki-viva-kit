#!/usr/bin/env python3
"""Build or inspect the local SQLite chunk index.

--rebuild reindexes the ingested-source chunks AND the wiki pages themselves
(memory pages are chunked and indexed under `page:<page_id>`), so retrieval —
the integration packet and the --query pass — finds EXISTING knowledge, not
only ingested sources.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:  # importing _common bootstraps sys.path so wiki_core resolves
    from scripts._common import ROOT  # package/spec-loader import
except ModuleNotFoundError:
    from _common import ROOT  # direct run: scripts/ on sys.path

from wiki_core.config import load_config
from wiki_core.index import build_index, check_index, index_pages
from wiki_core.index.page_collection import collect_page_chunks
from wiki_core.paths import WikiPaths
from wiki_core.traversal import require_wiki_boundaries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()
    config = load_config(ROOT)
    paths = WikiPaths(ROOT, config)
    db_path = paths.indexes / "wiki.sqlite"
    try:
        require_wiki_boundaries(ROOT, directories=(paths.source_manifests, paths.source_text, paths.chunks,
            paths.indexes, paths.extraction_events, paths.llm_cache, paths.coverage, paths.input_stage),
            files=(db_path, *(Path(str(db_path) + suffix) for suffix in ('-journal', '-wal', '-shm'))))
        if args.rebuild:
            require_wiki_boundaries(ROOT, files=paths.chunks.glob('*.json'))
    except (ValueError, OSError):
        print('wiki_build_index: derived_path_crosses_repository_boundary', file=sys.stderr)
        return 2
    paths.ensure()
    if args.rebuild:
        result = build_index(paths.chunks, db_path)
        result.update(index_pages(db_path, collect_page_chunks(ROOT, paths, config)))
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    result = check_index(db_path)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if args.check and not result["exists"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
