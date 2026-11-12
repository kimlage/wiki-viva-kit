#!/usr/bin/env python3
"""Publish authorized non-versioned artifacts to Drive and record their links.

Invoke only for authorized files and destination, under the wiki's privacy and
secret rules. WIKI_DRIVE_FOLDER_ID in .env selects the destination; the existing
local Google Workspace helper supplies account access. Configuration is not
authorization. Updates check manifest IDs against that folder first; a name
collision without a manifest ID requires reconciliation, not an arbitrary update.
Dry-run reads only local files and the local manifest; it does not authenticate,
contact Drive, verify remote state, or change files.

Coordinate writers and reconcile uncertain effects before repeating an upload.
Metadata checks are not atomic preconditions; manifest replacement is not CAS.
Cross-host concurrency and interrupted-effect recovery remain open in issue #234:
https://github.com/kimlage/wiki-viva-kit/issues/234.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import logging
import mimetypes
import os
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wiki_core.detectors import contains_secret_structure, scan_text  # noqa: E402
from wiki_core.extractors.text import extract_captured  # noqa: E402

MANIFEST_PATH = ROOT / "data" / "drive_artifacts_manifest.json"
ENV_PATH = ROOT / ".env"


class _RefusePDFDiagnostic(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        # A parser warning may contain source values even in strict mode.
        raise ValueError("PDF content validation unavailable")


def load_env(path: Path = ENV_PATH) -> dict[str, str]:
    """Minimal .env parser (KEY=VALUE, no expansion; comments with #)."""
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip("\"'")
    return env


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_container_coverage(suffix: str, raw: bytes) -> None:
    """Refuse known parts omitted by the body extractors, using captured bytes.

    Office content types identify parts even when their ZIP paths are renamed.
    PDF page dictionaries must be parsed: annotations can be encoded or stored
    in compressed objects and need not contain a searchable raw marker.
    """
    if suffix in {".docx", ".xlsx"}:
        omitted_types = (
            "wordprocessingml.header+", "wordprocessingml.footer+",
            "wordprocessingml.comments+", "wordprocessingml.footnotes+",
            "wordprocessingml.endnotes+", "spreadsheetml.comments+",
            "threadedcomments+",
        )
        word_ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        omitted_roots = {word_ns + name for name in ("hdr", "ftr", "comments", "footnotes", "endnotes")}
        omitted_roots.update({
            "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}comments",
            "{http://schemas.microsoft.com/office/spreadsheetml/2018/threadedcomments}ThreadedComments",
        })
        omitted_relations = {"header", "footer", "comments", "footnotes", "endnotes", "threadedcomment"}
        # extract_captured has already enforced the protected archive limits.
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            content_types = ET.fromstring(archive.read("[Content_Types].xml"))
            if any(any(kind in part.get("ContentType", "").lower() for kind in omitted_types)
                   for part in content_types):
                raise ValueError("Office part not covered by content extraction")
            # Also inspect roots and relationships: a default/generic content
            # type must not hide a part the body reader still omits.
            for name in archive.namelist():
                if name.lower().endswith((".xml", ".rels")):
                    root = ET.fromstring(archive.read(name))
                    if (root.tag in omitted_roots or
                            any(part.get("Type", "").rsplit("/", 1)[-1].lower() in omitted_relations
                                for part in root)):
                        raise ValueError("Office part not covered by content extraction")
    elif suffix == ".pdf":
        from pypdf import PdfReader  # noqa: PLC0415
        logger = logging.getLogger("pypdf")
        level = logger.level
        diagnostic = _RefusePDFDiagnostic()
        # Refuse diagnostics before they can reach source-bearing log output;
        # restore the caller's logging configuration even on parser failure.
        logger.handlers.insert(0, diagnostic)
        logger.setLevel(logging.WARNING)
        try:
            reader = PdfReader(io.BytesIO(raw), strict=True)
            if reader.is_encrypted or any(page.get("/Annots") for page in reader.pages):
                raise ValueError("PDF part not covered by content extraction")
        finally:
            logger.removeHandler(diagnostic)
            logger.setLevel(level)
            diagnostic.close()


def validate_artifact(path: Path) -> bytes:
    """Capture and check the selected bytes; never echo a detected secret."""
    raw = path.read_bytes()
    if any(f.category == "secret" for f in scan_text(raw.decode("utf-8", errors="replace"))):
        raise RuntimeError("Artifact contains an access secret; publication refused")
    try:
        formats = {".pdf": "pdf", ".docx": "document", ".xlsx": "spreadsheet", ".eml": "email"}
        suffix = path.suffix.lower()
        if suffix in formats:
            extracted = extract_captured(str(path), formats[suffix], raw)
            if extracted.warnings or (raw and not extracted.text.strip()):
                raise ValueError("incomplete extraction")
            require_container_coverage(suffix, raw)
            values: list[object] = [extracted.text]
            # Tables are JSON lines containing escaped cell strings. Check the
            # decoded values and associations as well as the serialized text.
            for unit in extracted.units:
                if unit["kind"] in {"sheet_row", "doc_table_row"}:
                    values.append(json.loads(unit["text"]))
        else:
            text = raw.decode("utf-8-sig")
            if "\x00" in text:
                raise ValueError("unsupported binary content")
            values = [text]
        secret = contains_secret_structure(values)
    except Exception:
        # Parser diagnostics may contain source content. Report only the missing
        # validation, before importing a provider or changing a manifest.
        raise RuntimeError("Artifact content validation unavailable; publication refused") from None
    if secret:
        raise RuntimeError("Artifact contains an access secret; publication refused")
    return raw


def execute_drive_upload(request, *, label: str) -> dict[str, str]:
    """Execute once, using chunks for resumable requests; propagate errors."""
    if getattr(request, "next_chunk", None) is None:
        return request.execute()
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"{label}: upload {int(status.progress() * 100)}%", file=sys.stderr)
    return response


