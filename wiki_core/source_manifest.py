from __future__ import annotations

import datetime as dt
import hashlib
import json
import mimetypes
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


def source_id_for(source: str, digest: str | None) -> str:
    parsed = urlparse(source)
    name = Path(parsed.path).name or parsed.netloc or "source"
    short = digest[:12] if digest else hashlib.sha256(source.encode("utf-8")).hexdigest()[:12]
    return f"source-{slugify(name)}-{short}"


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


def build_manifest(source: str, context: str) -> dict[str, object]:
    parsed = urlparse(source)
    now = dt.datetime.now().replace(microsecond=0).isoformat()
    source_type = classify_source(source)
    manifest: dict[str, object] = {
        "schema_version": "wiki_source_manifest.v1",
        "source_uri": source,
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
                "source_id": source_id_for(source, None),
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
                "source_id": source_id_for(source, digest),
                "hash_sha256": digest,
                "size_bytes": stat.st_size,
                "modified_at": dt.datetime.fromtimestamp(stat.st_mtime).replace(microsecond=0).isoformat(),
            }
        )
        if entry_count is not None:
            manifest["entry_count"] = entry_count
    else:
        manifest.update({"source_id": source_id_for(source, None), "hash_sha256": None, "size_bytes": None})
    return manifest


def write_manifest(manifest: dict[str, object], directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{manifest['source_id']}.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
