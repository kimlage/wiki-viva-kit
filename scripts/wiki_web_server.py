#!/usr/bin/env python3
"""Run the local Wiki Viva web cockpit operator server."""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from scripts._common import ROOT
except ModuleNotFoundError:
    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))

from wiki_core.web.server import main as server_main


if __name__ == "__main__":
    raise SystemExit(server_main(["--root", str(ROOT), *sys.argv[1:]]))
