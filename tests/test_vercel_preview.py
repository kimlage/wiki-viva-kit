from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from wiki_core.web.content import sidecar_name
from wiki_core.web.snapshot import _bundle_hash_for_artifacts, _payload_integrity
from wiki_core.web.vercel_preview import write_vercel_preview


KIT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_REL = Path("apps/wiki-cockpit/public/sample-snapshot/scenarios/walking_skeleton")
DIST_REL = Path("apps/wiki-cockpit/dist")
RUNTIME_REL = Path("apps/wiki-cockpit/deploy/vercel/runtime.cjs")


def _git(root: Path, *args: str) -> bytes:
    # Every write below is confined to a pytest temporary repository. Do not
    # consult the operator's Git identity, signing configuration or hooks.
    env = {
        **{name: value for name, value in os.environ.items() if not name.startswith("GIT_")},
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_AUTHOR_NAME": "Synthetic Preview Test",
        "GIT_AUTHOR_EMAIL": "preview@example.test",
        "GIT_COMMITTER_NAME": "Synthetic Preview Test",
        "GIT_COMMITTER_EMAIL": "preview@example.test",
        "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
        "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
        "GIT_OPTIONAL_LOCKS": "0",
    }
    return subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", *args],
        cwd=root,
        env=env,
        check=True,
        capture_output=True,
    ).stdout


def _write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    _write(path, json.dumps(payload, allow_nan=False, sort_keys=True, indent=2) + "\n")


def _commit_fixture(root: Path) -> None:
    _git(root, "add", "--", FIXTURE_REL.as_posix())
    _git(root, "commit", "--quiet", "-m", "Synthetic fixture test revision")


@pytest.fixture(scope="session")
def committed_demo() -> dict[str, bytes]:
    # Copy only the public Git-tracked fixture. No memory directories, local
    # account artifacts, environment files or runtime outputs are consulted.
    tracked = _git(KIT_ROOT, "ls-tree", "-rz", "--name-only", "HEAD", "--", FIXTURE_REL.as_posix())
    payloads: dict[str, bytes] = {}
    for raw_name in tracked.split(b"\0"):
        if raw_name:
            name = raw_name.decode("utf-8")
            payloads[name] = _git(KIT_ROOT, "show", f"HEAD:{name}")
    return payloads


@pytest.fixture
def preview_repo(tmp_path: Path, committed_demo: dict[str, bytes]) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    for name, payload in committed_demo.items():
        _write(root / name, payload)
    _git(root, "init", "--quiet", "-b", "main")
    _commit_fixture(root)
    _write(root / RUNTIME_REL, (KIT_ROOT / RUNTIME_REL).read_bytes())
    _write(root / DIST_REL / "index.html", '<!doctype html><html><head><link rel="stylesheet" href="/assets/app.css"></head><body><div id="root"></div><script type="module" src="/assets/app.js"></script></body></html>\n')
    _write(root / DIST_REL / "favicon.svg", '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><path d="M0 0h1v1H0z"/></svg>\n')
    _write(root / DIST_REL / "assets/app.js", 'document.getElementById("root").textContent = "Synthetic Preview";\n')
    _write(root / DIST_REL / "assets/app.css", "body { font-family: sans-serif; }\n")
    # Synthetic sentinels demonstrate that preview packaging neither loads nor
    # changes the consumer's config or existing deployment defaults.
    _write(root / "wiki.config.yaml", "repo_id: synthetic-test\ndefault_visibility: private_self\n")
    _write_json(root / "apps/wiki-cockpit/public/wiki-cockpit.config.json", {"mode": "local_operator", "api_base": "/api", "snapshot_base": "/existing-default"})
    _write_json(root / "vercel.json", {"version": 2, "builds": []})
    return root


