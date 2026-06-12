from __future__ import annotations

import json
from pathlib import Path

from wiki_core.config import WikiConfig
from wiki_core.llm.cache import cache_key
from wiki_core.llm.context_pass import CONTEXT_PASS_SCHEMA_VERSION
from wiki_core.quality import (
    QUALITY_REPORT_SCHEMA_VERSION,
    build_quality_report,
    render_markdown,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _page(page_id: str, page_type: str, title: str, body: str, *, context: str = "example") -> str:
    return f"""---
page_id: {page_id}
page_type: {page_type}
title: "{title}"
context: {context}
visibility: private_self
updated_at: 2026-06-12
stale_after_days: 30
sources_policy: synthetic
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
---

# {title}

{body}
"""


def test_quality_report_measures_links_density_and_repetition(tmp_path: Path) -> None:
    repeated = (
        "The same operational paragraph is copied here to simulate duplicated "
        "memory that should usually become a link or a perspective-specific "
        "summary instead of literal repetition across equivalent pages."
    )
    _write(
        tmp_path / "memories/index.md",
        _page(
            "root",
            "root_index",
            "Root",
            "- [One](notes/one.md)\n- [Two](notes/two.md)\n- [Perspective](perspectives/p.md)\n",
        ),
    )
    _write(
        tmp_path / "memories/notes/one.md",
        _page("one", "context_note", "One", f"{repeated}\n\n- [Root](../index.md)\n"),
    )
    _write(
        tmp_path / "memories/notes/two.md",
        _page("two", "context_note", "Two", f"{repeated}\n\n- [Root](../index.md)\n"),
    )
    _write(
        tmp_path / "memories/perspectives/p.md",
        _page(
            "perspective",
            "perspective",
            "Perspective",
            f"{repeated}\n\n- [Root](../index.md)\n",
            context="project",
        ),
    )

    report = build_quality_report(tmp_path, WikiConfig(contexts=("example", "project")))

    assert report["schema_version"] == QUALITY_REPORT_SCHEMA_VERSION
    assert report["summary"]["pages_total"] == 4
    # The same paragraph in same context+type is bad repetition; the perspective
    # page is still reported as repeated, but it does not make the block "bad".
    assert report["summary"]["repeated_blocks"] == 1
    assert report["summary"]["bad_repetition_blocks"] == 1
    assert report["summary"]["thin_link_pages"] == 0
    assert "bad_repetition_blocks" in render_markdown(report)


def test_quality_report_tracks_cost_telemetry_without_budget_gate(tmp_path: Path) -> None:
    cfg = WikiConfig(
        contexts=("example",),
        llm={
            **WikiConfig().llm,
            "prompt_versions": {**WikiConfig().llm["prompt_versions"], "context_deep_read": "v3"},
        },
    )
    _write(tmp_path / "memories/index.md", _page("root", "root_index", "Root", "- Ready.\n"))
    chunk_hash = "a" * 64
    chunks_payload = {
        "source_id": "source-synthetic",
        "chunks": [
            {
                "chunk_id": "chunk-1",
                "hash_sha256": chunk_hash,
                "token_estimate": 42,
                "text": "Synthetic source text for quality telemetry.",
            }
        ],
    }
    _write(
        tmp_path / "data/derived/wiki/chunks/source-synthetic.json",
        json.dumps(chunks_payload),
    )
    key = cache_key(chunk_hash, "v3", CONTEXT_PASS_SCHEMA_VERSION, "deep_context")
    _write(tmp_path / f"data/derived/wiki/llm-cache/{key}.json", "{}")

    report = build_quality_report(tmp_path, cfg)

    assert report["summary"]["chunks_total"] == 1
    assert report["summary"]["estimated_context_tokens"] == 42
    assert report["summary"]["cached_calls"] == 1
    assert report["summary"]["pending_calls"] == 0
    assert report["cost_telemetry"]["note"].endswith("does not enforce a hard budget.")


def test_quality_report_surfaces_unclosed_synthetic_event(tmp_path: Path) -> None:
    _write(tmp_path / "memories/index.md", _page("root", "root_index", "Root", "- Ready.\n"))
    _write(
        tmp_path / "memories/system/ingestion/events/2026-06-12-synthetic.md",
        _page(
            "event-synthetic",
            "ingestion_event",
            "Synthetic Event",
            "## Source\n\n- Synthetic.\n",
            context="system",
        ).replace("sensitive_data_policy: private_sensitive_allowed", "sensitive_data_policy: private_sensitive_allowed\nconsolidated_into: []"),
    )

    report = build_quality_report(tmp_path, WikiConfig(contexts=("example",)))

    assert report["summary"]["ingestion_events"] == 1
    assert report["summary"]["events_without_consolidated_into"] == 1
    assert report["quality_flags"]["events_without_consolidated_into"] == [
        "memories/system/ingestion/events/2026-06-12-synthetic.md"
    ]


def test_quality_report_counts_legacy_event_files_in_events_directory(tmp_path: Path) -> None:
    _write(tmp_path / "memories/index.md", _page("root", "root_index", "Root", "- Ready.\n"))
    _write(
        tmp_path / "memories/system/ingestion/events/README.md",
        _page(
            "events-index",
            "source_catalog",
            "Events Index",
            "- [Legacy](2026-06-12-legacy.md)\n",
            context="system",
        ),
    )
    _write(
        tmp_path / "memories/system/ingestion/events/2026-06-12-legacy.md",
        _page(
            "event-legacy",
            "source_catalog",
            "Legacy Event",
            "## Source\n\n- Synthetic legacy event.\n",
            context="system",
        ).replace(
            "sensitive_data_policy: private_sensitive_allowed",
            (
                "sensitive_data_policy: private_sensitive_allowed\n"
                "event_id: ingestion-2026-06-12-legacy\n"
                "source_id: source-legacy\n"
                "consolidated_into: []"
            ),
        ),
    )

    report = build_quality_report(tmp_path, WikiConfig(contexts=("example",)))

    assert report["summary"]["ingestion_events"] == 1
    assert report["summary"]["events_without_consolidated_into"] == 1
    assert report["quality_flags"]["events_without_consolidated_into"] == [
        "memories/system/ingestion/events/2026-06-12-legacy.md"
    ]


def test_quality_report_ignores_repetition_inside_event_pages(tmp_path: Path) -> None:
    _write(tmp_path / "memories/index.md", _page("root", "root_index", "Root", "- Ready.\n"))
    repeated = (
        "Repeated integration resolution text that is intentionally preserved in "
        "event pages as an audit trail rather than canonical page prose."
    )
    for idx in (1, 2):
        _write(
            tmp_path / f"memories/system/ingestion/events/2026-06-12-event-{idx}.md",
            _page(
                f"event-{idx}",
                "source_catalog",
                f"Event {idx}",
                repeated,
                context="system",
            ).replace(
                "sensitive_data_policy: private_sensitive_allowed",
                (
                    "sensitive_data_policy: private_sensitive_allowed\n"
                    f"event_id: event-{idx}\n"
                    f"source_id: source-{idx}\n"
                    "consolidated_into:\n"
                    "  - memories/index.md"
                ),
            ),
        )

    report = build_quality_report(tmp_path, WikiConfig(contexts=("example",)))

    assert report["summary"]["bad_repetition_blocks"] == 0


def test_quality_report_allows_justified_low_density_exemption(tmp_path: Path) -> None:
    _write(tmp_path / "memories/index.md", _page("root", "root_index", "Root", "- Ready.\n"))
    exempt = _page(
        "role-a",
        "role",
        "Role A",
        "Short structural atom.\n",
    ).replace(
        "sensitive_data_policy: private_sensitive_allowed",
        (
            "sensitive_data_policy: private_sensitive_allowed\n"
            "quality_exempt:\n"
            "  - low_density\n"
            "quality_exempt_reason: structural atom linked from the ontology hub"
        ),
    )
    missing_reason = _page(
        "role-b",
        "role",
        "Role B",
        "Short structural atom.\n",
    ).replace(
        "sensitive_data_policy: private_sensitive_allowed",
        "sensitive_data_policy: private_sensitive_allowed\nquality_exempt:\n  - low_density",
    )
    _write(tmp_path / "memories/roles/a.md", exempt)
    _write(tmp_path / "memories/roles/b.md", missing_reason)

    report = build_quality_report(tmp_path, WikiConfig(contexts=("example",)))

    assert "memories/roles/a.md" not in report["quality_flags"]["low_information_density_pages"]
    assert "memories/roles/b.md" not in report["quality_flags"]["low_information_density_pages"]
    assert report["summary"]["quality_exempt_pages"] == 2
    assert report["summary"]["quality_exemption_missing_reason"] == 1
    assert report["quality_flags"]["quality_exemption_missing_reason"] == ["memories/roles/b.md"]
