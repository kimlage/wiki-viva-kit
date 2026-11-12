"""General rule: non-versioned artifact -> content on Drive, link in the wiki.

Covers the drive_aware_md_link helper, the .env parser and the generic Drive
publication helper. Per-repository finance scripts are tested downstream. No
network.
"""

from __future__ import annotations

import importlib.util
import io
import json
import logging
import sys
import builtins
import traceback
import types
import zipfile

import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import wiki_core.drive_links as dl  # noqa: E402


def _load(path_rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / path_rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_drive_aware_link_uses_drive_for_untracked(monkeypatch, tmp_path):
    monkeypatch.setattr(dl, "_manifest_files", lambda: {"x.csv": {"view_url": "https://drive.google.com/file/d/abc/view"}})
    monkeypatch.setattr(dl, "_tracked_set", lambda: frozenset())
    link = dl.drive_aware_md_link(dl.ROOT / "data/derived/2026/x.csv", dl.ROOT / "memories")
    assert link == "[x.csv (Drive)](https://drive.google.com/file/d/abc/view)"


def test_drive_aware_link_local_for_tracked(monkeypatch):
    monkeypatch.setattr(dl, "_manifest_files", lambda: {"y.csv": {"view_url": "https://drive.google.com/file/d/zzz/view"}})
    monkeypatch.setattr(dl, "_tracked_set", lambda: frozenset({"data/derived/2026/y.csv"}))
    link = dl.drive_aware_md_link(dl.ROOT / "data/derived/2026/y.csv", dl.ROOT / "memories")
    assert "drive.google.com" not in link  # versioned: local relative link
    assert "../data/derived/2026/y.csv" in link


def test_drive_aware_link_local_when_unpublished(monkeypatch):
    monkeypatch.setattr(dl, "_manifest_files", lambda: {})
    monkeypatch.setattr(dl, "_tracked_set", lambda: frozenset())
    link = dl.drive_aware_md_link(dl.ROOT / "data/derived/2026/z.csv", dl.ROOT / "memories")
    assert "drive.google.com" not in link


def test_tracked_set_nul_split_handles_spaces_and_accents(monkeypatch):
    dl.invalidate_caches()
    calls: list[list[str]] = []

    def fake_check_output(cmd, cwd=None, **kwargs):
        calls.append(list(cmd))
        return "data/raw/relatório médico.pdf\x00docs/a b.md\x00".encode("utf-8")

    monkeypatch.setattr(dl.subprocess, "check_output", fake_check_output)
    try:
        tracked = dl._tracked_set()
        assert "data/raw/relatório médico.pdf" in tracked  # raw path, not git-quoted
        assert "docs/a b.md" in tracked
        assert "" not in tracked  # trailing NUL does not produce an empty entry
        assert "-z" in calls[0]
    finally:
        dl.invalidate_caches()


def test_invalidate_caches_clears_both_lru(monkeypatch, tmp_path):
    dl.invalidate_caches()
    counter = {"git": 0}

    def fake_check_output(cmd, cwd=None, **kwargs):
        counter["git"] += 1
        return b"a.md\x00"

    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"files": {"m.csv": {"view_url": "u"}}}), encoding="utf-8")
    monkeypatch.setattr(dl.subprocess, "check_output", fake_check_output)
    monkeypatch.setattr(dl, "MANIFEST_PATH", manifest)
    try:
        assert dl._tracked_set() == frozenset({"a.md"})
        dl._tracked_set()
        assert counter["git"] == 1  # cached
        assert dl._manifest_files() == {"m.csv": {"view_url": "u"}}
        manifest.write_text(json.dumps({"files": {}}), encoding="utf-8")
        dl.invalidate_caches()
        dl._tracked_set()
        assert counter["git"] == 2  # tracked-set cache cleared
        assert dl._manifest_files() == {}  # manifest cache cleared
    finally:
        dl.invalidate_caches()


def test_publish_env_parser(tmp_path):
    pub = _load("scripts/wiki_drive_publish.py", "wdp_test")
    env_file = tmp_path / ".env"
    env_file.write_text("# comentario\nWIKI_DRIVE_FOLDER_ID = 'abc123'\nOUTRA=x\n", encoding="utf-8")
    env = pub.load_env(env_file)
    assert env["WIKI_DRIVE_FOLDER_ID"] == "abc123"
    assert env["OUTRA"] == "x"
    assert pub.load_env(tmp_path / "inexistente.env") == {}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import socket
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("network"))
    monkeypatch.setattr(socket.socket, "connect_ex", lambda *a, **k: pytest.fail("network"))