def load_manifest() -> dict[str, object]:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return {
        "note": (
            "Non-versioned artifacts published to the personal Drive (Wiki Artefatos "
            "folder, id in .env). Wiki pages point to the view_url here; a local link "
            "to a gitignored file breaks on GitHub. Content lives in Drive, the "
            "manifest lives in git."
        ),
        "schema_version": "wiki_drive_artifacts.v1",
        "folder_id": "",
        "files": {},
    }


def save_manifest(manifest: dict[str, object]) -> None:
    """Replace complete local JSON atomically; this does not coordinate writers."""
    content = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=MANIFEST_PATH.parent, delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, MANIFEST_PATH)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def publish(paths: list[Path], folder_id: str, *, dry_run: bool = False) -> dict[str, object]:
    if not folder_id.strip():
        raise ValueError("A destination folder ID is required")
    manifest = load_manifest()
    files: dict[str, dict[str, str]] = manifest.setdefault("files", {})  # type: ignore[assignment]
    if files and manifest.get("folder_id") != folder_id:
        raise ValueError("Manifest destination differs or is missing; reconcile before publishing")
    names: set[str] = set()
    for path in paths:
        if path.name in names:
            raise ValueError(f"Duplicate artifact name in this batch: {path.name}")
        names.add(path.name)

    # Validate the complete selected batch before any provider import, including
    # local dry-run and files whose manifest hashes already match.
    captured = {path: validate_artifact(path) for path in paths if path.is_file()}
    drive = None
    results: list[str] = []
    for path in paths:
        if path not in captured:
            print(f"WARNING: {path} does not exist; skipping", file=sys.stderr)
            continue
        content = captured[path]
        digest = hashlib.sha256(content).hexdigest()
        entry = files.get(path.name, {})
        if entry.get("sha256") == digest and entry.get("drive_file_id"):
            results.append(f"{path.name}: local manifest has matching sha (remote unverified); skipped")
            continue
        if dry_run:
            results.append(f"{path.name}: would upload ({len(content)} bytes; remote unverified)")
            continue
        if drive is None:
            # The helper and Google libraries are local dependencies. Resolve
            # them only for an actual upload, never for offline inspection.
            helper = os.environ.get("GOOGLE_WORKSPACE_SCRIPTS") or str(
                Path.home() / ".codex" / "skills" / "google-workspace-files" / "scripts"
            )
            sys.path.insert(0, helper)
            from googleapiclient.http import MediaIoBaseUpload  # noqa: PLC0415
            from common.google_clients import DRIVE_SCOPE_FULL, build_service  # noqa: PLC0415

            drive = build_service("drive", "v3", required_scopes=[DRIVE_SCOPE_FULL])

        existing_id = entry.get("drive_file_id")
        if existing_id:
            target = drive.files().get(
                fileId=existing_id, fields="id,name,parents,trashed",
            ).execute()
            if (target.get("id") != existing_id or target.get("name") != path.name
                    or folder_id not in target.get("parents", []) or target.get("trashed") is not False):
                raise RuntimeError(f"{path.name}: manifest target differs; reconcile before publishing")
        else:
            safe_name = path.name.replace("\\", "\\\\").replace("'", "\\'")
            safe_folder = folder_id.replace("\\", "\\\\").replace("'", "\\'")
            matches = drive.files().list(
                q=f"'{safe_folder}' in parents and name = '{safe_name}' and trashed = false",
                fields="files(id),nextPageToken", pageSize=1,
            ).execute()
            if matches.get("files") or matches.get("nextPageToken"):
                raise RuntimeError(f"{path.name}: remote name is not reconciled with the manifest")

        media = MediaIoBaseUpload(
            io.BytesIO(content), mimetype=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            chunksize=8 * 1024 * 1024, resumable=True,
        )
        if existing_id:
            request = drive.files().update(fileId=existing_id, media_body=media, fields="id,webViewLink")
        else:
            request = drive.files().create(
                body={"name": path.name, "parents": [folder_id]},
                media_body=media, fields="id,webViewLink",
            )
        # No retry or alternate-target fallback after an uncertain remote effect.
        meta = execute_drive_upload(request, label=path.name)
        files[path.name] = {
            "drive_file_id": meta["id"],
            "view_url": meta.get("webViewLink", f"https://drive.google.com/file/d/{meta['id']}/view"),
            "sha256": digest,
            "updated_at": dt.date.today().isoformat(),
            "source_path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        }
        manifest["folder_id"] = folder_id
        save_manifest(manifest)
        results.append(f"{path.name}: published -> {files[path.name]['view_url']}")
    return {"folder_id": folder_id, "results": results}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("paths", nargs="+", type=Path, help="authorized files to publish")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    env = load_env()
    folder_id = env.get("WIKI_DRIVE_FOLDER_ID", "")
    if not folder_id:
        print(
            "ERROR: WIKI_DRIVE_FOLDER_ID missing from .env (see .env.example).",
            file=sys.stderr,
        )
        return 2
    if not args.dry_run and env.get("GOOGLE_WORKSPACE_SCRIPTS"):
        os.environ.setdefault("GOOGLE_WORKSPACE_SCRIPTS", env["GOOGLE_WORKSPACE_SCRIPTS"])
    report = publish([p if p.is_absolute() else ROOT / p for p in args.paths], folder_id, dry_run=args.dry_run)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
