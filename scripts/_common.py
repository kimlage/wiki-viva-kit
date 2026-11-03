#!/usr/bin/env python3
"""Canonical bootstrap shared by the ``scripts/`` command-line tools.

Every script in this directory repeated the same preamble — resolve the repo
root, push it onto ``sys.path`` so ``import wiki_core`` works. This module is
the single home for that boilerplate.

Importing this module computes ``CODE_ROOT`` and ``ROOT`` and inserts only
``CODE_ROOT`` into ``sys.path``. Scripts can import the content root with::

    from scripts._common import ROOT  # noqa: E402

(or ``from _common import ROOT`` when the file is run directly). After the
import, ``import wiki_core...`` resolves regardless of the current working
directory.

It deliberately has NO third-party dependencies and never imports the financial
core (``src/``) or ``wiki_core`` at module load, so it stays cheap and safe to
import from any tool.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Code root is the parent of scripts/. Resolve so the path is absolute even when
# the script is launched through a relative path or a spec loader (tests).
CODE_ROOT = Path(__file__).resolve().parents[1]
# The installed-operator launcher sets this explicit content-root binding.
ROOT = Path(os.environ["WIKI_INSTALLED_CONTENT_ROOT"]).resolve(strict=True) if "WIKI_INSTALLED_CONTENT_ROOT" in os.environ else CODE_ROOT

# Bootstrap: make the repo root importable (so ``import wiki_core`` works) the
# moment this module is imported. Idempotent — never inserts a duplicate.
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))
