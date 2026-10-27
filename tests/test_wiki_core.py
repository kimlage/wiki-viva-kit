"""Offline, deterministic tests for the wiki_core living-wiki kit.

No network, no writes outside tmp_path. These tests exercise the real public
APIs of wiki_core (ids, llm cache/context_pass, index, extractors, source
manifest) using only signatures verified against the source.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wiki_core.extractors.text import extract_source
from wiki_core.ids import sha256_text, slugify
from wiki_core.index.sqlite import build_index, sanitize_fts_query, search
from wiki_core.llm.cache import cache_key
from wiki_core.llm.context_pass import (
    DEFAULT_QUADRANTS,
    RESULT_REQUIRED_KEYS,
    build_context_request,
    read_result,
    source_pending,
    validate_result,
    write_result,
)
from wiki_core.source_manifest import build_manifest


# ---------------------------------------------------------------------------
# ids + cache_key
# ---------------------------------------------------------------------------


def test_cache_key_deterministic_and_stable():
    args = ("chunkhash", "v1", "schema.v2", "deep_context")
    first = cache_key(*args)
    second = cache_key(*args)
    assert first == second
    # A sha256 hex digest is 64 lowercase hex chars.
    assert len(first) == 64
    assert all(c in "0123456789abcdef" for c in first)


def test_cache_key_changes_with_any_input():
    # No longer includes the source hash (finding 4): identical chunks dedupe.
    base = cache_key("chunkhash", "v1", "schema.v2", "deep_context")
    variants = [
        cache_key("OTHER", "v1", "schema.v2", "deep_context"),
        cache_key("chunkhash", "v2", "schema.v2", "deep_context"),
        cache_key("chunkhash", "v1", "OTHER", "deep_context"),
        cache_key("chunkhash", "v1", "schema.v2", "OTHER"),
    ]
    for variant in variants:
        assert variant != base
    # All variants are distinct from one another too.
    assert len(set(variants)) == len(variants)


def test_cache_key_independent_of_source():
    # Same chunk_hash -> same key, regardless of source (dedup).
    a = cache_key("samechunk", "v1", "schema.v2", "deep_context")
    b = cache_key("samechunk", "v1", "schema.v2", "deep_context")
    assert a == b


def test_sha256_text_deterministic():
    assert sha256_text("alpha beta") == sha256_text("alpha beta")
    assert sha256_text("a") != sha256_text("b")
    assert len(sha256_text("anything")) == 64


def test_slugify_normalizes():
    assert slugify("Custo / Receita 2026") == "custo-receita-2026"
    assert slugify("  Hello   World  ") == "hello-world"
    # Falls back to a stable default when nothing usable remains.
    assert slugify("///") == "item"
    assert slugify("") == "item"


# ---------------------------------------------------------------------------
# sanitize_fts_query
# ---------------------------------------------------------------------------


def test_sanitize_fts_query_slash_does_not_raise_and_quotes_term():
    out = sanitize_fts_query("alpha/beta")
    # Single token (no spaces) -> one quoted term, slash kept inside the quotes.
    assert out == '"alpha/beta"'


def test_sanitize_fts_query_splits_on_spaces():
    out = sanitize_fts_query("custo - receita")
    assert out == '"custo" "-" "receita"'
    # Three distinct quoted terms.
    assert out.count('"') == 6


def test_sanitize_fts_query_empty():
    assert sanitize_fts_query("") == ""
    assert sanitize_fts_query("    ") == ""


# ---------------------------------------------------------------------------
# index: build + search
# ---------------------------------------------------------------------------


def _write_chunks_json(chunks_dir: Path) -> None:
    chunks_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "source_id": "source-fixture-abc123",
        "chunks": [
            {
                "chunk_id": "chunk-0001",
                "source_id": "source-fixture-abc123",
                "ordinal": 0,
                "hash_sha256": sha256_text("orcamento mensal agregador"),
                "token_estimate": 7,
                "text": "Monthly budget review and reconciliation notes",
            },
            {
                "chunk_id": "chunk-0002",
                "source_id": "source-fixture-abc123",
                "ordinal": 1,
                "hash_sha256": sha256_text("receita salario investimentos"),
                "token_estimate": 5,
                "text": "Receita de salario e investimentos do periodo.",
            },
        ],
    }
    (chunks_dir / "fixture.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def test_build_index_and_search_returns_correct_chunk(tmp_path):
    chunks_dir = tmp_path / "chunks"
    db_path = tmp_path / "index.sqlite"
    _write_chunks_json(chunks_dir)

    stats = build_index(chunks_dir, db_path)
    assert stats == {"sources_indexed": 1, "chunks_indexed": 2}
    assert db_path.exists()

    results = search(db_path, "salario")
    assert len(results) == 1
    assert results[0]["chunk_id"] == "chunk-0002"
    assert "salario" in results[0]["text"].lower()


def test_search_with_slash_does_not_raise(tmp_path):
    chunks_dir = tmp_path / "chunks"
    db_path = tmp_path / "index.sqlite"
    _write_chunks_json(chunks_dir)
    build_index(chunks_dir, db_path)

    # A '/' in the query must not raise sqlite3.OperationalError; it is sanitized.
    results = search(db_path, "alpha/beta")
    assert isinstance(results, list)

    # Empty query and missing index both return [] without raising.
    assert search(db_path, "") == []
    assert search(tmp_path / "does-not-exist.sqlite", "salario") == []


def test_detailed_search_distinguishes_index_state_without_writing(tmp_path, monkeypatch):
    import sqlite3
    from wiki_core.index import sqlite as index
    missing = tmp_path / "absent" / "wiki.sqlite"
    assert index.search_detailed(missing, "budget")["status"] == "index_missing"
    assert not missing.parent.exists()
    invalid = tmp_path / "invalid.sqlite"
    invalid.write_bytes(b"not sqlite")
    assert index.search_detailed(invalid, "budget")["status"] == "index_error"
    empty_schema = tmp_path / "empty.sqlite"
    sqlite3.connect(empty_schema).close()
    assert index.search_detailed(empty_schema, "budget")["status"] == "index_error"
    chunks = tmp_path / "chunks"
    _write_chunks_json(chunks)
    db = tmp_path / "wiki.sqlite"
    build_index(chunks, db)
    before = db.read_bytes()
    monkeypatch.setattr(index, "_connect", lambda *a: pytest.fail("lookup invoked writer"))
    assert index.search_detailed(db, "unmatched")["status"] == "no_matches"
    assert index.search_detailed(db, " ")["status"] == "invalid_query"
    assert index.search_detailed(db, "budget", limit=0)["status"] == "invalid_query"
    found = index.search_detailed(db, "salario")
    assert found["status"] == "ok" and found["hits"][0]["hash_sha256"]
    assert index.search_detailed(db, "alpha/beta")["status"] == "no_matches"
    assert db.read_bytes() == before


def test_find_filters_context_before_limit_and_reports_provenance_gaps(tmp_path):
    from wiki_core.config import WikiConfig
    from wiki_core.find import find
    from wiki_core.paths import WikiPaths
    cfg = WikiConfig()
    paths = WikiPaths(tmp_path, cfg)
    paths.chunks.mkdir(parents=True)
    paths.source_manifests.mkdir()
    for sid, context in [("source-alpha", "work"), ("source-beta", "personal")]:
        text = "unique search phrase"
        (paths.chunks / f"{sid}.json").write_text(json.dumps(dict(source_id=sid, chunks=[
            dict(chunk_id=sid + "-chunk", ordinal=0, hash_sha256=sha256_text(text), token_estimate=3, text=text)])))
        (paths.source_manifests / f"{sid}.json").write_text(json.dumps(dict(
            schema_version="wiki_source_manifest.v1", source_id=sid, context=context,
            source_uri=f"https://example.test/{sid}", hash_sha256="a" * 64, captured_at="2026-01-01")))
    db = paths.indexes / "wiki.sqlite"
    build_index(paths.chunks, db)
    result = find(tmp_path, cfg, "unique search", context="personal", limit=1)
    assert [h["source_id"] for h in result["hits"]] == ["source-beta"]
    assert result["hits"][0]["provenance"]["locator"] == "https://example.test/source-beta"
    assert result["freshness"] == "not_evaluated"
    assert result["coverage"]["index_revision"] == "unknown"
    # Duplicate metadata must not silently select a context or origin.
    (paths.source_manifests / "duplicate.json").write_bytes((paths.source_manifests / "source-beta.json").read_bytes())
    result = find(tmp_path, cfg, "unique", context="personal")
    assert result["status"] == "no_matches" and result["coverage"]["context_scope"] == "partial"
    assert {"source_id": "source-beta", "reason": "metadata_ambiguous"} in result["scope"]["metadata_gaps"]
    (paths.source_manifests / "source-alpha.json").unlink()
    result = find(tmp_path, cfg, "unique", source_id="source-alpha")
    assert result["status"] == "ok"
    assert result["hits"][0]["provenance"]["status"] == "missing"
    (paths.source_manifests / "broken.json").write_text("{broken")
    assert find(tmp_path, cfg, "unique")["scope"]["catalog_issues"]


def test_find_cli_missing_index_does_not_create_files(tmp_path, monkeypatch, capsys):
    from scripts import wiki_find
    monkeypatch.setattr(wiki_find, "ROOT", tmp_path)
    before = list(tmp_path.rglob("*"))
    assert wiki_find.main(["budget", "--context", "system"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "index_missing"
    assert list(tmp_path.rglob("*")) == before


def test_detailed_search_reports_wal_without_creating_sidecars(tmp_path):
    import sqlite3
    from wiki_core.index.sqlite import search_detailed
    db = tmp_path / "wal.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE retained(value)")
    conn.commit()
    conn.close()
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    result = search_detailed(db, "anything")
    assert result["status"] == "index_error"
    assert result["error"] == "index_journal_mode_unsupported"
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_find_reports_external_catalog_location_without_reading_it(tmp_path):
    from dataclasses import replace
    from wiki_core.config import WikiConfig
    from wiki_core.find import find
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "page.md").write_text("---\npage_id: outside\ncontext: secret\n---\n")
    cfg = WikiConfig()
    cfg = replace(cfg, paths={**cfg.paths, "memory_root": str(outside)})
    result = find(root, cfg, "query")
    assert result["status"] == "index_missing"
    assert result["scope"]["catalog_issues"] == [
        {"kind": "page", "reason": "metadata_path_outside_local_catalog"}]


# ---------------------------------------------------------------------------
# extractors
# ---------------------------------------------------------------------------


def test_extract_csv_yields_rows(tmp_path):
    csv_path = tmp_path / "data.csv"
    csv_path.write_text(
        "data,valor,categoria\n2026-01-01,100,receita\n2026-01-02,50,custo\n",
        encoding="utf-8",
    )
    doc = extract_source(str(csv_path), "table")

    assert doc.source_type == "table"
    assert doc.warnings == []
    lines = doc.text.splitlines()
    assert lines[0] == "data | valor | categoria"
    assert "2026-01-01 | 100 | receita" in lines
    # Header + two data rows -> 3 table_row units.
    assert len(doc.units) == 3
    assert all(u["kind"] == "table_row" for u in doc.units)


def test_extract_binary_source_warns_and_empty_text(tmp_path):
    bin_path = tmp_path / "blob.bin"
    bin_path.write_bytes(b"\x00\x01\x02\x00\xff\xfe binary garbage \x00")
    # Generic source_type routes through _read_text, which refuses raw binary.
    doc = extract_source(str(bin_path), "file")

    assert doc.text == ""
    assert any(w.startswith("unsupported_binary_source") for w in doc.warnings)


# ---------------------------------------------------------------------------
# context_pass: validate / write+read / build_context_request
# ---------------------------------------------------------------------------


def _complete_result(key: str = "cachekey-1") -> dict:
    quadrants = {q: f"conteudo {q}" for q in DEFAULT_QUADRANTS}
    result = {k: [] for k in RESULT_REQUIRED_KEYS}
    result.update(
        {
            "cache_key": key,
            "source_id": "source-fixture-abc123",
            "chunk_id": "chunk-0001",
            "prompt_version": "v1",
            "schema_version": "schema.v2",
            "model_profile": "deep_context",
            "produced_by": "claude-test",
            "quadrants": quadrants,
            "sensitivity": {"has_pii": False},
        }
    )
    return result


def test_validate_result_accepts_complete_result():
    assert validate_result(_complete_result()) == []


def test_validate_result_rejects_empty_quadrant():
    result = _complete_result()
    result["quadrants"]["interior_individual"] = "   "  # blank after strip
    errors = validate_result(result)
    assert "quadrant_empty:interior_individual" in errors


def test_validate_result_rejects_missing_keys():
    result = _complete_result()
    del result["claims"]
    del result["sensitivity"]
    errors = validate_result(result)
    assert "missing_key:claims" in errors
    assert "sensitivity_missing_has_pii" in errors


def test_write_result_and_read_result_round_trip(tmp_path):
    cache_dir = tmp_path / "llm-cache"
    # cache_key must be a sha256 hex digest (write_result validates the shape).
    key = sha256_text("roundtrip-key")
    result = _complete_result(key=key)
    path = write_result(cache_dir, result)
    assert path.exists()
    assert path.name == f"{key}.json"

    loaded = read_result(cache_dir, key)
    assert loaded == result

    # Missing key -> None, no raise.
    assert read_result(cache_dir, "never-written") is None


def test_write_result_rejects_invalid(tmp_path):
    cache_dir = tmp_path / "llm-cache"
    bad = _complete_result()
    del bad["quadrants"]
    with pytest.raises(ValueError):
        write_result(cache_dir, bad)


def test_build_context_request_marks_result_exists_and_counts_pending(tmp_path):
    cache_dir = tmp_path / "llm-cache"
    manifest = {
        "source_id": "source-fixture-abc123",
        "hash_sha256": "deadbeef" * 8,
    }
    chunks = [
        {
            "chunk_id": "chunk-0001",
            "hash_sha256": sha256_text("chunk one"),
            "token_estimate": 4,
            "text": "primeiro trecho",
        },
        {
            "chunk_id": "chunk-0002",
            "hash_sha256": sha256_text("chunk two"),
            "token_estimate": 4,
            "text": "segundo trecho",
        },
    ]
    prompt_version = "v1"
    schema_version = "schema.v2"
    model_profile = "deep_context"

    # Pre-seed a cached result for the FIRST chunk only.
    key0 = cache_key(
        chunks[0]["hash_sha256"], prompt_version, schema_version, model_profile
    )
    write_result(cache_dir, _complete_result(key=key0))

    request = build_context_request(
        manifest,
        chunks,
        cache_dir,
        prompt_version,
        schema_version,
        model_profile,
        prompt_name="context_deep_read",
    )

    assert request["kind"] == "llm_context_request"
    assert request["pending_llm_calls"] == 1
    assert request["cached_calls"] == 1

    rows = {row["chunk_id"]: row for row in request["chunks"]}
    assert rows["chunk-0001"]["result_exists"] is True
    assert rows["chunk-0002"]["result_exists"] is False
    assert rows["chunk-0001"]["cache_key"] == key0

    # source_pending agrees with the request's pending count.
    pending = source_pending(
        manifest, chunks, cache_dir, prompt_version, schema_version, model_profile
    )
    assert pending == 1


def test_build_context_request_includes_perspectives(tmp_path):
    request = build_context_request(
        {"source_id": "source-x", "hash_sha256": "deadbeef" * 8},
        [
            {
                "chunk_id": "chunk-1",
                "hash_sha256": sha256_text("chunk"),
                "text": "text",
            }
        ],
        tmp_path / "cache",
        "v3",
        "wiki_llm_context_pass.v4",
        "deep_context",
        perspectives_required=["perspective-technical"],
        perspectives_optional=["perspective-project"],
        root_entity={"page_id": "root-example", "path": "memories/example/index.md"},
        input_channel={"page_id": "input-channel-docs"},
        quadrant_map={"q4": ["perspective-technical"]},
        quadrant_semantics={
            "q4": {
                "semantic_key": "exterior_collective",
                "aqal_position": "Its / exterior collective",
            }
        },
        quadrant_boundary_rule="Tools and workflows are q4 when they coordinate work.",
        target_pages=["memories/example/index.md"],
        input_stage_status="configured",
    )

    assert request["context_pass_schema_version"] == "wiki_llm_context_pass.v4"
    assert request["perspectives_required"] == ["perspective-technical"]
    assert request["perspectives_optional"] == ["perspective-project"]
    assert request["root_entity"]["page_id"] == "root-example"
    assert request["input_channel"]["page_id"] == "input-channel-docs"
    assert request["quadrant_map"] == {"q4": ["perspective-technical"]}
    assert request["quadrant_semantics"]["q4"]["semantic_key"] == "exterior_collective"
    assert request["quadrant_boundary_rule"] == "Tools and workflows are q4 when they coordinate work."
    assert request["target_pages"] == ["memories/example/index.md"]
    assert request["input_stage_status"] == "configured"
    assert "perspectives" in request["result_required_keys"]


def test_validate_result_v4_requires_perspective_status():
    result = _complete_result()
    result["schema_version"] = "wiki_llm_context_pass.v4"
    result["perspectives_required"] = ["perspective-technical"]
    assert "perspectives_not_object" in validate_result(result)

    result["perspectives"] = {"perspective-technical": {"status": "not_applicable"}}
    assert "perspective_missing_reason:perspective-technical" in validate_result(result)

    result["perspectives"] = {
        "perspective-technical": {
            "status": "not_applicable",
            "reason": "No technical content in this chunk.",
        }
    }
    assert validate_result(result) == []


# ---------------------------------------------------------------------------
# source_manifest.build_manifest
# ---------------------------------------------------------------------------


def test_build_manifest_stable_hash_for_local_file(tmp_path):
    src = tmp_path / "nota.md"
    src.write_text("# Nota\nconteudo estavel\n", encoding="utf-8")

    first = build_manifest(str(src), context="teste")
    second = build_manifest(str(src), context="teste")

    assert first["exists"] is True
    assert first["source_id"]
    assert first["hash_sha256"]
    # Same file content -> same source_id and hash across calls.
    assert first["source_id"] == second["source_id"]
    assert first["hash_sha256"] == second["hash_sha256"]

    # Changing the file content changes the hash and the source_id.
    src.write_text("# Nota\nconteudo diferente\n", encoding="utf-8")
    third = build_manifest(str(src), context="teste")
    assert third["hash_sha256"] != first["hash_sha256"]
    assert third["source_id"] != first["source_id"]
