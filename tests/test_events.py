"""The shared ingestion-event walk (wiki_core/events.py) — the one copy of
"is this file a real normalized event page?" that closure and quality import."""

from __future__ import annotations

from pathlib import Path

from wiki_core.config import WikiConfig
from wiki_core.events import EVENT_INDEX_FILENAMES, event_pages, is_ingestion_event_page
from wiki_core.paths import WikiPaths


def test_event_pages_walks_only_the_events_dir(tmp_path: Path) -> None:
    config = WikiConfig(repo_id="events-test")
    paths = WikiPaths(tmp_path, config)
    # No events directory yet -> honest empty list.
    assert event_pages(paths) == []
    events_dir = paths.ingest_events_dir
    events_dir.mkdir(parents=True)
    (events_dir / "2026-07-01-drop.md").write_text("---\npage_type: ingestion_event\n---\n", encoding="utf-8")
    (events_dir / "README.md").write_text("# index\n", encoding="utf-8")
    found = event_pages(paths)
    assert [p.name for p in found] == ["2026-07-01-drop.md", "README.md"]


def test_is_ingestion_event_page_contract(tmp_path: Path) -> None:
    # Index/readme files are navigation, never events (case-insensitive).
    assert "readme.md" in EVENT_INDEX_FILENAMES
    assert not is_ingestion_event_page(Path("README.md"), {"page_type": "ingestion_event"})
    assert not is_ingestion_event_page(Path("index.md"), {"event_id": "e1"})
    # The declared type wins.
    assert is_ingestion_event_page(Path("drop.md"), {"page_type": "ingestion_event"})
    # Legacy migrations: event/source identity is authoritative in this dir.
    assert is_ingestion_event_page(Path("drop.md"), {"page_type": "source", "event_id": "e1"})
    assert is_ingestion_event_page(Path("drop.md"), {"source_id": "s1"})
    # No identity, no event type -> not an event.
    assert not is_ingestion_event_page(Path("drop.md"), {"page_type": "source"})