def _tree_state(directory: Path) -> dict[str, tuple[str, bytes | str]]:
    if not directory.exists() and not directory.is_symlink():
        return {}
    if directory.is_symlink():
        return {"": ("symlink", os.readlink(directory))}
    if directory.is_file():
        return {"": ("file", directory.read_bytes())}
    result: dict[str, tuple[str, bytes | str]] = {}
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        if ".git" in relative.parts:
            continue
        name = relative.as_posix()
        if path.is_symlink():
            result[name] = ("symlink", os.readlink(path))
        elif path.is_file():
            result[name] = ("file", path.read_bytes())
        else:
            result[name] = ("directory", "")
    return result


def _assert_refused_without_mutation(root: Path, out: Path, *watched: Path, frontend_dist: Path | None = None) -> None:
    before = [_tree_state(path) for path in (root, *watched)]
    with pytest.raises(ValueError):
        write_vercel_preview(root, out, frontend_dist=frontend_dist)
    assert [_tree_state(path) for path in (root, *watched)] == before


def _payloads(root: Path) -> dict[str, dict[str, Any]]:
    fixture = root / FIXTURE_REL
    return {name: _json(fixture / name) for name in _json(fixture / "manifest.json")["files"]}


def _reseal(root: Path, payloads: dict[str, dict[str, Any]], *, bind_sidecars: bool = True) -> None:
    """Reseal test payloads so a rejection exercises semantics, not dirty Git."""
    manifest = payloads["manifest.json"]
    manifest["bundle_hash"] = _bundle_hash_for_artifacts(payloads)
    manifest["snapshot_id"] = f"{manifest['repo']['repo_id']}-{manifest['bundle_hash'][:16]}"
    if bind_sidecars:
        for name, payload in payloads.items():
            if name.startswith("content/"):
                payload["snapshot_id"] = manifest["snapshot_id"]
    manifest["integrity"] = {name: _payload_integrity(payload) for name, payload in payloads.items() if name != "manifest.json"}
    for name, payload in payloads.items():
        _write_json(root / FIXTURE_REL / name, payload)


@pytest.mark.parametrize("change", ["unstaged", "staged", "removed", "untracked", "untracked-directory", "file-symlink", "directory-symlink", "no-git"])
def test_preview_refuses_fixture_that_is_not_exactly_git_head(preview_repo: Path, tmp_path: Path, change: str) -> None:
    root = preview_repo
    fixture = root / FIXTURE_REL
    pages = fixture / "pages.json"
    external = tmp_path / "external"
    if change in {"unstaged", "staged"}:
        # Semantically identical JSON still differs byte for byte from HEAD.
        pages.write_bytes(pages.read_bytes() + b"\n")
        if change == "staged":
            _git(root, "add", "--", (FIXTURE_REL / "pages.json").as_posix())
    elif change == "removed":
        pages.unlink()
    elif change == "untracked":
        _write_json(fixture / "untracked.json", {"id": "untracked-synthetic"})
    elif change == "untracked-directory":
        (fixture / "untracked-empty").mkdir()
    elif change == "file-symlink":
        _write(external / "pages.json", pages.read_bytes())
        pages.unlink()
        pages.symlink_to(external / "pages.json")
    elif change == "directory-symlink":
        external.mkdir()
        shutil.move(fixture / "content", external / "content")
        (fixture / "content").symlink_to(external / "content", target_is_directory=True)
    else:
        shutil.rmtree(root / ".git")
    _assert_refused_without_mutation(root, root / "tmp/preview", external)


@pytest.mark.parametrize("target", ["outside", "root", "empty", "non-empty", "owned-non-empty", "file", "target-symlink-outside", "ancestor-symlink-outside", "target-symlink-inside", "ancestor-symlink-inside"])
def test_preview_refuses_unsafe_or_existing_output_without_cleaning(preview_repo: Path, tmp_path: Path, target: str) -> None:
    root = preview_repo
    external = tmp_path / "external"
    external.mkdir()
    _write(external / "keep.txt", "synthetic external keeper\n")
    out = root / "tmp/preview"
    if target == "outside":
        out = external / "preview"
    elif target == "root":
        out = root
    elif target == "empty":
        out.mkdir(parents=True)
    elif target in {"non-empty", "owned-non-empty"}:
        _write(out / "keep.txt", "existing output keeper\n")
        if target == "owned-non-empty":
            _write_json(out / ".wiki-viva-output.json", {"schema_version": "wiki_viva_managed_output.v1", "kind": "vercel_preview", "repo_id": "wiki-viva-demo"})
    elif target == "file":
        _write(out, "file keeper\n")
    elif "symlink" in target:
        destination = external
        if target.endswith("inside"):
            destination = root / "internal-target"
            _write(destination / "keep.txt", "synthetic internal keeper\n")
        out = root / "linked-output"
        out.symlink_to(destination, target_is_directory=True)
        if target.startswith("ancestor"):
            out = out / "new-preview"
    _assert_refused_without_mutation(root, out, external)


