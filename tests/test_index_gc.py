"""Incremental indexing + orphan garbage collection (finding 13, scale).

- index_source reindexes ONE source without a full rebuild.
- prune_index removes sources outside the keep set.
- wiki_gc safely lists/removes orphan derived artifacts.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wiki_core.index.sqlite import build_index, check_index, index_source, prune_index, search


def _write_chunks(directory: Path, source_id: str, texts: list[str]) -> Path:
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
        json.dumps({"source_id": source_id, "chunks": chunks}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


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
    old = _write_chunks(chunks_dir, "source-notes-md-aaaaaaaaaaaa", ["stale content about gates"])
    index_source(db, old)
    assert search(db, "stale"), "sanity: the old version answers searches"

    # Re-ingestion of the edited source: same slug, new digest.
    new = _write_chunks(chunks_dir, "source-notes-md-bbbbbbbbbbbb", ["fresh content about gates"])
    res = index_source(db, new)
    assert res["pruned_versions"] == 1

    info = check_index(db)
    assert info["sources"] == 1
    assert {h["source_id"] for h in search(db, "gates")} == {"source-notes-md-bbbbbbbbbbbb"}
    assert search(db, "stale") == []


def test_index_source_prune_does_not_cross_distinct_slugs(tmp_path: Path) -> None:
    chunks_dir = tmp_path / "chunks"
    db = tmp_path / "wiki.sqlite"
    index_source(db, _write_chunks(chunks_dir, "source-notes-aaaaaaaaaaaa", ["alfa notes"]))
    # Slug 'notes-md' shares the textual prefix 'source-notes-' but is ANOTHER source.
    index_source(db, _write_chunks(chunks_dir, "source-notes-md-bbbbbbbbbbbb", ["beta manual"]))
    index_source(db, _write_chunks(chunks_dir, "source-other-dddddddddddd", ["gamma other"]))

    # Re-ingesting 'notes' with a new digest prunes only its own old version.
    res = index_source(db, _write_chunks(chunks_dir, "source-notes-cccccccccccc", ["alfa notes v2"]))
    assert res["pruned_versions"] == 1

    assert check_index(db)["sources"] == 3
    hits = {h["source_id"] for h in search(db, "notes") + search(db, "beta") + search(db, "gamma")}
    assert "source-notes-cccccccccccc" in hits
    assert "source-notes-md-bbbbbbbbbbbb" in hits
    assert "source-other-dddddddddddd" in hits
    assert "source-notes-aaaaaaaaaaaa" not in hits


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
    def __init__(self, base: Path, config):
        self.config = config
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

    class _Cfg:
        paths = {"memory_root": "memorias"}

    paths = _Paths(base, _Cfg())
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
    gc = _load_gc()
    ingest = tmp_path / "memorias" / "sistema" / "ingestao"
    _proposal(ingest / "ok.md", "approved", "src-live")
    _proposal(ingest / "old.md", "superseded", "src-superseded")
    # rejected is terminal too: its artifacts must be collectable, like superseded.
    _proposal(ingest / "no.md", "rejected", "src-rejected")
    # arquivo/ is not scanned (flat glob by design): archived sources are non-live.
    _proposal(ingest / "arquivo" / "gone.md", "archived", "src-archived")

    class _Cfg:
        paths = {"memory_root": "memorias"}

    paths = _Paths(tmp_path / "derived", _Cfg())
    assert gc.live_source_ids(tmp_path, paths) == {"src-live"}
