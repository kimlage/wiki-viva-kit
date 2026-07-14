from __future__ import annotations

import copy
import functools
import hashlib
import http.server
import json
import os
import shutil
import struct
import subprocess
import threading
import zlib
from pathlib import Path

import pytest

from scripts import wiki_visual_evidence as visual
from wiki_core.release_receipt import visual_evidence_file_metadata
from wiki_core.upgrade_lanes import canonical_json, canonical_sha256


ROOT = Path(__file__).resolve().parents[1]
TOOLCHAIN = {
    "name": "playwright-chromium",
    "version": "1.61.1+chromium.128.0.0",
}


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", checksum)
    )


@functools.lru_cache(maxsize=None)
def _png_bytes(width: int = 24, height: int = 18) -> bytes:
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    rows = b"".join(b"\x00" + (b"\x10\x20\x30" * width) for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(rows, 9))
        + _png_chunk(b"IEND", b"")
    )


def _source(tmp_path: Path) -> tuple[Path, str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init", "-q", "-b", "main")
    _git(source, "config", "user.name", "Public Synthetic")
    _git(source, "config", "user.email", "synthetic@example.invalid")
    (source / "README.md").write_text("public synthetic source\n", encoding="utf-8")
    _git(source, "add", "README.md")
    _git(source, "commit", "-q", "-m", "synthetic source")
    return source, _git(source, "rev-parse", "HEAD")


def _package(source_sha: str, profiles: list[str] | None = None) -> dict:
    return {
        "release": {"source_sha": source_sha},
        "migration": {
            "visual_profiles": profiles or list(visual.PROFILE_SPECS)
        },
    }


def _observations(profiles: list[str]) -> list[dict]:
    values = []
    for profile in profiles:
        spec = visual.PROFILE_SPECS[profile]
        values.append(
            {
                "profile": profile,
                "requested_route": spec["route"],
                "route": spec["route"],
                "viewport": spec["viewport"],
                "action_count": spec["action_count"],
                "state": spec["state"],
                "console_summary": {
                    "warning_count": 0,
                    "error_count": 0,
                    "page_error_count": 0,
                },
                "network_summary": {
                    "request_count": 3,
                    "response_error_count": 0,
                    "request_failed_count": 0,
                },
            }
        )
    return values


def _bundle(tmp_path: Path) -> tuple[Path, str, dict, Path]:
    source, source_sha = _source(tmp_path)
    package = _package(source_sha)
    output = tmp_path / "visual-evidence"
    (output / "images").mkdir(parents=True)
    (output / "records").mkdir()
    profiles = list(package["migration"]["visual_profiles"])
    for profile in profiles:
        viewport = visual.PROFILE_SPECS[profile]["viewport"]
        (output / "images" / f"{profile}.png").write_bytes(
            _png_bytes(viewport["width"], viewport["height"])
        )
    visual._write_bundle(
        output_root=output,
        profiles=profiles,
        source_sha=source_sha,
        package_sha256=canonical_sha256(package),
        toolchain=TOOLCHAIN,
        observations=_observations(profiles),
    )
    return source, source_sha, package, output


def _verify(
    source: Path,
    source_sha: str,
    package: dict,
    output: Path,
    *,
    toolchain: dict[str, str] | None = None,
) -> dict:
    return visual.verify_visual_evidence(
        visual_root=output,
        package=package,
        source_sha=source_sha,
        source_root=source,
        browser_probe=lambda _root: toolchain or TOOLCHAIN,
        strict_package=False,
    )


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(canonical_json(payload) + "\n", encoding="utf-8")


def _reseal_record(output: Path, profile: str, mutation) -> None:
    record_path = output / "records" / f"{profile}.json"
    record = _read_json(record_path)
    mutation(record)
    _write_json(record_path, record)
    manifest_path = output / visual.MANIFEST_REF
    manifest = _read_json(manifest_path)
    entry = next(item for item in manifest["entries"] if item["id"] == profile)
    entry["state"] = f"capture-{hashlib.sha256(record_path.read_bytes()).hexdigest()}"
    entry["route"] = record["route"]
    _write_json(manifest_path, manifest)


def _replace_image_and_reseal(
    output: Path, profile: str, *, width: int, height: int
) -> None:
    image_path = output / "images" / f"{profile}.png"
    image_path.write_bytes(_png_bytes(width, height))
    image = visual_evidence_file_metadata(
        output, f"images/{profile}.png", label=profile
    )
    record_path = output / "records" / f"{profile}.json"
    record = _read_json(record_path)
    record["image"] = image
    _write_json(record_path, record)
    manifest_path = output / visual.MANIFEST_REF
    manifest = _read_json(manifest_path)
    entry = next(item for item in manifest["entries"] if item["id"] == profile)
    entry["sha256"] = image["sha256"]
    entry["bytes"] = image["bytes"]
    entry["capture_dimensions"] = image["dimensions"]
    entry["state"] = f"capture-{hashlib.sha256(record_path.read_bytes()).hexdigest()}"
    _write_json(manifest_path, manifest)


def test_generated_bundle_verifies_exact_four_profiles(tmp_path: Path) -> None:
    source, source_sha, package, output = _bundle(tmp_path)
    result = _verify(source, source_sha, package, output)
    assert result["status"] == "verified"
    assert result["visual_profiles"] == sorted(visual.PROFILE_SPECS)
    assert result["visual_manifest_entry_count"] == 4
    assert result["trust"] == {
        "capture_provenance": "not_proven_by_reverification",
        "productive_authority": False,
        "release_authority": "requires_external_capture_attestation",
    }
    manifest = _read_json(output / visual.MANIFEST_REF)
    assert [entry["id"] for entry in manifest["entries"]] == sorted(
        visual.PROFILE_SPECS
    )


def test_manual_bundle_can_only_be_structurally_verified(tmp_path: Path) -> None:
    source, source_sha, package, output = _bundle(tmp_path)

    result = _verify(source, source_sha, package, output)

    assert result["status"] == "verified"
    assert result["trust"]["capture_provenance"] == (
        "not_proven_by_reverification"
    )
    assert result["trust"]["productive_authority"] is False
    assert result["trust"]["release_authority"] == (
        "requires_external_capture_attestation"
    )


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "undeclared"])
def test_manifest_profile_coverage_fails_closed(
    tmp_path: Path, mutation: str
) -> None:
    source, source_sha, package, output = _bundle(tmp_path)
    manifest_path = output / visual.MANIFEST_REF
    manifest = _read_json(manifest_path)
    if mutation == "missing":
        manifest["entries"].pop()
    elif mutation == "duplicate":
        manifest["entries"].append(copy.deepcopy(manifest["entries"][0]))
    else:
        manifest["entries"][0]["id"] = "undeclared"
    _write_json(manifest_path, manifest)
    with pytest.raises(
        visual.VisualEvidenceError, match="exactly cover sorted package visual_profiles"
    ):
        _verify(source, source_sha, package, output)