@pytest.mark.parametrize("entry", ["dist-root", "assets-directory", "index.html", "favicon.svg", "assets/app.js"])
def test_preview_refuses_frontend_symlinks_even_when_bytes_are_safe(preview_repo: Path, tmp_path: Path, entry: str) -> None:
    root = preview_repo
    dist = root / DIST_REL
    external = tmp_path / "external-assets"
    external.mkdir()
    if entry == "dist-root":
        shutil.move(dist, external / "dist")
        dist.symlink_to(external / "dist", target_is_directory=True)
    elif entry == "assets-directory":
        shutil.move(dist / "assets", external / "assets")
        (dist / "assets").symlink_to(external / "assets", target_is_directory=True)
    else:
        source = dist / entry
        _write(external / source.name, source.read_bytes())
        source.unlink()
        source.symlink_to(external / source.name)
    _assert_refused_without_mutation(root, root / "tmp/preview", external)


@pytest.mark.parametrize("name", ["extra.json", "app.js.map", "payload.py", "nested/app.js"])
def test_preview_refuses_unapproved_asset_extensions_and_subdirectories(preview_repo: Path, name: str) -> None:
    root = preview_repo
    _write(root / DIST_REL / "assets" / name, "synthetic unapproved asset\n")
    _assert_refused_without_mutation(root, root / "tmp/preview")


def test_preview_refuses_symlink_ancestor_of_an_explicit_frontend(preview_repo: Path, tmp_path: Path) -> None:
    root = preview_repo
    external = tmp_path / "external-dist"
    shutil.copytree(root / DIST_REL, external / "dist")
    link = root / "frontend-link"
    link.symlink_to(external, target_is_directory=True)
    _assert_refused_without_mutation(root, root / "tmp/preview", external, frontend_dist=link / "dist")


@pytest.mark.parametrize("missing", ["index.html", "favicon.svg", "assets"])
def test_preview_refuses_incomplete_frontend_before_creating_output(preview_repo: Path, missing: str) -> None:
    root = preview_repo
    path = root / DIST_REL / missing
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    _assert_refused_without_mutation(root, root / "tmp/preview")


