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


# Drive publication is suspended until the provider and manifest have safe
# concurrency and recovery contracts. No credentials or network are used.


@pytest.mark.parametrize("path_exists", [False, True])
def test_publish_refuses_before_loading_manifest_or_credentials(tmp_path, monkeypatch, path_exists):
    pub = _load("scripts/wiki_drive_publish.py", "wdp_refused")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text('{"files":{"synthetic":{"drive_file_id":"original"}}}')
    before = manifest_path.read_bytes()
    artifact = tmp_path / "synthetic.csv"
    if path_exists:
        artifact.write_text("synthetic", encoding="utf-8")
    original_import = builtins.__import__
    def guarded_import(name, *args, **kwargs):
        if name.startswith(("googleapiclient", "common.google_clients")):
            pytest.fail("provider imported before refusal")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(pub, "MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(pub, "load_manifest", lambda: pytest.fail("manifest read before refusal"))
    monkeypatch.setattr(pub, "load_env", lambda: pytest.fail("environment read before refusal"))
    with pytest.raises(pub.DrivePublicationSuspended, match="issue"):
        pub.publish([artifact], "synthetic-folder")
    assert manifest_path.read_bytes() == before
    assert set(p.name for p in tmp_path.iterdir()) == (
        {"manifest.json", "synthetic.csv"} if path_exists else {"manifest.json"}
    )


def test_cli_refuses_before_environment_or_files(tmp_path, monkeypatch, capsys):
    pub = _load("scripts/wiki_drive_publish.py", "wdp_cli_refused")
    monkeypatch.setattr(pub, "load_env", lambda: pytest.fail("environment read before refusal"))
    monkeypatch.setattr(pub, "publish", lambda *a, **k: pytest.fail("publication called"))
    assert pub.main([str(tmp_path / "synthetic.csv")]) == 2
    assert "suspended" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_direct_effect_helpers_refuse_before_request_or_manifest_write(tmp_path, monkeypatch):
    pub = _load("scripts/wiki_drive_publish.py", "wdp_helpers_refused")
    monkeypatch.setattr(pub, "MANIFEST_PATH", tmp_path / "nested" / "manifest.json")

    class Request:
        def execute(self):
            pytest.fail("request executed")

        def next_chunk(self):
            pytest.fail("request executed")

    with pytest.raises(pub.DrivePublicationSuspended):
        pub.execute_drive_upload(Request(), label="synthetic")
    with pytest.raises(pub.DrivePublicationSuspended):
        pub.save_manifest({"files": {}})
    assert list(tmp_path.iterdir()) == []


def test_dry_run_is_local_read_only_and_does_not_claim_remote_state(tmp_path, monkeypatch):
    pub = _load("scripts/wiki_drive_publish.py", "wdp_local_only")
    artifact = tmp_path / "synthetic.csv"
    artifact.write_text("synthetic content", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"files": {"synthetic.csv": {
        "sha256": pub.sha256_file(artifact), "drive_file_id": "synthetic-id"}}}))
    before = manifest.read_bytes()
    monkeypatch.setattr(pub, "MANIFEST_PATH", manifest)
    monkeypatch.setattr(pub, "save_manifest", lambda *a, **k: pytest.fail("manifest write"))
    monkeypatch.setattr(pub, "execute_drive_upload", lambda *a, **k: pytest.fail("upload"))
    import socket
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("network"))
    report = pub.publish([artifact], "synthetic-folder", dry_run=True)
    assert "remote unverified" in report["results"][0]
    assert manifest.read_bytes() == before
    assert {p.name for p in tmp_path.iterdir()} == {"manifest.json", "synthetic.csv"}