@pytest.mark.parametrize(
    "route",
    [
        "/private/demo",
        "/demo/%70rivate",
        "/demo/w?center=%2570rivate",
        "/demo/w?center=real",
        "/demo/w?token=synthetic",
    ],
)
def test_private_encoded_or_credential_route_is_rejected(route: str) -> None:
    with pytest.raises(visual.VisualEvidenceError):
        visual._public_demo_route(route)


def test_coherently_resealed_private_route_is_rejected(tmp_path: Path) -> None:
    source, source_sha, package, output = _bundle(tmp_path)
    _reseal_record(
        output,
        "desktop",
        lambda record: record.update(
            {
                "requested_route": "/demo/w?center=%2570rivate",
                "route": "/demo/w?center=%2570rivate",
            }
        ),
    )
    with pytest.raises(
        visual.VisualEvidenceError, match="percent|private|public-synthetic"
    ):
        _verify(source, source_sha, package, output)


def test_image_and_record_tamper_are_rejected(tmp_path: Path) -> None:
    source, source_sha, package, output = _bundle(tmp_path)
    image = output / "images" / "desktop.png"
    image.write_bytes(_png_bytes(99, 77))
    with pytest.raises(
        visual.VisualEvidenceError, match="DPR-1 viewport|hash/bytes/dimensions"
    ):
        _verify(source, source_sha, package, output)

    source, source_sha, package, output = _bundle(tmp_path / "record")
    record = output / "records" / "desktop.json"
    record.write_bytes(record.read_bytes() + b" ")
    with pytest.raises(visual.VisualEvidenceError, match="canonical digest"):
        _verify(source, source_sha, package, output)


def test_coherently_resealed_wrong_png_dimensions_cannot_impersonate_dpr1(
    tmp_path: Path,
) -> None:
    source, source_sha, package, output = _bundle(tmp_path)
    _replace_image_and_reseal(output, "desktop", width=720, height=500)

    with pytest.raises(visual.VisualEvidenceError, match="DPR-1 viewport"):
        _verify(source, source_sha, package, output)


def test_toolchain_and_source_identity_are_live_authority(tmp_path: Path) -> None:
    source, source_sha, package, output = _bundle(tmp_path)
    with pytest.raises(visual.VisualEvidenceError, match="toolchain|identity"):
        _verify(
            source,
            source_sha,
            package,
            output,
            toolchain={"name": "playwright-chromium", "version": "9.9.9"},
        )
    (source / "README.md").write_text("dirty source\n", encoding="utf-8")
    with pytest.raises(visual.VisualEvidenceError, match="clean"):
        _verify(source, source_sha, package, output)


