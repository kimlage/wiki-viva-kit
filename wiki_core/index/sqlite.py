from __future__ import annotations

import json
import datetime as dt
import re
import sqlite3
from pathlib import Path

_ORIGIN_RE = re.compile(r"^[0-9a-f]{64}$")


# Wiki pages are indexed under this source_id prefix so retrieval (integration
# packet, --query) can find EXISTING knowledge, not only ingested sources.
PAGE_SOURCE_PREFIX = "page:"


def _load_chunks(path: Path) -> dict:
    """Validate complete inputs before opening the index write transaction."""
    if path.is_symlink():
        raise ValueError("chunk artifact must not be a symbolic link")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("chunks"), list):
        raise ValueError("invalid chunk artifact")
    source_id = data.setdefault("source_id", path.stem)
    if not isinstance(source_id, str) or not source_id:
        raise ValueError("invalid source identity")
    origin = data.get("source_origin_id")
    if origin is not None and (not isinstance(origin, str) or not _ORIGIN_RE.fullmatch(origin)
                               or not source_id.startswith(f"source-v2-{origin}-")
                               or path.stem != source_id):
        raise ValueError("source origin does not match chunk artifact identity")
    for chunk in data["chunks"]:
        if not isinstance(chunk, dict) or not all(isinstance(chunk.get(k), str)
                for k in ("chunk_id", "hash_sha256", "text")):
            raise ValueError("invalid chunk row")
        int(chunk["ordinal"])
        int(chunk["token_estimate"])
    return data


def _observation_time(data: dict) -> dt.datetime | None:
    value = data.get("observed_at")
    if not isinstance(value, str) or data.get("extraction_complete") is False:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(dt.timezone.utc) if parsed.tzinfo is not None else None


def _select_observations(documents: list[dict]) -> tuple[list[dict], int]:
    """Newest observed version per proven origin; unordered/tied versions survive.

    Observed time is not a provider revision or factual freshness. Legacy IDs
    without origin evidence stay independent, even when their basenames match.
    """
    from collections import defaultdict
    groups = defaultdict(list)
    identities = set()
    for data in documents:
        if data["source_id"] in identities:
            raise ValueError("duplicate source identity in chunk artifacts")
        identities.add(data["source_id"])
        groups[("origin", data["source_origin_id"]) if data.get("source_origin_id")
               else ("legacy", data["source_id"])].append(data)
    selected, ambiguous = [], 0
    for key, versions in groups.items():
        if key[0] == "legacy":
            selected.extend(versions)
            continue
        ordered = [(date, data) for data in versions if (date := _observation_time(data)) is not None]
        latest = max((date for date, _ in ordered), default=None)
        winners = [data for date, data in ordered if date == latest]
        unordered = [data for data in versions if _observation_time(data) is None]
        # Failed empty extraction is evidence of a gap, never deletion of a
        # previously read version. Nonempty partial content stays explicit.
        winners.extend(data for data in unordered if data["chunks"] or data.get("extraction_complete") is not False)
        ambiguous += int(bool(unordered) or len(winners) > 1)
        selected.extend(winners)
    return selected, ambiguous


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


def index_source(db_path: Path, chunks_file: Path) -> dict[str, int]:
    """Reconcile only the incoming origin using the rebuild selection rule."""
    data = _load_chunks(chunks_file)
    origin = data.get("source_origin_id")
    documents = [data]
    if origin:
        documents = [_load_chunks(path) for path in sorted(chunks_file.parent.glob(f"source-v2-{origin}-*.json"))]
        if any(item.get("source_origin_id") != origin for item in documents):
            raise ValueError("origin candidate lacks matching metadata")
    selected, ambiguous = _select_observations(documents)
    candidate_ids = {item["source_id"] for item in documents}
    selected_ids = {item["source_id"] for item in selected}
    conn = _connect(db_path)
    try:
        with conn:
            indexed = {row[0] for row in conn.execute("SELECT DISTINCT source_id FROM chunks")}
            pruned = len((indexed & candidate_ids) - selected_ids)
            for source_id in candidate_ids:
                _delete_source(conn, source_id)
            total = sum(_insert_chunks(conn, item["source_id"], item["chunks"]) for item in selected)
    finally:
        conn.close()
    result = {"sources_indexed": len(selected), "chunks_indexed": total, "pruned_versions": pruned}
    if ambiguous:
        result["ambiguous_origins"] = ambiguous
    return result


def build_index(chunks_dir: Path, db_path: Path) -> dict[str, int]:
    """Full rebuild from the chunks directory (full reindex).

    Kept for reconstruction/integrity; the hot ingestion path uses `index_source`
    (incremental). Here we also PRUNE sources whose chunks file no longer exists,
    so the index does not retain orphans.
    """
    documents = [_load_chunks(path) for path in sorted(chunks_dir.glob("*.json"))]
    selected, ambiguous = _select_observations(documents)
    conn = _connect(db_path)
    try:
        with conn:
            indexed = {row[0] for row in conn.execute("SELECT DISTINCT source_id FROM chunks")}
            for source_id in indexed:
                if not source_id.startswith(PAGE_SOURCE_PREFIX):
                    _delete_source(conn, source_id)
            total = sum(_insert_chunks(conn, item["source_id"], item["chunks"]) for item in selected)
    finally:
        conn.close()
    result = {"sources_indexed": len(selected), "chunks_indexed": total}
    if ambiguous:
        result["ambiguous_origins"] = ambiguous
    return result


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