def _block_provider_imports(monkeypatch):
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name.startswith(("googleapiclient", "common.google_clients")):
            pytest.fail("provider import")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)


def _publisher(tmp_path, monkeypatch, files=None):
    pub = _load("scripts/wiki_drive_publish.py", "wdp_synthetic")
    monkeypatch.setattr(pub, "ROOT", tmp_path)
    monkeypatch.setattr(pub, "MANIFEST_PATH", tmp_path / "manifest.json")
    pub.MANIFEST_PATH.write_text(json.dumps({"folder_id": "synthetic-folder", "files": files or {}}))
    artifact = tmp_path / "synthetic.csv"
    artifact.write_text("synthetic content", encoding="utf-8")
    return pub, artifact


class _FakeRequest:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class _FakeDrive:
    def __init__(self, **behavior):
        self.behavior = behavior
        self.calls = []

    def files(self):
        return self

    def __getattr__(self, method):
        assert method in {"get", "list", "create", "update"}

        def request(**kwargs):
            self.calls.append((method, kwargs))
            return _FakeRequest(lambda: self.behavior[method](**kwargs))

        return request


def _install_fake_google(monkeypatch, drive, *, real_media=False):
    # No real helper, account, credentials or network. The optional media class
    # only wraps captured bytes locally; all service requests remain fake.
    if real_media:
        MediaIoBaseUpload = pytest.importorskip("googleapiclient.http").MediaIoBaseUpload
    monkeypatch.setattr(sys, "path", list(sys.path))
    calls = {"build": [], "media": []}
    pkg = types.ModuleType("googleapiclient")
    http = types.ModuleType("googleapiclient.http")
    def media(*args, **kwargs):
        calls["media"].append((args, kwargs))
        return MediaIoBaseUpload(*args, **kwargs) if real_media else object()
    http.MediaIoBaseUpload = media
    common = types.ModuleType("common")
    clients = types.ModuleType("common.google_clients")
    clients.DRIVE_SCOPE_FULL = "synthetic-scope"
    clients.build_service = lambda *a, **k: calls["build"].append((a, k)) or drive
    pkg.http = http
    common.google_clients = clients
    for name, module in {"googleapiclient": pkg, "googleapiclient.http": http,
                         "common": common, "common.google_clients": clients}.items():
        monkeypatch.setitem(sys.modules, name, module)
    return calls


@pytest.mark.parametrize("resumable", [False, True])
def test_upload_helper_executes_plain_and_resumable_requests(resumable, capsys):
    pub = _load("scripts/wiki_drive_publish.py", "wdp_chunks")
    meta = {"id": "synthetic-id"}
    calls = []
    request = _FakeRequest(lambda: calls.append("execute") or meta)
    if resumable:
        chunks = iter([(types.SimpleNamespace(progress=lambda: 0.5), None), (None, meta)])
        request.next_chunk = lambda: calls.append("chunk") or next(chunks)
    assert pub.execute_drive_upload(request, label="synthetic") == meta
    assert calls == (["chunk", "chunk"] if resumable else ["execute"])
    assert ("synthetic: upload 50%" in capsys.readouterr().err) == resumable


@pytest.mark.parametrize("replace_fails", [False, True])
def test_save_manifest_replaces_complete_json_and_preserves_original_on_failure(tmp_path, monkeypatch, replace_fails):
    pub, _ = _publisher(tmp_path, monkeypatch)
    original = pub.MANIFEST_PATH.read_bytes()
    manifest = {"files": {"synthetic.csv": {"drive_file_id": "synthetic-id"}}}
    if replace_fails:
        def fail(*args):
            raise OSError("synthetic replacement failure")
        monkeypatch.setattr(pub.os, "replace", fail)
        with pytest.raises(OSError, match="replacement"):
            pub.save_manifest(manifest)
        assert pub.MANIFEST_PATH.read_bytes() == original
    else:
        pub.save_manifest(manifest)
        assert json.loads(pub.MANIFEST_PATH.read_text()) == manifest
    assert {p.name for p in tmp_path.iterdir()} == {"synthetic.csv", "manifest.json"}


