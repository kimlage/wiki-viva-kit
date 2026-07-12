from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

from wiki_core.adapter_manifest import (
    ADAPTER_MANIFEST_SCHEMA_VERSION,
    AdapterManifestError,
    adapter_sha256,
    build_adapter_manifest,
    load_and_verify_adapter_manifest,
    serialize_adapter_manifest,
    validate_adapter_path,
)


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts/wiki_adapter_manifest.py"
SCHEMA = (
    ROOT / "docs/references/schemas/wiki-downstream-adapter-manifest-v1.schema.json"
)


def _run(root: Path, *args: str) -> str:
    return subprocess.check_output(args, cwd=root, text=True).strip()


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "consumer"
    root.mkdir()
    _run(root, "git", "init", "-q")
    _run(root, "git", "config", "user.email", "adapter@example.test")
    _run(root, "git", "config", "user.name", "Adapter Test")
    (root / "adapters").mkdir()
    (root / "adapters/runtime.py").write_text("ADAPTER = 'v1'\n", encoding="utf-8")
    (root / "adapters/presentation.json").write_text(
        '{"theme":"local"}\n', encoding="utf-8"
    )
    _run(root, "git", "add", "adapters")
    _run(root, "git", "commit", "-qm", "seed adapters")
    return root


def _publish(root: Path, files: list[str] | None = None) -> dict:
    payload = build_adapter_manifest(
        root,
        files or ["adapters/runtime.py", "adapters/presentation.json"],
    )
    (root / "wiki.adapter-manifest.json").write_text(
        serialize_adapter_manifest(payload), encoding="utf-8"
    )
    _run(root, "git", "add", "wiki.adapter-manifest.json")
    _run(root, "git", "commit", "-qm", "attest adapters")
    return payload


def test_manifest_compiles_sorted_files_and_verifies_tracked_bytes(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    payload = _publish(root)
    assert payload["schema_version"] == ADAPTER_MANIFEST_SCHEMA_VERSION
    assert [item["path"] for item in payload["files"]] == [
        "adapters/presentation.json",
        "adapters/runtime.py",
    ]
    assert payload["adapter_sha256"] == adapter_sha256(payload["files"])

    evidence = load_and_verify_adapter_manifest(
        root, expected_hash=payload["adapter_sha256"]
    )
    assert evidence["manifest"] == "wiki.adapter-manifest.json"
    assert evidence["file_count"] == 2
    assert evidence["files"] == payload["files"]

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(payload)


@pytest.mark.parametrize(
    "path",
    [
        "../adapter.py",
        "adapters/../adapter.py",
        "adapters//adapter.py",
        "./adapters/adapter.py",
        "/tmp/adapter.py",
        "C:\\adapter.py",
        "wiki.adapter-manifest.json",
        "apps/wiki-cockpit/public/wiki-cockpit.config.json",
        "memories/personal.md",
        "memorias/pessoal.md",
        "data/raw/export.csv",
        "data/derived/wiki/output.json",
        "private/adapter.py",
        "output/adapter.json",
        "test-results/adapter.json",
        "adapters/.env.local",
        "adapters/credentials.json",
        "adapters/my-secrets.json",
        "adapters/id_rsa",
    ],
)
def test_adapter_paths_reject_cycles_private_state_and_sensitive_names(
    path: str,
) -> None:
    with pytest.raises(AdapterManifestError):
        validate_adapter_path(path)


def test_manifest_requires_tracked_files_and_rejects_symlink_or_hardlink(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    (root / "adapters/untracked.py").write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(AdapterManifestError, match="untracked"):
        build_adapter_manifest(root, ["adapters/untracked.py"])

    os.symlink(root / "adapters", root / "linked-adapters")
    with pytest.raises(AdapterManifestError, match="symlink"):
        build_adapter_manifest(
            root, ["linked-adapters/runtime.py"], require_tracked=False
        )

    os.link(root / "adapters/runtime.py", root / "adapters/runtime-hardlink.py")
    _run(root, "git", "add", "adapters/runtime-hardlink.py")
    with pytest.raises(AdapterManifestError, match="hardlink"):
        build_adapter_manifest(root, ["adapters/runtime-hardlink.py"])


def test_verifier_requires_manifest_and_files_to_be_tracked_clean(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    payload = build_adapter_manifest(root, ["adapters/runtime.py"])
    (root / "wiki.adapter-manifest.json").write_text(
        serialize_adapter_manifest(payload), encoding="utf-8"
    )
    with pytest.raises(AdapterManifestError, match="untracked"):
        load_and_verify_adapter_manifest(root)

    _run(root, "git", "add", "wiki.adapter-manifest.json")
    _run(root, "git", "commit", "-qm", "track manifest")
    (root / "adapters/runtime.py").write_text("ADAPTER = 'drift'\n", encoding="utf-8")
    with pytest.raises(AdapterManifestError, match="not_clean"):
        load_and_verify_adapter_manifest(root)


@pytest.mark.parametrize("mutation", ["hash", "order", "duplicate", "extra"])
def test_verifier_rejects_tampered_manifest_shape_and_inventory(
    tmp_path: Path, mutation: str
) -> None:
    root = _repo(tmp_path)
    payload = build_adapter_manifest(
        root, ["adapters/runtime.py", "adapters/presentation.json"]
    )
    tampered = copy.deepcopy(payload)
    if mutation == "hash":
        tampered["adapter_sha256"] = "0" * 64
    elif mutation == "order":
        tampered["files"].reverse()
        tampered["adapter_sha256"] = adapter_sha256(tampered["files"])
    elif mutation == "duplicate":
        tampered["files"][1] = copy.deepcopy(tampered["files"][0])
        tampered["adapter_sha256"] = adapter_sha256(tampered["files"])
    else:
        tampered["self_asserted"] = True
    (root / "wiki.adapter-manifest.json").write_text(
        json.dumps(tampered, sort_keys=True), encoding="utf-8"
    )
    _run(root, "git", "add", "wiki.adapter-manifest.json")
    _run(root, "git", "commit", "-qm", f"tamper {mutation}")
    with pytest.raises(AdapterManifestError):
        load_and_verify_adapter_manifest(root)


def test_cli_build_then_committed_check_proves_real_hash(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    built = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "--root",
            str(root),
            "build",
            "--file",
            "adapters/runtime.py",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert built.returncode == 0, built.stderr
    built_payload = json.loads(built.stdout)
    assert built_payload["status"] == "built_unverified_until_committed"
    _run(root, "git", "add", "wiki.adapter-manifest.json")
    _run(root, "git", "commit", "-qm", "track adapter manifest")

    checked = subprocess.run(
        [sys.executable, str(CLI), "--root", str(root), "check"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert checked.returncode == 0, checked.stderr
    checked_payload = json.loads(checked.stdout)
    assert checked_payload["status"] == "verified"
    assert checked_payload["adapter_sha256"] == built_payload["adapter_sha256"]
