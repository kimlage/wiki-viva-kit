"""Drive-aware links for NON-VERSIONED artifacts (project-wide rule).

A useful file that is not versioned (data/raw/**, data/derived/**) lives in a
personal Drive folder (id in .env, published by scripts/wiki_drive_publish.py)
and the wiki points to the DRIVE LINK — a local link to a gitignored file breaks
on GitHub. The versioned manifest data/drive_artifacts_manifest.json records
filename -> view_url; this helper resolves the link during page generation.
"""

from __future__ import annotations

import json
import os
import subprocess
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "data" / "drive_artifacts_manifest.json"


@lru_cache(maxsize=1)
def _manifest_files() -> dict[str, dict[str, str]]:
    if not MANIFEST_PATH.exists():
        return {}
    try:
        return dict(json.loads(MANIFEST_PATH.read_text(encoding="utf-8")).get("files", {}))
    except (json.JSONDecodeError, OSError):
        return {}


@lru_cache(maxsize=1)
def _tracked_set() -> frozenset[str]:
    try:
        out = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True)
    except (subprocess.CalledProcessError, OSError):
        return frozenset()
    return frozenset(out.splitlines())


def drive_view_url(path: Path) -> str | None:
    """Drive view_url for ``path``, if published in the manifest; otherwise None."""
    entry = _manifest_files().get(Path(path).name)
    return (entry or {}).get("view_url") or None


def drive_aware_md_link(path: Path, base_dir: Path, label: str | None = None) -> str:
    """Markdown link for ``path``: Drive if non-versioned and published.

    - File NOT tracked in git (e.g.: data/derived/**) + published on Drive
      -> Drive link (stable on GitHub).
    - Otherwise -> local relative link (the wiki's default behavior).
    """
    path = Path(path)
    try:
        rel = path.relative_to(ROOT).as_posix()
    except ValueError:
        rel = path.name
    if rel not in _tracked_set():
        url = drive_view_url(path)
        if url:
            return f"[{label or path.name + ' (Drive)'}]({url})"
    href = os.path.relpath(path, base_dir).replace(os.sep, "/")
    return f"[{label or rel}]({href})"