@pytest.mark.parametrize("existing", [False, True])
def test_publish_creates_or_updates_exact_manifest_target(tmp_path, monkeypatch, existing):
    files = {"other.csv": {"drive_file_id": "keep-id"}}
    if existing:
        files["synthetic.csv"] = {"drive_file_id": "synthetic-id", "sha256": "old"}
    pub, artifact = _publisher(tmp_path, monkeypatch, files)
    target = {"id": "synthetic-id", "name": artifact.name, "parents": ["synthetic-folder"], "trashed": False}
    drive = _FakeDrive(get=lambda **k: target, list=lambda **k: {"files": []},
                       create=lambda **k: {"id": "synthetic-id"}, update=lambda **k: {"id": "synthetic-id"})
    calls = _install_fake_google(monkeypatch, drive)
    report = pub.publish([artifact], "synthetic-folder")
    assert "published -> https://drive.google.com/file/d/synthetic-id/view" in report["results"][0]
    saved = json.loads(pub.MANIFEST_PATH.read_text())
    assert saved["folder_id"] == "synthetic-folder"
    assert saved["files"]["other.csv"] == files["other.csv"]
    assert saved["files"][artifact.name] == {
        "drive_file_id": "synthetic-id", "sha256": pub.sha256_file(artifact),
        "view_url": "https://drive.google.com/file/d/synthetic-id/view",
        "source_path": artifact.name, "updated_at": pub.dt.date.today().isoformat(),
    }
    assert [method for method, _ in drive.calls] == (["get", "update"] if existing else ["list", "create"])
    effect = drive.calls[-1][1]
    if existing:
        assert effect["fileId"] == "synthetic-id"
    else:
        assert effect["body"] == {"name": artifact.name, "parents": ["synthetic-folder"]}
    assert calls["build"] == [(("drive", "v3"), {"required_scopes": ["synthetic-scope"]})]
    assert calls["media"][0][1] == {"mimetype": "text/csv", "chunksize": 8 * 1024 * 1024, "resumable": True}
    assert calls["media"][0][0][0].getvalue() == artifact.read_bytes()


@pytest.mark.parametrize("problem", ["name", "parents", "trashed", "missing-trashed", "id", "404", "update-error", "collision", "page"])
def test_target_conflicts_and_errors_preserve_manifest_without_fallback(tmp_path, monkeypatch, problem):
    entry = {} if problem in {"collision", "page"} else {"synthetic.csv": {"drive_file_id": "synthetic-id"}}
    pub, artifact = _publisher(tmp_path, monkeypatch, entry)
    before = pub.MANIFEST_PATH.read_bytes()
    target = {"id": "synthetic-id", "name": artifact.name, "parents": ["synthetic-folder"], "trashed": False}
    if problem in target:
        target[problem] = {"id": "different-id", "name": "different.csv", "parents": ["elsewhere"], "trashed": True}[problem]
    if problem == "missing-trashed":
        del target["trashed"]

    def get(**kwargs):
        if problem == "404":
            raise RuntimeError("synthetic HTTP 404")
        return target

    def update(**kwargs):
        raise RuntimeError("synthetic update error")

    drive = _FakeDrive(get=get, update=update, list=lambda **k: (
        {"files": [{"id": "unrelated"}]} if problem == "collision" else {"files": [], "nextPageToken": "more"}))
    _install_fake_google(monkeypatch, drive)
    with pytest.raises(RuntimeError):
        pub.publish([artifact], "synthetic-folder")
    assert pub.MANIFEST_PATH.read_bytes() == before
    assert [m for m, _ in drive.calls] == (
        ["list"] if problem in {"collision", "page"} else ["get", "update"] if problem == "update-error" else ["get"])


def test_completed_file_is_saved_before_later_uncertain_create(tmp_path, monkeypatch):
    pub, artifact = _publisher(tmp_path, monkeypatch)
    later = tmp_path / "later.csv"
    later.write_text("synthetic later content")
    effects = []

    def create(body, **kwargs):
        effects.append(body["name"])
        if body["name"] == later.name:
            raise ConnectionError("synthetic response lost after effect")
        return {"id": "synthetic-id", "webViewLink": "https://drive.google.com/file/d/synthetic-id/view"}

    drive = _FakeDrive(list=lambda **k: {"files": []}, create=create)
    _install_fake_google(monkeypatch, drive)
    with pytest.raises(ConnectionError, match="response lost"):
        pub.publish([artifact, later], "synthetic-folder")
    saved = json.loads(pub.MANIFEST_PATH.read_text())["files"]
    assert list(saved) == [artifact.name]
    assert saved[artifact.name]["drive_file_id"] == "synthetic-id"
    assert effects == [artifact.name, later.name]  # no retry; later effect still needs reconciliation