def test_existing_output_symlink_hardlink_and_extra_file_are_rejected(
    tmp_path: Path,
) -> None:
    source, source_sha, package, output = _bundle(tmp_path)
    with pytest.raises(visual.VisualEvidenceError, match="already exists"):
        visual._output_path(output, source_root=source, must_exist=False)

    image = output / "images" / "desktop.png"
    original = output / "images" / "desktop-original.png"
    image.rename(original)
    image.symlink_to(original.name)
    with pytest.raises(visual.VisualEvidenceError, match="strict PNG|symlink"):
        _verify(source, source_sha, package, output)

    source, source_sha, package, output = _bundle(tmp_path / "hardlink")
    record = output / "records" / "desktop.json"
    linked = output / "records" / "desktop-linked.json"
    try:
        os.link(record, linked)
    except OSError as exc:
        pytest.skip(f"hardlinks unavailable in this test environment: {exc}")
    with pytest.raises(visual.VisualEvidenceError, match="hard-linked|hardlink"):
        _verify(source, source_sha, package, output)

    source, source_sha, package, output = _bundle(tmp_path / "extra")
    (output / "undeclared.txt").write_text("not in manifest\n", encoding="utf-8")
    with pytest.raises(visual.VisualEvidenceError, match="undeclared files"):
        _verify(source, source_sha, package, output)


def test_output_inside_source_must_be_ignored(tmp_path: Path) -> None:
    source, _source_sha = _source(tmp_path)
    with pytest.raises(visual.VisualEvidenceError, match="gitignored"):
        visual._output_path(
            source / "visual-evidence", source_root=source, must_exist=False
        )
    (source / ".gitignore").write_text("ignored-evidence/\n", encoding="utf-8")
    _git(source, "add", ".gitignore")
    _git(source, "commit", "-q", "-m", "ignore external evidence")
    ignored_parent = source / "ignored-evidence"
    ignored_parent.mkdir()
    resolved = visual._output_path(
        ignored_parent / "run-1", source_root=source, must_exist=False
    )
    assert resolved == ignored_parent / "run-1"


def test_cli_bootstraps_repo_imports_outside_the_repo_cwd(tmp_path: Path) -> None:
    result = subprocess.run(
        ["python3", str(ROOT / "scripts/wiki_visual_evidence.py"), "--help"],
        cwd=tmp_path,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "public-synthetic visual evidence" in result.stdout
    assert "--productive" not in result.stdout
    assert "--trust" not in result.stdout
    assert "--test" not in result.stdout


class _SyntheticDemoHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        parsed = self.path
        fallback = "visual=1" in parsed
        timeline = "/timeline" in parsed
        scene_class = "sceneShell fallbackMode" if fallback else "sceneShell"
        canvas = "" if fallback else "<canvas width='32' height='24'></canvas>"
        view = "timeline" if timeline else "quadrants"
        body = f"""<!doctype html>
<html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body><main class="worldWorkspace" data-world-view="{view}" data-world-center="root-alex-rivera">
<section class="{scene_class}">{canvas}
<button data-world-target-kind="group" data-world-target-id="family:source">sources &amp; evidence</button>
<div hidden data-world-group-summary="family:source"><button data-world-member-id="source-action-ledger">Action ledger</button></div>
</section></main>
<script>
const group = document.querySelector('[data-world-target-kind="group"]');
const summary = document.querySelector('[data-world-group-summary]');
group.addEventListener('click', () => {{ summary.hidden = false; }});
summary.querySelector('[data-world-member-id]').addEventListener('click', () => {{
  document.querySelector('.worldWorkspace').dataset.worldCenter = 'source-action-ledger';
}});
</script></body></html>"""
        raw = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, _format: str, *args) -> None:
        return


def test_real_chromium_capture_is_bounded_and_strict_when_available(
    tmp_path: Path,
) -> None:
    if shutil.which("node") is None:
        pytest.skip("Node is unavailable for the real Chromium integration")
    try:
        visual._probe_browser_toolchain(ROOT)
    except visual.VisualEvidenceError as exc:
        pytest.skip(f"Playwright Chromium is unavailable: {exc}")
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _SyntheticDemoHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    output = tmp_path / "capture"
    (output / "images").mkdir(parents=True)
    try:
        toolchain, captures = visual._capture_profiles(
            source_root=ROOT,
            base_url=f"http://127.0.0.1:{server.server_address[1]}",
            output_root=output,
            profiles=list(visual.PROFILE_SPECS),
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert toolchain["name"] == "playwright-chromium"
    assert {item["profile"] for item in captures} == set(visual.PROFILE_SPECS)
    for profile in visual.PROFILE_SPECS:
        metadata = visual_evidence_file_metadata(
            output, f"images/{profile}.png", label=profile
        )
        assert metadata["bytes"] > 0
        assert metadata["dimensions"] == visual.PROFILE_SPECS[profile]["viewport"]
