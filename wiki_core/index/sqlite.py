from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

# Last '-'-segment of a versioned source_id: the short content digest appended by
# source_id_for (12 hex chars today; tolerant range for older/full digests).
_DIGEST_RE = re.compile(r"^[0-9a-f]{8,64}$")


# Wiki pages are indexed under this source_id prefix so retrieval (integration
# packet, --query) can find EXISTING knowledge, not only ingested sources.
PAGE_SOURCE_PREFIX = "page:"


def _source_prefix(source_id: str) -> str | None:
    """Versionless prefix of a source_id ('source-<slug>' for 'source-<slug>-<digest>').

    Derived by cutting the last segment after the last '-'. Returns None when that
    segment does not look like a content digest (the id is not versioned), so
    arbitrary ids such as 'src-a'/'src-b' are never treated as versions of each
    other.
    """
    base, sep, digest = source_id.rpartition("-")
    if not sep or not _DIGEST_RE.fullmatch(digest):
        return None
    return base


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS chunks (chunk_id TEXT PRIMARY KEY, source_id TEXT, ordinal INTEGER, hash_sha256 TEXT, token_estimate INTEGER, text TEXT)"
    )
    conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(chunk_id UNINDEXED, source_id UNINDEXED, text)")
    return conn


def _delete_source(conn: sqlite3.Connection, source_id: str) -> None:
    conn.execute("DELETE FROM chunks WHERE source_id = ?", (source_id,))
    conn.execute("DELETE FROM chunk_fts WHERE source_id = ?", (source_id,))


def _insert_chunks(conn: sqlite3.Connection, source_id: str, chunks: list[dict[str, object]]) -> int:
    total = 0
    for chunk in chunks:
        conn.execute(
            "INSERT OR REPLACE INTO chunks VALUES (?, ?, ?, ?, ?, ?)",
            (
                chunk["chunk_id"],
                source_id,
                int(chunk["ordinal"]),
                chunk["hash_sha256"],
                int(chunk["token_estimate"]),
                chunk["text"],
            ),
        )
        conn.execute("INSERT INTO chunk_fts VALUES (?, ?, ?)", (chunk["chunk_id"], source_id, chunk["text"]))
        total += 1
    return total


def _prune_previous_versions(conn: sqlite3.Connection, source_id: str) -> int:
    """Remove indexed rows from PREVIOUS versions of the same source.

    A re-ingested edited source gets a new digest, hence a new source_id with the
    same versionless prefix ('source-<slug>-<digest>'). Without this prune, the
    old version kept answering searches forever. Two ids are versions of the same
    source only when both end in a digest-looking segment AND share the prefix up
    to the last '-' — distinct slugs (even ones that are textual prefixes of each
    other, e.g. 'source-notes-*' vs 'source-notes-md-*') are never affected.
    """
    prefix = _source_prefix(source_id)
    if prefix is None:
        return 0
    pruned = 0
    rows = conn.execute(
        "SELECT DISTINCT source_id FROM chunks WHERE source_id != ?", (source_id,)
    ).fetchall()
    for (other,) in rows:
        if _source_prefix(other) == prefix:
            _delete_source(conn, other)
            pruned += 1
    return pruned


def index_source(db_path: Path, chunks_file: Path) -> dict[str, int]:
    """Index (or reindex) ONE source incrementally.

    Replaces the full rebuild on every ingestion (finding 13): only that source's
    rows are deleted and reinserted — O(source's chunks), not O(whole index).
    Also prunes previous DIGESTS of the same source (same versionless prefix),
    so re-ingesting an edited source stops the stale version from answering
    searches.
    """
    data = json.loads(chunks_file.read_text(encoding="utf-8"))
    source_id = str(data.get("source_id", chunks_file.stem))
    conn = _connect(db_path)
    try:
        _delete_source(conn, source_id)
        pruned = _prune_previous_versions(conn, source_id)
        total = _insert_chunks(conn, source_id, data.get("chunks", []))
        conn.commit()
    finally:
        conn.close()
    return {"sources_indexed": 1, "chunks_indexed": total, "pruned_versions": pruned}


