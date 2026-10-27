"""Robustness P2: content-based chunk, deterministic dir-hash, NFKD slugify.

Covers findings 3 and 4 of the critical review. No network.
"""

from __future__ import annotations

import os
from pathlib import Path
import pytest

from wiki_core.chunking import chunk_text
from wiki_core.ids import slugify
from wiki_core.llm.cache import cache_key
from wiki_core.source_manifest import sha256_directory_listing


# --------------------------------------------------------------------------- #
# slugify NFKD (accents)
# --------------------------------------------------------------------------- #


def test_slugify_normalizes_accents():
    assert slugify("Relatório Médico.pdf") == "relatorio-medico-pdf"
    assert slugify("café") == "cafe"


def test_slugify_no_accent_collision():
    # 'café' and 'caf!' collided as 'caf-' before NFKD.
    assert slugify("café") != slugify("caf!")


# --------------------------------------------------------------------------- #
# deterministic dir-hash (finding 3)
# --------------------------------------------------------------------------- #


def test_dir_hash_ignores_mtime_and_dotfiles(tmp_path: Path):
    (tmp_path / "a.txt").write_text("conteudo a", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.txt").write_text("conteudo b", encoding="utf-8")

    h1, n1 = sha256_directory_listing(tmp_path)
    os.utime(tmp_path / "a.txt", (1, 1))  # touch the mtime (simulates git checkout)
    (tmp_path / ".DS_Store").write_text("junk", encoding="utf-8")  # dotfile
    h2, n2 = sha256_directory_listing(tmp_path)

    assert h1 == h2  # mtime and dotfile have no effect
    assert n1 == n2 == 2  # only the 2 real files


def test_dir_hash_changes_with_content(tmp_path: Path):
    (tmp_path / "a.txt").write_text("um", encoding="utf-8")
    h1, _ = sha256_directory_listing(tmp_path)
    (tmp_path / "a.txt").write_text("um texto bem maior", encoding="utf-8")
    h2, _ = sha256_directory_listing(tmp_path)
    assert h1 != h2


def test_dir_hash_changes_with_same_size_bytes_and_paths(tmp_path: Path):
    source = tmp_path / "a.txt"
    source.write_bytes(b"alpha")
    before, count = sha256_directory_listing(tmp_path)
    source.write_bytes(b"bravo")
    after, _ = sha256_directory_listing(tmp_path)
    assert before != after and count == 1
    source.rename(tmp_path / "b.txt")
    renamed, _ = sha256_directory_listing(tmp_path)
    assert renamed != after


def test_dir_hash_matches_relocated_tree_and_rejects_symlinks(tmp_path: Path):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    for folder in (first, second):
        (folder / "one.txt").write_bytes(b"same bytes")
    assert sha256_directory_listing(first) == sha256_directory_listing(second)
    (second / "link.txt").symlink_to(first / "one.txt")
    with pytest.raises(ValueError, match="source_directory_symlink"):
        sha256_directory_listing(second)


def test_dir_hash_does_not_hide_read_errors(tmp_path: Path, monkeypatch):
    (tmp_path / "one.txt").write_bytes(b"content")
    def unavailable(_path):
        raise PermissionError("synthetic unreadable source")
    monkeypatch.setattr("wiki_core.source_manifest.sha256_file", unavailable)
    with pytest.raises(PermissionError, match="unreadable"):
        sha256_directory_listing(tmp_path)


# --------------------------------------------------------------------------- #
# content-based chunk + content-based cache_key (finding 4)
# --------------------------------------------------------------------------- #


def _paragraphed(n: int) -> str:
    return "\n\n".join(
        f"Paragrafo {i} com bastante texto operacional para ter conteudo. " * 3 for i in range(n)
    )


def test_chunk_local_edit_changes_only_one_chunk():
    text = _paragraphed(8)
    before = chunk_text("src", text, target_tokens=200, overlap_tokens=0)
    edited = text.replace("Paragrafo 0 ", "Paragrafo ZERO ", 1)
    after = chunk_text("src", edited, target_tokens=200, overlap_tokens=0)
    before_hashes = {c.hash_sha256 for c in before}
    after_hashes = {c.hash_sha256 for c in after}
    # Only 1 chunk changed (before: the word window redid everything downstream).
    assert len(before_hashes - after_hashes) == 1


def test_chunk_preserves_line_structure():
    # Table/CSV: lines preserved (the old split() collapsed them into one line).
    csv = "col_a | col_b\nv1 | v2\nv3 | v4"
    chunks = chunk_text("src", csv, target_tokens=200, overlap_tokens=0)
    joined = "\n".join(c.text for c in chunks)
    assert "col_a | col_b" in joined
    assert "v3 | v4" in joined


def test_chunk_line_units_regroup_with_single_newline():
    # Line units (tables/CSV) regroup with "\n": rejoining with "\n\n" used to
    # turn each row into a fake paragraph and break the table apart.
    csv = "id,name\n1,alpha\n2,beta"
    chunks = chunk_text("src", csv, target_tokens=200, overlap_tokens=0)
    assert len(chunks) == 1
    assert chunks[0].text == csv
    assert "\n\n" not in chunks[0].text


def test_chunk_paragraph_units_keep_blank_line_separator():
    text = "first paragraph here\n\nsecond paragraph here"
    chunks = chunk_text("src", text, target_tokens=200, overlap_tokens=0)
    assert len(chunks) == 1
    assert chunks[0].text == text


def test_chunk_empty_text():
    assert chunk_text("src", "   \n\n  ") == []


def test_cache_key_dedupes_identical_chunk_across_sources():
    # Same chunk content -> same key (independent of source).
    k = cache_key("samehash", "v1", "schema.v2", "deep_context")
    assert k == cache_key("samehash", "v1", "schema.v2", "deep_context")


def test_dir_hash_does_not_hide_subdirectory_enumeration_errors(tmp_path, monkeypatch):
    (tmp_path / "restricted").mkdir()
    original = os.scandir
    def guarded(path):
        if Path(path).name == "restricted":
            raise PermissionError("synthetic enumeration denied")
        return original(path)
    monkeypatch.setattr(os, "scandir", guarded)
    with pytest.raises(PermissionError, match="enumeration"):
        sha256_directory_listing(tmp_path)
