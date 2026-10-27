"""Incremental indexing + orphan garbage collection (finding 13, scale).

- index_source reindexes ONE source without a full rebuild.
- prune_index removes sources outside the keep set.
- wiki_gc safely lists/removes orphan derived artifacts.
"""

from __future__ import annotations

import importlib.util
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wiki_core.config import WikiConfig, load_config
from wiki_core.index.sqlite import build_index, check_index, index_source, prune_index, search
from wiki_core.paths import WikiPaths
from wiki_core.source_manifest import source_id_for, source_origin


def _write_chunks(directory: Path, source_id: str, texts: list[str], **metadata) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{source_id}.json"
    chunks = [
        {
            "chunk_id": f"{source_id}-{i}",
            "ordinal": i,
            "hash_sha256": f"hash-{source_id}-{i}",
            "token_estimate": len(t.split()),
            "text": t,
        }
        for i, t in enumerate(texts)
    ]
    path.write_text(
        json.dumps({"source_id": source_id, "chunks": chunks, **metadata}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def _observation(directory, source, texts, at, **metadata):
    digest = hashlib.sha256("\n".join(texts).encode()).hexdigest()
    origin = source_origin(str(source), directory.parent)
    source_id = source_id_for(str(source), digest, root=directory.parent)
    return _write_chunks(directory, source_id, texts, source_origin_id=origin["id"],
                         observed_at=at, extraction_complete=True, **metadata)


def test_index_source_incremental(tmp_path: Path) -> None:
    chunks_dir = tmp_path / "chunks"
    db = tmp_path / "wiki.sqlite"
    a = _write_chunks(chunks_dir, "src-a", ["alfa gate ingestao", "beta cockpit"])
    b = _write_chunks(chunks_dir, "src-b", ["gamma frescor auditoria"])

    index_source(db, a)
    index_source(db, b)
    assert check_index(db)["chunks"] == 3
    assert check_index(db)["sources"] == 2

    # Reindexing source A (with fewer chunks) only affects A, not B.
    a2 = _write_chunks(chunks_dir, "src-a", ["alfa atualizado"])
    index_source(db, a2)
    info = check_index(db)
    assert info["chunks"] == 2  # 1 from A (new) + 1 from B (intact)
    assert info["sources"] == 2
    assert any(h["source_id"] == "src-b" for h in search(db, "gamma"))


def test_index_source_prunes_previous_digests_of_same_source(tmp_path: Path) -> None:
    chunks_dir = tmp_path / "chunks"
    db = tmp_path / "wiki.sqlite"
    old = _observation(chunks_dir, tmp_path / "notes.md", ["stale content about gates"], "2026-01-01T00:00:00Z")
    index_source(db, old)
    assert search(db, "stale"), "sanity: the old version answers searches"

    # Re-ingestion of the edited source: same slug, new digest.
    new = _observation(chunks_dir, tmp_path / "notes.md", ["fresh content about gates"], "2026-01-02T00:00:00Z")
    res = index_source(db, new)
    assert res["pruned_versions"] == 1

    info = check_index(db)
    assert info["sources"] == 1
    assert {h["source_id"] for h in search(db, "gates")} == {new.stem}
    assert search(db, "stale") == []
    index_source(db, old)  # receiving an older observation cannot restore it
    assert search(db, "stale") == []
    build_index(chunks_dir, db)
    assert search(db, "stale") == []
    assert {h["source_id"] for h in search(db, "gates")} == {new.stem}


def test_legacy_ids_without_origin_are_not_pruned_by_slug(tmp_path: Path) -> None:
    chunks_dir = tmp_path / "chunks"
    db = tmp_path / "wiki.sqlite"
    index_source(db, _write_chunks(chunks_dir, "source-notes-aaaaaaaaaaaa", ["alfa notes"]))
    # Slug 'notes-md' shares the textual prefix 'source-notes-' but is ANOTHER source.
    index_source(db, _write_chunks(chunks_dir, "source-notes-md-bbbbbbbbbbbb", ["beta manual"]))
    index_source(db, _write_chunks(chunks_dir, "source-other-dddddddddddd", ["gamma other"]))

    # A digest-looking suffix and matching name do not prove common origin.
    res = index_source(db, _write_chunks(chunks_dir, "source-notes-cccccccccccc", ["alfa notes v2"]))
    assert res["pruned_versions"] == 0

    assert check_index(db)["sources"] == 4
    hits = {h["source_id"] for h in search(db, "notes") + search(db, "beta") + search(db, "gamma")}
    assert "source-notes-cccccccccccc" in hits
    assert "source-notes-md-bbbbbbbbbbbb" in hits
    assert "source-other-dddddddddddd" in hits
    assert "source-notes-aaaaaaaaaaaa" in hits


def test_same_named_origins_and_same_content_stay_distinct(tmp_path):
    folder, db = tmp_path / "chunks", tmp_path / "wiki.sqlite"
    a = _observation(folder, tmp_path / "north/report.md", ["identical content"], "2026-01-01T00:00:00Z")
    b = _observation(folder, tmp_path / "south/report.md", ["identical content"], "2026-01-02T00:00:00Z")
    assert a != b
    index_source(db, a)
    index_source(db, b)
    assert {hit["source_id"] for hit in search(db, "identical")} == {a.stem, b.stem}
    build_index(folder, db)
    assert {hit["source_id"] for hit in search(db, "identical")} == {a.stem, b.stem}


def test_empty_observation_removes_previous_text_on_both_paths(tmp_path):
    folder, db = tmp_path / "chunks", tmp_path / "wiki.sqlite"
    old = _observation(folder, tmp_path / "report.md", ["historical token"], "2026-01-01T00:00:00Z")
    index_source(db, old)
    empty = _observation(folder, tmp_path / "report.md", [], "2026-01-02T00:00:00Z")
    index_source(db, empty)
    assert search(db, "historical") == []
    index_source(db, old)
    assert search(db, "historical") == []
    build_index(folder, db)
    assert search(db, "historical") == []


def test_tied_or_unordered_observations_are_retained_explicitly(tmp_path):
    for timestamp in ["2026-01-02T00:00:00Z", "2026-01-03T00:00:00", None, "bad"]:
        case = tmp_path / str(timestamp).replace(":", "-")
        folder, db = case / "chunks", case / "wiki.sqlite"
        a = _observation(folder, case / "notes.md", ["first token"], "2026-01-02T00:00:00Z")
        b = _observation(folder, case / "notes.md", ["second token"], timestamp)
        result = index_source(db, b)
        assert result["ambiguous_origins"] == 1
        expected = {a.stem, b.stem}
        assert {hit["source_id"] for hit in search(db, "token")} == expected
        assert build_index(folder, db)["ambiguous_origins"] == 1
        assert {hit["source_id"] for hit in search(db, "token")} == expected


def test_bad_origin_neighbor_does_not_partially_prune_index(tmp_path):
    import pytest
    folder, db = tmp_path / "chunks", tmp_path / "wiki.sqlite"
    old = _observation(folder, tmp_path / "notes.md", ["retained token"], "2026-01-01T00:00:00Z")
    index_source(db, old)
    newer = _observation(folder, tmp_path / "notes.md", ["new token"], "2026-01-02T00:00:00Z")
    newer.write_text('{"truncated":')
    with pytest.raises(ValueError):
        index_source(db, old)
    assert {hit["source_id"] for hit in search(db, "retained")} == {old.stem}
    with pytest.raises(ValueError):
        build_index(folder, db)
    assert {hit["source_id"] for hit in search(db, "retained")} == {old.stem}


def test_index_source_keeps_ids_without_digest_suffix(tmp_path: Path) -> None:
    # Ids whose last segment is not a content digest are never treated as
    # versions of each other ('src-a' must not prune 'src-b').
    chunks_dir = tmp_path / "chunks"
    db = tmp_path / "wiki.sqlite"
    index_source(db, _write_chunks(chunks_dir, "src-a", ["alfa"]))
    res = index_source(db, _write_chunks(chunks_dir, "src-b", ["beta"]))
    assert res["pruned_versions"] == 0
    assert check_index(db)["sources"] == 2
    assert search(db, "alfa") and search(db, "beta")


def test_prune_index_removes_unkept_sources(tmp_path: Path) -> None:
    chunks_dir = tmp_path / "chunks"
    db = tmp_path / "wiki.sqlite"
    index_source(db, _write_chunks(chunks_dir, "src-a", ["alfa"]))
    index_source(db, _write_chunks(chunks_dir, "src-b", ["beta"]))
    res = prune_index(db, keep_source_ids={"src-a"})
    assert res["pruned_sources"] == 1
    assert check_index(db)["sources"] == 1
    assert search(db, "beta") == []


def test_build_index_prunes_missing_sources(tmp_path: Path) -> None:
    chunks_dir = tmp_path / "chunks"
    db = tmp_path / "wiki.sqlite"
    _write_chunks(chunks_dir, "src-a", ["alfa"])
    _write_chunks(chunks_dir, "src-b", ["beta"])
    build_index(chunks_dir, db)
    assert check_index(db)["sources"] == 2
    # Remove B's file from disk and rebuild: B drops out of the index.
    (chunks_dir / "src-b.json").unlink()
    build_index(chunks_dir, db)
    assert check_index(db)["sources"] == 1
    assert search(db, "beta") == []


# --------------------------------------------------------------------------- #
# wiki_gc
# --------------------------------------------------------------------------- #


def _load_gc():
    spec = importlib.util.spec_from_file_location("wiki_gc", ROOT / "scripts" / "wiki_gc.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["wiki_gc"] = module
    spec.loader.exec_module(module)
    return module


class _Paths:
    """Minimal stand-in for WikiPaths exposing only the derived-artifact dirs."""

    def __init__(self, base: Path):
        self.source_manifests = base / "source-manifests"
        self.source_text = base / "source-text"
        self.chunks = base / "chunks"
        self.extraction_events = base / "extraction-events"
        self.indexes = base / "indexes"


def test_gc_finds_orphans(tmp_path: Path) -> None:
    gc = _load_gc()
    base = tmp_path / "derived"
    for d in ("source-manifests", "chunks", "extraction-events"):
        (base / d).mkdir(parents=True)
    # src-live is referenced; src-orphan is not.
    (base / "source-manifests" / "src-live.json").write_text("{}", encoding="utf-8")
    (base / "source-manifests" / "src-orphan.json").write_text("{}", encoding="utf-8")
    (base / "chunks" / "src-orphan.json").write_text("{}", encoding="utf-8")
    (base / "extraction-events" / "src-orphan-llm-context-request.json").write_text("{}", encoding="utf-8")

    paths = _Paths(base)
    orphans = gc.find_orphans(paths, live={"src-live"})
    flat = {p.name for v in orphans.values() for p in v}
    assert "src-orphan.json" in flat
    assert "src-orphan-llm-context-request.json" in flat
    assert "src-live.json" not in flat


def test_gc_source_id_of_request(tmp_path: Path) -> None:
    gc = _load_gc()
    p = tmp_path / "abc123-llm-context-request.json"
    assert gc._source_id_of(p) == "abc123"
    q = tmp_path / "def456.json"
    assert gc._source_id_of(q) == "def456"


def _proposal(path: Path, state: str, source_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        f"gate_state: {state}\n"
        f"manifest_ref: data/derived/source-manifests/{source_id}.json\n"
        "---\n\n# proposal\n",
        encoding="utf-8",
    )


def test_live_source_ids_excludes_rejected_and_archived(tmp_path: Path) -> None:
    # English default layout (no `paths` pin): memories/system/ingestion.
    gc = _load_gc()
    paths = WikiPaths(tmp_path, WikiConfig())
    ingest = paths.ingest_dir
    assert ingest == tmp_path / "memories" / "system" / "ingestion"
    _proposal(ingest / "ok.md", "approved", "src-live")
    _proposal(ingest / "old.md", "superseded", "src-superseded")
    # rejected is terminal too: its artifacts must be collectable, like superseded.
    _proposal(ingest / "no.md", "rejected", "src-rejected")
    # archive/ is not scanned (flat glob by design): archived sources are non-live.
    _proposal(ingest / "archive" / "gone.md", "archived", "src-archived")

    assert gc.live_source_ids(paths) == {"src-live"}


def test_live_source_ids_follows_localized_layout(tmp_path: Path) -> None:
    # Compatibility for localized repos: a wiki.config.yaml pinning the pt
    # layout must drive the scan to memorias/sistema/ingestao.
    gc = _load_gc()
    (tmp_path / "wiki.config.yaml").write_text(
        "language: pt\n"
        "default_context: sistema\n"
        "paths:\n"
        "  memory_root: memorias\n"
        "  system_dirname: sistema\n"
        "  ingest_dirname: ingestao\n"
        "  archive_dirname: arquivo\n",
        encoding="utf-8",
    )
    paths = WikiPaths(tmp_path, load_config(tmp_path))
    ingest = paths.ingest_dir
    assert ingest == tmp_path / "memorias" / "sistema" / "ingestao"
    _proposal(ingest / "ok.md", "approved", "src-live")
    _proposal(ingest / "old.md", "superseded", "src-superseded")
    _proposal(ingest / "arquivo" / "gone.md", "archived", "src-archived")

    assert gc.live_source_ids(paths) == {"src-live"}
