#!/usr/bin/env python3
"""Canonical helpers shared by the ``scripts/`` command-line tools.

Every script in this directory repeated the same preamble — resolve the repo
root, push it onto ``sys.path`` so ``import wiki_core`` works — plus small
copies of ``md_link`` / ``load_json`` / ``write_csv``. This module is the single
home for that boilerplate.

Importing this module is the bootstrap: ``ROOT`` is computed and inserted into
``sys.path`` at import time, so a script only needs::

    from scripts._common import ROOT, load_json  # noqa: E402

(or ``from _common import ...`` when the file is run directly). After the import,
``import wiki_core...`` resolves regardless of the current working directory.

It deliberately has NO third-party dependencies and never imports the financial
core (``src/``) or ``wiki_core`` at module load, so it stays cheap and safe to
import from any tool.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

# Repo root is the parent of scripts/. Resolve so the path is absolute even when
# the script is launched through a relative path or a spec loader (tests).
ROOT = Path(__file__).resolve().parents[1]

# Bootstrap: make the repo root importable (so ``import wiki_core`` works) the
# moment this module is imported. Idempotent — never inserts a duplicate.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def bootstrap() -> Path:
    """Ensure the repo root is on ``sys.path`` and return it.

    The side effect already happened at import time; this is the explicit,
    readable handle for callers that want the path back (``ROOT = bootstrap()``).
    """
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    return ROOT


def md_link(label: str, target: str | Path) -> str:
    """Return a basic Markdown link ``[label](target)``.

    Drive-aware linking (local file vs. published Drive URL) lives in
    ``wiki_core.drive_links.drive_aware_md_link``; use that when the target may
    be a non-versioned artifact. This is the plain, deterministic builder.
    """
    return f"[{label}]({target})"


def load_json(path: str | Path) -> Any:
    """Read and parse a UTF-8 JSON file, returning whatever it contains."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def dump_json(path: str | Path, data: Any, *, indent: int = 2) -> None:
    """Write ``data`` as pretty UTF-8 JSON, creating parent directories.

    A trailing newline is added so the file plays nicely with text tooling.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=indent) + "\n",
        encoding="utf-8",
    )


def write_csv(
    path: str | Path,
    rows: Iterable[Mapping[str, Any]],
    fieldnames: Sequence[str],
) -> None:
    """Write ``rows`` to a CSV at ``path`` with the given header.

    Creates parent directories and uses ``newline=""`` so the standard library
    handles line endings (no blank rows on Windows).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(fieldnames))
        writer.writeheader()
        writer.writerows(rows)
