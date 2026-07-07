"""Tests for scripts/_common.py: the module imports cleanly and bootstraps
sys.path so wiki_core is importable from any script."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._common import ROOT as COMMON_ROOT  # noqa: E402


def test_common_imports_clean_and_bootstraps_path() -> None:
    # ROOT points at the repo root (parent of scripts/).
    assert COMMON_ROOT == ROOT
    assert (COMMON_ROOT / "scripts" / "_common.py").exists()
    # Importing the module made the repo root importable.
    assert str(COMMON_ROOT) in sys.path


def test_common_imports_via_spec_loader() -> None:
    # The scripts are loaded by some tests through spec_from_file_location; make
    # sure _common can be exec'd that way too without raising.
    spec = importlib.util.spec_from_file_location(
        "scripts._common", ROOT / "scripts" / "_common.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.ROOT == ROOT
