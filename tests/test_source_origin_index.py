"""Origin-qualified ingestion across the public pipeline and extraction CLI."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from wiki_core.config import WikiConfig
from wiki_core.ingest.pipeline import run
from wiki_core.index.sqlite import build_index, index_source, search
from wiki_core.paths import WikiPaths
from wiki_core.source_manifest import build_manifest, chunk_document, write_source_artifact


def test_pipeline_empty_observation_and_checkout_independent_identity(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "notes.md"
    source.write_text("Previous synthetic sentinel.\n")
    config = WikiConfig()
    first = run(str(source), "example", root, config, record_score=False)
    expected = build_manifest(str(source), "example", root=root)
    assert first.source_id == expected["source_id"]
    copy = tmp_path / "copy"
    copy.mkdir()
    (copy / "notes.md").write_text(source.read_text())
    assert build_manifest(str(copy / "notes.md"), "example", root=copy)["source_id"] == first.source_id
    paths = WikiPaths(root, config)
    data = json.loads((root / first.chunks_path).read_text())
    assert data["source_origin_id"] == expected["source_origin"]["id"]
    source.write_text("")
    empty = run(str(source), "example", root, config, record_score=False)
    assert empty.chunk_count == 0
    assert search(paths.indexes / "wiki.sqlite", "sentinel") == []
    build_index(paths.chunks, paths.indexes / "wiki.sqlite")
    assert search(paths.indexes / "wiki.sqlite", "sentinel") == []


def test_extraction_cli_and_pipeline_share_source_identity(tmp_path, monkeypatch, capsys):
    file = Path(__file__).resolve().parents[1] / "scripts/wiki_extract_text.py"
    spec = importlib.util.spec_from_file_location("origin_extract_cli", file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = tmp_path / "notes.md"
    source.write_text("Synthetic extraction content.\n")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", [str(file), "--source", str(source), "--context", "example", "--write-derived"])
    assert module.main() == 0
    capsys.readouterr()
    manifest = build_manifest(str(source), "example", root=tmp_path)
    paths = WikiPaths(tmp_path, WikiConfig())
    chunks_path = paths.chunks / (manifest["source_id"] + ".json")
    cli = json.loads(chunks_path.read_text())
    result = run(str(source), "example", tmp_path, WikiConfig(), record_score=False)
    pipeline = json.loads(chunks_path.read_text())
    assert result.source_id == cli["source_id"] == pipeline["source_id"]
    assert cli["source_origin_id"] == pipeline["source_origin_id"]
    assert cli["source_hash_sha256"] == pipeline["source_hash_sha256"]
    assert cli["chunks"] == pipeline["chunks"]


def test_failed_empty_extraction_cannot_delete_previously_read_content(tmp_path):
    source = tmp_path / "notes.md"
    source.write_text("Previously read sentinel.\n")
    config = WikiConfig()
    run(str(source), "example", tmp_path, config, record_score=False)
    paths = WikiPaths(tmp_path, config)
    source.write_text("synthetic failed extraction")
    manifest = build_manifest(str(source), "example", root=tmp_path)
    path = paths.chunks / (manifest["source_id"] + ".json")
    write_source_artifact(path, chunk_document(manifest, [], warnings=["extractor failed"]))
    assert index_source(paths.indexes / "wiki.sqlite", path)["ambiguous_origins"] == 1
    assert search(paths.indexes / "wiki.sqlite", "sentinel")
    assert build_index(paths.chunks, paths.indexes / "wiki.sqlite")["ambiguous_origins"] == 1
    assert search(paths.indexes / "wiki.sqlite", "sentinel")


def test_failed_atomic_publish_retains_previous_derived_artifact(tmp_path, monkeypatch):
    import wiki_core.source_manifest as module
    path = tmp_path / "artifact.json"
    write_source_artifact(path, {"complete": "old"})
    before = path.read_bytes()
    def fail(*_args):
        raise OSError("synthetic publication failure")
    monkeypatch.setattr(module.os, "replace", fail)
    with pytest.raises(OSError):
        write_source_artifact(path, {"complete": "new"})
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]
