#!/usr/bin/env python3
"""Publishes NON-VERSIONED artifacts to the personal Drive and updates the manifest.

General project rule: a useful file that is not versioned in git (data/raw/**,
data/derived/**) must live in a personal Drive folder, and the wiki must point
to the DRIVE LINK — a local link to a gitignored file breaks on GitHub.

- The folder comes from `.env` (WIKI_DRIVE_FOLDER_ID), not versioned; see `.env.example`.
- The versioned manifest `data/drive_artifacts_manifest.json` records
  filename -> {drive_file_id, view_url, sha256, updated_at}; this is what the
  wiki pages cite (and the auditor can verify).
- Upload is idempotent by name: if the file already exists in the folder, it updates
  the content (new revision), preserving the file_id and the link.

Examples:
  python3 scripts/wiki_drive_publish.py data/derived/2026/transacoes_2026_consolidado.csv
  python3 scripts/wiki_drive_publish.py data/derived/2026/*.json --dry-run
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import mimetypes
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# Google client helper location: per-user, NOT part of the kit. Configure via
# GOOGLE_WORKSPACE_SCRIPTS in the environment or .env (see .env.example).
_GOOGLE_HELPER = os.environ.get("GOOGLE_WORKSPACE_SCRIPTS") or str(
    Path.home() / ".codex" / "skills" / "google-workspace-files" / "scripts"
)
sys.path.insert(0, _GOOGLE_HELPER)

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
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def publish(paths: list[Path], folder_id: str, *, dry_run: bool = False) -> dict[str, object]:
    manifest = load_manifest()
    manifest["folder_id"] = folder_id
    files: dict[str, dict[str, str]] = manifest.setdefault("files", {})  # type: ignore[assignment]

    drive = None
    MediaFileUpload = None
    if not dry_run:
        # Lazy imports: the Google libs are a LOCAL dependency (not in
        # requirements/CI); dry-run and the matching-sha path do not need them.
        from googleapiclient.http import MediaFileUpload  # noqa: PLC0415

        from common.google_clients import DRIVE_SCOPE_FULL, build_service  # noqa: PLC0415

        drive = build_service("drive", "v3", required_scopes=[DRIVE_SCOPE_FULL])
    published: list[str] = []
    for path in paths:
        if not path.is_file():
            print(f"WARNING: {path} does not exist; skipping", file=sys.stderr)
            continue
        digest = sha256_file(path)
        name = path.name
        entry = files.get(name, {})
        if entry.get("sha256") == digest and entry.get("drive_file_id"):
            published.append(f"{name}: unchanged (same sha)")
            continue
        if dry_run:
            published.append(f"{name}: would upload ({path.stat().st_size} bytes)")
            continue
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        media = MediaFileUpload(str(path), mimetype=mime, resumable=False)
        existing_id = entry.get("drive_file_id")
        if existing_id:
            meta = drive.files().update(fileId=existing_id, media_body=media, fields="id,webViewLink").execute()
        else:
            safe = name.replace("\\", "\\\\").replace("'", "\\'")
            q = (
                f"'{folder_id}' in parents and name = '{safe}' and trashed = false"
            )
            hit = drive.files().list(q=q, fields="files(id)").execute().get("files", [])
            if hit:
                meta = drive.files().update(fileId=hit[0]["id"], media_body=media, fields="id,webViewLink").execute()
            else:
                meta = (
                    drive.files()
                    .create(body={"name": name, "parents": [folder_id]}, media_body=media, fields="id,webViewLink")
                    .execute()
                )
        files[name] = {
            "drive_file_id": meta["id"],
            "view_url": meta.get("webViewLink", f"https://drive.google.com/file/d/{meta['id']}/view"),
            "sha256": digest,
            "updated_at": dt.date.today().isoformat(),
            "source_path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        }
        published.append(f"{name}: published -> {files[name]['view_url']}")
    if not dry_run:
        save_manifest(manifest)
    return {"folder_id": folder_id, "results": published}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("paths", nargs="+", type=Path, help="files to publish")
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
    report = publish([p if p.is_absolute() else ROOT / p for p in args.paths], folder_id, dry_run=args.dry_run)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