@pytest.mark.parametrize("corruption", [
    "canonical-route-missing", "invalid-json", "non-finite-json",
    "integrity", "integrity-byte-count", "bundle-hash", "scenario-id",
    "sidecar-revision", "sidecar-id", "sidecar-path", "sidecar-schema",
    "sidecar-body", "sidecar-failed", "sidecar-coverage", "extra-sidecar",
    "extra-json", "unsafe-declared-path", "duplicate-declared-file",
])
def test_preview_refuses_committed_invalid_snapshot_or_incomplete_reader(preview_repo: Path, corruption: str) -> None:
    root = preview_repo
    fixture = root / FIXTURE_REL
    payloads = _payloads(root)
    manifest = payloads["manifest.json"]
    content_name = f"content/{sidecar_name('source-banco-export')}"
    content = payloads[content_name]
    if corruption == "canonical-route-missing":
        manifest["versions"].pop("canonical_route")
        _write_json(fixture / "manifest.json", manifest)
    elif corruption == "invalid-json":
        _write(fixture / "pages.json", "{not-json}\n")
    elif corruption == "non-finite-json":
        _write(fixture / "pages.json", '{"pages": [], "bad": NaN}\n')
    elif corruption == "integrity":
        payloads["pages.json"]["pages"][0]["title"] = "Changed synthetic page"
        _write_json(fixture / "pages.json", payloads["pages.json"])
    elif corruption in {"integrity-byte-count", "bundle-hash", "scenario-id", "unsafe-declared-path", "duplicate-declared-file"}:
        if corruption == "integrity-byte-count":
            manifest["integrity"]["pages.json"]["bytes"] += 1
        elif corruption == "bundle-hash":
            manifest["bundle_hash"] = "0" * 64
        elif corruption == "scenario-id":
            manifest["fixture"]["scenario_id"] = "normal_operations"
        elif corruption == "unsafe-declared-path":
            manifest["files"].append("../escape.json")
            manifest["integrity"]["../escape.json"] = _payload_integrity({"id": "escaped-synthetic"})
        else:
            manifest["files"].append("pages.json")
        _write_json(fixture / "manifest.json", manifest)
    elif corruption == "extra-json":
        _write_json(fixture / "extra.json", {"id": "extra-synthetic"})
    else:
        if corruption == "sidecar-revision":
            content["snapshot_id"] = "unrelated-revision"
        elif corruption == "sidecar-id":
            content["page"]["page_id"] = "different-page"
            content["frontmatter"]["page_id"] = "different-page"
        elif corruption == "sidecar-path":
            content["page"]["path"] = "memories/different-synthetic.md"
        elif corruption == "sidecar-schema":
            content["schema_version"] = "unsupported_content.v999"
        elif corruption == "sidecar-body":
            content.pop("body")
        elif corruption == "sidecar-failed":
            content["ok"] = False
        elif corruption == "sidecar-coverage":
            payloads.pop(content_name)
            manifest["files"].remove(content_name)
            (fixture / content_name).unlink()
        elif corruption == "extra-sidecar":
            name = f"content/{sidecar_name('extra-synthetic-page')}"
            payloads[name] = {**content, "page": {**content["page"], "page_id": "extra-synthetic-page"}}
            manifest["files"].append(name)
        _reseal(root, payloads, bind_sidecars=corruption != "sidecar-revision")
    _commit_fixture(root)
    assert not _git(root, "diff", "HEAD", "--", FIXTURE_REL.as_posix())
    _assert_refused_without_mutation(root, root / "tmp/preview")


def _release(out: Path) -> tuple[Path, dict[str, Any]]:
    bundle = out / ".vercel/output/functions/wiki.func/bundle"
    return bundle, _json(bundle / "release-manifest.json")


def _snapshot_prefix(files: dict[str, Any]) -> str:
    candidates = [uri for uri in files if uri.endswith("/manifest.json")]
    assert len(candidates) == 1
    return candidates[0].removesuffix("/manifest.json")


