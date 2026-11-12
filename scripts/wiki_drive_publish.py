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
import mimetypes
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wiki_core.detectors import scan_text  # noqa: E402
from wiki_core.extractors.text import extract_captured  # noqa: E402

MANIFEST_PATH = ROOT / "data" / "drive_artifacts_manifest.json"
ENV_PATH = ROOT / ".env"


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


def validate_artifact(path: Path) -> bytes:
    """Capture and check the selected bytes; never echo a detected secret."""
    raw = path.read_bytes()
    if any(f.category == "secret" for f in scan_text(raw.decode("utf-8", errors="replace"))):
        raise RuntimeError("Artifact contains an access secret; publication refused")
    try:
        formats = {".pdf": "pdf", ".docx": "document", ".xlsx": "spreadsheet", ".eml": "email"}
        if path.suffix.lower() in formats:
            extracted = extract_captured(str(path), formats[path.suffix.lower()], raw)
            if extracted.warnings or (raw and not extracted.text.strip()):
                raise ValueError("incomplete extraction")
            text = extracted.text
        else:
            text = raw.decode("utf-8-sig")
            if "\x00" in text:
                raise ValueError("unsupported binary content")
    except Exception:
        # Parser diagnostics may contain source content. Report only the missing
        # validation, before importing a provider or changing a manifest.
        raise RuntimeError("Artifact content validation unavailable; publication refused") from None
    if any(f.category == "secret" for f in scan_text(text)):
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