@pytest.mark.parametrize("problem", ["missing-folder", "different-folder", "legacy-unscoped", "duplicate-name"])
def test_local_destination_and_batch_conflicts_fail_before_provider(tmp_path, monkeypatch, problem):
    pub, artifact = _publisher(tmp_path, monkeypatch, {"original.csv": {"drive_file_id": "original-id"}})
    if problem == "legacy-unscoped":
        pub.MANIFEST_PATH.write_text(json.dumps({"files": {"original.csv": {"drive_file_id": "original-id"}}}))
    before = pub.MANIFEST_PATH.read_bytes()
    folder = "" if problem == "missing-folder" else "elsewhere" if problem == "different-folder" else "synthetic-folder"
    paths = [artifact, tmp_path / "other" / artifact.name] if problem == "duplicate-name" else [artifact]
    _block_provider_imports(monkeypatch)
    with pytest.raises(ValueError):
        pub.publish(paths, folder)
    assert pub.MANIFEST_PATH.read_bytes() == before


@pytest.mark.parametrize("matching", [False, True])
def test_dry_run_is_local_read_only_and_does_not_claim_remote_state(tmp_path, monkeypatch, matching):
    pub, artifact = _publisher(tmp_path, monkeypatch)
    pub.MANIFEST_PATH.write_text(json.dumps({"folder_id": "synthetic-folder", "files": {artifact.name: {
        "sha256": pub.sha256_file(artifact) if matching else "old", "drive_file_id": "synthetic-id"}}}))
    before = pub.MANIFEST_PATH.read_bytes()
    _block_provider_imports(monkeypatch)
    monkeypatch.setattr(pub, "save_manifest", lambda *a, **k: pytest.fail("manifest write"))
    monkeypatch.setattr(pub, "execute_drive_upload", lambda *a, **k: pytest.fail("upload"))
    monkeypatch.setattr(pub, "load_env", lambda: pytest.fail("environment read"))
    report = pub.publish([artifact, tmp_path / "missing.csv"], "synthetic-folder", dry_run=True)
    assert len(report["results"]) == 1
    assert "remote unverified" in report["results"][0]
    assert ("matching sha" if matching else "would upload") in report["results"][0]
    assert pub.MANIFEST_PATH.read_bytes() == before
    assert {p.name for p in tmp_path.iterdir()} == {"manifest.json", "synthetic.csv"}


def test_matching_local_sha_skips_upload_without_claiming_remote_verification(tmp_path, monkeypatch):
    pub, artifact = _publisher(tmp_path, monkeypatch)
    pub.MANIFEST_PATH.write_text(json.dumps({"folder_id": "synthetic-folder", "files": {artifact.name: {
        "sha256": pub.sha256_file(artifact), "drive_file_id": "synthetic-id"}}}))
    before = pub.MANIFEST_PATH.read_bytes()
    _block_provider_imports(monkeypatch)
    monkeypatch.setattr(pub, "save_manifest", lambda *a, **k: pytest.fail("manifest write"))
    assert "remote unverified" in pub.publish([artifact], "synthetic-folder")["results"][0]
    assert pub.MANIFEST_PATH.read_bytes() == before


@pytest.mark.parametrize("dry_run", [False, True])
def test_secret_in_later_artifact_rejects_whole_batch_before_provider(tmp_path, monkeypatch, dry_run):
    pub, artifact = _publisher(tmp_path, monkeypatch)
    secret = tmp_path / "later.txt"
    secret.write_text("-----BEGIN " + "PRIVATE KEY-----\nsynthetic-only\n")
    before = pub.MANIFEST_PATH.read_bytes()
    _block_provider_imports(monkeypatch)
    with pytest.raises(RuntimeError, match="contains an access secret") as error:
        pub.publish([artifact, secret], "synthetic-folder", dry_run=dry_run)
    assert "synthetic-only" not in str(error.value)
    assert pub.MANIFEST_PATH.read_bytes() == before


@pytest.mark.parametrize("failure", ["secret", "warning", "exception", "binary"])
def test_unvalidated_or_extracted_secret_content_never_reaches_provider(tmp_path, monkeypatch, failure):
    pub, _ = _publisher(tmp_path, monkeypatch)
    artifact = tmp_path / ("artifact.bin" if failure == "binary" else "artifact.pdf")
    artifact.write_bytes(b"\x00synthetic binary" if failure == "binary" else _pdf_artifact()[2])
    def extracted(*args):
        if failure == "exception":
            raise ValueError("source content must not leak")
        return types.SimpleNamespace(
            text="-----BEGIN " + "PRIVATE KEY-----" if failure == "secret" else "synthetic text",
            warnings=["extraction incomplete"] if failure == "warning" else [],
            units=[],
        )
    monkeypatch.setattr(pub, "extract_captured", extracted)
    _block_provider_imports(monkeypatch)
    before = pub.MANIFEST_PATH.read_bytes()
    with pytest.raises(RuntimeError, match="contains an access secret" if failure == "secret" else "validation unavailable") as error:
        pub.publish([artifact], "synthetic-folder")
    assert "source content must not leak" not in str(error.value)
    assert pub.MANIFEST_PATH.read_bytes() == before


