"""Explicit-source checks must not confuse absent/broken extraction with empty input."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wiki_core.config import WikiConfig
from wiki_core.ingest import run
from wiki_core.llm import write_result
from wiki_core.paths import WikiPaths
from wiki_core.source_manifest import build_manifest


@pytest.fixture
def source_check(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("context_pass_source_artifacts", ROOT / "scripts/wiki_llm_context_pass.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config = WikiConfig(repo_id="synthetic-source-check")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "load_config", lambda _: config)
    source = tmp_path / "source.md"
    source.write_text("A synthetic observation that must be read.\n", encoding="utf-8")
    paths = WikiPaths(tmp_path, config)

    def check(*extra, source_override=None):
        monkeypatch.setattr(sys, "argv", ["wiki_llm_context_pass.py", "--source", str(source_override or source), "--context", "system", *extra])
        return module.main()

    return source, config, paths, check


def _artifact(paths, source, directory="chunks"):
    source_id = build_manifest(str(source), "system", root=paths.root)["source_id"]
    return getattr(paths, directory) / f"{source_id}.json"


def _legacy_capture(source, config, paths):
    from wiki_core.ids import slugify
    current = run(str(source), "system", paths.root, config)
    manifest_path = _artifact(paths, source, "source_manifests")
    manifest = json.loads(manifest_path.read_text())
    legacy_id = f"source-{slugify(source.name)}-{manifest['hash_sha256'][:12]}"
    for directory in (paths.source_manifests, paths.source_text, paths.chunks):
        path = directory / (current.source_id + ".json")
        data = json.loads(path.read_text().replace(current.source_id, legacy_id))
        for key in ("source_origin", "source_origin_id", "observed_at", "extraction_complete"):
            data.pop(key, None)
        (directory / (legacy_id + ".json")).write_text(json.dumps(data))
        path.unlink()
    return legacy_id


@pytest.mark.parametrize("inventory_manifest", [False, True])
def test_legacy_source_is_discovered_without_reingestion(source_check, capsys, monkeypatch, inventory_manifest):
    source, config, paths, check = source_check
    legacy_id = _legacy_capture(source, config, paths)
    if inventory_manifest:
        from wiki_core.source_manifest import write_manifest
        write_manifest(build_manifest(str(source), "system", root=paths.root), paths.source_manifests)
    before = {p: p.read_bytes() for p in paths.derived_root.rglob("*") if p.is_file()}
    assert check("--check") == 1  # valid capture, deep read still pending
    report = json.loads(capsys.readouterr().out)
    assert report["source_id"] == legacy_id and report["chunks"] == 1
    spec = importlib.util.spec_from_file_location("legacy_cache_inspect", ROOT / "scripts/wiki_cache_inspect.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", paths.root)
    monkeypatch.setattr(module, "load_config", lambda _: config)
    monkeypatch.setattr(sys, "argv", ["wiki_cache_inspect.py", "--source", str(source)])
    assert module.main() == 0
    inspected = json.loads(capsys.readouterr().out)["source"]
    assert inspected["source_id"] == legacy_id and inspected["chunks_exist"]
    assert inspected["identity_resolution"] == "verified_legacy_manifest"
    assert {p: p.read_bytes() for p in paths.derived_root.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("fault", ["different_origin", "missing_origin", "conflicting_locators", "missing_manifest"])
def test_legacy_basename_and_digest_are_not_origin_proof(source_check, capsys, fault):
    source, config, paths, check = source_check
    legacy_id = _legacy_capture(source, config, paths)
    path = paths.source_manifests / (legacy_id + ".json")
    data = json.loads(path.read_text())
    if fault == "missing_manifest":
        path.unlink()
    else:
        if fault == "different_origin":
            data.update(source_uri=str(paths.root / "other" / source.name), absolute_path=str(paths.root / "other" / source.name))
        elif fault == "missing_origin":
            data.pop("source_uri")
            data.pop("absolute_path")
        else:
            data["absolute_path"] = str(paths.root / "other" / source.name)
        path.write_text(json.dumps(data))
    assert check("--check") == 2
    assert "source_legacy_origin_" in json.loads(capsys.readouterr().out)["error"]


@pytest.mark.parametrize("required", [True, False])
def test_explicit_source_without_extraction_fails(source_check, capsys, required):
    source, config, paths, check = source_check
    config.llm["required_context_pass"] = required
    assert check("--check") == 2
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is False
    assert "source_artifact_missing" in report["error"]
    assert not list(paths.extraction_events.glob("*-llm-context-request.json"))


@pytest.mark.parametrize("fault, expected", [
    ("json", "source_artifact_invalid_json"),
    ("utf8", "source_artifact_unreadable"),
    ("top_level", "source_artifact_schema"),
    ("schema_missing", "source_artifact_schema"),
    ("schema_wrong", "source_artifact_schema"),
    ("source_id", "source_artifact_identity"),
    ("source_hash_missing", "source_artifact_hash"),
    ("source_hash", "source_artifact_hash"),
    ("chunks_missing", "source_chunks_schema"),
    ("chunks_null", "source_chunks_schema"),
    ("chunks_object", "source_chunks_schema"),
    ("chunk_not_object", "source_chunk_schema"),
    ("text_missing", "source_chunk_schema"),
    ("text_empty", "source_chunk_schema"),
    ("chunk_id", "source_chunk_identity"),
    ("duplicate_id", "source_chunk_identity"),
    ("chunk_source", "source_chunk_identity"),
    ("chunk_hash", "source_chunk_hash"),
    ("tampered_text", "source_chunk_hash"),
])
def test_invalid_source_chunks_are_rejected(source_check, capsys, fault, expected):
    source, config, paths, check = source_check
    run(str(source), "system", paths.root, config)
    path = _artifact(paths, source)
    data = json.loads(path.read_text())
    if fault == "json":
        path.write_text("{ truncated")
    elif fault == "utf8":
        path.write_bytes(b"\xff")
    else:
        if fault == "top_level":
            data = []
        elif fault == "schema_missing":
            data.pop("schema_version")
        elif fault == "schema_wrong":
            data["schema_version"] = "unknown.v1"
        elif fault == "source_id":
            data["source_id"] = "other-source"
        elif fault == "source_hash_missing":
            data.pop("source_hash_sha256")
        elif fault == "source_hash":
            data["source_hash_sha256"] = "0" * 64
        elif fault == "chunks_missing":
            data.pop("chunks")
        elif fault == "chunks_null":
            data["chunks"] = None
        elif fault == "chunks_object":
            data["chunks"] = {}
        elif fault == "chunk_not_object":
            data["chunks"] = ["invalid"]
        elif fault == "text_missing":
            data["chunks"][0].pop("text")
        elif fault == "text_empty":
            data["chunks"][0]["text"] = " \n"
        elif fault == "chunk_id":
            data["chunks"][0]["chunk_id"] = "other-source-chunk-0001"
        elif fault == "duplicate_id":
            data["chunks"].append(dict(data["chunks"][0]))
        elif fault == "chunk_source":
            data["chunks"][0]["source_id"] = "other-source"
        elif fault == "chunk_hash":
            data["chunks"][0]["hash_sha256"] = "0" * 64
        elif fault == "tampered_text":
            data["chunks"][0]["text"] += " changed"
        path.write_text(json.dumps(data))
    assert check("--check") == 2
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is False
    assert expected in report["error"]


@pytest.mark.parametrize("text", ["", " \n\t"])
def test_legitimate_empty_ingestion_needs_no_request(source_check, capsys, text):
    source, config, paths, check = source_check
    source.write_text(text)
    result = run(str(source), "system", paths.root, config)
    assert result.chunk_count == 0 and result.request_path is None
    assert check("--check") == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True and report["chunks"] == 0


def test_empty_extraction_without_units_is_valid(source_check, capsys):
    source, config, paths, check = source_check
    # Empty extractor observations may legitimately contain no units at all.
    source.write_text("")
    run(str(source), "system", paths.root, config)
    path = _artifact(paths, source, "source_text")
    observation = json.loads(path.read_text())
    observation["units"] = []
    path.write_text(json.dumps(observation))
    assert check("--check") == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True


@pytest.mark.parametrize("fault, expected", [
    ("missing", "source_artifact_missing"),
    ("json", "source_artifact_invalid_json"),
    ("schema", "source_artifact_schema"),
    ("identity", "source_artifact_identity"),
    ("warnings_missing", "source_extraction_schema"),
    ("warnings_type", "source_extraction_schema"),
    ("units_missing", "source_extraction_schema"),
    ("unit_text_missing", "source_extraction_schema"),
    ("characters_missing", "source_extraction_schema"),
    ("characters_bool", "source_extraction_schema"),
    ("warnings", "source_extraction_warning"),
    ("text_without_chunks", "source_extraction_not_empty"),
    ("characters_without_units", "source_extraction_count_mismatch"),
])
def test_empty_chunks_need_complete_extraction_observation(source_check, capsys, fault, expected):
    source, config, paths, check = source_check
    source.write_text("")
    run(str(source), "system", paths.root, config)
    path = _artifact(paths, source, "source_text")
    data = json.loads(path.read_text())
    if fault == "missing":
        path.unlink()
    elif fault == "json":
        path.write_text("{")
    else:
        if fault == "schema":
            data["schema_version"] = "unknown.v1"
        elif fault == "identity":
            data["source_id"] = "other-source"
        elif fault == "warnings_missing":
            data.pop("warnings")
        elif fault == "warnings_type":
            data["warnings"] = "not-a-list"
        elif fault == "units_missing":
            data.pop("units")
        elif fault == "unit_text_missing":
            data["units"] = [{}]
        elif fault == "characters_missing":
            data.pop("text_characters")
        elif fault == "characters_bool":
            data["text_characters"] = False
        elif fault == "warnings":
            data["warnings"] = ["pdftotext_unavailable:install_poppler"]
        elif fault == "text_without_chunks":
            data["units"] = [{"text": "unread evidence"}]
            data["text_characters"] = 15
        elif fault == "characters_without_units":
            data["units"] = []
            data["text_characters"] = 15
        path.write_text(json.dumps(data))
    assert check("--check") == 2
    assert expected in json.loads(capsys.readouterr().out)["error"]


def test_real_binary_extraction_warning_is_not_empty_success(source_check, capsys):
    source, config, paths, check = source_check
    source.write_bytes(b"synthetic\x00binary")
    result = run(str(source), "system", paths.root, config)
    assert result.chunk_count == 0 and result.warnings
    assert check("--check") == 2
    assert "source_extraction_warning" in json.loads(capsys.readouterr().out)["error"]


@pytest.mark.parametrize("characters, texts", [
    (999, [""]),
    (1, [""]),
    (0, ["", ""]),
    (0, [" "]),
    (4, [" ", " "]),
    (2, [" ", " "]),
])
def test_empty_extraction_character_count_is_exact(source_check, capsys, characters, texts):
    source, config, paths, check = source_check
    source.write_text("")
    run(str(source), "system", paths.root, config)
    path = _artifact(paths, source, "source_text")
    data = json.loads(path.read_text())
    data.update(text_characters=characters, units=[{"text": t} for t in texts])
    path.write_text(json.dumps(data))
    assert check("--check") == 2
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is False
    assert "source_extraction_count_mismatch" in report["error"]
    assert "wiki_ingest.py --source <source> --context <context>" in report["remediation"]


@pytest.mark.parametrize("kind, text", [
    ("csv", ""),
    ("csv", "\n \n\n"),
    ("docx", ""),
    ("docx", " \t"),
    ("eml", ""),
    ("eml", "\n \n\t"),
    ("eml", 'MIME-Version: 1.0\nContent-Type: multipart/mixed; boundary="synthetic"\n\n'
            '--synthetic\nContent-Type: text/plain\n\n \n'
            '--synthetic\nContent-Type: text/plain\n\n\t\n--synthetic--\n'),
])
def test_real_empty_producers_preserve_units_and_separators(source_check, capsys, kind, text):
    _source, config, paths, check = source_check
    source = paths.root / f"empty.{kind}"
    if kind == "docx":
        from docx import Document
        document = Document()
        document.add_paragraph(text)
        document.save(source)
    else:
        source.write_text(text)
    result = run(str(source), "system", paths.root, config)
    assert result.warnings == []
    assert result.chunk_count == 0 and result.request_path is None
    extracted = json.loads(_artifact(paths, source, "source_text").read_text())
    assert extracted["text_characters"] == len("\n".join(u["text"] for u in extracted["units"]))
    assert check("--check", source_override=source) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_email_headers_are_not_mistaken_for_empty_body(source_check, capsys):
    _source, config, paths, check = source_check
    source = paths.root / "headers.eml"
    source.write_text("Subject: Synthetic heading\n\n \n")
    result = run(str(source), "system", paths.root, config)
    assert result.chunk_count > 0
    path = _artifact(paths, source)
    data = json.loads(path.read_text())
    data["chunks"] = []
    path.write_text(json.dumps(data))
    assert check("--check", source_override=source) == 2
    assert "source_extraction_not_empty" in json.loads(capsys.readouterr().out)["error"]


def test_check_remediation_does_not_echo_extractor_messages(source_check, capsys):
    source, config, paths, check = source_check
    source.write_text("")
    run(str(source), "system", paths.root, config)
    path = _artifact(paths, source, "source_text")
    data = json.loads(path.read_text())
    marker = "synthetic-private-extractor-message"
    data["warnings"] = [marker]
    path.write_text(json.dumps(data))
    assert check("--check") == 2
    output = capsys.readouterr()
    assert marker not in output.out + output.err
    report = json.loads(output.out)
    assert "resolve extraction warnings" in report["remediation"]


def test_valid_ingestion_pending_then_recorded_and_optional(source_check, capsys):
    source, config, paths, check = source_check
    result = run(str(source), "system", paths.root, config)
    assert check("--check") == 1
    assert json.loads(capsys.readouterr().out)["pending_llm_calls"] > 0
    config.llm["required_context_pass"] = False
    assert check("--check") == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    config.llm["required_context_pass"] = True
    request = json.loads((paths.root / result.request_path).read_text())
    template = json.loads((ROOT / "tests/fixtures/e2e/context_pass_result.sample.json").read_text())
    for chunk in request["chunks"]:
        recorded = dict(template, cache_key=chunk["cache_key"], source_id=result.source_id, chunk_id=chunk["chunk_id"])
        write_result(paths.llm_cache, recorded)
    assert check("--check") == 0
    assert json.loads(capsys.readouterr().out)["pending_llm_calls"] == 0


def test_invalid_source_cannot_emit_request(source_check, capsys):
    source, config, paths, check = source_check
    assert check("--emit-request") == 2
    assert "source_artifact_missing" in capsys.readouterr().err
    assert not list(paths.extraction_events.glob("*-llm-context-request.json"))


def test_query_without_matches_remains_success(source_check, capsys, monkeypatch):
    source, config, paths, check = source_check
    run(str(source), "system", paths.root, config)
    # Reuse the loaded command with the same real index and no matching terms.
    spec = importlib.util.spec_from_file_location("context_pass_query_empty", ROOT / "scripts/wiki_llm_context_pass.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", paths.root)
    monkeypatch.setattr(module, "load_config", lambda _: config)
    monkeypatch.setattr(sys, "argv", ["wiki_llm_context_pass.py", "--query", "nomatchunique", "--context", "system", "--check"])
    assert module.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True and report["chunks"] == 0
