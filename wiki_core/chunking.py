from __future__ import annotations

import re
from dataclasses import dataclass

from .ids import sha256_text


@dataclass(frozen=True)
class TextChunk:
    chunk_id: str
    ordinal: int
    text: str
    token_estimate: int
    hash_sha256: str


def _estimate_tokens(text: str) -> int:
    return max(1, int(len(text.split()) * 1.35))


def _split_units(text: str) -> list[str]:
    """Split the text into CONTENT units, preserving structure.

    Preference: paragraphs (separated by a blank line). If there are none,
    lines (preserves tables/CSV, which split() used to collapse). If it is a
    single block, return the block.
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(paragraphs) > 1:
        return paragraphs
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) > 1:
        return lines
    stripped = text.strip()
    return [stripped] if stripped else []


def chunk_text(source_id: str, text: str, target_tokens: int = 1200, overlap_tokens: int = 150) -> list[TextChunk]:
    """CONTENT-based chunking (finding 4): boundaries at paragraphs/lines instead
    of a fixed word window. This way a local edit (e.g. fixing a typo in a
    paragraph) only changes that paragraph's chunk — the others keep the same text
    and, with the content-based cache_key, hit the cache. Structure is preserved
    (joined with a blank line). Units much larger than the target are subdivided by
    a word window with `overlap_tokens`.
    """
    target_words = max(80, int(target_tokens / 1.35))
    overlap_words = max(0, int(overlap_tokens / 1.35))
    units = _split_units(text)
    if not units:
        return []

    # Subdivide units that are too large (a giant paragraph) by a word window.
    expanded: list[str] = []
    for unit in units:
        unit_words = unit.split()
        if len(unit_words) > int(target_words * 1.5):
            start = 0
            while start < len(unit_words):
                end = min(len(unit_words), start + target_words)
                expanded.append(" ".join(unit_words[start:end]))
                if end >= len(unit_words):
                    break
                start = max(end - overlap_words, start + 1)
        else:
            expanded.append(unit)

    # Group units up to the target, without splitting a unit in half.
    grouped: list[str] = []
    current: list[str] = []
    current_words = 0
    for unit in expanded:
        unit_words = len(unit.split())
        if current and current_words + unit_words > target_words:
            grouped.append("\n\n".join(current))
            current = []
            current_words = 0
        current.append(unit)
        current_words += unit_words
    if current:
        grouped.append("\n\n".join(current))

    chunks: list[TextChunk] = []
    for ordinal, chunk in enumerate(grouped, start=1):
        digest = sha256_text(chunk)
        chunks.append(
            TextChunk(
                chunk_id=f"{source_id}-chunk-{ordinal:04d}-{digest[:10]}",
                ordinal=ordinal,
                text=chunk,
                token_estimate=_estimate_tokens(chunk),
                hash_sha256=digest,
            )
        )
    return chunks
