"""Collect and fingerprint the current set of wiki page chunks."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from wiki_core.chunking import chunk_text
from wiki_core.frontmatter import parse_frontmatter
from wiki_core.paths import WikiPaths
from wiki_core.traversal import wiki_markdown_files


def collect_page_chunks(root: Path, paths: WikiPaths, config) -> list[tuple[str, list[dict[str, object]]]]:
    """Chunk every memory page with a page_id (body only, frontmatter excluded)."""
    target = int(config.llm.get("chunk_target_tokens", 1200))
    overlap = int(config.llm.get("chunk_overlap_tokens", 150))
    pages: list[tuple[str, list[dict[str, object]]]] = []
    seen: set[str] = set()
    memory_root = paths.memory_root
    if not memory_root.is_dir():
        return pages
    for md in sorted(wiki_markdown_files(memory_root, wiki_root=root)):
        fm, _ = parse_frontmatter(md)
        page_id = str(fm.get("page_id") or "")
        if not page_id:
            continue
        if page_id in seen:
            raise ValueError("duplicate wiki page_id; cannot build a safe page index")
        seen.add(page_id)
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



def page_rows_signature(rows: list[tuple]) -> str:
    """Hash sorted index rows, including text, identity and chunk metadata."""
    raw = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def page_index_signature(pages: list[tuple[str, list[dict[str, object]]]]) -> str:
    """Bind a page index to all current visible page IDs and chunk bytes."""
    rows = [(f'page:{page_id}', chunk['chunk_id'], int(chunk['ordinal']),
             chunk['hash_sha256'], int(chunk['token_estimate']), chunk['text'])
            for page_id, chunks in pages for chunk in chunks]
    rows.sort(key=lambda row: (row[0], row[1]))
    return page_rows_signature(rows)


def current_page_signature(paths: WikiPaths) -> str:
    return page_index_signature(collect_page_chunks(paths.root, paths, paths.config))
