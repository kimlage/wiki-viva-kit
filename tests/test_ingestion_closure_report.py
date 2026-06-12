from __future__ import annotations

from pathlib import Path

from wiki_core.closure import build_ingestion_closure_report, render_markdown
from wiki_core.config import WikiConfig


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _page(page_id: str, page_type: str, body: str, extra: str = "") -> str:
    return f"""---
page_id: {page_id}
page_type: {page_type}
context: system
visibility: private_self
updated_at: 2026-06-12
stale_after_days: 30
sources_policy: synthetic
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
{extra}---

# {page_id}

{body}
"""


def test_ingestion_closure_report_tracks_events_sources_and_candidates(tmp_path: Path) -> None:
    _write(tmp_path / "memories/index.md", _page("root", "root_index", "- Ready.\n"))
    _write(
        tmp_path / "memories/sources/source-a.md",
        _page(
            "source-a",
            "source",
            "- Source A.\n",
            "source_type: reference\ningestion_state: ingested\nlast_ingested_at: 2026-06-12\n",
        ),
    )
    _write(
        tmp_path / "memories/sources/source-b.md",
        _page(
            "source-b",
            "source",
            "- Source B.\n",
            "source_type: reference\ningestion_state: ingested\nlast_ingested_at: 2026-06-12\n",
        ),
    )
    _write(
        tmp_path / "memories/system/ingestion/events/2026-06-12-closed.md",
        _page(
            "event-closed",
            "ingestion_event",
            "## Source\n\n- Synthetic.\n\n## Claims candidates\n\n- Claim A.\n",
            "event_id: event-closed\nsource_refs:\n  - source-a\nconsolidated_into:\n  - memories/index.md\n",
        ),
    )
    _write(
        tmp_path / "memories/system/ingestion/events/2026-06-12-open.md",
        _page(
            "event-open",
            "source_catalog",
            "## Source\n\n- Synthetic.\n\n## Candidate actions\n\n- Action A.\n",
            "event_id: event-open\nsource_id: source-b\n",
        ),
    )

    report = build_ingestion_closure_report(tmp_path, WikiConfig(contexts=("system",)))

    assert report["summary"]["events_total"] == 2
    assert report["summary"]["events_closed"] == 1
    assert report["summary"]["events_without_consolidated_into"] == 1
    assert report["summary"]["ingested_sources"] == 2
    assert report["summary"]["ingested_sources_without_closed_event"] == 1
    assert report["summary"]["candidate_claims"] == 1
    assert report["summary"]["candidate_actions"] == 1
    assert report["summary"]["candidate_total"] == 2
    assert report["summary"]["consolidated_targets"] == 1
    source_a = next(source for source in report["ingested_sources"] if source["page_id"] == "source-a")
    source_b = next(source for source in report["ingested_sources"] if source["page_id"] == "source-b")
    assert source_a["closed_event_paths"] == [
        "memories/system/ingestion/events/2026-06-12-closed.md"
    ]
    assert source_a["consolidated_targets"] == ["memories/index.md"]
    assert source_a["candidate_total"] == 1
    assert source_a["candidate_units_per_target"] == 1.0
    assert source_b["closed_event_paths"] == []
    assert source_b["event_paths"] == [
        "memories/system/ingestion/events/2026-06-12-open.md"
    ]
    assert "Wiki ingestion closure report" in render_markdown(report)
    assert "Source Compression" in render_markdown(report)