def build_index(chunks_dir: Path, db_path: Path) -> dict[str, int]:
    """Full rebuild from the chunks directory (full reindex).

    Kept for reconstruction/integrity; the hot ingestion path uses `index_source`
    (incremental). Here we also PRUNE sources whose chunks file no longer exists,
    so the index does not retain orphans.
    """
    conn = _connect(db_path)
    total = 0
    sources = 0
    present: set[str] = set()
    for path in sorted(chunks_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        source_id = str(data.get("source_id", path.stem))
        present.add(source_id)
        sources += 1
        _delete_source(conn, source_id)
        total += _insert_chunks(conn, source_id, data.get("chunks", []))
    indexed = {row[0] for row in conn.execute("SELECT DISTINCT source_id FROM chunks").fetchall()}
    for orphan in indexed - present:
        if orphan.startswith(PAGE_SOURCE_PREFIX):
            continue  # wiki-page entries are managed by index_pages(), not chunks/
        _delete_source(conn, orphan)
    conn.commit()
    conn.close()
    return {"sources_indexed": sources, "chunks_indexed": total}


def index_pages(db_path: Path, pages: list[tuple[str, list[dict[str, object]]]]) -> dict[str, int]:
    """(Re)index wiki pages: ``pages`` is [(page_id, chunk dicts)]. Replaces every
    existing page: entry (full page reindex — pages are small)."""
    conn = _connect(db_path)
    total = 0
    try:
        indexed = {row[0] for row in conn.execute("SELECT DISTINCT source_id FROM chunks").fetchall()}
        for source_id in indexed:
            if source_id.startswith(PAGE_SOURCE_PREFIX):
                _delete_source(conn, source_id)
        for page_id, chunks in pages:
            total += _insert_chunks(conn, f"{PAGE_SOURCE_PREFIX}{page_id}", chunks)
        conn.commit()
    finally:
        conn.close()
    return {"pages_indexed": len(pages), "chunks_indexed": total}


def prune_index(db_path: Path, keep_source_ids: set[str]) -> dict[str, int]:
    """Remove from the index the sources that are not in ``keep_source_ids``.

    page: entries (wiki pages) are always kept — they are pruned/refreshed by
    index_pages() on rebuild, not by the source GC."""
    if not db_path.exists():
        return {"pruned_sources": 0}
    conn = sqlite3.connect(db_path)
    pruned = 0
    try:
        indexed = {row[0] for row in conn.execute("SELECT DISTINCT source_id FROM chunks").fetchall()}
        for source_id in indexed - keep_source_ids:
            if source_id.startswith(PAGE_SOURCE_PREFIX):
                continue
            _delete_source(conn, source_id)
            pruned += 1
        conn.commit()
    finally:
        conn.close()
    return {"pruned_sources": pruned}


def check_index(db_path: Path) -> dict[str, object]:
    if not db_path.exists():
        return {"exists": False, "chunks": 0, "sources": 0}
    conn = sqlite3.connect(db_path)
    chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    sources = conn.execute("SELECT COUNT(DISTINCT source_id) FROM chunks").fetchone()[0]
    conn.close()
    return {"exists": True, "chunks": chunks, "sources": sources}


def sanitize_fts_query(query: str) -> str:
    """Turn a natural-language query into a safe FTS5 expression.

    Each token becomes a quoted string (internal quotes doubled), preventing
    characters like '/', '-' or quotes from being interpreted as FTS5 syntax and
    breaking the MATCH with an OperationalError. Tokens are combined by implicit
    AND.
    """
    tokens = [t for t in query.replace("\t", " ").split(" ") if t.strip()]
    quoted = ['"' + t.replace('"', '""') + '"' for t in tokens]
    return " ".join(quoted)


def search(db_path: Path, query: str, limit: int = 20) -> list[dict[str, object]]:
    """Search chunks by relevance (BM25). Returns [] for an empty query or missing index."""
    if not db_path.exists():
        return []
    match = sanitize_fts_query(query)
    if not match:
        return []
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT chunk_id, source_id, text, bm25(chunk_fts) AS rank "
            "FROM chunk_fts WHERE chunk_fts MATCH ? ORDER BY rank LIMIT ?",
            (match, int(limit)),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()
    return [
        {"chunk_id": row[0], "source_id": row[1], "text": row[2], "rank": row[3]}
        for row in rows
    ]


def search_detailed(db_path: Path, query: str, limit: int = 20, *, source_ids=None) -> dict:
    """Read the existing FTS index with explicit availability and scope.

    This never creates/schema-upgrades a database. The caller can resolve the
    indexed identities against its catalog; indexed revision/coverage is unknown
    in legacy databases. Filtering happens before ranking's result limit.
    """
    match = sanitize_fts_query(query)
    result = dict(status="invalid_query", query=query, effective_query=match,
                  operator="AND", limit=limit, hits=[], indexed_source_ids=[])
    if not match or type(limit) is not int or not 1 <= limit <= 1000:
        return result
    if not db_path.is_file():
        return {**result, "status": "index_missing"}
    allowed = None if source_ids is None else sorted(set(source_ids))
    conn = None
    try:
        # SQLite mode=ro can create WAL/SHM sidecars. The kit's index producer
        # uses rollback journaling; report other modes without changing them.
        # Header offsets: https://sqlite.org/fileformat.html#file_format_version_numbers
        with db_path.open("rb") as source:
            header = source.read(20)
        if header.startswith(b"SQLite format 3\x00") and header[18:20] != b"\x01\x01":
            return {**result, "status": "index_error", "error": "index_journal_mode_unsupported"}
        conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
        conn.execute("BEGIN")
        result["indexed_source_ids"] = [r[0] for r in conn.execute(
            "SELECT DISTINCT source_id FROM chunks ORDER BY source_id")]
        scope, params = "", [match]
        if allowed is not None:
            scope = " AND chunk_fts.source_id IN (" + ",".join("?" for _ in allowed) + ")" if allowed else " AND 0"
            params.extend(allowed)
        params.append(limit)
        rows = conn.execute(
            "SELECT chunk_fts.chunk_id, chunk_fts.source_id, chunk_fts.text, "
            "bm25(chunk_fts) AS rank, chunks.hash_sha256 FROM chunk_fts "
            "LEFT JOIN chunks ON chunks.chunk_id = chunk_fts.chunk_id "
            "AND chunks.source_id = chunk_fts.source_id "
            "WHERE chunk_fts MATCH ?" + scope + " ORDER BY rank, chunk_fts.chunk_id LIMIT ?",
            params).fetchall()
    except (sqlite3.Error, OSError):
        return {**result, "status": "index_error", "error": "index_unreadable_or_invalid"}
    finally:
        if conn is not None:
            conn.close()
    result["hits"] = [dict(chunk_id=r[0], source_id=r[1], text=r[2], rank=r[3],
                           hash_sha256=r[4]) for r in rows]
    result["status"] = "ok" if rows else "no_matches"
    return result