def _office_artifact(case, value):
    target = io.BytesIO()
    if case.startswith("docx"):
        from docx import Document
        document = Document()
        document.add_paragraph("Synthetic body")
        if case == "docx-header":
            document.sections[0].header.paragraphs[0].text = value
        elif case == "docx-footer":
            document.sections[0].footer.paragraphs[0].text = value
        else:
            document.add_table(rows=1, cols=1).cell(0, 0).text = value
        document.save(target)
        return ".docx", "document", target.getvalue()
    from openpyxl import Workbook
    from openpyxl.comments import Comment
    workbook = Workbook()
    workbook.active["A1"] = "Synthetic body"
    if case == "xlsx-comment":
        workbook.active["A1"].comment = Comment(value, "Synthetic author")
    else:
        workbook.active["B1"] = value
    workbook.save(target)
    workbook.close()
    return ".xlsx", "spreadsheet", target.getvalue()


def _pdf_artifact(annotation=None, *, body="Synthetic PDF content"):
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import (ArrayObject, ByteStringObject, DecodedStreamObject, DictionaryObject,
                              NameObject, NumberObject)
    from tests.test_protected_capture_formats import pdf_bytes
    writer = PdfWriter()
    writer.add_page(PdfReader(io.BytesIO(pdf_bytes())).pages[0])
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 20 250 Td (" + body.encode("ascii") + b") Tj ET")
    writer.pages[0][NameObject("/Contents")] = writer._add_object(stream)
    if annotation is not None:
        note = DictionaryObject({
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Text"),
            NameObject("/Rect"): ArrayObject([NumberObject(n) for n in (0, 0, 20, 20)]),
            # A real PDF hex string in UTF-16BE; raw UTF-8 scanning cannot see it.
            NameObject("/Contents"): ByteStringObject(b"\xfe\xff" + annotation.encode("utf-16-be")),
        })
        writer.pages[0][NameObject("/Annots")] = ArrayObject([writer._add_object(note)])
    target = io.BytesIO()
    writer.write(target)
    return ".pdf", "pdf", target.getvalue()


def _association_table(suffix, rows):
    target = io.BytesIO()
    if suffix == ".docx":
        from docx import Document
        document = Document()
        document.add_paragraph("Synthetic table body")
        table = document.add_table(rows=0, cols=2)
        for values in rows:
            for cell, value in zip(table.add_row().cells, values):
                cell.text = value
        document.save(target)
    else:
        from openpyxl import Workbook
        workbook = Workbook()
        workbook.active.append(["Synthetic table body"])
        for values in rows:
            workbook.active.append(values)
        workbook.save(target)
        workbook.close()
    return target.getvalue()


@pytest.mark.parametrize("suffix", [".docx", ".xlsx"])
@pytest.mark.parametrize("layout", ["fields", "headers", "reversed"])
@pytest.mark.parametrize("dry_run", [False, True])
def test_real_table_credential_associations_refused_before_provider(tmp_path, monkeypatch, suffix, layout, dry_run):
    from wiki_core.detectors import contains_secret_structure
    from wiki_core.extractors.text import extract_captured
    credentials = {"client_id": "synthetic-client", "refresh_token": "synthetic-short"}
    assert contains_secret_structure(credentials)
    rows = list(credentials.items())
    if layout == "headers":
        rows = list(zip(*rows))
    elif layout == "reversed":
        rows = [tuple(reversed(row)) for row in rows]
    pub, first = _publisher(tmp_path, monkeypatch)
    artifact = tmp_path / ("credentials" + suffix)
    data = _association_table(suffix, rows)
    artifact.write_bytes(data)
    extracted = extract_captured(str(artifact), "document" if suffix == ".docx" else "spreadsheet", data)
    assert not extracted.warnings and extracted.text.strip()
    # Decoding the extractor envelopes still misses the association.
    assert not contains_secret_structure([json.loads(unit["text"]) for unit in extracted.units
                                          if unit["kind"] in {"sheet_row", "doc_table_row"}])
    drive = _FakeDrive(list=lambda **k: {"files": []}, create=lambda **k: {"id": "synthetic-id"})
    calls = _install_fake_google(monkeypatch, drive, real_media=True)
    before = pub.MANIFEST_PATH.read_bytes()
    with pytest.raises(RuntimeError, match="contains an access secret"):
        pub.publish([first, artifact], "synthetic-folder", dry_run=dry_run)
    assert not drive.calls and calls == {"build": [], "media": []}
    assert pub.MANIFEST_PATH.read_bytes() == before


