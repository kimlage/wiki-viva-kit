"""Tests for the consolidation layer (the integration half of ingestion):
aggregate from llm-cache, event generation, integration packet, pending check,
the audit_consolidation gate and wiki-page indexing."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wiki_core.config import WikiConfig
from wiki_core.consolidate import (
    aggregate_results,
    build_event_markdown,
    build_packet,
    deep_read_complete,
    pending_consolidations,
)
from wiki_core.chunking import chunk_text
from wiki_core.index import PAGE_SOURCE_PREFIX, build_index, index_pages, index_source, prune_index
from wiki_core.index.sqlite import search
from wiki_core.paths import WikiPaths

SOURCE_ID = "source-test-doc-abcdef123456"


def _result(key: str, ordinal: int) -> dict[str, object]:
    return {
        "cache_key": key,
        "source_id": SOURCE_ID,
        "chunk_id": f"c{ordinal}",
        "prompt_version": "v2",
        "schema_version": "s",
        "model_profile": "m",
        "produced_by": "claude",
        "quadrants": {
            "interior_individual": f"Ana wants the migration (chunk {ordinal}).",
            "exterior_individual": "Bruno shipped the fix.",
            "interior_collective": "absent: technical chunk",
            "exterior_collective": "Deploys go through Jira weekly.",
        },
        "quadrant_confidence": {
            "interior_individual": "high",
            "exterior_individual": "medium" if ordinal else "high",
            "interior_collective": "low",
            "exterior_collective": "high",
        },
        "entities": [{"name": "Ana Souza", "type": "person"}],
        "claims": [{"claim": f"Deploy is weekly and manual (chunk {ordinal}).",
                    "status_epistemologico": "fato", "chunk_id": f"c{ordinal}"}],
        "decisions": [{"decision": "Prioritize the Q3 migration"}],
        "actions": [{"action": "Open the card", "owner": "Bruno"}],
        "risks": ["Tight window"],
        "uncertainties": ["Exact freeze date"],
        "relationships": [{"from": "Ana Souza", "to": "Q3 migration", "kind": "owns"}],
        "sensitivity": {"has_pii": False, "notes": ""},
    }


@pytest.fixture()
def repo(tmp_path):
    cfg = WikiConfig()  # English defaults
    paths = WikiPaths(tmp_path, cfg)
    paths.ensure()
    (tmp_path / "memories/system/ingestion/events").mkdir(parents=True)
    keys = ["a" * 64, "b" * 64]
    for i, key in enumerate(keys):
        (paths.llm_cache / f"{key}.json").write_text(json.dumps(_result(key, i)), encoding="utf-8")
    request = {
        "source_id": SOURCE_ID,
        "prompt_version": "v2",
        "chunks": [{"cache_key": keys[0], "ordinal": 0}, {"cache_key": keys[1], "ordinal": 1}],
    }
    (paths.extraction_events / f"{SOURCE_ID}-llm-context-request.json").write_text(
        json.dumps(request), encoding="utf-8"
    )
    return tmp_path, cfg, paths, request


def test_aggregate_merges_and_keeps_worst_confidence(repo):
    _, _, paths, request = repo
    agg = aggregate_results(request, paths.llm_cache)
    assert len(agg["claims"]) == 2  # distinct chunk claims survive dedup
    assert len(agg["decisions"]) == 1  # identical decisions deduped
    assert agg["quadrant_confidence"]["exterior_individual"] == "medium"  # worst wins
    assert agg["quadrants"]["interior_collective"].startswith("absent:")


def test_deep_read_complete_requires_every_chunk(repo):
    _, _, paths, request = repo
    assert deep_read_complete(request, paths.llm_cache)
    request_missing = {**request, "chunks": request["chunks"] + [{"cache_key": "c" * 64}]}
    assert not deep_read_complete(request_missing, paths.llm_cache)


@pytest.mark.parametrize("language, forbidden", [("en", "A preencher"), ("pt", "To fill in")])
def test_event_markdown_is_specific_never_placeholder(repo, language, forbidden):
    tmp, _, paths, request = repo
    cfg = WikiConfig(language=language)
    agg = aggregate_results(request, paths.llm_cache)
    md = build_event_markdown(
        agg, config=cfg, context="system", date=dt.date(2026, 6, 11),
        event_dir=paths.ingest_events_dir, root=tmp,
    )
    assert forbidden not in md
    assert "Ana wants the migration" in md          # real content from the cache
    assert f"source_id: {SOURCE_ID}" in md           # gate hook
    assert "consolidated_into: []" in md             # integration to close
    assert "affected_pages: {must_update: [], should_review: []}" in md
    assert "impact_closure:" in md
    assert "| Tight window" not in md                # risks are bullets, not table rows


def test_pending_lifecycle_until_consolidated(repo):
    tmp, cfg, paths, request = repo
    pend = pending_consolidations(tmp, cfg)
    assert [p["state"] for p in pend] == ["missing_event"]

    agg = aggregate_results(request, paths.llm_cache)
    md = build_event_markdown(
        agg, config=cfg, context="system", date=dt.date(2026, 6, 11),
        event_dir=paths.ingest_events_dir, root=tmp,
    )
    event = paths.ingest_events_dir / "2026-06-11-test-doc.md"
    event.write_text(md, encoding="utf-8")
    assert [p["state"] for p in pending_consolidations(tmp, cfg)] == ["missing_consolidated_into"]

    event.write_text(
        md.replace("consolidated_into: []", "consolidated_into:\n  - memories/index.md"),
        encoding="utf-8",
    )
    assert pending_consolidations(tmp, cfg) == []


def test_packet_finds_entity_pages_and_claim_overlaps(repo):
    tmp, cfg, paths, request = repo
    (tmp / "memories/people").mkdir(parents=True)
    (tmp / "memories/people/ana.md").write_text(
        '---\npage_id: person-ana\npage_type: person\ntitle: "Ana Souza"\n---\n# Ana Souza\n',
        encoding="utf-8",
    )
    (tmp / "memories/claims").mkdir(parents=True)
    (tmp / "memories/claims/deploy.md").write_text(
        '---\npage_id: claim-deploy-weekly\npage_type: claim\ntitle: "Deploy is weekly and manual"\n---\n',
        encoding="utf-8",
    )
    agg = aggregate_results(request, paths.llm_cache)
    packet = build_packet(agg, tmp, cfg, paths)
    assert packet["schema_version"] == "wiki_integration_packet.v2"
    ana = next(e for e in packet["entities"] if e["entity"] == "Ana Souza")
    assert ana["pages"] and ana["pages"][0]["page_id"] == "person-ana"
    assert packet["claims"][0]["overlapping_claims"], "claim overlap should be detected"
    assert packet["claims"][0]["potential_conflict"] is True
    assert "memories/people/ana.md" in packet["impact"]["should_review"]


# --------------------------------------------------------------------------- #
# audit_consolidation gate
# --------------------------------------------------------------------------- #


def _load_audit():
    path = ROOT / "scripts" / "wiki_audit.py"
    spec = importlib.util.spec_from_file_location("wiki_audit_consolidation_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _event_text(consolidated: str, claims_bullet: str = "- Deploy is weekly.") -> str:
    return (
        "---\n"
        "page_id: event-x\n"
        f"source_id: {SOURCE_ID}\n"
        "source_ref: source-test\n"
        f"{consolidated}\n"
        "---\n\n"
        "## Candidate claims\n\n"
        f"{claims_bullet}\n"
    )


def test_audit_consolidation_bites_and_passes(tmp_path, monkeypatch):
    audit = _load_audit()
    cfg = WikiConfig()
    events = tmp_path / "memories/system/ingestion/events"
    events.mkdir(parents=True)
    target = tmp_path / "memories/index.md"
    target.write_text(
        "---\npage_id: memories-index\nsource_refs:\n  - source-test\n---\n", encoding="utf-8"
    )
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    audit.parse_frontmatter.cache_clear()

    # 1) new event without consolidated_into -> ERROR
    (events / "e1.md").write_text(_event_text("consolidated_into: []"), encoding="utf-8")
    errors, warnings = [], []
    audit.audit_consolidation(errors, warnings, cfg)
    assert any("no consolidated_into" in e for e in errors)

    # 2) consolidated into a page that references the source back + claims noted -> clean
    (events / "e1.md").write_text(
        _event_text("consolidated_into:\n  - memories/index.md\nsem_claim: synthesis merged into hub"),
        encoding="utf-8",
    )
    audit.parse_frontmatter.cache_clear()
    errors, warnings = [], []
    audit.audit_consolidation(errors, warnings, cfg)
    assert errors == []

    # 3) target without the reverse source_refs -> ERROR
    target.write_text("---\npage_id: memories-index\nsource_refs: []\n---\n", encoding="utf-8")
    audit.parse_frontmatter.cache_clear()
    errors, warnings = [], []
    audit.audit_consolidation(errors, warnings, cfg)
    assert any("does not reference the source back" in e for e in errors)

    # 4) legacy event (no source_id) -> warning only
    (events / "e1.md").write_text("---\npage_id: old\n---\n## Quadrantes\n", encoding="utf-8")
    audit.parse_frontmatter.cache_clear()
    errors, warnings = [], []
    audit.audit_consolidation(errors, warnings, cfg)
    assert errors == [] and any("legacy event" in w for w in warnings)


def test_claims_cannot_be_skipped_silently(tmp_path, monkeypatch):
    audit = _load_audit()
    cfg = WikiConfig()
    events = tmp_path / "memories/system/ingestion/events"
    events.mkdir(parents=True)
    (tmp_path / "memories/index.md").write_text(
        "---\npage_id: memories-index\nsource_refs:\n  - source-test\n---\n", encoding="utf-8"
    )
    (events / "e1.md").write_text(
        _event_text("consolidated_into:\n  - memories/index.md"), encoding="utf-8"
    )
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    audit.parse_frontmatter.cache_clear()
    errors, warnings = [], []
    audit.audit_consolidation(errors, warnings, cfg)
    assert any("claim breakdown cannot be skipped" in e for e in errors)


def test_audit_impact_closure_requires_closure_and_reason(tmp_path, monkeypatch):
    audit = _load_audit()
    cfg = WikiConfig(audit={**WikiConfig().audit, "impact_closure_check": True})
    events = tmp_path / "memories/system/ingestion/events"
    events.mkdir(parents=True)
    monkeypatch.setattr(audit, "ROOT", tmp_path)

    event = events / "e1.md"
    event.write_text(
        "---\n"
        "page_id: event-x\n"
        "affected_pages:\n"
        "  must_update:\n"
        "    - memories/projects/x.md\n"
        "impact_closure:\n"
        "  updated: []\n"
        "  no_change: []\n"
        "  blocked: []\n"
        "---\n",
        encoding="utf-8",
    )
    errors: list[str] = []
    audit.audit_impact_closure(errors, cfg)
    assert any("not closed" in error for error in errors)

    event.write_text(
        "---\n"
        "page_id: event-x\n"
        "affected_pages:\n"
        "  must_update:\n"
        "    - memories/projects/x.md\n"
        "impact_closure:\n"
        "  updated: []\n"
        "  no_change:\n"
        "    - page: memories/projects/x.md\n"
        "      reason: duplicate of existing status\n"
        "  blocked: []\n"
        "---\n",
        encoding="utf-8",
    )
    errors = []
    audit.audit_impact_closure(errors, cfg)
    assert errors == []


# --------------------------------------------------------------------------- #
# Wiki-page indexing
# --------------------------------------------------------------------------- #


def test_index_pages_searchable_and_survives_rebuild_and_prune(tmp_path):
    db = tmp_path / "wiki.sqlite"
    chunks_dir = tmp_path / "chunks"
    chunks_dir.mkdir()
    source_chunks = [
        {"chunk_id": "s1", "ordinal": 0, "hash_sha256": "h1", "token_estimate": 5,
         "text": "ledger reconciliation rules"}
    ]
    (chunks_dir / "src.json").write_text(
        json.dumps({"source_id": "source-x-abcdef123456", "chunks": source_chunks}), encoding="utf-8"
    )
    build_index(chunks_dir, db)

    page_chunks = chunk_text("page:claim-deploy", "The deploy is weekly and manual via Jira.", 100, 10)
    rows = [{"chunk_id": c.chunk_id, "ordinal": c.ordinal, "hash_sha256": c.hash_sha256,
             "token_estimate": c.token_estimate, "text": c.text} for c in page_chunks]
    index_pages(db, [("claim-deploy", rows)])

    hits = search(db, '"deploy"', limit=5)
    assert any(str(h["source_id"]).startswith(PAGE_SOURCE_PREFIX) for h in hits)

    # full rebuild from chunks/ must NOT orphan-prune page entries
    build_index(chunks_dir, db)
    hits = search(db, '"deploy"', limit=5)
    assert any(str(h["source_id"]).startswith(PAGE_SOURCE_PREFIX) for h in hits)

    # GC prune keeps page entries even when not in keep set
    prune_index(db, {"source-x-abcdef123456"})
    hits = search(db, '"deploy"', limit=5)
    assert any(str(h["source_id"]).startswith(PAGE_SOURCE_PREFIX) for h in hits)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
