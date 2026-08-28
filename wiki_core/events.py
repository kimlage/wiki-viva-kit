"""Shared walk over normalized ingestion-event pages.

Closure and quality reports both iterate the canonical events directory
(`WikiPaths.ingest_events_dir`) and need the same answer to "is this file a
real normalized event page?" — index/readme files are navigation, and legacy
migrations sometimes kept a broader page_type while writing event files in the
canonical directory (there, event/source identity is authoritative). One copy
of that contract lives here so the two reports can never drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping

from wiki_core.paths import WikiPaths

EVENT_INDEX_FILENAMES = {"readme.md", "index.md"}
CANONICAL_INGESTION_EVENT_PAGE_TYPE = "ingestion_event"
LEGACY_INGESTION_EVENT_PAGE_TYPES = frozenset({"source", "source_catalog"})
IngestionEventCompatibility = Literal[
    "canonical",
    "legacy_page_type",
    "legacy_identity",
    "navigation",
    "not_event",
]


@dataclass(frozen=True)
class IngestionEventIdentity:
    """Typed semantic identity shared by closure, quality and temporal views."""

    recognized: bool
    event_id: str
    page_id: str
    source_id: str
    authored_page_type: str
    canonical_page_type: str
    compatibility: IngestionEventCompatibility

    @property
    def is_legacy(self) -> bool:
        return self.compatibility in {"legacy_page_type", "legacy_identity"}


def _text(values: Mapping[str, Any], key: str) -> str:
    return str(values.get(key) or "").strip()


def resolve_ingestion_event_identity(
    path: Path,
    values: Mapping[str, Any],
    *,
    in_events_directory: bool = True,
) -> IngestionEventIdentity:
    """Resolve canonical and compatibility ingestion-event identity.

    ``event_pages`` already scopes authored Markdown to the configured events
    directory, so ``in_events_directory`` defaults to true for compatibility
    with the historical :func:`is_ingestion_event_page` signature. Read-model
    consumers that walk every page must pass the real directory context.
    """

    authored_page_type = _text(values, "page_type")
    page_id = _text(values, "page_id") or _text(values, "id")
    source_id = _text(values, "source_id")
    event_id = _text(values, "event_id") or page_id or source_id

    if path.name.lower() in EVENT_INDEX_FILENAMES:
        return IngestionEventIdentity(
            recognized=False,
            event_id=event_id,
            page_id=page_id,
            source_id=source_id,
            authored_page_type=authored_page_type,
            canonical_page_type="",
            compatibility="navigation",
        )

    if authored_page_type == CANONICAL_INGESTION_EVENT_PAGE_TYPE:
        return IngestionEventIdentity(
            recognized=True,
            event_id=event_id,
            page_id=page_id,
            source_id=source_id,
            authored_page_type=authored_page_type,
            canonical_page_type=CANONICAL_INGESTION_EVENT_PAGE_TYPE,
            compatibility="canonical",
        )

    explicit_legacy_identity = bool(_text(values, "event_id") or source_id)
    typed_legacy_identity = (
        authored_page_type in LEGACY_INGESTION_EVENT_PAGE_TYPES and bool(page_id)
    )
    if in_events_directory and (explicit_legacy_identity or typed_legacy_identity):
        compatibility: IngestionEventCompatibility = (
            "legacy_page_type"
            if authored_page_type in LEGACY_INGESTION_EVENT_PAGE_TYPES
            else "legacy_identity"
        )
        return IngestionEventIdentity(
            recognized=True,
            event_id=event_id,
            page_id=page_id,
            source_id=source_id,
            authored_page_type=authored_page_type,
            canonical_page_type=CANONICAL_INGESTION_EVENT_PAGE_TYPE,
            compatibility=compatibility,
        )

    return IngestionEventIdentity(
        recognized=False,
        event_id=event_id,
        page_id=page_id,
        source_id=source_id,
        authored_page_type=authored_page_type,
        canonical_page_type="",
        compatibility="not_event",
    )


def event_pages(paths: WikiPaths) -> list[Path]:
    """Every Markdown file under the canonical events directory, sorted."""
    if not paths.ingest_events_dir.exists():
        return []
    return sorted(paths.ingest_events_dir.rglob("*.md"))


def is_ingestion_event_page(path: Path, values: dict[str, Any]) -> bool:
    """Whether a file from `event_pages` is a normalized event (not navigation)."""
    return resolve_ingestion_event_identity(path, values).recognized