def test_preview_packages_only_whitelisted_frontend_and_committed_fixture(preview_repo: Path) -> None:
    root = preview_repo
    before_defaults = {path: path.read_bytes() for path in [
        root / "wiki.config.yaml", root / "vercel.json",
        root / "apps/wiki-cockpit/public/wiki-cockpit.config.json",
    ]}
    fixture_before = _tree_state(root / FIXTURE_REL)
    dist = root / DIST_REL
    marker = "unapproved-dist-mirror"
    _write_json(dist / "wiki-cockpit.config.json", {"id": marker, "mode": "local_operator", "api_base": "/api"})
    _write_json(dist / "sample-snapshot/scenarios/walking_skeleton/pages.json", {"id": marker})
    _write_json(dist / "other-root-data.json", {"id": marker})
    out = root / "tmp/preview"
    written = write_vercel_preview(root, out)
    assert written["output"] == out
    assert written["receipt"] == out / "preview-receipt.json"
    assert not (out / ".vercel/output/static").exists()
    assert _json(out / ".vercel/output/config.json") == {"version": 3, "routes": [{"src": "/(.*)", "dest": "/wiki"}]}
    function = out / ".vercel/output/functions/wiki.func"
    assert _json(function / ".vc-config.json") == {
        "runtime": "nodejs22.x", "handler": "index.cjs", "launcherType": "Nodejs", "shouldAddHelpers": False, "maxDuration": 10,
    }
    assert (function / "index.cjs").is_file()
    assert (function / "runtime.cjs").is_file()
    assert not any(path.is_symlink() for path in out.rglob("*"))
    bundle, release = _release(out)
    assert release["schema_version"] == "wiki_vercel_preview.v1"
    assert release["synthetic_fixture"] == "walking_skeleton"
    assert release["source_head"] == written["source_head"] == _git(root, "rev-parse", "HEAD").decode().strip()
    expected = _payloads(root)
    assert release["snapshot_id"] == written["snapshot_id"] == expected["manifest.json"]["snapshot_id"]
    files = release["files"]
    prefix = _snapshot_prefix(files)
    config = _json(bundle / "wiki-cockpit.config.json")
    assert config["api_base"] == ""
    assert config["mode"] == "static"
    assert config["snapshot_base"].rstrip("/") == prefix
    assert not config.get("codex", {}).get("enabled", False)
    assert set(files) == {
        "/index.html", "/favicon.svg", "/assets/app.js", "/assets/app.css", "/wiki-cockpit.config.json",
        *[f"{prefix}/{name}" for name in expected], release["downloads"]["synthetic-note"]["uri"],
    }
    assert written["payload_count"] == len(files)
    for uri, metadata in files.items():
        assert uri.startswith("/") and ".." not in Path(uri).parts
        payload = (bundle / uri.lstrip("/")).read_bytes()
        assert metadata["sha256"] == hashlib.sha256(payload).hexdigest()
        assert metadata["bytes"] == len(payload)
        assert metadata["content_type"]
        assert marker.encode() not in payload
    for name in expected:
        assert (bundle / f"{prefix.lstrip('/')}/{name}").read_bytes() == _git(root, "show", f"HEAD:{FIXTURE_REL.as_posix()}/{name}")
    for name in ["index.html", "favicon.svg", "assets/app.js", "assets/app.css"]:
        assert (bundle / name).read_bytes() == (dist / name).read_bytes()
    assert release["reader"] == {
        page["id"]: f"{prefix}/content/{sidecar_name(page['id'])}"
        for page in expected["pages.json"]["pages"]
    }
    for page_id, uri in release["reader"].items():
        sidecar = _json(bundle / uri.lstrip("/"))
        assert sidecar["ok"] is True
        assert sidecar["schema_version"] == "wiki_web_page_content.v1"
        assert sidecar["snapshot_id"] == release["snapshot_id"]
        assert sidecar["page"]["page_id"] == page_id
        assert isinstance(sidecar["body"], str) and sidecar["body"]
    note = (bundle / release["downloads"]["synthetic-note"]["uri"].lstrip("/")).read_bytes()
    assert note == b"Synthetic attachment: no consumer or account data.\n"
    digest = hashlib.sha256((bundle / "release-manifest.json").read_bytes()).hexdigest()
    assert written["manifest_sha256"] == digest
    assert digest in (function / "index.cjs").read_text(encoding="utf-8")
    assert _json(written["receipt"])["manifest_sha256"] == digest
    assert set(_tree_state(bundle)) == {uri.lstrip("/") for uri in files} | {
        "release-manifest.json", *[path.relative_to(bundle).as_posix() for path in bundle.rglob("*") if path.is_dir()]
    }
    assert _tree_state(root / FIXTURE_REL) == fixture_before
    assert {path: path.read_bytes() for path in before_defaults} == before_defaults
    assert str(root).encode() not in (bundle / "release-manifest.json").read_bytes()
    assert str(root).encode() not in written["receipt"].read_bytes()


def test_preview_receipt_and_entire_output_are_repeatable_across_output_locations(preview_repo: Path) -> None:
    root = preview_repo
    first = root / "tmp/preview-a"
    second = root / "tmp/preview-b"
    written_first = write_vercel_preview(root, first)
    written_second = write_vercel_preview(root, second, frontend_dist=root / DIST_REL)
    assert _tree_state(first) == _tree_state(second)
    assert written_first["source_head"] == written_second["source_head"]
    assert written_first["snapshot_id"] == written_second["snapshot_id"]
    assert written_first["manifest_sha256"] == written_second["manifest_sha256"]
    assert _json(written_first["receipt"]) == _json(written_second["receipt"])
    _assert_refused_without_mutation(root, first)


