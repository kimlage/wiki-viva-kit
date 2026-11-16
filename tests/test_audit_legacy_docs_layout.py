"""Issue #518: the retired docs layout is scoped to the consumer's config.

Synthetic consumers only; no consumer data. The default keeps protecting every
consumer that does not declare its layout, while a consumer whose legitimate
sources live in a year folder such as `docs/2026/` declares the prefixes that
are retired for it.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import scripts.wiki_audit as audit
from wiki_core.config import load_config


def _consumer(tmp_path: Path, monkeypatch, config_text: str, files: dict[str, str]) -> Path:
    root = tmp_path / "consumer"
    root.mkdir()
    (root / "wiki.config.yaml").write_text(config_text, encoding="utf-8")
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    monkeypatch.setattr(audit, "ROOT", root)
    audit._audit_git_inventory.cache_clear()
    audit.tracked_files.cache_clear()
    return root


@pytest.fixture(autouse=True)
def _clear_inventory_cache():
    yield
    audit._audit_git_inventory.cache_clear()
    audit.tracked_files.cache_clear()


SOURCE_FILES = {
    "docs/2026/README.md": "# Synthetic 2026 source folder\n",
    "notes/cycle.md": "# Synthetic\n\nSee docs/2026/README.md for the cycle source.\n",
}


def _run(root: Path) -> list[str]:
    errors: list[str] = []
    audit.audit_old_paths(errors, load_config(root))
    return errors


def test_default_layout_still_rejects_retired_docs_paths(tmp_path, monkeypatch):
    root = _consumer(tmp_path, monkeypatch, "audit: {}\n", {
        **SOURCE_FILES, "docs/memories/old.md": "# Synthetic retired page\n",
    })
    errors = _run(root)
    assert "docs/2026/README.md: old docs path is still tracked" in errors
    assert "docs/memories/old.md: old docs path is still tracked" in errors
    assert "notes/cycle.md: old docs path reference outside migration history" in errors


def test_consumer_declared_layout_admits_year_source_folder(tmp_path, monkeypatch):
    root = _consumer(
        tmp_path, monkeypatch,
        "audit:\n  legacy_docs_prefixes: [docs/memorias/, docs/memories]\n",
        SOURCE_FILES,
    )
    assert _run(root) == []


def test_declared_layout_keeps_protection_for_retired_prefixes(tmp_path, monkeypatch):
    root = _consumer(
        tmp_path, monkeypatch,
        "audit:\n  legacy_docs_prefixes: [docs/memorias/, docs/memories/]\n",
        {**SOURCE_FILES,
         "docs/memories/old.md": "# Synthetic retired page\n",
         "notes/link.md": "# Synthetic\n\nMoved from docs/memorias/x.md.\n"},
    )
    assert sorted(_run(root)) == [
        "docs/memories/old.md: old docs path is still tracked",
        "notes/link.md: old docs path reference outside migration history",
    ]


def test_empty_declaration_means_no_retired_layout(tmp_path, monkeypatch):
    root = _consumer(tmp_path, monkeypatch, "audit:\n  legacy_docs_prefixes: []\n", SOURCE_FILES)
    assert _run(root) == []


@pytest.mark.parametrize("value", [
    "docs/2026/", "[/etc/]", "['../docs/']", "['docs/../x/']", "['']", "[3]", "['docs\\\\x/']", "{a: b}",
])
def test_malformed_declaration_fails_closed_to_default(tmp_path, monkeypatch, value):
    root = _consumer(tmp_path, monkeypatch, f"audit:\n  legacy_docs_prefixes: {value}\n", SOURCE_FILES)
    errors = _run(root)
    assert any("audit.legacy_docs_prefixes must be a list" in e for e in errors)
    assert "docs/2026/README.md: old docs path is still tracked" in errors


def test_allowed_reference_exemption_still_does_not_exempt_tracked_file(tmp_path, monkeypatch):
    root = _consumer(
        tmp_path, monkeypatch,
        "audit:\n  allowed_old_path_references: [notes/cycle.md]\n", SOURCE_FILES,
    )
    assert _run(root) == ["docs/2026/README.md: old docs path is still tracked"]
