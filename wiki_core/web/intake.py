"""Intake: add a NEW external file into the wiki's raw area — safely.

The old Add flow dead-ended on new external files: it accepted only a free-text
path that had to already resolve INSIDE the repo, so a PDF in ~/Downloads was
un-addable. This copies a file the operator points at (a local absolute path, or
a repo-relative one) into ``data/raw/<context>/`` so it becomes addressable and
can be triaged/ingested like any source.

Guardrails (this is a LOCAL-operator-only write surface):
* the destination is sandboxed to ``paths.raw_root`` — no traversal, no symlink
  escape;
* the SOURCE is secret-scanned before the copy and REFUSED if a secret is
  detected (never smuggle a token into the repo);
* the context must be a real configured context;
* nothing is git-added or pushed — the file just lands in the untracked raw area.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from wiki_core.config import WikiConfig
from wiki_core.web.commands import SECRET_VALUE_RE

_CONTEXT_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")
_MAX_SCAN_BYTES = 2_000_000


def _resolve_source(root: Path, source_path: str) -> Path | None:
    raw = str(source_path or "").strip()
    if not raw or "\x00" in raw:
        return None
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = root / raw
    # Reject symlinks on the LITERAL path (resolve() would follow them).
    if candidate.is_symlink():
        return None
    resolved = candidate.resolve()
    if resolved.is_symlink() or not resolved.is_file():
        return None
    return resolved


def _secret_scan_block(path: Path) -> str | None:
    """The refusal reason when the file must not be copied, else None.

    Fails CLOSED: a source that cannot be read/scanned is treated as
    potentially secret-bearing rather than waved through unscanned.
    """
    try:
        with path.open("rb") as handle:
            chunk = handle.read(_MAX_SCAN_BYTES)
    except OSError as exc:
        return f"could not secret-scan the source, treating it as potentially secret-bearing ({exc})"
    text = chunk.decode("utf-8", errors="ignore")
    if SECRET_VALUE_RE.search(text):
        return "the file appears to contain a secret"
    return None


def intake_copy(root: Path, config: WikiConfig, source_path: str, context: str) -> dict[str, Any]:
    """Copy a file into ``data/raw/<context>/`` after a secret scan. Returns the
    new repo-relative path, or an honest ``ok:False`` reason."""
    ctx = str(context or config.default_context).strip()
    if not _CONTEXT_RE.fullmatch(ctx) or (config.contexts and ctx not in config.contexts):
        return {"ok": False, "error": f"unknown context: {context}"}
    source = _resolve_source(root, source_path)
    if source is None:
        return {"ok": False, "error": "source file not found or unreadable", "source": source_path}
    scan_block = _secret_scan_block(source)
    if scan_block is not None:
        return {"ok": False, "error": f"refused: {scan_block}", "reason": "secret_block"}

    raw_root = str(config.paths.get("raw_root") or "data/raw").rstrip("/")
    dest_dir = (root / raw_root / ctx).resolve()
    repo_base = (root / raw_root).resolve()
    if not str(dest_dir).startswith(str(repo_base)):
        return {"ok": False, "error": "destination escapes the raw root"}
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / source.name
    # Never clobber: suffix on collision so an existing raw file is preserved.
    if dest.exists():
        stem, suffix = dest.stem, dest.suffix
        counter = 2
        while dest.exists():
            dest = dest_dir / f"{stem}-{counter}{suffix}"
            counter += 1
    try:
        shutil.copyfile(source, dest)
    except OSError as exc:
        return {"ok": False, "error": f"copy failed: {exc}"}
    rel = dest.relative_to(root).as_posix()
    return {"ok": True, "path": rel, "context": ctx, "filename": dest.name}
