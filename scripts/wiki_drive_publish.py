#!/usr/bin/env python3
"""Inspect a local artifact publication plan; Drive publishing is suspended.

The previous publisher could overwrite remote objects and lose manifest updates
under concurrency or after an interrupted upload. Non-dry-run publication is
disabled pending https://github.com/kimlage/wiki-viva-kit/issues/234.
Dry-run reads only local files and the local manifest; it does not authenticate,
contact Drive, verify remote state, or change files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "data" / "drive_artifacts_manifest.json"
ENV_PATH = ROOT / ".env"
SUSPENSION = "Drive publication is suspended; see https://github.com/kimlage/wiki-viva-kit/issues/234"


class DrivePublicationSuspended(RuntimeError):
    """Publication is unavailable until the concurrency contract is repaired."""


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


def execute_drive_upload(request, *, label: str) -> dict[str, str]:
    """Refuse direct requests as well as the normal publication path."""
    raise DrivePublicationSuspended(SUSPENSION)


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
    """Refuse the former non-atomic manifest write, including direct calls."""
    raise DrivePublicationSuspended(SUSPENSION)


def publish(paths: list[Path], folder_id: str, *, dry_run: bool = False) -> dict[str, object]:
    if not dry_run:
        raise DrivePublicationSuspended(SUSPENSION)
    manifest = load_manifest()
    files: dict[str, dict[str, str]] = manifest.get("files", {})  # type: ignore[assignment]
    planned: list[str] = []
    for path in paths:
        if not path.is_file():
            print(f"WARNING: {path} does not exist; skipping", file=sys.stderr)
            continue
        digest = sha256_file(path)
        entry = files.get(path.name, {})
        if entry.get("sha256") == digest and entry.get("drive_file_id"):
            planned.append(f"{path.name}: local manifest has matching sha (remote unverified)")
        else:
            planned.append(f"{path.name}: would upload ({path.stat().st_size} bytes; publication suspended)")
    return {"folder_id": folder_id, "results": planned}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("paths", nargs="+", type=Path, help="files to inspect")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not args.dry_run:
        print(f"ERROR: {SUSPENSION}", file=sys.stderr)
        return 2

    env = load_env()
    folder_id = env.get("WIKI_DRIVE_FOLDER_ID", "")
    if not folder_id:
        print(
            "ERROR: WIKI_DRIVE_FOLDER_ID missing from .env (see .env.example).",
            file=sys.stderr,
        )
        return 2
    report = publish([p if p.is_absolute() else ROOT / p for p in args.paths], folder_id, dry_run=True)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