@pytest.mark.parametrize("suffix", [".docx", ".xlsx"])
@pytest.mark.parametrize("layout", ["fields", "headers", "reversed"])
def test_real_table_associations_allow_synthetic_pii(tmp_path, monkeypatch, suffix, layout):
    rows = [("name", "Synthetic person"), ("cpf", "529.982.247-25")]
    if layout == "headers":
        rows = list(zip(*rows))
    elif layout == "reversed":
        rows = [tuple(reversed(row)) for row in rows]
    pub, _ = _publisher(tmp_path, monkeypatch)
    artifact = tmp_path / ("pii" + suffix)
    data = _association_table(suffix, rows)
    artifact.write_bytes(data)
    uploaded = []
    def create(media_body, **kwargs):
        uploaded.append(media_body.getbytes(0, media_body.size()))
        return {"id": "synthetic-id"}
    drive = _FakeDrive(list=lambda **k: {"files": []}, create=create)
    _install_fake_google(monkeypatch, drive, real_media=True)
    pub.publish([artifact], "synthetic-folder")
    assert uploaded == [data]
    entry = json.loads(pub.MANIFEST_PATH.read_text())["files"][artifact.name]
    assert entry["sha256"] == pub.hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize("case", ["docx-header", "xlsx-comment", "pdf-annotation", "docx-table", "xlsx-cell"])
@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("matching", [False, True])
@pytest.mark.parametrize("real_media", [False, True])
def test_real_container_bypasses_are_refused_before_provider(tmp_path, monkeypatch, case, dry_run, matching, real_media):
    from wiki_core.detectors import scan_text
    from wiki_core.extractors.text import extract_captured
    pub, first = _publisher(tmp_path, monkeypatch)
    value = (json.dumps({"client_id": "synthetic-client", "refresh_token": "synthetic-short"})
             if case in {"docx-table", "xlsx-cell"} else "-----BEGIN " + "PRIVATE KEY-----\nsynthetic-only")
    suffix, kind, data = (_pdf_artifact(value) if case == "pdf-annotation" else _office_artifact(case, value))
    artifact = tmp_path / ("later" + suffix)
    artifact.write_bytes(data)
    # Prove the original gap using the real extractor, not a patched provider
    # response or extractor. Both old scans miss the omitted/escaped material.
    assert not any(f.category == "secret" for f in scan_text(data.decode("utf-8", errors="replace")))
    extracted = extract_captured(str(artifact), kind, data)
    assert extracted.text.strip() and not extracted.warnings
    assert not any(f.category == "secret" for f in scan_text(extracted.text))
    drive = _FakeDrive(list=lambda **k: {"files": []}, create=lambda **k: {"id": "synthetic-id"})
    calls = _install_fake_google(monkeypatch, drive, real_media=real_media)
    if matching:
        pub.MANIFEST_PATH.write_text(json.dumps({"folder_id": "synthetic-folder", "files": {
            artifact.name: {"sha256": pub.hashlib.sha256(data).hexdigest(), "drive_file_id": "synthetic-id"}}}))
    before = pub.MANIFEST_PATH.read_bytes()
    with pytest.raises(RuntimeError, match="publication refused") as error:
        pub.publish([first, artifact], "synthetic-folder", dry_run=dry_run)
    rendered = "".join(traceback.format_exception(error.type, error.value, error.tb))
    assert value not in rendered and "synthetic-short" not in rendered and "synthetic-only" not in rendered
    assert not drive.calls and calls == {"build": [], "media": []}
    assert pub.MANIFEST_PATH.read_bytes() == before


