"""Shared walk over normalized ingestion-event pages.

Closure and quality reports both iterate the canonical events directory
(`WikiPaths.ingest_events_dir`) and need the same answer to "is this file a
real normalized event page?" — index/readme files are navigation, and legacy
migrations sometimes kept a broader page_type while writing event files in the
canonical directory (there, event/source identity is authoritative). One copy
of that contract lives here so the two reports can never drift.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from wiki_core.paths import WikiPaths

EVENT_INDEX_FILENAMES = {"readme.md", "index.md"}


def event_pages(paths: WikiPaths) -> list[Path]:
    """Every Markdown file under the canonical events directory, sorted."""
    if not paths.ingest_events_dir.exists():
        return []
    return sorted(paths.ingest_events_dir.rglob("*.md"))


def is_ingestion_event_page(path: Path, values: dict[str, Any]) -> bool:
    """Whether a file from `event_pages` is a normalized event (not navigation)."""
    if path.name.lower() in EVENT_INDEX_FILENAMES:
        return False
    if values.get("page_type") == "ingestion_event":
        return True
    # Legacy migrations sometimes wrote normalized event files in the canonical
    # events directory while keeping a broader source/catalog page type. The
    # directory is authoritative once the page carries event or source identity.
    return bool(values.get("event_id") or values.get("source_id"))
