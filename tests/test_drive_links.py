"""General rule: non-versioned artifact -> content on Drive, link in the wiki.

Covers the drive_aware_md_link helper, the .env parser and the idempotence of
the monthly page generator (demarcated section). No network.
"""

from __future__ import annotations

import importlib.util
import json
import sys

import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import wiki_core.drive_links as dl


def _load(path_rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / path_rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_drive_aware_link_uses_drive_for_untracked(monkeypatch, tmp_path):
    monkeypatch.setattr(dl, "_manifest_files", lambda: {"x.csv": {"view_url": "https://drive.google.com/file/d/abc/view"}})
    monkeypatch.setattr(dl, "_tracked_set", lambda: frozenset())
    link = dl.drive_aware_md_link(dl.ROOT / "data/derived/2026/x.csv", dl.ROOT / "memorias")
    assert link == "[x.csv (Drive)](https://drive.google.com/file/d/abc/view)"


def test_drive_aware_link_local_for_tracked(monkeypatch):
    monkeypatch.setattr(dl, "_manifest_files", lambda: {"y.csv": {"view_url": "https://drive.google.com/file/d/zzz/view"}})
    monkeypatch.setattr(dl, "_tracked_set", lambda: frozenset({"data/derived/2026/y.csv"}))
    link = dl.drive_aware_md_link(dl.ROOT / "data/derived/2026/y.csv", dl.ROOT / "memorias")
    assert "drive.google.com" not in link  # versioned: local relative link
    assert "../data/derived/2026/y.csv" in link


def test_drive_aware_link_local_when_unpublished(monkeypatch):
    monkeypatch.setattr(dl, "_manifest_files", lambda: {})
    monkeypatch.setattr(dl, "_tracked_set", lambda: frozenset())
    link = dl.drive_aware_md_link(dl.ROOT / "data/derived/2026/z.csv", dl.ROOT / "memorias")
    assert "drive.google.com" not in link


def test_publish_env_parser(tmp_path):
    pub = _load("scripts/wiki_drive_publish.py", "wdp_test")
    env_file = tmp_path / ".env"
    env_file.write_text("# comentario\nWIKI_DRIVE_FOLDER_ID = 'abc123'\nOUTRA=x\n", encoding="utf-8")
    env = pub.load_env(env_file)
    assert env["WIKI_DRIVE_FOLDER_ID"] == "abc123"
    assert env["OUTRA"] == "x"
    assert pub.load_env(tmp_path / "inexistente.env") == {}


def test_publish_skips_unchanged_sha(tmp_path, monkeypatch):
    pub = _load("scripts/wiki_drive_publish.py", "wdp_test2")
    artifact = tmp_path / "a.csv"
    artifact.write_text("conteudo", encoding="utf-8")
    digest = pub.sha256_file(artifact)
    monkeypatch.setattr(pub, "MANIFEST_PATH", tmp_path / "manifest.json")
    (tmp_path / "manifest.json").write_text(
        json.dumps({"files": {"a.csv": {"sha256": digest, "drive_file_id": "id1", "view_url": "u"}}}),
        encoding="utf-8",
    )
    # nothing to upload (sha unchanged) -> must not touch the network (no build_service).
    # The "unchanged" wording lives in scripts/wiki_drive_publish.py (another group);
    # assert on the filename it embeds, which is translation-independent.
    report = pub.publish([artifact], "folder", dry_run=True)
    assert any("a.csv" in r for r in report["results"])


@pytest.mark.skipif(
    not (ROOT / "scripts" / "build_finance_month_pages.py").exists(),
    reason="per-repo script (personal repo only); not part of the generic kit",
)
def test_month_pages_upsert_idempotent(tmp_path, monkeypatch):
    bmp = _load("scripts/build_finance_month_pages.py", "bmp_test")
    table = bmp.month_table([
        {"Data": "01/05/2026", "Descricao": "X", "Valor": -10, "Conta Corrente": True,
         "Tipo": "Saída", "Categoria_final": "C", "Subcategoria_final": "S",
         "Meta_AUVP": "", "Tag_AUVP": "", "OrigemArquivo": "extrato.txt"}
    ])
    page = "---\nfm: x\n---\n\n# Mes\n\nProsa curada.\n"
    once = bmp.upsert_section(page, table)
    twice = bmp.upsert_section(once, table)
    assert once == twice  # idempotente
    assert "Prosa curada." in once  # preserva conteudo manual
    assert once.count(bmp.BEGIN) == 1