@pytest.mark.parametrize("case", ["docx-table", "xlsx-cell", "pdf", "eml", "txt"])
@pytest.mark.parametrize("real_media", [False, True])
def test_real_covered_formats_publish_synthetic_pii(tmp_path, monkeypatch, case, real_media):
    from wiki_core.detectors import scan_text
    value = "Synthetic CPF 529.982.247-25"
    assert any(f.category == "pii" for f in scan_text(value))
    pub, _ = _publisher(tmp_path, monkeypatch)
    if case == "pdf":
        suffix, _, data = _pdf_artifact(body=value)
    elif case in {"eml", "txt"}:
        suffix = "." + case
        data = (("From: synthetic@example.invalid\nSubject: Synthetic\n\n" if case == "eml" else "") + value).encode()
    else:
        suffix, _, data = _office_artifact(case, value)
    artifact = tmp_path / ("covered" + suffix)
    artifact.write_bytes(data)
    uploaded = []
    def create(media_body, **kwargs):
        if real_media:
            uploaded.append(media_body.getbytes(0, media_body.size()))
        return {"id": "synthetic-id"}
    drive = _FakeDrive(list=lambda **k: {"files": []}, create=create)
    calls = _install_fake_google(monkeypatch, drive, real_media=real_media)
    pub.publish([artifact], "synthetic-folder")
    assert [method for method, _ in drive.calls] == ["list", "create"]
    assert calls["media"][0][0][0].getvalue() == data
    if real_media:
        assert uploaded == [data]
    entry = json.loads(pub.MANIFEST_PATH.read_text())["files"][artifact.name]
    assert entry["sha256"] == pub.hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize("case", ["docx-header", "docx-footer", "xlsx-comment", "pdf-annotation"])
def test_uncovered_parts_are_refused_even_without_a_detected_secret(tmp_path, monkeypatch, case):
    pub, _ = _publisher(tmp_path, monkeypatch)
    suffix, _, data = (_pdf_artifact("Synthetic note") if case == "pdf-annotation"
                       else _office_artifact(case, "Synthetic note"))
    artifact = tmp_path / ("uncovered" + suffix)
    artifact.write_bytes(data)
    before = pub.MANIFEST_PATH.read_bytes()
    _block_provider_imports(monkeypatch)
    with pytest.raises(RuntimeError, match="validation unavailable"):
        pub.publish([artifact], "synthetic-folder")
    assert pub.MANIFEST_PATH.read_bytes() == before


@pytest.mark.parametrize("case", ["docx-header", "xlsx-comment"])
def test_office_part_coverage_is_not_inferred_from_its_name_or_content_type(tmp_path, monkeypatch, case):
    from wiki_core.extractors.text import extract_captured
    pub, _ = _publisher(tmp_path, monkeypatch)
    suffix, kind, original = _office_artifact(case, "Synthetic omitted text")
    target = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original)) as archive, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as rewritten:
        old = next(name for name in archive.namelist()
                   if name.endswith(".xml") and ("/header" in name or "/comment" in name))
        new = str(Path(old).with_name("synthetic-part.xml"))
        for entry in archive.infolist():
            data = archive.read(entry)
            if entry.filename == "[Content_Types].xml":
                from xml.etree import ElementTree as ET
                root = ET.fromstring(data)
                for part in root:
                    if part.get("PartName") == "/" + old:
                        part.set("PartName", "/" + new)
                        part.set("ContentType", "application/xml")
                data = ET.tostring(root)
            elif entry.filename.endswith(".rels"):
                data = data.replace(Path(old).name.encode(), Path(new).name.encode())
            rewritten.writestr(new if entry.filename == old else entry.filename, data)
    artifact = tmp_path / ("renamed" + suffix)
    artifact.write_bytes(target.getvalue())
    extracted = extract_captured(str(artifact), kind, artifact.read_bytes())
    assert extracted.text.strip() and not extracted.warnings
    _block_provider_imports(monkeypatch)
    with pytest.raises(RuntimeError, match="validation unavailable"):
        pub.validate_artifact(artifact)


@pytest.mark.parametrize("suffix", [".docx", ".xlsx", ".pdf"])
def test_real_parser_failures_have_opaque_tracebacks(tmp_path, monkeypatch, suffix):
    pub, _ = _publisher(tmp_path, monkeypatch)
    artifact = tmp_path / ("malformed" + suffix)
    artifact.write_bytes(b"malformed synthetic source diagnostic must stay opaque")
    before = pub.MANIFEST_PATH.read_bytes()
    _block_provider_imports(monkeypatch)
    with pytest.raises(RuntimeError, match="validation unavailable") as error:
        pub.publish([artifact], "synthetic-folder")
    assert "source diagnostic" not in "".join(traceback.format_exception(error.type, error.value, error.tb))
    assert pub.MANIFEST_PATH.read_bytes() == before


