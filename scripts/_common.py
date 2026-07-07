#!/usr/bin/env python3
"""Canonical bootstrap shared by the ``scripts/`` command-line tools.

Every script in this directory repeated the same preamble — resolve the repo
root, push it onto ``sys.path`` so ``import wiki_core`` works. This module is
the single home for that boilerplate.

Importing this module is the bootstrap: ``ROOT`` is computed and inserted into
``sys.path`` at import time, so a script only needs::

    from scripts._common import ROOT  # noqa: E402

(or ``from _common import ROOT`` when the file is run directly). After the
import, ``import wiki_core...`` resolves regardless of the current working
directory.

It deliberately has NO third-party dependencies and never imports the financial
core (``src/``) or ``wiki_core`` at module load, so it stays cheap and safe to
import from any tool.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Repo root is the parent of scripts/. Resolve so the path is absolute even when
# the script is launched through a relative path or a spec loader (tests).
ROOT = Path(__file__).resolve().parents[1]

# Bootstrap: make the repo root importable (so ``import wiki_core`` works) the
# moment this module is imported. Idempotent — never inserts a duplicate.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
