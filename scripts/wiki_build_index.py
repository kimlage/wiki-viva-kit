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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wiki_core.chunking import chunk_text
from wiki_core.config import load_config
from wiki_core.consolidate import _read_frontmatter
from wiki_core.index import build_index, check_index, index_pages
from wiki_core.paths import WikiPaths


def collect_page_chunks(root: Path, paths: WikiPaths, config) -> list[tuple[str, list[dict[str, object]]]]:
    """Chunk every memory page with a page_id (body only, frontmatter excluded)."""
    target = int(config.llm.get("chunk_target_tokens", 1200))
    overlap = int(config.llm.get("chunk_overlap_tokens", 150))
    pages: list[tuple[str, list[dict[str, object]]]] = []
    memory_root = paths.memory_root
    if not memory_root.is_dir():
        return pages
    for md in sorted(memory_root.rglob("*.md")):
        fm = _read_frontmatter(md)
        page_id = str(fm.get("page_id") or "")
        if not page_id:
            continue
        text = md.read_text(encoding="utf-8", errors="replace")
        if text.startswith("---\n"):
            end = text.find("\n---", 4)
            if end != -1:
                text = text[end + 4 :]
        chunks = chunk_text(f"page:{page_id}", text, target, overlap)
        if chunks:
            pages.append(
                (
                    page_id,
                    [
                        {
                            "chunk_id": c.chunk_id,
                            "ordinal": c.ordinal,
                            "hash_sha256": c.hash_sha256,
                            "token_estimate": c.token_estimate,
                            "text": c.text,
                        }
                        for c in chunks
                    ],
                )
            )
    return pages


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()
    config = load_config(ROOT)
    paths = WikiPaths(ROOT, config)
    paths.ensure()
    db_path = paths.indexes / "wiki.sqlite"
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