def test_preview_preserves_equivalent_committed_json_bytes_without_imposing_formatting(preview_repo: Path) -> None:
    root = preview_repo
    fixture = root / FIXTURE_REL
    names = ["pages.json", f"content/{sidecar_name('source-banco-export')}"]
    compact = {name: json.dumps(_json(fixture / name), sort_keys=True, separators=(",", ":")).encode() for name in names}
    for name, data in compact.items():
        _write(fixture / name, data)
    _commit_fixture(root)
    out = root / "tmp/preview"
    write_vercel_preview(root, out)
    bundle, release = _release(out)
    prefix = _snapshot_prefix(release["files"])
    for name, data in compact.items():
        assert (bundle / prefix.lstrip("/") / name).read_bytes() == data
        assert release["files"][f"{prefix}/{name}"]["sha256"] == hashlib.sha256(data).hexdigest()


def test_preview_accepts_direct_vite_chunk_names_with_tilde(preview_repo: Path) -> None:
    root = preview_repo
    _write(root / DIST_REL / "assets/part~Q.js", "export const syntheticChunk = true;\n")
    out = root / "tmp/preview"
    write_vercel_preview(root, out)
    bundle, release = _release(out)
    assert "/assets/part~Q.js" in release["files"]
    assert (bundle / "assets/part~Q.js").read_bytes() == (root / DIST_REL / "assets/part~Q.js").read_bytes()


