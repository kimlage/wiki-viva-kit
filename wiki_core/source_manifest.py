from __future__ import annotations

import datetime as dt
import hashlib
import json
import mimetypes
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from .ids import sha256_file, slugify


def classify_source(source: str) -> str:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        return "url"
    suffix = Path(source).suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".md", ".markdown", ".txt"}:
        return "markdown"
    if suffix in {".csv", ".tsv"}:
        return "table"
    if suffix in {".xlsx", ".xls"}:
        return "spreadsheet"
    if suffix in {".docx", ".doc"}:
        return "document"
    if suffix in {".eml", ".mbox"}:
        return "email"
    return "file"


def source_origin(source: str, root: Path | None = None) -> dict[str, str]:
    """Identify a locator, not an authenticated account or its permissions."""
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        identity = {"kind": "url", "locator": source}
    else:
        path = Path(source).expanduser().resolve()
        if root is not None and path.is_relative_to(root.resolve()):
            identity = {"kind": "repository_path", "locator": path.relative_to(root.resolve()).as_posix()}
        else:
            identity = {"kind": "file_uri", "locator": path.as_uri()}
    raw = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return {**identity, "id": hashlib.sha256(raw.encode("utf-8")).hexdigest()}


def source_id_for(source: str, digest: str | None, *, root: Path | None = None) -> str:
    parsed = urlparse(source)
    name = Path(parsed.path).name or parsed.netloc or "source"
    origin = source_origin(source, root)["id"]
    version = digest[:16] if digest else "unobserved"
    return f"source-v2-{origin}-{slugify(name)[:48]}-{version}"


def sha256_directory_listing(path: Path) -> tuple[str, int]:
    """DETERMINISTIC hash of a directory's content (finding 3).

    It used to include `int(st_mtime)`: since git clone/checkout rewrites mtimes,
    a directory source's source_id differed between the local machine and a clean
    clone/CI (orphan manifests/chunks, source seemed "changed" without changing).
    Now the hash uses only kind + relative path + size of the FILES, ignores
    dotfiles (.DS_Store, .git) and depends on neither mtime nor directory size
    (platform-dependent).
    """
    entries: list[str] = []
    for child in sorted(path.rglob("*")):
        rel_parts = child.relative_to(path).parts
        if any(part.startswith(".") for part in rel_parts):
            continue  # ignore dotfiles/dotdirs (.DS_Store, .git, ...)
        if not child.is_file():
            continue
        try:
            rel = child.relative_to(path).as_posix()
            size = child.stat().st_size
        except OSError:
            continue
        entries.append(f"file\t{rel}\t{size}")
    payload = "\n".join(entries)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest(), len(entries)


def build_manifest(source: str, context: str, *, root: Path | None = None) -> dict[str, object]:
    parsed = urlparse(source)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    source_type = classify_source(source)
    manifest: dict[str, object] = {
        "schema_version": "wiki_source_manifest.v1",
        "source_uri": source,
        "source_origin": source_origin(source, root),
        "source_type": source_type,
        "context": context,
        "captured_at": now,
        "risk_level": "medium" if source_type in {"pdf", "spreadsheet", "document", "email"} else "low",
        "visibility_initial": "private_self",
        "privacy_policy": "extract_private_operational_context_without_access_secrets",
    }
    if parsed.scheme in {"http", "https"}:
        manifest.update(
            {
                "source_id": source_id_for(source, None, root=root),
                "exists": None,
                "hash_sha256": None,
                "size_bytes": None,
                "mime_type": None,
            }
        )
        return manifest

    path = Path(source).expanduser()
    manifest["absolute_path"] = str(path.resolve()) if path.exists() else str(path)
    manifest["exists"] = path.exists()
    manifest["mime_type"] = mimetypes.guess_type(str(path))[0]
    if path.exists():
        stat = path.stat()
        if path.is_dir():
            digest, entry_count = sha256_directory_listing(path)
        else:
            digest = sha256_file(path)
            entry_count = None
        manifest.update(
            {
                "source_id": source_id_for(source, digest, root=root),
                "hash_sha256": digest,
                "size_bytes": stat.st_size,
                "modified_at": dt.datetime.fromtimestamp(stat.st_mtime).replace(microsecond=0).isoformat(),
            }
        )
        if entry_count is not None:
            manifest["entry_count"] = entry_count
    else:
        manifest.update({"source_id": source_id_for(source, None, root=root), "hash_sha256": None, "size_bytes": None})
    return manifest


def write_manifest(manifest: dict[str, object], directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{manifest['source_id']}.json"
    write_source_artifact(path, manifest)
    return path


def chunk_document(manifest: dict, chunks: list[dict], *, warnings=()) -> dict:
    """The pipeline and extraction CLI persist the same origin/version evidence."""
    return dict(schema_version="wiki_chunks.v1", source_id=manifest["source_id"],
                source_hash_sha256=manifest.get("hash_sha256"),
                source_origin_id=manifest["source_origin"]["id"],
                observed_at=manifest["captured_at"], extraction_complete=not bool(warnings), chunks=chunks)


def write_source_artifact(path: Path, payload: dict) -> None:
    """Publish one complete derived JSON; readers never see a truncated write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".source-", suffix=".tmp", delete=False) as out:
            temporary = Path(out.name)
            out.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
