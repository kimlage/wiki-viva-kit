"""Tests for the shared scripts/_common.py helpers.

Covers the canonical helpers (md_link, load_json, dump_json, write_csv) and
that the module imports cleanly while bootstrapping sys.path so wiki_core is
importable.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._common import (  # noqa: E402
    ROOT as COMMON_ROOT,
    bootstrap,
    dump_json,
    load_json,
    md_link,
    write_csv,
)


def test_common_imports_clean_and_bootstraps_path() -> None:
    # ROOT points at the repo root (parent of scripts/).
    assert COMMON_ROOT == ROOT
    assert (COMMON_ROOT / "scripts" / "_common.py").exists()
    # Importing the module made the repo root importable.
    assert str(COMMON_ROOT) in sys.path
    # bootstrap() is idempotent and returns the same root.
    assert bootstrap() == COMMON_ROOT


def test_common_imports_via_spec_loader() -> None:
    # The scripts are loaded by some tests through spec_from_file_location; make
    # sure _common can be exec'd that way too without raising.
    spec = importlib.util.spec_from_file_location(
        "scripts._common", ROOT / "scripts" / "_common.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.ROOT == ROOT
    assert callable(module.md_link)


def test_md_link_basic() -> None:
    assert md_link("Home", "index.md") == "[Home](index.md)"


def test_md_link_accepts_path_target() -> None:
    link = md_link("doc", Path("memorias") / "page.md")
    assert link == "[doc](memorias/page.md)"


def test_load_json_roundtrip(tmp_path: Path) -> None:
    payload = {"name": "kim", "items": [1, 2, 3], "nested": {"ok": True}}
    target = tmp_path / "data.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    assert load_json(target) == payload


def test_load_json_accepts_list(tmp_path: Path) -> None:
    target = tmp_path / "list.json"
    target.write_text("[1, 2, 3]", encoding="utf-8")
    assert load_json(target) == [1, 2, 3]


def test_dump_json_creates_dirs_and_trailing_newline(tmp_path: Path) -> None:
    target = tmp_path / "sub" / "deep" / "out.json"
    data = {"acentuação": "ção", "n": 1}
    dump_json(target, data)
    assert target.exists()
    text = target.read_text(encoding="utf-8")
    assert text.endswith("\n")
    # ensure_ascii=False keeps accents readable.
    assert "acentuação" in text
    assert json.loads(text) == data


def test_dump_load_json_roundtrip(tmp_path: Path) -> None:
    target = tmp_path / "rt.json"
    data = {"a": [1, 2], "b": "x"}
    dump_json(target, data)
    assert load_json(target) == data


def test_write_csv_writes_header_and_rows(tmp_path: Path) -> None:
    target = tmp_path / "out" / "rows.csv"
    rows = [
        {"name": "a", "value": "1"},
        {"name": "b", "value": "2"},
    ]
    write_csv(target, rows, ["name", "value"])
    assert target.exists()
    with target.open(newline="", encoding="utf-8") as fh:
        parsed = list(csv.DictReader(fh))
    assert parsed == rows


def test_write_csv_empty_rows_still_writes_header(tmp_path: Path) -> None:
    target = tmp_path / "empty.csv"
    write_csv(target, [], ["a", "b"])
    content = target.read_text(encoding="utf-8")
    assert content.splitlines()[0] == "a,b"
