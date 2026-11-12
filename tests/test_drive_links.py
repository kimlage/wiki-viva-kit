"""General rule: non-versioned artifact -> content on Drive, link in the wiki.

Covers the drive_aware_md_link helper, the .env parser and the generic Drive
publication helper. Per-repository finance scripts are tested downstream. No
network.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import builtins
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


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import socket
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("network"))


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


def _install_fake_google(monkeypatch, drive):
    # No real helper, Google libraries, account, credentials or network.
    monkeypatch.setattr(sys, "path", list(sys.path))
    calls = {"build": [], "media": []}
    pkg = types.ModuleType("googleapiclient")
    http = types.ModuleType("googleapiclient.http")
    http.MediaFileUpload = lambda *a, **k: calls["media"].append((a, k)) or object()
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