@pytest.mark.parametrize("failure", ["missing-parser", "diagnostic"])
def test_pdf_structure_check_fails_opaquely_without_parser_or_on_diagnostic(tmp_path, monkeypatch, caplog, failure):
    import pypdf
    pub, _ = _publisher(tmp_path, monkeypatch)
    artifact = tmp_path / "checked.pdf"
    artifact.write_bytes(_pdf_artifact()[2])
    logger = logging.getLogger("pypdf")
    original_handlers, original_level = list(logger.handlers), logger.level
    before = pub.MANIFEST_PATH.read_bytes()
    _block_provider_imports(monkeypatch)
    if failure == "missing-parser":
        original_import = builtins.__import__
        def guarded(name, *args, **kwargs):
            if name == "pypdf":
                raise ImportError("synthetic source diagnostic must not leak")
            return original_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", guarded)
    else:
        def reader(*args, **kwargs):
            logging.getLogger("pypdf._reader").warning("synthetic source diagnostic must not leak")
            pytest.fail("parser diagnostic was not refused")
        monkeypatch.setattr(pypdf, "PdfReader", reader)
    with pytest.raises(RuntimeError, match="validation unavailable") as error:
        pub.publish([artifact], "synthetic-folder")
    assert "source diagnostic" not in "".join(traceback.format_exception(error.type, error.value, error.tb))
    assert "source diagnostic" not in caplog.text
    assert logger.handlers == original_handlers and logger.level == original_level
    assert pub.MANIFEST_PATH.read_bytes() == before


def test_upload_uses_checked_bytes_when_original_changes_before_provider(tmp_path, monkeypatch):
    pub, artifact = _publisher(tmp_path, monkeypatch)
    original = artifact.read_bytes()
    validate = pub.validate_artifact
    def replace_after_validation(path):
        captured = validate(path)
        path.write_text("different synthetic content")
        return captured
    monkeypatch.setattr(pub, "validate_artifact", replace_after_validation)
    drive = _FakeDrive(list=lambda **k: {"files": []}, create=lambda **k: {"id": "synthetic-id"})
    calls = _install_fake_google(monkeypatch, drive)
    pub.publish([artifact], "synthetic-folder")
    assert calls["media"][0][0][0].getvalue() == original
    saved = json.loads(pub.MANIFEST_PATH.read_text())["files"][artifact.name]
    assert saved["sha256"] == pub.hashlib.sha256(original).hexdigest()


def test_structured_validation_receives_captured_bytes_without_reopening(tmp_path, monkeypatch):
    pub, _ = _publisher(tmp_path, monkeypatch)
    artifact = tmp_path / "artifact.pdf"
    artifact.write_bytes(_pdf_artifact()[2])
    original = artifact.read_bytes()
    def extract(source, kind, content):
        assert (source, kind, content) == (str(artifact), "pdf", original)
        artifact.write_bytes(b"different contents after capture")
        return types.SimpleNamespace(text="synthetic extracted text", warnings=[], units=[])
    monkeypatch.setattr(pub, "extract_captured", extract)
    assert pub.validate_artifact(artifact) == original


@pytest.mark.parametrize("dry_run", [False, True])
def test_cli_uses_configured_destination_and_requested_mode(tmp_path, monkeypatch, capsys, dry_run):
    pub = _load("scripts/wiki_drive_publish.py", "wdp_cli")
    monkeypatch.setattr(pub, "ROOT", tmp_path)
    helper = str(tmp_path / "synthetic-helper")
    monkeypatch.delenv("GOOGLE_WORKSPACE_SCRIPTS", raising=False)
    monkeypatch.setattr(pub, "load_env", lambda: {
        "WIKI_DRIVE_FOLDER_ID": "synthetic-folder", "GOOGLE_WORKSPACE_SCRIPTS": helper})
    calls = []
    monkeypatch.setattr(pub, "publish", lambda *a, **k: calls.append((a, k)) or {"results": []})
    assert pub.main(["synthetic.csv"] + (["--dry-run"] if dry_run else [])) == 0
    assert calls == [(([tmp_path / "synthetic.csv"], "synthetic-folder"), {"dry_run": dry_run})]
    assert pub.os.environ.get("GOOGLE_WORKSPACE_SCRIPTS") == (None if dry_run else helper)
    assert json.loads(capsys.readouterr().out) == {"results": []}


def test_cli_missing_destination_fails_before_publication(monkeypatch, capsys):
    pub = _load("scripts/wiki_drive_publish.py", "wdp_cli_missing")
    monkeypatch.setattr(pub, "load_env", lambda: {})
    monkeypatch.setattr(pub, "publish", lambda *a, **k: pytest.fail("publication"))
    assert pub.main(["synthetic.csv"]) == 2
    assert "WIKI_DRIVE_FOLDER_ID missing" in capsys.readouterr().err