def _invoke_packaged_handler(out: Path, requests: list[dict[str, str]]) -> list[dict[str, Any]]:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the packaged runtime integration")
    # Invoke the exact pinned entrypoint produced by Python, without opening a
    # port, changing Vercel ACLs or simulating host authentication.
    driver = """
const handler = require(process.argv[1]);
const requests = JSON.parse(process.argv[2]);
const results = requests.map(request => {
  const response = {
    statusCode: 0, headers: {}, body: '',
    setHeader(name, value) { this.headers[name.toLowerCase()] = String(value); },
    end(bytes) { this.body = bytes === undefined ? '' : Buffer.from(bytes).toString('utf8'); }
  };
  handler({ method: request.method || 'GET', url: request.url, headers: {} }, response);
  return response;
});
process.stdout.write(JSON.stringify(results));
"""
    result = subprocess.run(
        [node, "-e", driver, str(out / ".vercel/output/functions/wiki.func/index.cjs"), json.dumps(requests)],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    return json.loads(result.stdout)


def test_python_package_boot_and_complete_reader_run_through_the_pinned_node_entrypoint(preview_repo: Path) -> None:
    root = preview_repo
    out = root / "tmp/preview"
    write_vercel_preview(root, out)
    bundle, release = _release(out)
    requests = [
        {"url": "/"}, {"url": release["default_route"]}, {"url": "/snapshot/boot"},
        {"url": "/snapshot/manifest.json"}, {"url": "/wiki-cockpit.config.json"},
        {"url": "/files/synthetic-note"}, {"url": "/files/synthetic-note.txt"},
        {"url": "/pages/source-banco-export/content"},
    ]
    page_ids = sorted(release["reader"])
    requests.extend({"url": f"/pages/{page_id}/content?snapshot_id={release['snapshot_id']}"} for page_id in page_ids)
    requests.append({"url": f"/pages/source-banco-export/content?snapshot_id={release['snapshot_id']}", "method": "HEAD"})
    responses = _invoke_packaged_handler(out, requests)
    assert [response["statusCode"] for response in responses[:8]] == [307, 200, 404, 200, 200, 200, 404, 409]
    assert responses[0]["headers"]["location"] == release["default_route"]
    assert responses[1]["body"] == (root / DIST_REL / "index.html").read_text()
    assert json.loads(responses[2]["body"])["error_code"] == "not_found"
    assert json.loads(responses[3]["body"])["snapshot_id"] == release["snapshot_id"]
    assert json.loads(responses[4]["body"])["api_base"] == ""
    assert responses[5]["headers"]["content-disposition"] == 'attachment; filename="synthetic-note.txt"'
    assert responses[5]["body"] == "Synthetic attachment: no consumer or account data.\n"
    assert json.loads(responses[6]["body"])["error_code"] == "not_found"
    assert json.loads(responses[7]["body"])["error_code"] == "snapshot_revision_mismatch"
    for page_id, response in zip(page_ids, responses[8:8 + len(page_ids)]):
        assert response["statusCode"] == 200
        expected = (bundle / release["reader"][page_id].lstrip("/")).read_text()
        assert response["body"] == expected
        assert json.loads(response["body"])["page"]["page_id"] == page_id
        assert json.loads(response["body"])["snapshot_id"] == release["snapshot_id"]
    assert responses[-1]["statusCode"] == 200
    assert responses[-1]["body"] == ""
    assert int(responses[-1]["headers"]["content-length"]) == len((bundle / release["reader"]["source-banco-export"].lstrip("/")).read_bytes())
    for response in responses:
        assert response["headers"]["cache-control"] == "private, no-store, max-age=0"


@pytest.mark.parametrize("tamper", ["fixture-bytes", "release-manifest"])
def test_pinned_packaged_runtime_refuses_post_package_raw_byte_changes(preview_repo: Path, tamper: str) -> None:
    root = preview_repo
    out = root / "tmp/preview"
    write_vercel_preview(root, out)
    bundle, _ = _release(out)
    filename = bundle / ("snapshot/pages.json" if tamper == "fixture-bytes" else "release-manifest.json")
    # A whitespace-only change preserves JSON semantics and canonical hash,
    # but must fail the independent raw byte pin of the deployed release.
    filename.write_bytes(filename.read_bytes() + b"\n")
    responses = _invoke_packaged_handler(out, [{"url": "/w"}, {"url": "/snapshot/pages.json"}])
    assert [response["statusCode"] for response in responses] == [503, 503]
    for response in responses:
        assert json.loads(response["body"])["error_code"] == "release_unavailable"
        assert str(root) not in response["body"]
        assert response["headers"]["cache-control"] == "private, no-store, max-age=0"


def test_cli_requires_demo_and_reports_a_local_package_without_changing_defaults(preview_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from scripts import wiki_vercel_preview as cli

    root = preview_repo
    monkeypatch.setattr(cli, "ROOT", root)
    before = _tree_state(root)
    monkeypatch.setattr(sys, "argv", ["wiki_vercel_preview.py", "--out", "tmp/preview"])
    with pytest.raises(SystemExit) as rejected:
        cli.main()
    assert rejected.value.code == 2
    assert _tree_state(root) == before
    capsys.readouterr()
    monkeypatch.setattr(sys, "argv", ["wiki_vercel_preview.py", "--demo", "--out", "tmp/preview"])
    assert cli.main() == 0
    reported = capsys.readouterr()
    assert "output: tmp/preview" in reported.out
    assert "source_head:" in reported.out and "snapshot_id:" in reported.out
    assert "separate operator actions" in reported.out
    assert not reported.err
    assert (root / "tmp/preview/.vercel/output/functions/wiki.func/index.cjs").is_file()


@pytest.mark.parametrize("override", [["--private-ok"], ["--data-boundary", "private_ok"], ["--force-unowned-output"], ["--clean"]])
def test_cli_exposes_no_private_export_or_existing_output_override(preview_repo: Path, monkeypatch: pytest.MonkeyPatch, override: list[str]) -> None:
    from scripts import wiki_vercel_preview as cli

    root = preview_repo
    monkeypatch.setattr(cli, "ROOT", root)
    monkeypatch.setattr(sys, "argv", ["wiki_vercel_preview.py", "--demo", "--out", "tmp/preview", *override])
    before = _tree_state(root)
    with pytest.raises(SystemExit) as rejected:
        cli.main()
    assert rejected.value.code == 2
    assert _tree_state(root) == before
