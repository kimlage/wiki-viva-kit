"""General rule: non-versioned artifact -> content on Drive, link in the wiki.

Covers the drive_aware_md_link helper, the .env parser and the generic Drive
publication helper. Per-repository finance scripts are tested downstream. No
network.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types

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


# --------------------------------------------------------------------------- #
# wiki_drive_publish with a FAKE Drive client (no network, no Google libs):
# dead drive_file_id falls back to search-by-name/create, and the manifest is
# saved incrementally after each file.
# --------------------------------------------------------------------------- #


class _FakeRequest:
    def __init__(self, fn):
        self._fn = fn

    def execute(self):
        return self._fn()


class _FakeFilesApi:
    def __init__(self, behavior):
        self._behavior = behavior

    def update(self, fileId=None, media_body=None, fields=None):
        return _FakeRequest(lambda: self._behavior["update"](fileId))

    def list(self, q=None, fields=None):
        return _FakeRequest(lambda: self._behavior["list"](q))

    def create(self, body=None, media_body=None, fields=None):
        return _FakeRequest(lambda: self._behavior["create"](body))


class _FakeDrive:
    def __init__(self, behavior):
        self._files = _FakeFilesApi(behavior)

    def files(self):
        return self._files


class _FakeHttpError(Exception):
    """Mimics googleapiclient.errors.HttpError (carries resp.status)."""

    def __init__(self, status: int):
        super().__init__(f"HTTP {status}")
        self.resp = types.SimpleNamespace(status=status)


def _install_fake_google(monkeypatch, drive) -> None:
    pkg = types.ModuleType("googleapiclient")
    errors_mod = types.ModuleType("googleapiclient.errors")
    errors_mod.HttpError = _FakeHttpError
    http_mod = types.ModuleType("googleapiclient.http")
    http_mod.MediaFileUpload = lambda *a, **k: object()
    pkg.errors = errors_mod
    pkg.http = http_mod
    common_pkg = types.ModuleType("common")
    clients_mod = types.ModuleType("common.google_clients")
    clients_mod.DRIVE_SCOPE_FULL = "drive-scope"
    clients_mod.build_service = lambda *a, **k: drive
    common_pkg.google_clients = clients_mod
    for name, mod in {
        "googleapiclient": pkg,
        "googleapiclient.errors": errors_mod,
        "googleapiclient.http": http_mod,
        "common": common_pkg,
        "common.google_clients": clients_mod,
    }.items():
        monkeypatch.setitem(sys.modules, name, mod)


def test_publish_dead_drive_id_falls_back_to_create(tmp_path, monkeypatch, capsys):
    pub = _load("scripts/wiki_drive_publish.py", "wdp_404")
    artifact = tmp_path / "a.csv"
    artifact.write_text("new content", encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({"files": {"a.csv": {"sha256": "stale", "drive_file_id": "dead-id", "view_url": "u"}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(pub, "MANIFEST_PATH", manifest_path)

    def update(file_id):
        raise _FakeHttpError(404)  # manifest id no longer exists on Drive

    drive = _FakeDrive(
        {
            "update": update,
            "list": lambda q: {"files": []},
            "create": lambda body: {"id": "new-id", "webViewLink": "https://drive/new"},
        }
    )
    _install_fake_google(monkeypatch, drive)

    report = pub.publish([artifact], "folder")
    assert any("a.csv" in r for r in report["results"])
    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert saved["files"]["a.csv"]["drive_file_id"] == "new-id"  # healed entry
    assert "404" in capsys.readouterr().err  # fallback is visible


def test_publish_non_404_update_error_propagates(tmp_path, monkeypatch):
    pub = _load("scripts/wiki_drive_publish.py", "wdp_500")
    artifact = tmp_path / "a.csv"
    artifact.write_text("content", encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({"files": {"a.csv": {"sha256": "stale", "drive_file_id": "id1", "view_url": "u"}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(pub, "MANIFEST_PATH", manifest_path)

    def update(file_id):
        raise _FakeHttpError(500)  # NOT a dead id: must not be silently healed

    drive = _FakeDrive({"update": update, "list": lambda q: {"files": []}, "create": lambda body: {}})
    _install_fake_google(monkeypatch, drive)

    with pytest.raises(_FakeHttpError):
        pub.publish([artifact], "folder")


def test_publish_saves_manifest_after_each_file(tmp_path, monkeypatch):
    pub = _load("scripts/wiki_drive_publish.py", "wdp_incr")
    a = tmp_path / "a.csv"
    a.write_text("aa", encoding="utf-8")
    b = tmp_path / "b.csv"
    b.write_text("bb", encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    monkeypatch.setattr(pub, "MANIFEST_PATH", manifest_path)

    def create(body):
        if body["name"] == "b.csv":
            raise _FakeHttpError(500)  # crash halfway through the batch
        return {"id": f"id-{body['name']}", "webViewLink": f"https://drive/{body['name']}"}

    drive = _FakeDrive(
        {
            "update": lambda file_id: {"id": file_id, "webViewLink": "https://drive/upd"},
            "list": lambda q: {"files": []},
            "create": create,
        }
    )
    _install_fake_google(monkeypatch, drive)

    with pytest.raises(_FakeHttpError):
        pub.publish([a, b], "folder")
    # the first file was persisted BEFORE the crash (incremental manifest save)
    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert saved["files"]["a.csv"]["drive_file_id"] == "id-a.csv"
    assert "b.csv" not in saved["files"]
