from __future__ import annotations

import copy
import functools
import hashlib
import json
import os
import shutil
import struct
import subprocess
import zlib
from pathlib import Path
from typing import Mapping

import pytest
from jsonschema import Draft202012Validator

from wiki_core.upgrade import CONFIG_BOUND_C3_ROLE_SPECS, boundary_operations_sha256
from wiki_core.upgrade_lanes import (
    ADOPTION_RECEIPT_SCHEMA_VERSION,
    AdoptionEvidenceAuthority,
    GATE_CLASSES,
    IMPACT_REGISTRY_SCHEMA_VERSION,
    LEGACY_EXECUTION_ATTESTATION_SCHEMA_VERSION,
    LEGACY_RELEASE_CAPSULE_SCHEMA_VERSION,
    LEGACY_TOOLCHAIN_PROBE_SCHEMA_VERSION,
    NEVER_REUSABLE_GATES,
    RELEASE_CAPSULE_SCHEMA_VERSION,
    TOOLCHAIN_PROBE_SCHEMA_VERSION,
    ReleaseCapsuleAuthority,
    UpgradeLaneError,
    VISUAL_PROFILE_CONTRACTS,
    _safe_file_bytes,
    _toolchain_probe_metadata,
    _git_bytes,
    canonical_json,
    canonical_sha256,
    classify_consumer_c3_path,
    consumer_c3_authority_from_git,
    collect_release_attestation,
    _verify_git_boundary_chain,
    load_mapping,
    public_acceptance_budget_projection,
    public_migration_report_projection,
    seal_adoption_receipt,
    seal_impact_registry,
    seal_release_capsule,
    select_impacted_gates,
    select_promotion_gates,
    validate_acceptance_budget,
    validate_boundary_ownership,
    validate_c1_projection,
    validate_canary_evidence,
    verify_adoption_receipt,
    verify_adoption_evidence,
    verify_gate_omissions,
    verify_config_bound_c3_git_content,
    verify_consumer_c3_authority,
    verify_impact_registry,
    verify_release_capsule,
)
from wiki_core.node_workspace import (
    ALLOWED_SCRIPTS,
    authority_identity_sha256,
    build_policy,
    npm_workspace_toolchain_identity,
    serialize_policy,
)
from wiki_core.release_receipt import visual_evidence_file_metadata


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "docs/references/upgrades/wiki-viva-v8/impact-registry.yaml"
CAPSULE_SCHEMA_PATH = (
    ROOT / "docs/references/schemas/wiki-upgrade-release-capsule-v2.schema.json"
)
REGISTRY_SCHEMA_PATH = (
    ROOT / "docs/references/schemas/wiki-upgrade-impact-registry-v1.schema.json"
)

_RC37_RAW_NODE_COMMANDS = {
    "architecture": "npm --prefix apps/wiki-cockpit run check:architecture",
    "assets": "npm --prefix apps/wiki-cockpit run check:assets",
    "browser_synthetic_release": "npm --prefix apps/wiki-cockpit run test:e2e:release",
    "build": "npm --prefix apps/wiki-cockpit run build",
    "bundle": "npm --prefix apps/wiki-cockpit run check:bundle",
    "consumer_browser_matrix": "npm --prefix apps/wiki-cockpit run test:e2e:operator",
    "frontend": "npm --prefix apps/wiki-cockpit test -- --reporter=tap",
    "frontend_focused": "npm --prefix apps/wiki-cockpit test",
    "node_gates": "npm --prefix apps/wiki-cockpit run test:gates",
    "operator_security": "npm --prefix apps/wiki-cockpit run test:e2e:operator",
    "real_canary": "npm --prefix apps/wiki-cockpit run test:e2e:operator",
    "release_matrix_inventory": "npm --prefix apps/wiki-cockpit run check:release-matrix",
    "visual_profiles": "npm --prefix apps/wiki-cockpit run test:visual",
}


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _registry() -> dict:
    return load_mapping(REGISTRY_PATH)


def test_legacy_v1_toolchain_probe_remains_read_only_verifiable(
    tmp_path: Path,
) -> None:
    entries = []
    identities = {
        "browser": {"name": "playwright-chromium", "version": "1.61.1+chromium.128"},
        "node": {"name": "node", "version": "22.22.3"},
        "python": {"name": "cpython-resolved", "version": f"3.12.4+deps.{'1' * 64}"},
        "runner": {"name": "wiki-upgrade", "version": f"1.4.0+payload.{'2' * 64}"},
    }
    for tool_id, identity in identities.items():
        output_ref = f"toolchain/{tool_id}.log"
        output = f"{identity['name']} {identity['version']}\n".encode()
        path = tmp_path / output_ref
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(output)
        entries.append(
            {
                "id": tool_id,
                **identity,
                "provenance": "executed",
                "probe_argv": [tool_id, "--version"],
                "exit_code": 0,
                "output_ref": output_ref,
                "output_sha256": hashlib.sha256(output).hexdigest(),
                "output_bytes": len(output),
            }
        )
    manifest = {
        "schema_version": LEGACY_TOOLCHAIN_PROBE_SCHEMA_VERSION,
        "run_id": "legacy-v1-run",
        "entries": entries,
    }
    manifest_path = tmp_path / "toolchain/probe-manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n")
    _digest_value, count, tools, bindings = _toolchain_probe_metadata(
        gate_output_root=tmp_path,
        probe_ref="toolchain/probe-manifest.json",
        run_id="legacy-v1-run",
        capsule_schema_version=LEGACY_RELEASE_CAPSULE_SCHEMA_VERSION,
    )
    assert count == 4
    assert tools == identities
    assert [item["id"] for item in bindings] == list(identities)


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()


def _sentinel_git_command(tmp_path: Path) -> tuple[Path, Path]:
    script = tmp_path / "git-policy-sentinel.sh"
    sentinel = Path(f"{script}.executed")
    script.write_text(
        '#!/bin/sh\n: > "${0}.executed"\nexit 0\n',
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script, sentinel


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return (
        struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)
    )


@functools.lru_cache(maxsize=None)
def _png_bytes(width: int = 16, height: int = 12) -> bytes:
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    rows = b"".join(b"\x00" + (b"\x00\x00\x00" * width) for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(rows, 9))
        + _png_chunk(b"IEND", b"")
    )


@pytest.fixture
def capsule_authority(tmp_path: Path) -> dict:
    registry = _registry()
    source_root = tmp_path / "public-kit"
    source_root.mkdir()
    _git(source_root, "init", "-q", "-b", "main")
    _git(source_root, "config", "user.name", "Synthetic Release")
    _git(source_root, "config", "user.email", "release@example.invalid")
    (source_root / "wiki_core").mkdir()
    (source_root / "wiki_core/config.py").write_text(
        "PUBLIC_SYNTHETIC = True\n", encoding="utf-8"
    )
    (source_root / "memories").mkdir()
    (source_root / "memories/private-note.md").write_text(
        "blocked consumer content\n", encoding="utf-8"
    )
    cockpit = source_root / "apps/wiki-cockpit"
    cockpit.mkdir(parents=True)
    (cockpit / "package.json").write_text(
        json.dumps(
            {
                "name": "wiki-viva-synthetic-cockpit",
                "version": "1.0.0",
                "private": True,
                "packageManager": "npm@10.9.8",
                "scripts": {name: "node --version" for name in ALLOWED_SCRIPTS},
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (cockpit / "package-lock.json").write_text(
        json.dumps(
            {
                "name": "wiki-viva-synthetic-cockpit",
                "version": "1.0.0",
                "lockfileVersion": 3,
                "requires": True,
                "packages": {},
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    node_workspace_policy = build_policy(source_root)
    (cockpit / "node-workspace.lock.json").write_bytes(
        serialize_policy(node_workspace_policy)
    )
    _git(source_root, "add", ".")
    _git(source_root, "commit", "-q", "-m", "public synthetic source")
    source_sha = _git(source_root, "rev-parse", "HEAD")
    package = load_mapping(
        ROOT / "docs/references/upgrades/wiki-viva-v8/upgrade-package.yaml"
    )
    package["release"] = {
        "id": "wiki-viva-v8-public-synthetic",
        "status": "ready",
        "source_sha": source_sha,
        "plan": "docs/references/proposals/synthetic.md",
    }
    boundary = package["migration"]["boundary_operations"]
    boundary["registry_sha256"] = boundary_operations_sha256(boundary)
    node_workspace_authority = {
        "schema_version": "wiki_viva_node_workspace_authority.v1",
        "policy_sha256": node_workspace_policy["policy_sha256"],
        "source_sha": source_sha,
        "platform": {"system": "linux", "machine": "x86_64"},
        "node": {
            "name": "node-resolved",
            "version": "22.17.0",
            "platform_system": "linux",
            "platform_machine": "x86_64",
            "executable_sha256": "7" * 64,
            "executable_bytes": 1024,
            "runtime_tree_sha256": "8" * 64,
            "runtime_entry_count": 12,
            "runtime_total_bytes": 4096,
        },
        "npm": {
            "name": "npm-resolved",
            "version": "10.9.8",
            "entrypoint_sha256": "9" * 64,
            "platform_system": "linux",
            "platform_machine": "x86_64",
            "tree_sha256": "a" * 64,
            "entry_count": 24,
            "total_bytes": 8192,
        },
        "node_modules": {
            "tree_sha256": "b" * 64,
            "entry_count": 48,
            "total_bytes": 16384,
        },
    }
    node_workspace_authority_sha256 = authority_identity_sha256(
        node_workspace_authority
    )
    toolchain = {
        "browser": {
            "name": "playwright-chromium",
            "version": "1.61.1+chromium.128.0.0",
        },
        "node": {
            "name": "node-resolved",
            "version": f"22.17.0+linux.x86_64.runtime.{'8' * 64}",
        },
        "npm": npm_workspace_toolchain_identity(node_workspace_authority),
        "python": {"name": "cpython", "version": "3.12.9"},
        "runner": {"name": "wiki-upgrade", "version": "1.1.0"},
    }
    visual_root = tmp_path / "public-visuals"
    (visual_root / "images").mkdir(parents=True)
    (visual_root / "records").mkdir()
    visual_entries = []
    for profile in sorted(package["migration"]["visual_profiles"]):
        spec = VISUAL_PROFILE_CONTRACTS[profile]
        image_ref = f"images/{profile}.png"
        image_raw = _png_bytes(
            width=spec["viewport"]["width"],
            height=spec["viewport"]["height"],
        )
        (visual_root / image_ref).write_bytes(image_raw)
        image = {
            "path": image_ref,
            "sha256": hashlib.sha256(image_raw).hexdigest(),
            "bytes": len(image_raw),
            "dimensions": dict(spec["viewport"]),
        }
        record = {
            "schema_version": "wiki_visual_evidence_capture.v2",
            "profile": profile,
            "source_sha": source_sha,
            "package_sha256": canonical_sha256(package),
            "requested_route": spec["route"],
            "route": spec["route"],
            "viewport": spec["viewport"],
            "view": spec["view"],
            "runtime_mode": spec["runtime_mode"],
            "browser_toolchain": toolchain["browser"],
            "browser_toolchain_sha256": canonical_sha256(toolchain["browser"]),
            "image": image,
            "console_summary": {
                "capture": "sanitized_counts_only",
                "warning_count": 0,
                "error_count": 0,
                "page_error_count": 0,
                "truncated": False,
            },
            "network_summary": {
                "capture": "sanitized_counts_only",
                "request_count": 4,
                "response_error_count": 0,
                "request_failed_count": 0,
                "truncated": False,
            },
            "capture": {
                "method": "playwright_served_public_synthetic",
                "action_count": spec["action_count"],
                "state": spec["state"],
                "settled": True,
            },
        }
        record_raw = (canonical_json(record) + "\n").encode("utf-8")
        (visual_root / "records" / f"{profile}.json").write_bytes(record_raw)
        visual_entries.append(
            {
                "id": profile,
                "path": image_ref,
                "sha256": image["sha256"],
                "bytes": image["bytes"],
                "route": spec["route"],
                "browser": "chromium",
                "viewport": spec["viewport"],
                "capture_dimensions": image["dimensions"],
                "state": f"capture-{hashlib.sha256(record_raw).hexdigest()}",
                "public_synthetic": True,
            }
        )
    visual_manifest_ref = "visual-manifest.json"
    (visual_root / visual_manifest_ref).write_text(
        canonical_json(
            {
                "schema_version": "wiki_visual_evidence_manifest.v1",
                "entries": visual_entries,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    commands = [dict(item) for item in registry["gate_catalog"]]
    gate_output_root = tmp_path / "public-gate-run"
    (gate_output_root / "outputs").mkdir(parents=True)
    certified = [
        {
            "id": item["id"],
            "class": "upstream_certified",
            "provenance": "executed",
            "status": "passed",
            "exit_code": 0,
            "subject_sha": source_sha,
            "command_sha256": hashlib.sha256(
                item["command"].encode("utf-8")
            ).hexdigest(),
            "output_ref": f"outputs/{item['id']}.log",
            "output_sha256": "0" * 64,
            "output_bytes": 1,
        }
        for item in commands
        if item["class"] == "upstream_certified"
    ]
    for gate in certified:
        (gate_output_root / gate["output_ref"]).write_text(
            f"gate={gate['id']}\nstatus=passed\n", encoding="utf-8"
        )
    probe_entries = []
    for tool_id, identity in sorted(toolchain.items()):
        output_ref = f"toolchain/{tool_id}.log"
        output_path = gate_output_root / output_ref
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            f"{identity['name']} {identity['version']}\n", encoding="utf-8"
        )
        raw = output_path.read_bytes()
        probe_entries.append(
            {
                "id": tool_id,
                **identity,
                "provenance": "executed",
                "probe_argv": [tool_id, "--version"],
                "exit_code": 0,
                "output_ref": output_ref,
                "output_sha256": hashlib.sha256(raw).hexdigest(),
                "output_bytes": len(raw),
            }
        )
    toolchain_probe_ref = "toolchain/probe-manifest.json"
    (gate_output_root / toolchain_probe_ref).write_text(
        json.dumps(
            {
                "schema_version": TOOLCHAIN_PROBE_SCHEMA_VERSION,
                "run_id": "synthetic-run",
                "entries": probe_entries,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    payload = {
        "schema_version": RELEASE_CAPSULE_SCHEMA_VERSION,
        "release_id": "wiki-viva-v8-public-synthetic",
        "status": "certified",
        "source_sha": source_sha,
        "package_sha256": "0" * 64,
        "portable_tree_sha256": "0" * 64,
        "command_registry": commands,
        "toolchain": toolchain,
        "node_workspace_authority": node_workspace_authority,
        "node_workspace_authority_sha256": (node_workspace_authority_sha256),
        "toolchain_probe_ref": toolchain_probe_ref,
        "certified_gates": certified,
        "run_id": "synthetic-run",
        "visual_manifest_ref": visual_manifest_ref,
        "visual_manifest_sha256": "0" * 64,
        "attestation_authority_id": "synthetic-ci",
        "attestation_ref": "execution-attestation.json",
    }
    attestation = collect_release_attestation(
        payload,
        package=package,
        impact_registry=registry,
        source_root=source_root,
        visual_root=visual_root,
        gate_output_root=gate_output_root,
    )
    attestation_path = gate_output_root / payload["attestation_ref"]
    attestation_path.write_text(
        json.dumps(attestation, sort_keys=True) + "\n", encoding="utf-8"
    )
    attestation_sha256 = hashlib.sha256(attestation_path.read_bytes()).hexdigest()
    authority = ReleaseCapsuleAuthority(
        package=package,
        impact_registry=registry,
        source_root=source_root,
        visual_root=visual_root,
        gate_output_root=gate_output_root,
        verified_attestation_sha256=attestation_sha256,
    )
    capsule = seal_release_capsule(payload, authority=authority)
    consumer_root = tmp_path / "public-consumer"
    consumer_root.mkdir()
    _git(consumer_root, "init", "-q", "-b", "main")
    _git(consumer_root, "config", "user.name", "Synthetic Consumer")
    _git(consumer_root, "config", "user.email", "consumer@example.invalid")
    (consumer_root / ".gitignore").write_text(".wiki-viva/\n", encoding="utf-8")
    (consumer_root / "README.md").write_text("synthetic consumer\n", encoding="utf-8")
    (consumer_root / "wiki.config.yaml").write_text(
        "repo_id: public-synthetic\n", encoding="utf-8"
    )
    _git(consumer_root, "add", ".")
    _git(consumer_root, "commit", "-q", "-m", "consumer B0")
    consumer_b0 = _git(consumer_root, "rev-parse", "HEAD")
    (consumer_root / "wiki_core").mkdir()
    (consumer_root / "wiki_core/config.py").write_bytes(
        (source_root / "wiki_core/config.py").read_bytes()
    )
    _git(consumer_root, "add", "wiki_core/config.py")
    _git(consumer_root, "commit", "-q", "-m", "consumer C1")
    consumer_c1 = _git(consumer_root, "rev-parse", "HEAD")
    snapshot = consumer_root / "apps/wiki-cockpit/public/sample-snapshot/snapshot.json"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text('{"synthetic":true}\n', encoding="utf-8")
    _git(consumer_root, "add", snapshot.relative_to(consumer_root).as_posix())
    _git(consumer_root, "commit", "-q", "-m", "consumer C2")
    consumer_c2 = _git(consumer_root, "rev-parse", "HEAD")
    (consumer_root / "wiki.config.yaml").write_text(
        "repo_id: public-synthetic-v8\n", encoding="utf-8"
    )
    _git(consumer_root, "add", "wiki.config.yaml")
    _git(consumer_root, "commit", "-q", "-m", "consumer C3")
    consumer_c3 = _git(consumer_root, "rev-parse", "HEAD")
    return {
        "authority": authority,
        "capsule": capsule,
        "verified": verify_release_capsule(capsule, authority=authority),
        "source_root": source_root,
        "visual_root": visual_root,
        "gate_output_root": gate_output_root,
        "attestation_path": attestation_path,
        "consumer_root": consumer_root,
        "consumer_B0": consumer_b0,
        "consumer_C1": consumer_c1,
        "consumer_C2": consumer_c2,
        "consumer_C3": consumer_c3,
        "adoption_tokens": {},
        "adoption_run_roots": {},
    }


def _capsule(capsule_authority: dict) -> dict:
    return copy.deepcopy(capsule_authority["capsule"])


def _replace_visual_image_and_reseal(
    capsule_authority: dict,
    profile: str,
    *,
    width: int,
    height: int,
) -> None:
    root = capsule_authority["visual_root"]
    image_ref = f"images/{profile}.png"
    (root / image_ref).write_bytes(_png_bytes(width=width, height=height))
    image = visual_evidence_file_metadata(root, image_ref, label=profile)

    record_path = root / "records" / f"{profile}.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["image"] = image
    record_path.write_text(canonical_json(record) + "\n", encoding="utf-8")

    manifest_path = root / "visual-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = next(item for item in manifest["entries"] if item["id"] == profile)
    entry["sha256"] = image["sha256"]
    entry["bytes"] = image["bytes"]
    entry["capture_dimensions"] = image["dimensions"]
    entry["state"] = f"capture-{hashlib.sha256(record_path.read_bytes()).hexdigest()}"
    manifest_path.write_text(canonical_json(manifest) + "\n", encoding="utf-8")


def _identity(capsule: dict, capsule_authority: dict) -> dict[str, str]:
    return {
        "source_sha": capsule["source_sha"],
        "package_sha256": capsule["package_sha256"],
        "portable_tree_sha256": capsule["portable_tree_sha256"],
        "consumer_B0": capsule_authority["consumer_B0"],
        "consumer_C3": capsule_authority["consumer_C3"],
        "command_registry_sha256": capsule["command_registry_sha256"],
        "toolchain_sha256": capsule["toolchain_sha256"],
    }


def _consumer_c3_authority(
    capsule_authority: dict, package: Mapping[str, object] | None = None
) -> dict:
    return consumer_c3_authority_from_git(
        capsule_authority["consumer_root"],
        capsule_authority["consumer_B0"],
        package or capsule_authority["authority"].package,
    )


def _selection(registry: dict, capsule_authority: dict) -> dict:
    package = capsule_authority["authority"].package
    authority = consumer_c3_authority_from_git(
        capsule_authority["consumer_root"],
        capsule_authority["consumer_B0"],
        package,
    )
    return select_promotion_gates(
        package,
        registry,
        changed_paths=["wiki.config.yaml"],
        changed_contracts=[],
        consumer_c3_authority=authority,
    )


def _receipt(
    capsule_authority: dict,
    registry: dict | None = None,
    capsule: dict | None = None,
    selection: dict | None = None,
) -> tuple[dict, dict, dict, dict, str]:
    registry = registry or _registry()
    capsule = capsule or _capsule(capsule_authority)
    selection = selection or _selection(registry, capsule_authority)
    identity = _identity(capsule, capsule_authority)
    consumer_c3_authority = consumer_c3_authority_from_git(
        capsule_authority["consumer_root"],
        capsule_authority["consumer_B0"],
        capsule_authority["authority"].package,
    )
    consumer_c3_authority_sha256 = consumer_c3_authority["authority_sha256"]
    classes = {item["id"]: item["class"] for item in registry["gate_catalog"]}
    commands = {item["id"]: item["command"] for item in registry["gate_catalog"]}
    plan_sha256 = _digest("synthetic-read-only-plan")
    run_root = (
        capsule_authority["consumer_root"]
        / ".wiki-viva/upgrade/runs"
        / plan_sha256[:16]
    )
    (run_root / "logs").mkdir(parents=True, exist_ok=True)
    gate_results = []
    for gate_id in selection["selected_gates"]:
        output = f"gate={gate_id}\nstatus=passed\n".encode("utf-8")
        (run_root / "logs" / f"{gate_id}.log").write_bytes(output)
        gate_results.append(
            {
                "id": gate_id,
                "class": classes[gate_id],
                "provenance": "executed",
                "status": "passed",
                "exit_code": 0,
                "subject_sha": identity["consumer_C3"],
                "command_sha256": hashlib.sha256(
                    commands[gate_id].encode("utf-8")
                ).hexdigest(),
                "output_sha256": hashlib.sha256(output).hexdigest(),
            }
        )
    certified = {item["id"] for item in capsule["certified_gates"]}
    omissions = [
        {
            "gate_id": gate_id,
            "reason": (
                "verified_upstream_capsule" if gate_id in certified else "not_affected"
            ),
            "derivation_sha256": (
                capsule["capsule_sha256"]
                if gate_id in certified
                else selection["derivation_sha256"]
            ),
        }
        for gate_id in selection["omitted_gates"]
    ]
    consumer_root = capsule_authority["consumer_root"]
    c1_digest = hashlib.sha256(
        (consumer_root / "wiki_core/config.py").read_bytes()
    ).hexdigest()
    c2_digest = hashlib.sha256(
        (
            consumer_root / "apps/wiki-cockpit/public/sample-snapshot/snapshot.json"
        ).read_bytes()
    ).hexdigest()
    c3_digest = hashlib.sha256(
        (consumer_root / "wiki.config.yaml").read_bytes()
    ).hexdigest()
    boundaries = {
        "C1": [
            {
                "path": "wiki_core/config.py",
                "operation": "upsert",
                "mode": "100644",
                "sha256": c1_digest,
                "source_mode": "100644",
                "source_sha256": c1_digest,
            }
        ],
        "C2": [
            {
                "path": "apps/wiki-cockpit/public/sample-snapshot/snapshot.json",
                "operation": "upsert",
                "mode": "100644",
                "sha256": c2_digest,
                "generator_sha256": _digest("python3 scripts/wiki_build_demo.py"),
            }
        ],
        "C3": [
            {
                "path": "wiki.config.yaml",
                "operation": "upsert",
                "mode": "100644",
                "sha256": c3_digest,
            }
        ],
    }
    boundary_commits = {
        "B0": capsule_authority["consumer_B0"],
        "C1": capsule_authority["consumer_C1"],
        "C2": capsule_authority["consumer_C2"],
        "C3": capsule_authority["consumer_C3"],
    }
    b0_tree = _git(
        capsule_authority["consumer_root"],
        "rev-parse",
        f"{identity['consumer_B0']}^{{tree}}",
    )
    rollback = {
        "schema_version": "wiki_viva_upgrade_rollback_execution.v1",
        "provenance": "executed",
        "status": "verified",
        "subject_sha": identity["consumer_C3"],
        "consumer_B0": identity["consumer_B0"],
        "before_tree_sha": b0_tree,
        "rolled_back_tree_sha": b0_tree,
        "tree_equal": True,
        "method": "reverse_binary_patch_in_disposable_clone",
        "boundary_digest": canonical_sha256(boundaries),
    }
    rollback["evidence_sha256"] = canonical_sha256(rollback)
    (run_root / "rollback.json").write_text(
        json.dumps(rollback, sort_keys=True) + "\n", encoding="utf-8"
    )
    evidence = {
        "gate_logs": [
            {
                "gate_id": result["id"],
                "subject_sha": identity["consumer_C3"],
                "command_sha256": result["command_sha256"],
                "output_sha256": result["output_sha256"],
            }
            for result in gate_results
        ],
        "screenshots": [],
        "console": [
            {
                "ref": f"console-{result['id']}",
                "gate_id": result["id"],
                "subject_sha": identity["consumer_C3"],
                "capture": "process_stdout_stderr",
                "sha256": _digest(f"console:{result['id']}"),
            }
            for result in gate_results
        ],
        "network": [],
        "capture_status": {
            "screenshots": "captured",
            "console": "captured",
            "network": "captured",
        },
    }
    canary_id = "real_canary"
    canary_dir = run_root / "evidence" / canary_id
    canary_dir.mkdir(parents=True, exist_ok=True)
    network_raw = json.dumps(
        {
            "schema_version": "wiki_viva_network_capture_summary.v1",
            "capture_method": "synthetic-browser-observer",
            "request_count": 3,
            "error_count": 0,
            "payloads_redacted": True,
        },
        sort_keys=True,
    ).encode("utf-8")
    network_file = "network-summary.bin"
    (canary_dir / network_file).write_bytes(network_raw)
    evidence["network"].append(
        {
            "ref": "network-real-canary",
            "gate_id": canary_id,
            "subject_sha": identity["consumer_C3"],
            "sha256": hashlib.sha256(network_raw).hexdigest(),
            "capture": "gate_emitted_sanitized_network_summary",
            "request_count": 3,
            "error_count": 0,
            "artifact_file": network_file,
        }
    )
    console_raw = json.dumps(
        {
            "schema_version": "wiki_viva_browser_console_summary.v1",
            "error_count": 0,
            "warning_count": 0,
            "payloads_redacted": True,
        },
        sort_keys=True,
    ).encode("utf-8")
    console_file = "browser-console-summary.bin"
    (canary_dir / console_file).write_bytes(console_raw)
    evidence["console"].append(
        {
            "ref": "browser-console-real-canary",
            "gate_id": canary_id,
            "subject_sha": identity["consumer_C3"],
            "sha256": hashlib.sha256(console_raw).hexdigest(),
            "capture": "gate_emitted_browser_console_summary",
            "error_count": 0,
            "warning_count": 0,
            "artifact_file": console_file,
        }
    )
    visual_profiles = capsule_authority["authority"].package["migration"][
        "visual_profiles"
    ]
    for profile in visual_profiles:
        canary_viewport = VISUAL_PROFILE_CONTRACTS[profile]["canary_viewport"]
        width = canary_viewport["width"]
        height = canary_viewport["height"]
        image = _png_bytes(width, height)
        image_file = f"screenshot-{profile}.png"
        (canary_dir / image_file).write_bytes(image)
        evidence["screenshots"].append(
            {
                "ref": f"screenshot-{profile}",
                "gate_id": canary_id,
                "subject_sha": identity["consumer_C3"],
                "sha256": hashlib.sha256(image).hexdigest(),
                "profile": profile,
                "route": VISUAL_PROFILE_CONTRACTS[profile]["canary_route"],
                "view": VISUAL_PROFILE_CONTRACTS[profile]["view"],
                "runtime_mode": VISUAL_PROFILE_CONTRACTS[profile]["runtime_mode"],
                "viewport": {"width": width, "height": height},
                "width": width,
                "height": height,
                "artifact_file": image_file,
            }
        )
    for kind in ("screenshots", "console", "network"):
        evidence[kind].sort(key=lambda item: item["gate_id"])
    acceptance_budget = {
        "schema_version": "wiki_viva_upgrade_acceptance_budget.v1",
        "scope": "plan_to_real_canary",
        "limit_seconds": 1200,
        "enforcement": "promotion_blocking",
        "plan_started_at": "2026-07-14T00:00:00.000000Z",
        "canary_completed_at": "2026-07-14T00:00:01.000000Z",
        "elapsed_milliseconds": 1000,
        "status": "met",
    }
    report = {
        "schema_version": "wiki_viva_upgrade_runner_report.v3",
        "status": "complete",
        "lane": "lane_b",
        "mode": "canary",
        "plan_sha256": plan_sha256,
        "consumer_c3_authority_sha256": consumer_c3_authority_sha256,
        "identity": identity,
        "selection": {
            "escalation": selection["escalation"],
            "impact_derivation_sha256": selection["derivation_sha256"],
            "selected_gate_count": len(selection["selected_gates"]),
            "omitted_gate_count": len(selection["omitted_gates"]),
            "matched_surfaces": selection["matched_surfaces"],
        },
        "boundaries": {
            "digest": canonical_sha256(boundaries),
            "counts": {key: len(value) for key, value in boundaries.items()},
        },
        "gate_results": [
            {
                "id": result["id"],
                "class": result["class"],
                "status": result["status"],
                "output_sha256": result["output_sha256"],
            }
            for result in sorted(gate_results, key=lambda item: item["id"])
        ],
        "rollback_evidence_sha256": rollback["evidence_sha256"],
        "acceptance_budget": acceptance_budget,
        "evidence": evidence,
        "promotion_ready": True,
        "human_gate_required": True,
    }
    private_raw = (json.dumps(report, sort_keys=True) + "\n").encode("utf-8")
    (run_root / "migration-report.private.json").write_bytes(private_raw)
    public_report = public_migration_report_projection(report)
    public_raw = (json.dumps(public_report, sort_keys=True) + "\n").encode("utf-8")
    (run_root / "migration-report.public.json").write_bytes(public_raw)
    (run_root / "migration-report.json").write_bytes(public_raw)
    state_gate_results = {
        result["id"]: {
            **result,
            "_completed_at": (
                acceptance_budget["canary_completed_at"]
                if result["class"] == "canary"
                else acceptance_budget["plan_started_at"]
            ),
            "_evidence": {
                kind: [
                    item for item in evidence[kind] if item["gate_id"] == result["id"]
                ]
                for kind in ("screenshots", "console", "network")
            },
        }
        for result in gate_results
    }
    canary_result = state_gate_results["real_canary"]
    canary_projection = [
        {
            "id": "real_canary",
            "class": canary_result["class"],
            "status": canary_result["status"],
            "subject_sha": canary_result["subject_sha"],
            "command_sha256": canary_result["command_sha256"],
            "output_sha256": canary_result["output_sha256"],
            "completed_at": canary_result["_completed_at"],
            "evidence_sha256": canonical_sha256(canary_result["_evidence"]),
        }
    ]
    completion_anchor = {
        "schema_version": "wiki_viva_upgrade_canary_completion_anchor.v1",
        "authority": {
            "kind": "external_sha256",
            "id": "wiki_upgrade_real_canary_first_completion",
        },
        "plan_sha256": plan_sha256,
        "identity_sha256": canonical_sha256(identity),
        "canary_completed_at": acceptance_budget["canary_completed_at"],
        "canary_results_sha256": canonical_sha256(canary_projection),
    }
    completion_anchor["anchor_sha256"] = canonical_sha256(completion_anchor)
    completion_raw = (json.dumps(completion_anchor, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    completion_file_sha256 = hashlib.sha256(completion_raw).hexdigest()
    (run_root / "canary-completion-anchor.json").write_bytes(completion_raw)
    completion_reference = {
        "schema_version": "wiki_viva_upgrade_canary_completion_anchor_reference.v1",
        "anchor_sha256": completion_anchor["anchor_sha256"],
        "file_sha256": completion_file_sha256,
    }
    payload = {
        "status": "passed",
        "identity": identity,
        "capsule_sha256": capsule["capsule_sha256"],
        "impact_registry_sha256": registry["registry_sha256"],
        "impact_derivation_sha256": selection["derivation_sha256"],
        "plan_sha256": plan_sha256,
        "consumer_c3_authority_sha256": consumer_c3_authority_sha256,
        "acceptance_budget": acceptance_budget,
        "canary_completion_anchor": completion_reference,
        "resume": {
            "identity_sha256": canonical_sha256(identity),
            "plan_sha256": plan_sha256,
            "completed_gates": sorted(selection["selected_gates"]),
        },
        "boundary_commits": boundary_commits,
        "boundaries": boundaries,
        "gate_results": gate_results,
        "omitted_gates": omissions,
        "rollback_verification": {
            "provenance": "executed",
            "status": "verified",
            "subject_sha": identity["consumer_C3"],
            "evidence_sha256": rollback["evidence_sha256"],
        },
        "report_verification": {
            "provenance": "executed",
            "status": "verified",
            "subject_sha": identity["consumer_C3"],
            "evidence_sha256": hashlib.sha256(private_raw).hexdigest(),
        },
    }
    receipt = seal_adoption_receipt(payload)
    state = {
        "schema_version": "wiki_viva_upgrade_runner_state.v4",
        "status": "complete",
        "plan_sha256": plan_sha256,
        "identity_sha256": canonical_sha256(identity),
        "capsule_sha256": capsule["capsule_sha256"],
        "impact_registry_sha256": registry["registry_sha256"],
        "toolchain_sha256": identity["toolchain_sha256"],
        "consumer_c3_authority_sha256": consumer_c3_authority_sha256,
        "boundary_commits": boundary_commits,
        "run_started_unix_ns": 1,
        "acceptance_budget": acceptance_budget,
        "gate_results": state_gate_results,
    }
    (run_root / "state.json").write_text(
        json.dumps(state, sort_keys=True) + "\n", encoding="utf-8"
    )
    token = verify_adoption_evidence(
        receipt,
        authority=AdoptionEvidenceAuthority(
            consumer_root=capsule_authority["consumer_root"],
            run_root=run_root,
            trusted_canary_completion_anchor_sha256=completion_file_sha256,
        ),
        package=capsule_authority["authority"].package,
        registry=registry,
        selection=selection,
    )
    capsule_authority["adoption_tokens"][receipt["receipt_sha256"]] = token
    capsule_authority["adoption_run_roots"][receipt["receipt_sha256"]] = run_root
    return (
        receipt,
        identity,
        capsule,
        selection,
        plan_sha256,
    )


def _blocked_run_receipt(
    capsule_authority: dict,
    receipt: dict,
) -> tuple[dict, Path, str]:
    """Rewrite one synthetic completed run into a coherent budget-blocked run."""

    run_root = capsule_authority["adoption_run_roots"][receipt["receipt_sha256"]]
    blocked = copy.deepcopy(receipt)
    blocked_budget = copy.deepcopy(blocked["acceptance_budget"])
    blocked_budget.update(
        {
            "canary_completed_at": "2026-07-14T00:20:00.001000Z",
            "elapsed_milliseconds": 1_200_001,
            "status": "exceeded",
        }
    )
    blocked["status"] = "blocked"
    blocked["acceptance_budget"] = blocked_budget

    state_path = run_root / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["acceptance_budget"] = blocked_budget
    for result in state["gate_results"].values():
        if result["class"] == "canary":
            result["_completed_at"] = blocked_budget["canary_completed_at"]
    state_path.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
    canary_result = state["gate_results"]["real_canary"]
    canary_projection = [
        {
            "id": "real_canary",
            "class": canary_result["class"],
            "status": canary_result["status"],
            "subject_sha": canary_result["subject_sha"],
            "command_sha256": canary_result["command_sha256"],
            "output_sha256": canary_result["output_sha256"],
            "completed_at": canary_result["_completed_at"],
            "evidence_sha256": canonical_sha256(canary_result["_evidence"]),
        }
    ]
    completion_anchor = json.loads(
        (run_root / "canary-completion-anchor.json").read_text(encoding="utf-8")
    )
    completion_anchor["canary_completed_at"] = blocked_budget["canary_completed_at"]
    completion_anchor["canary_results_sha256"] = canonical_sha256(canary_projection)
    completion_anchor.pop("anchor_sha256")
    completion_anchor["anchor_sha256"] = canonical_sha256(completion_anchor)
    completion_raw = (json.dumps(completion_anchor, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    completion_digest = hashlib.sha256(completion_raw).hexdigest()
    (run_root / "canary-completion-anchor.json").write_bytes(completion_raw)
    blocked["canary_completion_anchor"] = {
        "schema_version": "wiki_viva_upgrade_canary_completion_anchor_reference.v1",
        "anchor_sha256": completion_anchor["anchor_sha256"],
        "file_sha256": completion_digest,
    }

    private_path = run_root / "migration-report.private.json"
    private_report = json.loads(private_path.read_text(encoding="utf-8"))
    private_report["acceptance_budget"] = blocked_budget
    private_report["promotion_ready"] = False
    private_raw = (json.dumps(private_report, sort_keys=True) + "\n").encode("utf-8")
    private_path.write_bytes(private_raw)
    blocked["report_verification"]["evidence_sha256"] = hashlib.sha256(
        private_raw
    ).hexdigest()
    blocked = seal_adoption_receipt(blocked)

    public_report = public_migration_report_projection(private_report)
    public_raw = (json.dumps(public_report, sort_keys=True) + "\n").encode("utf-8")
    (run_root / "migration-report.public.json").write_bytes(public_raw)
    (run_root / "migration-report.json").write_bytes(public_raw)
    return blocked, run_root, completion_digest


def _reseal(receipt: dict) -> dict:
    receipt = copy.deepcopy(receipt)
    receipt["resume"]["identity_sha256"] = canonical_sha256(receipt["identity"])
    return seal_adoption_receipt(receipt)


def _reseal_capsule(capsule: dict) -> dict:
    capsule = copy.deepcopy(capsule)
    capsule.pop("capsule_sha256", None)
    capsule["capsule_sha256"] = canonical_sha256(capsule)
    return capsule


def _legacy_rc37_shape(capsule_authority: dict) -> dict:
    """Build public synthetic v1 evidence with the exact pre-RT173 Node shape."""

    current = capsule_authority["authority"]
    package = copy.deepcopy(dict(current.package))
    registry = copy.deepcopy(dict(current.impact_registry))
    package["portable_import"]["block"].remove("apps/wiki-cockpit/node_modules/**")

    for item in registry["gate_catalog"]:
        replacement = _RC37_RAW_NODE_COMMANDS.get(item["id"])
        if replacement is not None:
            item["command"] = replacement
    registry.pop("registry_sha256")
    registry["registry_sha256"] = canonical_sha256(registry)

    migration = package["migration"]
    migration.pop("command_registry", None)
    for gate_id, command in _RC37_RAW_NODE_COMMANDS.items():
        migration["gate_commands"][gate_id] = command
    migration["command_registry_sha256"] = canonical_sha256(registry["gate_catalog"])
    migration["impact_registry"]["sha256"] = registry["registry_sha256"]
    visual_generator = next(
        item
        for item in migration["boundary_operations"]["c2_generators"]
        if item["id"] == "visual_baselines"
    )
    visual_generator["command"] = (
        "npm --prefix apps/wiki-cockpit run test:visual:update"
    )
    migration["boundary_operations"]["registry_sha256"] = boundary_operations_sha256(
        migration["boundary_operations"]
    )

    package_sha256 = canonical_sha256(package)
    visual_root = capsule_authority["visual_root"]
    manifest_path = visual_root / "visual-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["entries"]:
        record_path = visual_root / "records" / f"{entry['id']}.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["package_sha256"] = package_sha256
        record_raw = (canonical_json(record) + "\n").encode("utf-8")
        record_path.write_bytes(record_raw)
        entry["state"] = f"capture-{hashlib.sha256(record_raw).hexdigest()}"
    manifest_path.write_text(canonical_json(manifest) + "\n", encoding="utf-8")

    capsule = _capsule(capsule_authority)
    capsule["schema_version"] = LEGACY_RELEASE_CAPSULE_SCHEMA_VERSION
    capsule.pop("node_workspace_authority")
    capsule.pop("node_workspace_authority_sha256")
    capsule["command_registry"] = copy.deepcopy(registry["gate_catalog"])
    command_by_id = {item["id"]: item["command"] for item in registry["gate_catalog"]}
    for result in capsule["certified_gates"]:
        result["command_sha256"] = hashlib.sha256(
            command_by_id[result["id"]].encode("utf-8")
        ).hexdigest()
    capsule["command_registry_sha256"] = canonical_sha256(capsule["command_registry"])
    capsule["toolchain"] = {
        "browser": copy.deepcopy(capsule["toolchain"]["browser"]),
        "node": {"name": "node", "version": "22.22.3"},
        "python": {
            "name": "cpython-resolved",
            "version": f"3.12.4+deps.{'1' * 64}",
        },
        "runner": {
            "name": "wiki-upgrade",
            "version": f"1.4.0+payload.{'2' * 64}",
        },
    }
    capsule["toolchain_sha256"] = canonical_sha256(capsule["toolchain"])
    capsule["toolchain_probe_ref"] = "toolchain/probe-manifest-v1.json"
    capsule["attestation_ref"] = "execution-attestation-v1.json"

    probe_entries = []
    for tool_id, identity in sorted(capsule["toolchain"].items()):
        output_ref = f"toolchain/legacy-{tool_id}.log"
        output = f"{identity['name']} {identity['version']}\n".encode("utf-8")
        output_path = capsule_authority["gate_output_root"] / output_ref
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(output)
        probe_entries.append(
            {
                "id": tool_id,
                **identity,
                "provenance": "executed",
                "probe_argv": [tool_id, "--version"],
                "exit_code": 0,
                "output_ref": output_ref,
                "output_sha256": hashlib.sha256(output).hexdigest(),
                "output_bytes": len(output),
            }
        )
    (capsule_authority["gate_output_root"] / capsule["toolchain_probe_ref"]).write_text(
        json.dumps(
            {
                "schema_version": LEGACY_TOOLCHAIN_PROBE_SCHEMA_VERSION,
                "run_id": capsule["run_id"],
                "entries": probe_entries,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    evidence = collect_release_attestation(
        capsule,
        package=package,
        impact_registry=registry,
        source_root=current.source_root,
        visual_root=current.visual_root,
        gate_output_root=current.gate_output_root,
    )
    for field in (
        "package_sha256",
        "portable_tree_sha256",
        "portable_tree_entry_count",
        "visual_manifest_sha256",
        "visual_manifest_entry_count",
        "command_registry_sha256",
        "toolchain",
        "toolchain_sha256",
        "toolchain_probe_sha256",
        "toolchain_probe_entry_count",
    ):
        capsule[field] = evidence[field]
    output_by_id = {item["id"]: item for item in evidence["gate_outputs"]}
    for result in capsule["certified_gates"]:
        output = output_by_id[result["id"]]
        for field in ("output_ref", "output_sha256", "output_bytes"):
            result[field] = output[field]
    capsule["gate_receipt_sha256"] = canonical_sha256(capsule["certified_gates"])
    attestation_path = current.gate_output_root / capsule["attestation_ref"]
    attestation_path.write_text(
        json.dumps(evidence, sort_keys=True) + "\n", encoding="utf-8"
    )
    capsule["attestation_sha256"] = hashlib.sha256(
        attestation_path.read_bytes()
    ).hexdigest()
    capsule = _reseal_capsule(capsule)
    authority = ReleaseCapsuleAuthority(
        package=package,
        impact_registry=registry,
        source_root=current.source_root,
        visual_root=current.visual_root,
        gate_output_root=current.gate_output_root,
        verified_attestation_sha256=capsule["attestation_sha256"],
    )
    return {
        "capsule": capsule,
        "authority": authority,
        "package": package,
        "registry": registry,
    }


def _authority_with_attestation_sha(
    capsule_authority: dict, digest: str
) -> ReleaseCapsuleAuthority:
    current = capsule_authority["authority"]
    return ReleaseCapsuleAuthority(
        package=current.package,
        impact_registry=current.impact_registry,
        source_root=current.source_root,
        visual_root=current.visual_root,
        gate_output_root=current.gate_output_root,
        verified_attestation_sha256=digest,
    )


def _verify(
    receipt: dict,
    identity: dict,
    capsule: dict,
    selection: dict,
    plan_sha256: str,
    capsule_authority: dict,
) -> str:
    consumer_c3_authority = consumer_c3_authority_from_git(
        capsule_authority["consumer_root"],
        capsule_authority["consumer_B0"],
        capsule_authority["authority"].package,
    )
    return verify_adoption_receipt(
        receipt,
        expected_identity=identity,
        expected_plan_sha256=plan_sha256,
        capsule=capsule,
        verified_capsule=verify_release_capsule(
            capsule, authority=capsule_authority["authority"]
        ),
        verified_evidence=capsule_authority["adoption_tokens"].get(
            receipt["receipt_sha256"]
        ),
        package=capsule_authority["authority"].package,
        registry=_registry(),
        selection=selection,
        consumer_c3_authority=consumer_c3_authority,
    )


def _adoption_authority(
    capsule_authority: dict,
    run_root: Path,
    *,
    trusted_digest: str | None = None,
) -> AdoptionEvidenceAuthority:
    digest = (
        trusted_digest
        or hashlib.sha256(
            (run_root / "canary-completion-anchor.json").read_bytes()
        ).hexdigest()
    )
    return AdoptionEvidenceAuthority(
        consumer_root=capsule_authority["consumer_root"],
        run_root=run_root,
        trusted_canary_completion_anchor_sha256=digest,
    )


def test_published_gate_classes_and_never_reusable_ids_are_exact() -> None:
    assert GATE_CLASSES == (
        "upstream_certified",
        "consumer_always",
        "affected",
        "canary",
        "background_certification",
    )
    assert NEVER_REUSABLE_GATES == {
        "audit",
        "public_evidence_redaction",
        "input_stage",
        "operational_pass",
        "semantic_inventory",
        "adapter_identity",
        "snapshot_contract",
        "real_canary",
        "diff_check",
        "rollback_report_verification",
    }


def test_public_registry_is_canonical_versioned_and_schema_valid() -> None:
    registry = _registry()
    assert registry["schema_version"] == IMPACT_REGISTRY_SCHEMA_VERSION
    assert verify_impact_registry(registry) == registry["registry_sha256"]
    schema = json.loads(REGISTRY_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(registry)) == []
    assert seal_impact_registry(registry) == registry


@pytest.mark.parametrize(
    "command",
    [
        "npm --prefix apps/wiki-cockpit run check:bundle",
        "node apps/wiki-cockpit/scripts/check-bundle.mjs",
    ],
)
def test_impact_registry_rejects_raw_node_commands(command: str) -> None:
    registry = copy.deepcopy(_registry())
    target = next(item for item in registry["gate_catalog"] if item["id"] == "bundle")
    target["command"] = command
    unsigned = dict(registry)
    unsigned.pop("registry_sha256")
    registry["registry_sha256"] = canonical_sha256(unsigned)

    with pytest.raises(UpgradeLaneError, match="Node workspace policy"):
        verify_impact_registry(registry)


def test_release_capsule_is_immutable_canonical_and_schema_valid(
    capsule_authority: dict,
) -> None:
    capsule = _capsule(capsule_authority)
    assert capsule["schema_version"] == RELEASE_CAPSULE_SCHEMA_VERSION
    assert capsule["status"] == "certified"
    assert capsule["node_workspace_authority_sha256"] == (
        authority_identity_sha256(capsule["node_workspace_authority"])
    )
    assert capsule["toolchain"]["npm"] == npm_workspace_toolchain_identity(
        capsule["node_workspace_authority"]
    )
    verified = verify_release_capsule(capsule, authority=capsule_authority["authority"])
    assert verified.digest == capsule["capsule_sha256"]
    schema = json.loads(CAPSULE_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(capsule)) == []
    assert (
        seal_release_capsule(capsule, authority=capsule_authority["authority"])
        == capsule
    )


@pytest.mark.parametrize("operation", ["seal", "verify"])
def test_release_capsule_rejects_raw_node_commands_before_attestation(
    capsule_authority: dict, operation: str
) -> None:
    capsule = _capsule(capsule_authority)
    target = next(
        item for item in capsule["command_registry"] if item["id"] == "bundle"
    )
    target["command"] = "npm --prefix apps/wiki-cockpit run check:bundle"
    capsule["command_registry_sha256"] = canonical_sha256(capsule["command_registry"])

    with pytest.raises(UpgradeLaneError, match="Node workspace policy"):
        if operation == "seal":
            seal_release_capsule(capsule, authority=capsule_authority["authority"])
        else:
            verify_release_capsule(capsule, authority=capsule_authority["authority"])


def test_legacy_v1_capsule_and_attestation_remain_verifiable_without_reseal(
    capsule_authority: dict,
) -> None:
    legacy = _legacy_rc37_shape(capsule_authority)
    capsule = legacy["capsule"]
    package = legacy["package"]
    registry = legacy["registry"]

    assert (
        "apps/wiki-cockpit/node_modules/**" not in package["portable_import"]["block"]
    )
    assert {
        item["id"]: item["command"]
        for item in registry["gate_catalog"]
        if item["id"] in _RC37_RAW_NODE_COMMANDS
    } == _RC37_RAW_NODE_COMMANDS
    assert capsule["toolchain_probe_entry_count"] == 4
    assert "npm" not in capsule["toolchain"]
    with pytest.raises(UpgradeLaneError, match="Node workspace policy"):
        verify_impact_registry(registry)

    verified = verify_release_capsule(capsule, authority=legacy["authority"])

    assert verified.digest == capsule["capsule_sha256"]
    attestation = json.loads(
        (capsule_authority["gate_output_root"] / capsule["attestation_ref"]).read_text(
            encoding="utf-8"
        )
    )
    assert attestation["schema_version"] == LEGACY_EXECUTION_ATTESTATION_SCHEMA_VERSION
    assert "node_workspace_authority" not in attestation
    with pytest.raises(UpgradeLaneError, match="verification-only"):
        seal_release_capsule(capsule, authority=legacy["authority"])


def test_legacy_v1_raw_node_compatibility_does_not_weaken_byte_identity(
    capsule_authority: dict,
) -> None:
    legacy = _legacy_rc37_shape(capsule_authority)
    capsule = copy.deepcopy(legacy["capsule"])
    target = next(
        item for item in capsule["command_registry"] if item["id"] == "bundle"
    )
    target["command"] += " --synthetic-tamper"
    capsule = _reseal_capsule(capsule)

    with pytest.raises(UpgradeLaneError, match="command_registry_sha256 mismatch"):
        verify_release_capsule(capsule, authority=legacy["authority"])


def test_capsule_v2_requires_complete_node_workspace_authority(
    capsule_authority: dict,
) -> None:
    capsule = _capsule(capsule_authority)
    capsule.pop("node_workspace_authority")
    capsule = _reseal_capsule(capsule)
    with pytest.raises(UpgradeLaneError, match="schema rejected"):
        verify_release_capsule(capsule, authority=capsule_authority["authority"])

    capsule = _capsule(capsule_authority)
    capsule["node_workspace_authority"]["host_path"] = "/tmp/forged"
    capsule = _reseal_capsule(capsule)
    with pytest.raises(UpgradeLaneError, match="schema rejected"):
        verify_release_capsule(capsule, authority=capsule_authority["authority"])


def test_capsule_v2_rejects_node_workspace_authority_digest_source_and_policy_drift(
    capsule_authority: dict,
) -> None:
    capsule = _capsule(capsule_authority)
    capsule["node_workspace_authority_sha256"] = "f" * 64
    capsule = _reseal_capsule(capsule)
    with pytest.raises(UpgradeLaneError, match="authority_sha256 mismatch"):
        verify_release_capsule(capsule, authority=capsule_authority["authority"])

    capsule = _capsule(capsule_authority)
    capsule["node_workspace_authority"]["source_sha"] = "f" * 40
    capsule["node_workspace_authority_sha256"] = authority_identity_sha256(
        capsule["node_workspace_authority"]
    )
    capsule = _reseal_capsule(capsule)
    with pytest.raises(UpgradeLaneError, match="belongs to another source"):
        verify_release_capsule(capsule, authority=capsule_authority["authority"])

    capsule = _capsule(capsule_authority)
    capsule["node_workspace_authority"]["policy_sha256"] = "f" * 64
    capsule["node_workspace_authority_sha256"] = authority_identity_sha256(
        capsule["node_workspace_authority"]
    )
    capsule = _reseal_capsule(capsule)
    with pytest.raises(UpgradeLaneError, match="policy differs from exact source"):
        verify_release_capsule(capsule, authority=capsule_authority["authority"])


def test_capsule_v2_authority_changes_invalidate_toolchain_identity(
    capsule_authority: dict,
) -> None:
    capsule = _capsule(capsule_authority)
    previous_authority_sha256 = capsule["node_workspace_authority_sha256"]
    previous_toolchain_sha256 = capsule["toolchain_sha256"]
    capsule["node_workspace_authority"]["node_modules"]["tree_sha256"] = "e" * 64
    capsule["node_workspace_authority_sha256"] = authority_identity_sha256(
        capsule["node_workspace_authority"]
    )
    capsule = _reseal_capsule(capsule)

    assert capsule["node_workspace_authority_sha256"] != previous_authority_sha256
    assert capsule["toolchain_sha256"] == previous_toolchain_sha256
    with pytest.raises(UpgradeLaneError, match="npm toolchain differs"):
        verify_release_capsule(capsule, authority=capsule_authority["authority"])


def test_capsule_v2_rejects_internally_mismatched_authority_platform(
    capsule_authority: dict,
) -> None:
    capsule = _capsule(capsule_authority)
    capsule["node_workspace_authority"]["platform"]["machine"] = "arm64"
    capsule["node_workspace_authority_sha256"] = canonical_sha256(
        capsule["node_workspace_authority"]
    )
    capsule = _reseal_capsule(capsule)
    with pytest.raises(UpgradeLaneError, match="authority is invalid"):
        verify_release_capsule(capsule, authority=capsule_authority["authority"])


def test_productive_visual_authority_requires_external_capture_attestation(
    capsule_authority: dict,
) -> None:
    attestation = json.loads(
        capsule_authority["attestation_path"].read_text(encoding="utf-8")
    )

    assert (
        attestation["node_workspace_authority"]
        == capsule_authority["capsule"]["node_workspace_authority"]
    )
    assert attestation["node_workspace_authority_sha256"] == (
        capsule_authority["capsule"]["node_workspace_authority_sha256"]
    )
    assert attestation["visual_capture_trust"] == {
        "model": "external_capture_execution_attestation",
        "capture_method": "playwright_served_public_synthetic",
        "bundle_verification": "structural_only",
        "productive_authority": "external_sha256",
    }
    assert attestation["authority"] == {
        "kind": "external_sha256",
        "id": "synthetic-ci",
    }
    with pytest.raises(UpgradeLaneError, match="requires exact package/tree"):
        verify_release_capsule(capsule_authority["capsule"])


def test_safe_file_bytes_remains_pinned_when_path_is_replaced_mid_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "authority"
    evidence = root / "records" / "desktop.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_bytes(b"trusted-descriptor-bytes")
    original_read = os.read
    replaced = False

    def replace_path_then_read(descriptor: int, size: int) -> bytes:
        nonlocal replaced
        if not replaced:
            replaced = True
            evidence.rename(evidence.with_name("desktop-original.json"))
            evidence.write_bytes(b"attacker-path-bytes")
        return original_read(descriptor, size)

    monkeypatch.setattr(os, "read", replace_path_then_read)
    relative, raw = _safe_file_bytes(
        root, "records/desktop.json", label="visual record"
    )

    assert replaced is True
    assert relative == "records/desktop.json"
    assert raw == b"trusted-descriptor-bytes"
    assert evidence.read_bytes() == b"attacker-path-bytes"


def test_safe_file_bytes_rejects_symlinks_and_hardlinks(tmp_path: Path) -> None:
    root = tmp_path / "authority"
    records = root / "records"
    records.mkdir(parents=True)
    regular = records / "desktop.json"
    regular.write_bytes(b"trusted")

    final_symlink = records / "final-link.json"
    final_symlink.symlink_to(regular.name)
    with pytest.raises(UpgradeLaneError, match="without symlink traversal"):
        _safe_file_bytes(root, "records/final-link.json", label="visual record")

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "record.json").write_bytes(b"outside")
    (root / "linked-directory").symlink_to(outside, target_is_directory=True)
    with pytest.raises(UpgradeLaneError, match="without symlink traversal"):
        _safe_file_bytes(root, "linked-directory/record.json", label="visual record")

    hardlink = records / "desktop-hardlink.json"
    try:
        os.link(regular, hardlink)
    except OSError as exc:
        pytest.skip(f"hardlinks unavailable in this test environment: {exc}")
    with pytest.raises(UpgradeLaneError, match="non-hard-linked"):
        _safe_file_bytes(root, "records/desktop.json", label="visual record")

    fifo = records / "named-pipe.json"
    if hasattr(os, "mkfifo"):
        os.mkfifo(fifo)
        with pytest.raises(UpgradeLaneError, match="regular"):
            _safe_file_bytes(root, "records/named-pipe.json", label="visual record")


def test_release_capsule_rejects_tamper_and_manual_evidence(
    capsule_authority: dict,
) -> None:
    capsule = _capsule(capsule_authority)
    tampered = copy.deepcopy(capsule)
    tampered["visual_manifest_sha256"] = "f" * 64
    with pytest.raises(UpgradeLaneError, match="recomputed visual_manifest_sha256"):
        verify_release_capsule(tampered, authority=capsule_authority["authority"])

    manual = copy.deepcopy(capsule)
    manual["certified_gates"][0]["provenance"] = "manual"
    manual["gate_receipt_sha256"] = canonical_sha256(manual["certified_gates"])
    unsigned = dict(manual)
    unsigned.pop("capsule_sha256")
    manual["capsule_sha256"] = canonical_sha256(unsigned)
    with pytest.raises(UpgradeLaneError, match="schema rejected"):
        verify_release_capsule(manual, authority=capsule_authority["authority"])


def test_release_capsule_rejects_placeholder_command(
    capsule_authority: dict,
) -> None:
    capsule = _capsule(capsule_authority)
    capsule["command_registry"][0]["command"] = "true"
    with pytest.raises(UpgradeLaneError, match="placeholder/manual"):
        seal_release_capsule(capsule, authority=capsule_authority["authority"])


def test_shape_only_capsule_cannot_authorize_verification_or_omissions(
    capsule_authority: dict,
) -> None:
    capsule = _capsule(capsule_authority)
    with pytest.raises(UpgradeLaneError, match="requires exact package/tree"):
        verify_release_capsule(capsule)

    receipt, _identity_value, capsule, selection, _plan_sha256 = _receipt(
        capsule_authority
    )
    with pytest.raises(UpgradeLaneError, match="shape-only"):
        verify_gate_omissions(
            _registry(),
            selection,
            receipt["omitted_gates"],
            capsule,
        )


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("package_sha256", "recomputed package_sha256 mismatch"),
        ("portable_tree_sha256", "recomputed portable_tree_sha256 mismatch"),
        ("toolchain_sha256", "toolchain_sha256 mismatch"),
    ],
)
def test_capsule_rejects_resealed_digest_shaped_identity_substitution(
    field: str, message: str, capsule_authority: dict
) -> None:
    capsule = _capsule(capsule_authority)
    capsule[field] = "f" * 64
    capsule = _reseal_capsule(capsule)
    with pytest.raises(UpgradeLaneError, match=message):
        verify_release_capsule(capsule, authority=capsule_authority["authority"])


def test_verified_token_rejects_a_capsule_mutated_after_verification(
    capsule_authority: dict,
) -> None:
    receipt, _identity_value, capsule, selection, _plan_sha256 = _receipt(
        capsule_authority
    )
    capsule["certified_gates"][0]["output_bytes"] += 1
    with pytest.raises(UpgradeLaneError, match="shape-only"):
        verify_gate_omissions(
            _registry(),
            selection,
            receipt["omitted_gates"],
            capsule,
            verified_capsule=capsule_authority["verified"],
        )


def test_capsule_recomputes_the_pinned_git_tree_not_the_dirty_worktree(
    capsule_authority: dict,
) -> None:
    source_file = capsule_authority["source_root"] / "wiki_core/config.py"
    source_file.write_text("DIRTY_WORKTREE = True\n", encoding="utf-8")
    verified = verify_release_capsule(
        capsule_authority["capsule"],
        authority=capsule_authority["authority"],
    )
    assert (
        verified.portable_tree_sha256
        == capsule_authority["capsule"]["portable_tree_sha256"]
    )


def test_capsule_rejects_substituted_strict_png_evidence(
    capsule_authority: dict,
) -> None:
    image_path = capsule_authority["visual_root"] / "images/desktop.png"
    image_path.write_bytes(_png_bytes(width=17, height=12))
    with pytest.raises(UpgradeLaneError, match="DPR-1 viewport|hash/bytes/dimensions"):
        verify_release_capsule(
            capsule_authority["capsule"],
            authority=capsule_authority["authority"],
        )


def test_capsule_rejects_coherently_resealed_wrong_dpr1_dimensions(
    capsule_authority: dict,
) -> None:
    _replace_visual_image_and_reseal(
        capsule_authority, "desktop", width=720, height=500
    )

    with pytest.raises(UpgradeLaneError, match="DPR-1 viewport"):
        verify_release_capsule(
            capsule_authority["capsule"],
            authority=capsule_authority["authority"],
        )


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "undeclared"])
def test_capsule_visual_manifest_exactly_covers_package_profiles(
    capsule_authority: dict, mutation: str
) -> None:
    manifest_path = capsule_authority["visual_root"] / "visual-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if mutation == "missing":
        manifest["entries"].pop()
    elif mutation == "duplicate":
        manifest["entries"].append(copy.deepcopy(manifest["entries"][0]))
    else:
        manifest["entries"][0]["id"] = "undeclared"
    manifest_path.write_text(canonical_json(manifest) + "\n", encoding="utf-8")
    with pytest.raises(UpgradeLaneError, match="exactly cover"):
        verify_release_capsule(
            capsule_authority["capsule"],
            authority=capsule_authority["authority"],
        )


@pytest.mark.parametrize(
    "mutation", ["source", "toolchain", "route", "view", "runtime", "console"]
)
def test_capsule_reopens_record_backed_visual_authority(
    capsule_authority: dict, mutation: str
) -> None:
    root = capsule_authority["visual_root"]
    record_path = root / "records/desktop.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    if mutation == "source":
        record["source_sha"] = "f" * 40
    elif mutation == "toolchain":
        record["browser_toolchain"]["version"] = "9.9.9"
        record["browser_toolchain_sha256"] = canonical_sha256(
            record["browser_toolchain"]
        )
    elif mutation == "route":
        record["requested_route"] = "/demo/w?center=%2570rivate"
        record["route"] = "/demo/w?center=%2570rivate"
    elif mutation == "runtime":
        record["runtime_mode"] = "compat"
    elif mutation == "view":
        record["view"] = "timeline"
    else:
        record["console_summary"]["error_count"] = 1
    record_path.write_text(canonical_json(record) + "\n", encoding="utf-8")
    manifest_path = root / "visual-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = next(item for item in manifest["entries"] if item["id"] == "desktop")
    entry["state"] = f"capture-{hashlib.sha256(record_path.read_bytes()).hexdigest()}"
    entry["route"] = record["route"]
    manifest_path.write_text(canonical_json(manifest) + "\n", encoding="utf-8")
    with pytest.raises(UpgradeLaneError, match="visual capture record|visual profile"):
        verify_release_capsule(
            capsule_authority["capsule"],
            authority=capsule_authority["authority"],
        )


def test_capsule_rejects_gate_output_changed_after_the_attested_run(
    capsule_authority: dict,
) -> None:
    gate = capsule_authority["capsule"]["certified_gates"][0]
    output = capsule_authority["gate_output_root"] / gate["output_ref"]
    output.write_text(
        output.read_text(encoding="utf-8") + "changed=true\n", encoding="utf-8"
    )
    with pytest.raises(UpgradeLaneError, match="output binding mismatch"):
        verify_release_capsule(
            capsule_authority["capsule"],
            authority=capsule_authority["authority"],
        )


def test_capsule_rejects_toolchain_probe_output_changed_after_run(
    capsule_authority: dict,
) -> None:
    probe_output = capsule_authority["gate_output_root"] / "toolchain/python.log"
    probe_output.write_text("cpython 9.9.9\n", encoding="utf-8")
    with pytest.raises(UpgradeLaneError, match="toolchain probe output binding"):
        verify_release_capsule(
            capsule_authority["capsule"],
            authority=capsule_authority["authority"],
        )


def test_self_declared_or_fabricated_execution_attestation_is_rejected(
    capsule_authority: dict,
) -> None:
    attestation_path = capsule_authority["attestation_path"]
    attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
    attestation["gate_outputs"][0]["provenance"] = "manual"
    attestation_path.write_text(
        json.dumps(attestation, sort_keys=True) + "\n", encoding="utf-8"
    )
    digest = hashlib.sha256(attestation_path.read_bytes()).hexdigest()
    capsule = _capsule(capsule_authority)
    capsule["attestation_sha256"] = digest
    capsule = _reseal_capsule(capsule)
    authority = _authority_with_attestation_sha(capsule_authority, digest)
    with pytest.raises(UpgradeLaneError, match="does not bind exact"):
        verify_release_capsule(capsule, authority=authority)


def test_capsule_attestation_digest_inside_capsule_is_not_a_trust_anchor(
    capsule_authority: dict,
) -> None:
    authority = _authority_with_attestation_sha(capsule_authority, "f" * 64)
    with pytest.raises(UpgradeLaneError, match="external trust anchor"):
        verify_release_capsule(capsule_authority["capsule"], authority=authority)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("command", "semantically invalid"),
        ("class", "schema rejected"),
        ("digest", "semantically invalid"),
        ("boundary", "C3 ownership differs"),
    ],
)
def test_capsule_rejects_package_registry_command_class_or_digest_drift(
    mutation: str, message: str, capsule_authority: dict
) -> None:
    current = capsule_authority["authority"]
    package = copy.deepcopy(current.package)
    gate_id = package["migration"]["required_gates"][0]
    if mutation == "command":
        package["migration"]["gate_commands"][gate_id] += " --changed"
    elif mutation == "class":
        package["migration"]["gate_policies"][gate_id]["class"] = "affected"
    elif mutation == "boundary":
        boundary = package["migration"]["boundary_operations"]
        boundary["c3_adapter"]["owns_patterns"].append("consumer-extra/**")
        boundary["registry_sha256"] = boundary_operations_sha256(boundary)
    else:
        package["migration"]["command_registry_sha256"] = "f" * 64
    authority = ReleaseCapsuleAuthority(
        package=package,
        impact_registry=current.impact_registry,
        source_root=current.source_root,
        visual_root=current.visual_root,
        gate_output_root=current.gate_output_root,
        verified_attestation_sha256=current.verified_attestation_sha256,
    )
    with pytest.raises(UpgradeLaneError, match=message):
        verify_release_capsule(capsule_authority["capsule"], authority=authority)


def test_capsule_cannot_certify_unpinned_or_mismatched_release_identity(
    capsule_authority: dict,
) -> None:
    current = capsule_authority["authority"]
    blocked_package = copy.deepcopy(current.package)
    blocked_package["release"]["status"] = "validation_pending"
    blocked_authority = ReleaseCapsuleAuthority(
        package=blocked_package,
        impact_registry=current.impact_registry,
        source_root=current.source_root,
        visual_root=current.visual_root,
        gate_output_root=current.gate_output_root,
        verified_attestation_sha256=current.verified_attestation_sha256,
    )
    with pytest.raises(UpgradeLaneError, match="not pinned/releasable"):
        verify_release_capsule(
            capsule_authority["capsule"], authority=blocked_authority
        )

    mismatched = _capsule(capsule_authority)
    mismatched["release_id"] = "wiki-viva-v8-other-release"
    mismatched = _reseal_capsule(mismatched)
    with pytest.raises(UpgradeLaneError, match="release_id differs"):
        verify_release_capsule(mismatched, authority=current)


def test_capsule_rejects_a_normatively_incomplete_upgrade_package(
    capsule_authority: dict,
) -> None:
    current = capsule_authority["authority"]
    package = copy.deepcopy(current.package)
    del package["contract_versions"]["consumer_c3_authority"]
    authority = ReleaseCapsuleAuthority(
        package=package,
        impact_registry=current.impact_registry,
        source_root=current.source_root,
        visual_root=current.visual_root,
        gate_output_root=current.gate_output_root,
        verified_attestation_sha256=current.verified_attestation_sha256,
    )
    with pytest.raises(UpgradeLaneError, match="upgrade package schema rejected"):
        verify_release_capsule(capsule_authority["capsule"], authority=authority)


def test_known_delta_selects_consumer_invariants_canary_and_affected_gates() -> None:
    registry = _registry()
    selection = select_impacted_gates(
        registry,
        changed_paths=["apps/wiki-cockpit/public/navigation.overrides.json"],
        changed_contracts=[],
    )
    assert selection["requires_lane_a"] is False
    assert selection["escalation"] == "consumer_delta"
    assert selection["matched_surfaces"] == [
        "consumer_configuration",
        "route_navigation",
        "snapshot_adapter",
    ]
    assert NEVER_REUSABLE_GATES.issubset(selection["selected_gates"])
    assert {"frontend_focused", "temporal_parity", "visual_profiles"}.issubset(
        selection["selected_gates"]
    )


def test_promotion_selection_adds_required_background_gate_and_dependencies(
    capsule_authority: dict,
) -> None:
    package = copy.deepcopy(capsule_authority["authority"].package)
    selection = select_promotion_gates(
        package,
        _registry(),
        changed_paths=["wiki.config.yaml"],
        changed_contracts=[],
        consumer_c3_authority=consumer_c3_authority_from_git(
            capsule_authority["consumer_root"],
            capsule_authority["consumer_B0"],
            package,
        ),
    )
    assert "consumer_browser_matrix" in selection["selected_gates"]


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/private-ci.yml",
        ".skills/local-operator/SKILL.md",
        ".skills/README.md",
        "AGENTS.md",
        "adapters/custom/adapter.py",
        "docs/references/releases/private-v8.md",
        "requirements.txt",
        "tests/test_private_adapter.py",
        "wiki.page-types.yaml",
        "wiki.page-types.local.yaml",
        "wiki.templates.yaml",
        "wiki.templates.local.yaml",
    ],
)
def test_every_allowed_consumer_c3_surface_stays_in_lane_b(path: str) -> None:
    selection = select_impacted_gates(
        _registry(), changed_paths=[path], changed_contracts=[]
    )
    assert selection["unknown_paths"] == []
    assert selection["requires_lane_a"] is False
    assert selection["escalation"] == "consumer_delta"
    assert "operational_pass" in selection["selected_gates"]


@pytest.mark.parametrize(
    ("changed_paths", "changed_contracts", "unknown_field"),
    [
        (["unclassified/surface.txt"], [], "unknown_paths"),
        ([], ["unknown.contract"], "unknown_contracts"),
    ],
)
def test_unknown_path_or_contract_selects_complete_matrix_and_lane_a(
    changed_paths: list[str],
    changed_contracts: list[str],
    unknown_field: str,
) -> None:
    registry = _registry()
    selection = select_impacted_gates(
        registry,
        changed_paths=changed_paths,
        changed_contracts=changed_contracts,
    )
    assert selection["requires_lane_a"] is True
    assert selection["escalation"] == "unknown_impact_full_lane"
    assert selection["selected_gates"] == registry["full_matrix_gates"]
    assert selection[unknown_field]


def test_portable_path_or_contract_requires_new_lane_a_capsule() -> None:
    selection = select_impacted_gates(
        _registry(),
        changed_paths=["wiki_core/upgrade.py"],
        changed_contracts=["wiki_upgrade_package.v3"],
    )
    assert selection["requires_lane_a"] is True
    assert selection["escalation"] == "portable_change_lane_a"


def test_portable_wiki_skill_wins_over_broad_consumer_skill_namespace() -> None:
    selection = select_impacted_gates(
        _registry(),
        changed_paths=[".skills/wiki-viva/SKILL.md"],
        changed_contracts=[],
    )
    assert selection["matched_surfaces"] == ["portable_core"]
    assert selection["requires_lane_a"] is True
    assert selection["escalation"] == "portable_change_lane_a"


def test_skill_root_index_is_explicit_consumer_agent_routing() -> None:
    selection = select_impacted_gates(
        _registry(), changed_paths=[".skills/README.md"], changed_contracts=[]
    )
    assert selection["matched_surfaces"] == [
        "consumer_agent_routing",
        "consumer_configuration",
    ]
    assert selection["unknown_paths"] == []
    assert selection["requires_lane_a"] is False
    assert selection["escalation"] == "consumer_delta"


def test_broad_consumer_skill_pattern_does_not_cover_skill_root_index() -> None:
    registry = _registry()
    routing = next(
        surface
        for surface in registry["surfaces"]
        if surface["id"] == "consumer_agent_routing"
    )
    routing["path_patterns"].remove(".skills/README.md")
    registry["boundary_policy"]["c3_consumer_patterns"].remove(".skills/README.md")
    registry = seal_impact_registry(registry)

    selection = select_impacted_gates(
        registry, changed_paths=[".skills/README.md"], changed_contracts=[]
    )
    assert selection["unknown_paths"] == [".skills/README.md"]
    assert selection["requires_lane_a"] is True
    assert selection["escalation"] == "unknown_impact_full_lane"


def _localized_c3_chain(
    tmp_path: Path,
    package: Mapping[str, object],
    *,
    files: Mapping[str, tuple[bytes, str]],
    c3_config: str | None = None,
) -> tuple[Path, dict, dict, dict]:
    consumer = tmp_path / "localized-consumer"
    consumer.mkdir()
    _git(consumer, "init", "-q", "-b", "main")
    _git(consumer, "config", "user.name", "Synthetic Consumer")
    _git(consumer, "config", "user.email", "consumer@example.invalid")
    (consumer / "wiki.config.yaml").write_text(
        "\n".join(
            [
                "repo_id: localized-public-synthetic",
                "paths:",
                "  memory_root: memoria-publica",
                "  references_root: docs/referencias-publicas",
                "  command_reference_page: memoria-publica/sistema/referencia-comandos.md",
                "  operational_pass_page: memoria-publica/sistema/passagem-operacional.md",
                "",
            ]
        ),
        encoding="utf-8",
    )
    _git(consumer, "add", ".")
    _git(consumer, "commit", "-q", "-m", "consumer B0")
    b0 = _git(consumer, "rev-parse", "HEAD")
    _git(consumer, "commit", "-q", "--allow-empty", "-m", "consumer C1")
    c1 = _git(consumer, "rev-parse", "HEAD")
    _git(consumer, "commit", "-q", "--allow-empty", "-m", "consumer C2")
    c2 = _git(consumer, "rev-parse", "HEAD")
    for path, (raw, mode) in files.items():
        target = consumer / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        target.chmod(0o755 if mode == "100755" else 0o644)
    if c3_config is not None:
        (consumer / "wiki.config.yaml").write_text(c3_config, encoding="utf-8")
    _git(consumer, "add", "-A")
    _git(consumer, "commit", "-q", "-m", "consumer C3")
    c3 = _git(consumer, "rev-parse", "HEAD")
    boundaries = {"C1": [], "C2": [], "C3": []}
    for path, (raw, mode) in files.items():
        boundaries["C3"].append(
            {
                "path": path,
                "operation": "upsert",
                "mode": mode,
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    if c3_config is not None:
        raw = c3_config.encode("utf-8")
        boundaries["C3"].append(
            {
                "path": "wiki.config.yaml",
                "operation": "upsert",
                "mode": "100644",
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    boundaries["C3"].sort(key=lambda item: item["path"])
    commits = {"B0": b0, "C1": c1, "C2": c2, "C3": c3}
    authority = consumer_c3_authority_from_git(consumer, b0, package)
    return consumer, commits, boundaries, authority


def test_localized_b0_authority_accepts_only_three_exact_technical_roles(
    tmp_path: Path, capsule_authority: dict
) -> None:
    package = capsule_authority["authority"].package
    files = {
        "memoria-publica/sistema/referencia-comandos.md": (
            b"# Comandos publicos sinteticos\n",
            "100644",
        ),
        "memoria-publica/sistema/passagem-operacional.md": (
            b"# Passagem operacional sintetica\n",
            "100644",
        ),
        "docs/referencias-publicas/releases/wiki-viva-v8-rc22.md": (
            b"# Registro sintetico rc22\n",
            "100644",
        ),
    }
    consumer, commits, boundaries, authority = _localized_c3_chain(
        tmp_path, package, files=files
    )

    assert [classify_consumer_c3_path(path, authority) for path in sorted(files)] == [
        "release_records",
        "operational_pass_page",
        "command_reference_page",
    ]
    selection = select_promotion_gates(
        package,
        _registry(),
        changed_paths=sorted(files),
        changed_contracts=[],
        consumer_c3_authority=authority,
    )
    assert selection["requires_lane_a"] is False
    assert selection["unknown_paths"] == []
    validate_boundary_ownership(
        boundaries,
        _registry(),
        package=package,
        consumer_c3_authority=authority,
    )
    verify_config_bound_c3_git_content(
        consumer,
        commits=commits,
        boundaries=boundaries,
        authority=authority,
        package=package,
    )


def test_localized_domain_path_matches_default_content_impact_but_stays_out_of_c3(
    tmp_path: Path, capsule_authority: dict
) -> None:
    package = capsule_authority["authority"].package
    path = "memoria-publica/financeiro/ledger.md"
    _consumer, _commits, boundaries, authority = _localized_c3_chain(
        tmp_path,
        package,
        files={path: (b"# Dados sinteticos\n", "100644")},
    )
    selection = select_impacted_gates(
        _registry(),
        changed_paths=[path],
        changed_contracts=[],
        consumer_c3_authority=authority,
    )
    default_selection = select_impacted_gates(
        _registry(),
        changed_paths=["memories/finance/ledger.md"],
        changed_contracts=[],
    )
    assert selection["matched_surfaces"] == [
        "consumer_configuration",
        "content_semantics",
    ]
    assert selection["selected_gates"] == default_selection["selected_gates"]
    assert selection["omitted_gates"] == default_selection["omitted_gates"]
    assert selection["requires_lane_a"] is False
    assert selection["unknown_paths"] == []
    assert selection["escalation"] == "consumer_delta"
    assert "real_canary" in selection["selected_gates"]
    assert "semantic_inventory" in selection["selected_gates"]
    assert "visual_profiles" not in selection["selected_gates"]
    with pytest.raises(UpgradeLaneError, match="domain content is forbidden"):
        validate_boundary_ownership(
            boundaries,
            _registry(),
            package=package,
            consumer_c3_authority=authority,
        )


def test_localized_memory_root_prefix_confusion_remains_unknown_full_lane(
    tmp_path: Path, capsule_authority: dict
) -> None:
    package = capsule_authority["authority"].package
    path = "memoria-publica-archive/financeiro/ledger.md"
    _consumer, _commits, _boundaries, authority = _localized_c3_chain(
        tmp_path,
        package,
        files={path: (b"# Dados sinteticos arquivados\n", "100644")},
    )
    registry = _registry()
    selection = select_impacted_gates(
        registry,
        changed_paths=[path],
        changed_contracts=[],
        consumer_c3_authority=authority,
    )
    assert selection["unknown_paths"] == [path]
    assert selection["requires_lane_a"] is True
    assert selection["escalation"] == "unknown_impact_full_lane"
    assert selection["selected_gates"] == registry["full_matrix_gates"]


def test_localized_memory_root_requires_one_content_contract_surface(
    tmp_path: Path, capsule_authority: dict
) -> None:
    package = capsule_authority["authority"].package
    path = "memoria-publica/financeiro/ledger.md"
    _consumer, _commits, _boundaries, authority = _localized_c3_chain(
        tmp_path,
        package,
        files={path: (b"# Dados sinteticos\n", "100644")},
    )
    missing = _registry()
    content = next(
        item for item in missing["surfaces"] if item["id"] == "content_semantics"
    )
    content["contracts"].remove("wiki_content.v1")
    missing = seal_impact_registry(missing)

    ambiguous = _registry()
    consumer_tests = next(
        item for item in ambiguous["surfaces"] if item["id"] == "consumer_tests"
    )
    consumer_tests["contracts"].append("wiki_content.v1")
    ambiguous = seal_impact_registry(ambiguous)

    for registry in (missing, ambiguous):
        selection = select_impacted_gates(
            registry,
            changed_paths=[path],
            changed_contracts=[],
            consumer_c3_authority=authority,
        )
        assert selection["unknown_paths"] == [path]
        assert selection["requires_lane_a"] is True
        assert selection["escalation"] == "unknown_impact_full_lane"
        assert selection["selected_gates"] == registry["full_matrix_gates"]


def test_c3_config_edit_cannot_expand_the_b0_authority(
    tmp_path: Path, capsule_authority: dict
) -> None:
    package = capsule_authority["authority"].package
    new_path = "memoria-publica/financeiro/referencia-comandos.md"
    c3_config = "\n".join(
        [
            "repo_id: localized-public-synthetic",
            "paths:",
            "  memory_root: memoria-publica",
            "  references_root: docs/referencias-publicas",
            f"  command_reference_page: {new_path}",
            "  operational_pass_page: memoria-publica/sistema/passagem-operacional.md",
            "",
        ]
    )
    consumer, _commits, boundaries, authority = _localized_c3_chain(
        tmp_path,
        package,
        files={new_path: (b"# Tentativa de ampliacao\n", "100644")},
        c3_config=c3_config,
    )
    assert classify_consumer_c3_path(new_path, authority) is None
    assert (
        verify_consumer_c3_authority(
            authority,
            consumer_root=consumer,
            consumer_B0=authority["consumer_B0"],
            package=package,
        )
        == authority["authority_sha256"]
    )
    with pytest.raises(UpgradeLaneError, match="domain content is forbidden"):
        validate_boundary_ownership(
            boundaries,
            _registry(),
            package=package,
            consumer_c3_authority=authority,
        )


@pytest.mark.parametrize(
    ("path", "raw", "mode", "message"),
    [
        (
            "docs/referencias-publicas/releases/postinstall.sh",
            b"#!/bin/sh\nexit 0\n",
            "100644",
            "must be inert Markdown",
        ),
        (
            "docs/referencias-publicas/releases/executable.md",
            b"# Executavel\n",
            "100755",
            "inert 100644 Markdown",
        ),
        (
            "docs/referencias-publicas/releases/binary.md",
            b"\xff\xfe\xfd",
            "100644",
            "must be UTF-8",
        ),
        (
            "docs/referencias-publicas/releases/nul.md",
            b"# Registro\x00invalido\n",
            "100644",
            "inert 100644 Markdown",
        ),
        (
            "docs/referencias-publicas/releases/secret.md",
            b"api_key=super-secret-token-value-1234567890\n",
            "100644",
            "contains an access secret",
        ),
    ],
)
def test_release_records_fail_closed_as_inert_markdown(
    path: str,
    raw: bytes,
    mode: str,
    message: str,
    tmp_path: Path,
    capsule_authority: dict,
) -> None:
    package = capsule_authority["authority"].package
    consumer, commits, boundaries, authority = _localized_c3_chain(
        tmp_path, package, files={path: (raw, mode)}
    )
    if path.endswith(".sh") or mode == "100755":
        with pytest.raises(UpgradeLaneError, match=message):
            validate_boundary_ownership(
                boundaries,
                _registry(),
                package=package,
                consumer_c3_authority=authority,
            )
        return
    validate_boundary_ownership(
        boundaries,
        _registry(),
        package=package,
        consumer_c3_authority=authority,
    )
    with pytest.raises(UpgradeLaneError, match=message):
        verify_config_bound_c3_git_content(
            consumer,
            commits=commits,
            boundaries=boundaries,
            authority=authority,
            package=package,
        )


def test_resealed_consumer_c3_authority_tamper_is_rejected_against_b0(
    tmp_path: Path, capsule_authority: dict
) -> None:
    package = capsule_authority["authority"].package
    consumer, _commits, _boundaries, authority = _localized_c3_chain(
        tmp_path,
        package,
        files={
            "memoria-publica/sistema/referencia-comandos.md": (
                b"# Sintetico\n",
                "100644",
            )
        },
    )
    forged = copy.deepcopy(authority)
    forged["exact_markdown_paths"][0][
        "path"
    ] = "memoria-publica/financeiro/referencia-comandos.md"
    unsigned = copy.deepcopy(forged)
    unsigned.pop("authority_sha256")
    forged["authority_sha256"] = canonical_sha256(unsigned)
    with pytest.raises(UpgradeLaneError, match="differs from exact B0 config"):
        verify_consumer_c3_authority(
            forged,
            consumer_root=consumer,
            consumer_B0=authority["consumer_B0"],
            package=package,
        )


def _canary_evidence() -> tuple[dict, dict, list[str], list[dict], str]:
    subject = "6" * 40
    package = {"migration": {"visual_profiles": ["desktop", "mobile"]}}
    catalog = [
        {
            "id": "real_canary",
            "class": "canary",
            "command": "npm run canary",
        }
    ]
    evidence = {
        "network": [
            {
                "gate_id": "real_canary",
                "subject_sha": subject,
                "capture": "gate_emitted_sanitized_network_summary",
                "request_count": 4,
                "error_count": 0,
            }
        ],
        "console": [
            {
                "gate_id": "real_canary",
                "subject_sha": subject,
                "capture": "gate_emitted_browser_console_summary",
                "error_count": 0,
            }
        ],
        "screenshots": [
            {
                "gate_id": "real_canary",
                "subject_sha": subject,
                "profile": "desktop",
                "route": "/w?view=quadrants&tour=0",
                "view": "quadrants",
                "runtime_mode": "v8",
                "viewport": {"width": 1440, "height": 1000},
                "width": 1440,
                "height": 1000,
            },
            {
                "gate_id": "real_canary",
                "subject_sha": subject,
                "profile": "mobile",
                "route": "/w?view=timeline&tour=0",
                "view": "timeline",
                "runtime_mode": "v8",
                "viewport": {"width": 390, "height": 844},
                "width": 390,
                "height": 844,
            },
        ],
    }
    return package, evidence, ["real_canary"], catalog, subject


def test_canary_requires_real_requests_zero_errors_and_exact_visuals() -> None:
    package, evidence, selected, catalog, subject = _canary_evidence()
    validate_canary_evidence(
        package,
        evidence,
        selected_gates=selected,
        gate_catalog=catalog,
        subject_sha=subject,
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("request_count", 0, "requests>0"),
        ("error_count", 1, "errors=0"),
    ],
)
def test_canary_rejects_empty_or_erroring_network_capture(
    field: str, value: int, message: str
) -> None:
    package, evidence, selected, catalog, subject = _canary_evidence()
    evidence["network"][0][field] = value
    with pytest.raises(UpgradeLaneError, match=message):
        validate_canary_evidence(
            package,
            evidence,
            selected_gates=selected,
            gate_catalog=catalog,
            subject_sha=subject,
        )


def test_canary_rejects_duplicate_or_missing_visual_profile() -> None:
    package, evidence, selected, catalog, subject = _canary_evidence()
    evidence["screenshots"][1] = copy.deepcopy(evidence["screenshots"][0])
    with pytest.raises(UpgradeLaneError, match="duplicate|coverage differs"):
        validate_canary_evidence(
            package,
            evidence,
            selected_gates=selected,
            gate_catalog=catalog,
            subject_sha=subject,
        )


def test_canary_rejects_bounded_but_noncanonical_viewport() -> None:
    package, evidence, selected, catalog, subject = _canary_evidence()
    evidence["screenshots"][0].update(
        {
            "viewport": {"width": 1280, "height": 900},
            "width": 1280,
            "height": 900,
        }
    )
    with pytest.raises(UpgradeLaneError, match="viewport"):
        validate_canary_evidence(
            package,
            evidence,
            selected_gates=selected,
            gate_catalog=catalog,
            subject_sha=subject,
        )


@pytest.mark.parametrize("runtime_mode", [None, "compat", "legacy"])
def test_canary_rejects_missing_or_non_v8_runtime(runtime_mode: str | None) -> None:
    package, evidence, selected, catalog, subject = _canary_evidence()
    if runtime_mode is None:
        evidence["screenshots"][0].pop("runtime_mode")
    else:
        evidence["screenshots"][0]["runtime_mode"] = runtime_mode
    with pytest.raises(UpgradeLaneError, match="runtime"):
        validate_canary_evidence(
            package,
            evidence,
            selected_gates=selected,
            gate_catalog=catalog,
            subject_sha=subject,
        )


@pytest.mark.parametrize(
    ("profile", "route", "view"),
    [
        ("desktop", "/totally-wrong-but-safe", "quadrants"),
        ("desktop", "/w/quadrants", "quadrants"),
        ("desktop", "/w?view=quadrants&tour=0", "timeline"),
        ("custom_profile", "/w?view=quadrants&tour=0", "quadrants"),
    ],
)
def test_canary_rejects_wrong_native_route_view_or_unknown_profile(
    profile: str, route: str, view: str
) -> None:
    package, evidence, selected, catalog, subject = _canary_evidence()
    package["migration"]["visual_profiles"][0] = profile
    evidence["screenshots"][0].update(
        {"profile": profile, "route": route, "view": view}
    )
    with pytest.raises(UpgradeLaneError, match="route|view|profile"):
        validate_canary_evidence(
            package,
            evidence,
            selected_gates=selected,
            gate_catalog=catalog,
            subject_sha=subject,
        )


@pytest.mark.parametrize(
    "route",
    ["/%72eal/customer", "/redirect?next=%252Fconsumer%252Faccount"],
)
def test_canary_rejects_percent_encoded_private_route(route: str) -> None:
    package, evidence, selected, catalog, subject = _canary_evidence()
    evidence["screenshots"][0]["route"] = route
    with pytest.raises(UpgradeLaneError, match="profile/route/view/runtime/viewport"):
        validate_canary_evidence(
            package,
            evidence,
            selected_gates=selected,
            gate_catalog=catalog,
            subject_sha=subject,
        )


def test_registry_rejects_dependency_cycles_and_incomplete_full_matrix() -> None:
    registry = _registry()
    cycle = copy.deepcopy(registry)
    next(item for item in cycle["surfaces"] if item["id"] == "consumer_configuration")[
        "depends_on"
    ] = ["snapshot_adapter"]
    with pytest.raises(UpgradeLaneError, match="dependency cycle"):
        seal_impact_registry(cycle)

    incomplete = copy.deepcopy(registry)
    incomplete["full_matrix_gates"].remove("audit")
    with pytest.raises(UpgradeLaneError, match="complete sorted gate catalog"):
        seal_impact_registry(incomplete)


def test_registry_binds_each_configured_role_to_its_exact_impact_contract() -> None:
    registry = _registry()
    wrong_contract = copy.deepcopy(registry)
    surface = next(
        item
        for item in wrong_contract["surfaces"]
        if "command_reference_page" in item.get("configured_path_roles", [])
    )
    surface["contracts"].remove("wiki_consumer_command_reference.v1")
    surface["contracts"].append("wiki_consumer_operational_pass.v1")
    with pytest.raises(UpgradeLaneError, match="role/contract binding differs"):
        seal_impact_registry(wrong_contract)

    duplicate_role = copy.deepcopy(registry)
    surface = next(
        item for item in duplicate_role["surfaces"] if item["id"] == "content_semantics"
    )
    surface["configured_path_roles"].append("command_reference_page")
    surface["contracts"].append("wiki_consumer_command_reference.v1")
    with pytest.raises(UpgradeLaneError, match="exactly one impact surface"):
        seal_impact_registry(duplicate_role)


def test_valid_adoption_receipt_reuses_only_exact_subject(
    capsule_authority: dict,
) -> None:
    receipt, identity, capsule, selection, plan_sha256 = _receipt(capsule_authority)
    assert receipt["schema_version"] == ADOPTION_RECEIPT_SCHEMA_VERSION
    assert (
        _verify(
            receipt,
            identity,
            capsule,
            selection,
            plan_sha256,
            capsule_authority,
        )
        == receipt["receipt_sha256"]
    )


def test_adoption_evidence_accepts_ignored_runner_artifacts(
    capsule_authority: dict,
) -> None:
    receipt, _identity_value, _capsule_value, selection, _plan = _receipt(
        capsule_authority
    )
    run_root = capsule_authority["adoption_run_roots"][receipt["receipt_sha256"]]
    ignored_probe = run_root / "operator-note.txt"
    ignored_probe.write_text("ignored synthetic evidence\n", encoding="utf-8")

    verify_adoption_evidence(
        receipt,
        authority=_adoption_authority(capsule_authority, run_root),
        package=capsule_authority["authority"].package,
        registry=_registry(),
        selection=selection,
    )


def test_adoption_git_authority_ignores_ambient_identity_and_process_injection(
    capsule_authority: dict,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    receipt, _identity_value, _capsule_value, selection, _plan = _receipt(
        capsule_authority
    )
    run_root = capsule_authority["adoption_run_roots"][receipt["receipt_sha256"]]
    decoy = tmp_path / "ambient-decoy"
    decoy.mkdir()
    _git(decoy, "init", "-q", "-b", "main")
    _git(decoy, "config", "user.name", "Ambient Decoy")
    _git(decoy, "config", "user.email", "decoy@example.invalid")
    (decoy / "decoy.txt").write_text("wrong authority\n", encoding="utf-8")
    _git(decoy, "add", "decoy.txt")
    _git(decoy, "commit", "-q", "-m", "decoy subject")
    assert _git(decoy, "rev-parse", "HEAD") != capsule_authority["consumer_C3"]
    script, sentinel = _sentinel_git_command(tmp_path)
    injected = {
        "GIT_DIR": str(decoy / ".git"),
        "GIT_WORK_TREE": str(decoy),
        "GIT_INDEX_FILE": str(decoy / ".git/index"),
        "GIT_OBJECT_DIRECTORY": str(decoy / ".git/objects"),
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.fsmonitor",
        "GIT_CONFIG_VALUE_0": str(script),
        "GIT_EXTERNAL_DIFF": str(script),
    }
    for key, value in injected.items():
        monkeypatch.setenv(key, value)
    observed_head = (
        _git_bytes(
            capsule_authority["consumer_root"],
            ["rev-parse", "HEAD"],
            label="ambient consumer identity",
        )
        .decode("ascii", "strict")
        .strip()
    )

    verified = verify_adoption_evidence(
        receipt,
        authority=_adoption_authority(capsule_authority, run_root),
        package=capsule_authority["authority"].package,
        registry=_registry(),
        selection=selection,
    )

    assert verified.receipt_digest == receipt["receipt_sha256"]
    assert observed_head == capsule_authority["consumer_C3"]
    assert verified.consumer_C3 == capsule_authority["consumer_C3"]
    assert not sentinel.exists()


def test_release_source_rejects_local_executable_git_config_without_running_it(
    capsule_authority: dict,
    tmp_path: Path,
) -> None:
    source = capsule_authority["source_root"]
    script, sentinel = _sentinel_git_command(tmp_path)
    _git(source, "config", "core.fsmonitor", str(script))

    with pytest.raises(
        UpgradeLaneError,
        match="source authority Git configuration contains executable policy",
    ):
        verify_release_capsule(
            _capsule(capsule_authority),
            authority=capsule_authority["authority"],
        )

    assert not sentinel.exists()


def test_consumer_authority_rejects_local_worktree_identity_redirect(
    capsule_authority: dict,
    tmp_path: Path,
) -> None:
    receipt, _identity_value, _capsule_value, selection, _plan = _receipt(
        capsule_authority
    )
    run_root = capsule_authority["adoption_run_roots"][receipt["receipt_sha256"]]
    decoy = tmp_path / "local-worktree-decoy"
    decoy.mkdir()
    (decoy / "wiki.config.yaml").write_text(
        "repo_id: redirected-decoy\n", encoding="utf-8"
    )
    _git(capsule_authority["consumer_root"], "config", "core.worktree", str(decoy))

    with pytest.raises(
        UpgradeLaneError,
        match="consumer authority Git configuration contains executable policy",
    ):
        verify_adoption_evidence(
            receipt,
            authority=_adoption_authority(capsule_authority, run_root),
            package=capsule_authority["authority"].package,
            registry=_registry(),
            selection=selection,
        )

    assert (decoy / "wiki.config.yaml").read_text(encoding="utf-8") == (
        "repo_id: redirected-decoy\n"
    )


def test_adoption_evidence_binds_custom_plan_parent_and_exact_run_key(
    capsule_authority: dict,
) -> None:
    receipt, _identity_value, _capsule_value, selection, _plan = _receipt(
        capsule_authority
    )
    consumer = capsule_authority["consumer_root"]
    original = capsule_authority["adoption_run_roots"][receipt["receipt_sha256"]]
    info_exclude = consumer / ".git/info/exclude"
    info_exclude.write_text(
        info_exclude.read_text(encoding="utf-8") + "\n/output/upgrade/\n",
        encoding="utf-8",
    )
    run_key = receipt["plan_sha256"][:16]
    custom = consumer / "output/upgrade/runs" / run_key
    shutil.copytree(original, custom)

    verify_adoption_evidence(
        receipt,
        authority=_adoption_authority(capsule_authority, custom),
        package=capsule_authority["authority"].package,
        registry=_registry(),
        selection=selection,
    )

    trusted_digest = hashlib.sha256(
        (custom / "canary-completion-anchor.json").read_bytes()
    ).hexdigest()
    wrong_key = consumer / "output/upgrade/runs" / ("0" * 16)
    wrong_key.mkdir(parents=True)
    wrong_shape = consumer / "output/upgrade/state" / run_key
    wrong_shape.mkdir(parents=True)
    for invalid in (wrong_key, wrong_shape):
        with pytest.raises(
            UpgradeLaneError,
            match="exact plan-parent runs boundary",
        ):
            verify_adoption_evidence(
                receipt,
                authority=_adoption_authority(
                    capsule_authority,
                    invalid,
                    trusted_digest=trusted_digest,
                ),
                package=capsule_authority["authority"].package,
                registry=_registry(),
                selection=selection,
            )


def test_verifiers_reject_package_policy_drift_before_promotion_reuse(
    capsule_authority: dict,
) -> None:
    receipt, identity, capsule, selection, plan_sha256 = _receipt(capsule_authority)
    run_root = capsule_authority["adoption_run_roots"][receipt["receipt_sha256"]]
    package = copy.deepcopy(capsule_authority["authority"].package)
    policy = package["migration"]["gate_policies"]["consumer_browser_matrix"]
    policy["required_for_promotion"] = not policy["required_for_promotion"]

    with pytest.raises(UpgradeLaneError, match="C3 authority is stale"):
        verify_adoption_evidence(
            receipt,
            authority=_adoption_authority(capsule_authority, run_root),
            package=package,
            registry=_registry(),
            selection=selection,
        )
    with pytest.raises(
        UpgradeLaneError, match="consumer C3 authority differs from package policy"
    ):
        verify_adoption_receipt(
            receipt,
            expected_identity=identity,
            expected_plan_sha256=plan_sha256,
            capsule=capsule,
            verified_capsule=capsule_authority["verified"],
            verified_evidence=capsule_authority["adoption_tokens"][
                receipt["receipt_sha256"]
            ],
            package=package,
            registry=_registry(),
            selection=selection,
            consumer_c3_authority=consumer_c3_authority_from_git(
                capsule_authority["consumer_root"],
                capsule_authority["consumer_B0"],
                capsule_authority["authority"].package,
            ),
        )


def test_adoption_evidence_rejects_fabricated_intermediate_git_boundaries(
    capsule_authority: dict,
) -> None:
    receipt, _identity, _capsule, selection, _plan = _receipt(capsule_authority)
    run_root = capsule_authority["adoption_run_roots"][receipt["receipt_sha256"]]
    forged = copy.deepcopy(receipt)
    forged["boundary_commits"]["C2"] = forged["boundary_commits"]["C1"]
    forged = seal_adoption_receipt(forged)
    with pytest.raises(UpgradeLaneError, match="direct single-parent chain"):
        verify_adoption_evidence(
            forged,
            authority=_adoption_authority(capsule_authority, run_root),
            package=capsule_authority["authority"].package,
            registry=_registry(),
            selection=selection,
        )


def test_adoption_evidence_rejects_state_boundary_chain_drift(
    capsule_authority: dict,
) -> None:
    receipt, _identity, _capsule, selection, _plan = _receipt(capsule_authority)
    run_root = capsule_authority["adoption_run_roots"][receipt["receipt_sha256"]]
    state_path = run_root / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["boundary_commits"]["C2"] = state["boundary_commits"]["C1"]
    state_path.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(UpgradeLaneError, match="stale or incomplete"):
        verify_adoption_evidence(
            receipt,
            authority=_adoption_authority(capsule_authority, run_root),
            package=capsule_authority["authority"].package,
            registry=_registry(),
            selection=selection,
        )


def test_adoption_evidence_rejects_extra_runner_state_fields(
    capsule_authority: dict,
) -> None:
    receipt, _identity, _capsule, selection, _plan = _receipt(capsule_authority)
    run_root = capsule_authority["adoption_run_roots"][receipt["receipt_sha256"]]
    state_path = run_root / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["manual_override"] = "fabricated"
    state_path.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(UpgradeLaneError, match="fields must be exact"):
        verify_adoption_evidence(
            receipt,
            authority=_adoption_authority(capsule_authority, run_root),
            package=capsule_authority["authority"].package,
            registry=_registry(),
            selection=selection,
        )


def test_adoption_evidence_rejects_nonignored_untracked_consumer_file(
    capsule_authority: dict,
) -> None:
    receipt, _identity_value, _capsule_value, selection, _plan = _receipt(
        capsule_authority
    )
    run_root = capsule_authority["adoption_run_roots"][receipt["receipt_sha256"]]
    (capsule_authority["consumer_root"] / "untracked-private-note.txt").write_text(
        "must invalidate final evidence\n", encoding="utf-8"
    )

    with pytest.raises(UpgradeLaneError, match="tracked or untracked worktree"):
        verify_adoption_evidence(
            receipt,
            authority=_adoption_authority(capsule_authority, run_root),
            package=capsule_authority["authority"].package,
            registry=_registry(),
            selection=selection,
        )


def test_shape_only_adoption_receipt_cannot_authorize_reuse(
    capsule_authority: dict,
) -> None:
    receipt, identity, capsule, selection, plan_sha256 = _receipt(capsule_authority)
    with pytest.raises(UpgradeLaneError, match="shape-only adoption receipt"):
        verify_adoption_receipt(
            receipt,
            expected_identity=identity,
            expected_plan_sha256=plan_sha256,
            capsule=capsule,
            verified_capsule=capsule_authority["verified"],
            verified_evidence=None,
            package=capsule_authority["authority"].package,
            registry=_registry(),
            selection=selection,
            consumer_c3_authority=consumer_c3_authority_from_git(
                capsule_authority["consumer_root"],
                capsule_authority["consumer_B0"],
                capsule_authority["authority"].package,
            ),
        )


def test_adoption_evidence_rejects_arbitrary_executed_output_hash(
    capsule_authority: dict,
) -> None:
    receipt, _identity_value, _capsule_value, selection, _plan = _receipt(
        capsule_authority
    )
    run_root = capsule_authority["adoption_run_roots"][receipt["receipt_sha256"]]
    forged = copy.deepcopy(receipt)
    forged["gate_results"][0]["output_sha256"] = "f" * 64
    forged = _reseal(forged)
    with pytest.raises(UpgradeLaneError, match="runner state gate result differs"):
        verify_adoption_evidence(
            forged,
            authority=_adoption_authority(capsule_authority, run_root),
            package=capsule_authority["authority"].package,
            registry=_registry(),
            selection=selection,
        )


def test_adoption_evidence_rejects_changed_real_gate_log(
    capsule_authority: dict,
) -> None:
    receipt, _identity_value, _capsule_value, selection, _plan = _receipt(
        capsule_authority
    )
    run_root = capsule_authority["adoption_run_roots"][receipt["receipt_sha256"]]
    gate_id = receipt["gate_results"][0]["id"]
    (run_root / "logs" / f"{gate_id}.log").write_text(
        "changed after execution\n", encoding="utf-8"
    )
    with pytest.raises(UpgradeLaneError, match="gate log hash differs"):
        verify_adoption_evidence(
            receipt,
            authority=_adoption_authority(capsule_authority, run_root),
            package=capsule_authority["authority"].package,
            registry=_registry(),
            selection=selection,
        )


@pytest.mark.parametrize(
    ("artifact", "mutation", "message"),
    [
        ("rollback.json", {"tree_equal": False}, "exact B0 restoration"),
        (
            "migration-report.private.json",
            {"promotion_ready": False},
            "private migration report",
        ),
    ],
)
def test_adoption_evidence_rejects_fabricated_rollback_or_report(
    artifact: str,
    mutation: dict,
    message: str,
    capsule_authority: dict,
) -> None:
    receipt, _identity_value, _capsule_value, selection, _plan = _receipt(
        capsule_authority
    )
    run_root = capsule_authority["adoption_run_roots"][receipt["receipt_sha256"]]
    path = run_root / artifact
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update(mutation)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(UpgradeLaneError, match=message):
        verify_adoption_evidence(
            receipt,
            authority=_adoption_authority(capsule_authority, run_root),
            package=capsule_authority["authority"].package,
            registry=_registry(),
            selection=selection,
        )


@pytest.mark.parametrize(
    ("field_path", "forged_value"),
    [
        (("lane",), "lane_a"),
        (("mode",), "background_certification"),
        (("selection", "impact_derivation_sha256"), "f" * 64),
        (("selection", "selected_gate_count"), 999),
        (("boundaries", "digest"), "e" * 64),
        (("boundaries", "counts", "C3"), 999),
    ],
)
def test_adoption_evidence_rejects_coherently_resealed_report_binding_tamper(
    field_path: tuple[str, ...],
    forged_value: object,
    capsule_authority: dict,
) -> None:
    receipt, _identity_value, _capsule_value, selection, _plan = _receipt(
        capsule_authority
    )
    run_root = capsule_authority["adoption_run_roots"][receipt["receipt_sha256"]]
    private_path = run_root / "migration-report.private.json"
    private_report = json.loads(private_path.read_text(encoding="utf-8"))
    target = private_report
    for part in field_path[:-1]:
        target = target[part]
    target[field_path[-1]] = forged_value
    private_raw = (json.dumps(private_report, sort_keys=True) + "\n").encode("utf-8")
    private_path.write_bytes(private_raw)

    # Keep both public files coherent with the forged private report and bind
    # the receipt to its new bytes.  Verification must still derive authority
    # from Lane B's selection and receipt boundaries, not trust self-consistent
    # attacker-controlled artifacts.
    public_report = public_migration_report_projection(private_report)
    public_raw = (json.dumps(public_report, sort_keys=True) + "\n").encode("utf-8")
    (run_root / "migration-report.public.json").write_bytes(public_raw)
    (run_root / "migration-report.json").write_bytes(public_raw)
    forged = copy.deepcopy(receipt)
    forged["report_verification"]["evidence_sha256"] = hashlib.sha256(
        private_raw
    ).hexdigest()
    forged = seal_adoption_receipt(forged)

    with pytest.raises(UpgradeLaneError, match="private migration report is stale"):
        verify_adoption_evidence(
            forged,
            authority=_adoption_authority(capsule_authority, run_root),
            package=capsule_authority["authority"].package,
            registry=_registry(),
            selection=selection,
        )


def test_public_migration_report_rejects_private_consumer_identity_sha(
    capsule_authority: dict,
) -> None:
    receipt, _identity_value, _capsule_value, selection, _plan = _receipt(
        capsule_authority
    )
    run_root = capsule_authority["adoption_run_roots"][receipt["receipt_sha256"]]
    public_path = run_root / "migration-report.public.json"
    public_report = json.loads(public_path.read_text(encoding="utf-8"))
    public_report["identity"] = receipt["identity"]
    raw = (json.dumps(public_report, sort_keys=True) + "\n").encode("utf-8")
    public_path.write_bytes(raw)
    (run_root / "migration-report.json").write_bytes(raw)
    with pytest.raises(UpgradeLaneError, match="public migration report is stale"):
        verify_adoption_evidence(
            receipt,
            authority=_adoption_authority(capsule_authority, run_root),
            package=capsule_authority["authority"].package,
            registry=_registry(),
            selection=selection,
        )


@pytest.mark.parametrize(
    "field",
    [
        "source_sha",
        "package_sha256",
        "portable_tree_sha256",
        "consumer_B0",
        "consumer_C3",
        "command_registry_sha256",
        "toolchain_sha256",
    ],
)
def test_receipt_reuse_rejects_every_divergent_identity_term(
    field: str, capsule_authority: dict
) -> None:
    receipt, identity, capsule, selection, plan_sha256 = _receipt(capsule_authority)
    changed = copy.deepcopy(receipt)
    changed["identity"][field] = (
        "d" * 40 if field in {"source_sha", "consumer_B0", "consumer_C3"} else "d" * 64
    )
    if field == "consumer_C3":
        for result in changed["gate_results"]:
            result["subject_sha"] = changed["identity"][field]
        changed["rollback_verification"]["subject_sha"] = changed["identity"][field]
        changed["report_verification"]["subject_sha"] = changed["identity"][field]
    changed = _reseal(changed)
    with pytest.raises(UpgradeLaneError, match=f"identity mismatch: {field}"):
        _verify(
            changed,
            identity,
            capsule,
            selection,
            plan_sha256,
            capsule_authority,
        )


def test_c3_changed_after_gates_invalidates_all_stale_results(
    capsule_authority: dict,
) -> None:
    receipt, identity, capsule, selection, plan_sha256 = _receipt(capsule_authority)
    changed_identity = dict(identity)
    changed_identity["consumer_C3"] = "d" * 40
    receipt["identity"] = changed_identity
    receipt = _reseal(receipt)
    with pytest.raises(UpgradeLaneError, match="gate result is stale after C3 changed"):
        _verify(
            receipt,
            changed_identity,
            capsule,
            selection,
            plan_sha256,
            capsule_authority,
        )


def test_manual_or_fabricated_gate_evidence_is_rejected(
    capsule_authority: dict,
) -> None:
    receipt, identity, capsule, selection, plan_sha256 = _receipt(capsule_authority)
    receipt["gate_results"][0]["provenance"] = "fabricated"
    receipt = _reseal(receipt)
    with pytest.raises(UpgradeLaneError, match="manual/fabricated evidence"):
        _verify(
            receipt,
            identity,
            capsule,
            selection,
            plan_sha256,
            capsule_authority,
        )


def test_resume_state_must_match_current_identity_and_plan(
    capsule_authority: dict,
) -> None:
    receipt, identity, capsule, selection, plan_sha256 = _receipt(capsule_authority)
    stale_identity = copy.deepcopy(receipt)
    stale_identity["resume"]["identity_sha256"] = "e" * 64
    stale_identity = seal_adoption_receipt(stale_identity)
    stale_identity["resume"]["identity_sha256"] = "e" * 64
    unsigned = dict(stale_identity)
    unsigned.pop("receipt_sha256")
    stale_identity["receipt_sha256"] = canonical_sha256(unsigned)
    with pytest.raises(UpgradeLaneError, match="resume state identity is stale"):
        _verify(
            stale_identity,
            identity,
            capsule,
            selection,
            plan_sha256,
            capsule_authority,
        )

    stale_plan = copy.deepcopy(receipt)
    stale_plan["resume"]["plan_sha256"] = "e" * 64
    unsigned = dict(stale_plan)
    unsigned.pop("receipt_sha256")
    stale_plan["receipt_sha256"] = canonical_sha256(unsigned)
    with pytest.raises(UpgradeLaneError, match="resume state plan is stale"):
        _verify(
            stale_plan,
            identity,
            capsule,
            selection,
            plan_sha256,
            capsule_authority,
        )


def test_gate_omission_requires_exact_capsule_or_impact_derivation(
    capsule_authority: dict,
) -> None:
    receipt, _identity_value, capsule, selection, _plan_sha256 = _receipt(
        capsule_authority
    )
    registry = _registry()
    verified = capsule_authority["verified"]
    omission = next(
        item for item in receipt["omitted_gates"] if item["reason"] == "not_affected"
    )
    omission["derivation_sha256"] = "e" * 64
    with pytest.raises(UpgradeLaneError, match="lacks exact impact derivation"):
        verify_gate_omissions(
            registry,
            selection,
            receipt["omitted_gates"],
            capsule,
            verified_capsule=verified,
        )

    upstream = next(
        item
        for item in receipt["omitted_gates"]
        if item["reason"] == "verified_upstream_capsule"
    )
    upstream["derivation_sha256"] = "e" * 64
    with pytest.raises(UpgradeLaneError, match="lacks exact capsule proof"):
        verify_gate_omissions(
            registry,
            selection,
            receipt["omitted_gates"],
            capsule,
            verified_capsule=verified,
        )


def test_never_reusable_gate_cannot_be_omitted_even_with_claimed_derivation(
    capsule_authority: dict,
) -> None:
    receipt, _identity_value, capsule, selection, _plan_sha256 = _receipt(
        capsule_authority
    )
    registry = _registry()
    forged_selection = copy.deepcopy(selection)
    forged_selection["selected_gates"].remove("audit")
    forged_selection["omitted_gates"].append("audit")
    forged_selection["omitted_gates"].sort()
    forged = copy.deepcopy(receipt["omitted_gates"])
    forged.append(
        {
            "gate_id": "audit",
            "reason": "not_affected",
            "derivation_sha256": selection["derivation_sha256"],
        }
    )
    with pytest.raises(UpgradeLaneError, match="never-reusable gate cannot be omitted"):
        verify_gate_omissions(
            registry,
            forged_selection,
            forged,
            capsule,
            verified_capsule=capsule_authority["verified"],
        )


def test_private_host_path_cannot_leak_into_receipt_output(
    capsule_authority: dict,
) -> None:
    receipt, identity, capsule, selection, plan_sha256 = _receipt(capsule_authority)
    receipt["boundaries"]["C3"][0]["path"] = "/Users/example/private/wiki.config.yaml"
    receipt = _reseal(receipt)
    with pytest.raises(UpgradeLaneError, match="host-local path"):
        _verify(
            receipt,
            identity,
            capsule,
            selection,
            plan_sha256,
            capsule_authority,
        )


@pytest.mark.parametrize(
    ("placement", "leaked", "message"),
    [
        ("value", "/tmp/wiki-viva/report.json", "host-local path"),
        ("value", "/opt/wiki-viva/runtime", "host-local path"),
        ("value", "/nix/store/synthetic-python", "host-local path"),
        ("value", "/workspace/repo/tests/test_public.py", "host-local path"),
        ("value", "/run/user/501/wiki-viva", "host-local path"),
        ("value", "/__w/wiki-viva-kit/wiki-viva-kit", "host-local path"),
        ("key", "/var/folders/private-report", "host-local path"),
        ("value", "/consumer/w/timeline", "private consumer route"),
        ("key", "/private/wiki", "private"),
        ("value", "/real/dashboard", "private consumer route"),
        ("value", "route=[/real/customer]", "private consumer route"),
        ("key", "route,{/consumer/account}", "private consumer route"),
        ("value", "[/real]", "private consumer route"),
        ("value", "route=%2Freal%2Fcustomer", "private consumer route"),
        ("key", "route=%252Fconsumer%252Faccount", "private consumer route"),
        (
            "value",
            "route=%2525252Freal%2525252Fcustomer",
            "invalid percent-encoded",
        ),
        (
            "value",
            "https://example.invalid/%72eal/customer",
            "private consumer route",
        ),
        ("value", "artifact=%2Ftmp%2Fprivate-proof.json", "host-local path"),
        (
            "value",
            "https://consumer.invalid/consumer/w/radar",
            "private consumer route",
        ),
        ("value", "api_key=not-public", "secret/private data"),
    ],
)
def test_public_projection_rejects_private_path_route_or_data_in_any_string_or_key(
    placement: str,
    leaked: str,
    message: str,
    capsule_authority: dict,
) -> None:
    receipt, _identity, _capsule_value, _selection_value, _plan = _receipt(
        capsule_authority
    )
    run_root = capsule_authority["adoption_run_roots"][receipt["receipt_sha256"]]
    private_report = json.loads(
        (run_root / "migration-report.private.json").read_text(encoding="utf-8")
    )
    if placement == "key":
        private_report["selection"][leaked] = "redacted"
    else:
        private_report["selection"]["publication_probe"] = leaked

    with pytest.raises(UpgradeLaneError, match=message):
        public_migration_report_projection(private_report)


def test_public_projection_preserves_legitimate_public_routes(
    capsule_authority: dict,
) -> None:
    receipt, _identity, _capsule_value, _selection_value, _plan = _receipt(
        capsule_authority
    )
    run_root = capsule_authority["adoption_run_roots"][receipt["receipt_sha256"]]
    private_report = json.loads(
        (run_root / "migration-report.private.json").read_text(encoding="utf-8")
    )
    private_report["selection"]["publication_probe"] = "/demo/w/radar"
    private_report["selection"]["encoded_public_probe"] = "%2Fdemo%2Fw%2Fradar"
    private_report["selection"]["encoded_docs_probe"] = "docs%2Freal%2Fcustomer.md"

    public_report = public_migration_report_projection(private_report)

    assert public_report["selection"]["publication_probe"] == "/demo/w/radar"
    assert public_report["selection"]["encoded_public_probe"] == "%2Fdemo%2Fw%2Fradar"


def test_private_data_marker_cannot_leak_into_capsule(
    capsule_authority: dict,
) -> None:
    capsule = _capsule(capsule_authority)
    capsule["command_registry"][0]["command"] = "python3 tool.py --token=secret-value"
    with pytest.raises(UpgradeLaneError, match="secret/private data"):
        seal_release_capsule(capsule, authority=capsule_authority["authority"])


def test_acceptance_budget_exact_boundary_and_fail_closed_clock() -> None:
    base = {
        "schema_version": "wiki_viva_upgrade_acceptance_budget.v1",
        "scope": "plan_to_real_canary",
        "limit_seconds": 1200,
        "enforcement": "promotion_blocking",
        "plan_started_at": "2026-07-14T00:00:00.000000Z",
        "canary_completed_at": "2026-07-14T00:20:00.000000Z",
        "elapsed_milliseconds": 1_200_000,
        "status": "met",
    }
    assert validate_acceptance_budget(base)["status"] == "met"

    exceeded = copy.deepcopy(base)
    exceeded["canary_completed_at"] = "2026-07-14T00:20:00.001000Z"
    exceeded["elapsed_milliseconds"] = 1_200_001
    exceeded["status"] = "exceeded"
    assert validate_acceptance_budget(exceeded)["status"] == "exceeded"

    contradictory = copy.deepcopy(exceeded)
    contradictory["status"] = "met"
    with pytest.raises(UpgradeLaneError, match="contradicts"):
        validate_acceptance_budget(contradictory)

    backwards = copy.deepcopy(base)
    backwards["canary_completed_at"] = "2026-07-13T23:59:59.999999Z"
    with pytest.raises(UpgradeLaneError, match="timestamps are invalid"):
        validate_acceptance_budget(backwards)

    stale_elapsed = copy.deepcopy(base)
    stale_elapsed["elapsed_milliseconds"] -= 1
    with pytest.raises(UpgradeLaneError, match="elapsed time is stale"):
        validate_acceptance_budget(stale_elapsed)

    pending_with_measurement = copy.deepcopy(base)
    pending_with_measurement["status"] = "pending"
    with pytest.raises(UpgradeLaneError, match="pending acceptance budget"):
        validate_acceptance_budget(pending_with_measurement)

    noncanonical = copy.deepcopy(base)
    noncanonical["plan_started_at"] = "2026-07-14T00:00:00Z"
    with pytest.raises(UpgradeLaneError, match="canonical UTC RFC3339"):
        validate_acceptance_budget(noncanonical)

    impossible = copy.deepcopy(base)
    impossible["plan_started_at"] = "2026-02-30T00:00:00.000000Z"
    with pytest.raises(UpgradeLaneError, match="real UTC instant"):
        validate_acceptance_budget(impossible)

    pre_epoch = copy.deepcopy(base)
    pre_epoch["plan_started_at"] = "1969-12-31T23:59:59.999999Z"
    with pytest.raises(UpgradeLaneError, match="after the Unix epoch"):
        validate_acceptance_budget(pre_epoch)

    missing = copy.deepcopy(base)
    del missing["canary_completed_at"]
    with pytest.raises(UpgradeLaneError, match="fields must be exact"):
        validate_acceptance_budget(missing)


def test_public_acceptance_budget_projection_is_typed_without_timing() -> None:
    private_budget = {
        "schema_version": "wiki_viva_upgrade_acceptance_budget.v1",
        "scope": "plan_to_real_canary",
        "limit_seconds": 1200,
        "enforcement": "promotion_blocking",
        "plan_started_at": "2026-07-14T00:00:00.000000Z",
        "canary_completed_at": "2026-07-14T00:00:01.000000Z",
        "elapsed_milliseconds": 1000,
        "status": "met",
    }
    assert public_acceptance_budget_projection(private_budget) == {
        "schema_version": "wiki_viva_upgrade_acceptance_budget_public.v1",
        "scope": "plan_to_real_canary",
        "limit_seconds": 1200,
        "enforcement": "promotion_blocking",
        "status": "met",
    }


def test_receipt_v4_budget_must_match_runner_and_reports(
    capsule_authority: dict,
) -> None:
    receipt, _identity, _capsule, selection, _plan_sha256 = _receipt(capsule_authority)
    changed = copy.deepcopy(receipt)
    changed["acceptance_budget"].update(
        {
            "plan_started_at": "2026-07-15T00:00:00.000000Z",
            "canary_completed_at": "2026-07-15T00:00:01.000000Z",
        }
    )
    changed = seal_adoption_receipt(changed)
    run_root = capsule_authority["adoption_run_roots"][receipt["receipt_sha256"]]
    with pytest.raises(UpgradeLaneError, match="runner state is stale"):
        verify_adoption_evidence(
            changed,
            authority=_adoption_authority(capsule_authority, run_root),
            package=capsule_authority["authority"].package,
            registry=_registry(),
            selection=selection,
        )


def test_receipt_v4_budget_must_match_runner_canary_completion(
    capsule_authority: dict,
) -> None:
    receipt, _identity, _capsule, selection, _plan_sha256 = _receipt(capsule_authority)
    run_root = capsule_authority["adoption_run_roots"][receipt["receipt_sha256"]]
    state_path = run_root / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    canary_id = next(
        result["id"]
        for result in receipt["gate_results"]
        if result["class"] == "canary"
    )
    state["gate_results"][canary_id]["_completed_at"] = receipt["acceptance_budget"][
        "plan_started_at"
    ]
    state_path.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(UpgradeLaneError, match="completed real canary"):
        verify_adoption_evidence(
            receipt,
            authority=_adoption_authority(capsule_authority, run_root),
            package=capsule_authority["authority"].package,
            registry=_registry(),
            selection=selection,
        )


def test_legacy_adoption_receipt_v1_is_rejected(capsule_authority: dict) -> None:
    receipt, _identity, _capsule, selection, _plan_sha256 = _receipt(capsule_authority)
    legacy = copy.deepcopy(receipt)
    legacy["schema_version"] = "wiki_viva_upgrade_adoption_receipt.v1"
    unsigned = dict(legacy)
    unsigned.pop("receipt_sha256")
    legacy["receipt_sha256"] = canonical_sha256(unsigned)
    run_root = capsule_authority["adoption_run_roots"][receipt["receipt_sha256"]]
    with pytest.raises(UpgradeLaneError, match="unsupported adoption receipt"):
        verify_adoption_evidence(
            legacy,
            authority=_adoption_authority(capsule_authority, run_root),
            package=capsule_authority["authority"].package,
            registry=_registry(),
            selection=selection,
        )


def test_budget_blocked_receipt_has_integrity_proof_but_is_never_reusable(
    capsule_authority: dict,
) -> None:
    receipt, identity, capsule, selection, plan_sha256 = _receipt(capsule_authority)
    blocked, run_root, completion_digest = _blocked_run_receipt(
        capsule_authority, receipt
    )
    verified_evidence = verify_adoption_evidence(
        blocked,
        authority=AdoptionEvidenceAuthority(
            consumer_root=capsule_authority["consumer_root"],
            run_root=run_root,
            trusted_canary_completion_anchor_sha256=completion_digest,
        ),
        package=capsule_authority["authority"].package,
        registry=_registry(),
        selection=selection,
    )
    with pytest.raises(UpgradeLaneError, match="only passed"):
        verify_adoption_receipt(
            blocked,
            expected_identity=identity,
            expected_plan_sha256=plan_sha256,
            capsule=capsule,
            verified_capsule=capsule_authority["verified"],
            verified_evidence=verified_evidence,
            package=capsule_authority["authority"].package,
            registry=_registry(),
            selection=selection,
            consumer_c3_authority=consumer_c3_authority_from_git(
                capsule_authority["consumer_root"],
                capsule_authority["consumer_B0"],
                capsule_authority["authority"].package,
            ),
        )


def test_external_canary_anchor_rejects_coherently_resealed_budget_promotion(
    capsule_authority: dict,
) -> None:
    receipt, _identity, _capsule, selection, _plan_sha256 = _receipt(capsule_authority)
    forged, run_root, trusted_blocked_digest = _blocked_run_receipt(
        capsule_authority, receipt
    )
    met_budget = copy.deepcopy(forged["acceptance_budget"])
    met_budget.update(
        {
            "canary_completed_at": "2026-07-14T00:00:10.000000Z",
            "elapsed_milliseconds": 10_000,
            "status": "met",
        }
    )
    forged["status"] = "passed"
    forged["acceptance_budget"] = met_budget

    state_path = run_root / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["acceptance_budget"] = met_budget
    canary = state["gate_results"]["real_canary"]
    canary["_completed_at"] = met_budget["canary_completed_at"]
    state_path.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")

    canary_projection = [
        {
            "id": "real_canary",
            "class": canary["class"],
            "status": canary["status"],
            "subject_sha": canary["subject_sha"],
            "command_sha256": canary["command_sha256"],
            "output_sha256": canary["output_sha256"],
            "completed_at": canary["_completed_at"],
            "evidence_sha256": canonical_sha256(canary["_evidence"]),
        }
    ]
    anchor_path = run_root / "canary-completion-anchor.json"
    anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
    anchor["canary_completed_at"] = met_budget["canary_completed_at"]
    anchor["canary_results_sha256"] = canonical_sha256(canary_projection)
    anchor.pop("anchor_sha256")
    anchor["anchor_sha256"] = canonical_sha256(anchor)
    anchor_raw = (json.dumps(anchor, sort_keys=True) + "\n").encode("utf-8")
    anchor_path.write_bytes(anchor_raw)
    forged["canary_completion_anchor"] = {
        "schema_version": "wiki_viva_upgrade_canary_completion_anchor_reference.v1",
        "anchor_sha256": anchor["anchor_sha256"],
        "file_sha256": hashlib.sha256(anchor_raw).hexdigest(),
    }

    private_path = run_root / "migration-report.private.json"
    private_report = json.loads(private_path.read_text(encoding="utf-8"))
    private_report["acceptance_budget"] = met_budget
    private_report["promotion_ready"] = True
    private_raw = (json.dumps(private_report, sort_keys=True) + "\n").encode("utf-8")
    private_path.write_bytes(private_raw)
    forged["report_verification"]["evidence_sha256"] = hashlib.sha256(
        private_raw
    ).hexdigest()
    public_raw = (
        json.dumps(public_migration_report_projection(private_report), sort_keys=True)
        + "\n"
    ).encode("utf-8")
    (run_root / "migration-report.public.json").write_bytes(public_raw)
    (run_root / "migration-report.json").write_bytes(public_raw)
    forged = seal_adoption_receipt(forged)

    with pytest.raises(UpgradeLaneError, match="out-of-band authority"):
        verify_adoption_evidence(
            forged,
            authority=_adoption_authority(
                capsule_authority,
                run_root,
                trusted_digest=trusted_blocked_digest,
            ),
            package=capsule_authority["authority"].package,
            registry=_registry(),
            selection=selection,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"provenance": "manual"}, "manual/fabricated evidence"),
        ({"status": "failed", "exit_code": 1}, "gate result did not pass"),
        ({"exit_code": False}, "gate result did not pass"),
    ],
)
def test_budget_blocked_receipt_rejects_nonexecuted_or_failed_gate_integrity(
    mutation: dict,
    message: str,
    capsule_authority: dict,
) -> None:
    receipt, _identity, _capsule, selection, _plan_sha256 = _receipt(capsule_authority)
    blocked, run_root, completion_digest = _blocked_run_receipt(
        capsule_authority, receipt
    )
    gate_id = blocked["gate_results"][0]["id"]
    blocked["gate_results"][0].update(mutation)
    blocked = seal_adoption_receipt(blocked)
    state_path = run_root / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["gate_results"][gate_id].update(mutation)
    state_path.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(UpgradeLaneError, match=message):
        verify_adoption_evidence(
            blocked,
            authority=AdoptionEvidenceAuthority(
                consumer_root=capsule_authority["consumer_root"],
                run_root=run_root,
                trusted_canary_completion_anchor_sha256=completion_digest,
            ),
            package=capsule_authority["authority"].package,
            registry=_registry(),
            selection=selection,
        )


def test_budget_blocked_public_report_rejects_forged_promotion_ready(
    capsule_authority: dict,
) -> None:
    receipt, _identity, _capsule, selection, _plan_sha256 = _receipt(capsule_authority)
    blocked, run_root, completion_digest = _blocked_run_receipt(
        capsule_authority, receipt
    )
    public_path = run_root / "migration-report.public.json"
    public_report = json.loads(public_path.read_text(encoding="utf-8"))
    public_report["promotion_ready"] = True
    public_raw = (json.dumps(public_report, sort_keys=True) + "\n").encode("utf-8")
    public_path.write_bytes(public_raw)
    (run_root / "migration-report.json").write_bytes(public_raw)
    with pytest.raises(UpgradeLaneError, match="public migration report is stale"):
        verify_adoption_evidence(
            blocked,
            authority=AdoptionEvidenceAuthority(
                consumer_root=capsule_authority["consumer_root"],
                run_root=run_root,
                trusted_canary_completion_anchor_sha256=completion_digest,
            ),
            package=capsule_authority["authority"].package,
            registry=_registry(),
            selection=selection,
        )


def test_public_report_rejects_private_acceptance_timing_fields(
    capsule_authority: dict,
) -> None:
    receipt, _identity, _capsule, selection, _plan_sha256 = _receipt(capsule_authority)
    run_root = capsule_authority["adoption_run_roots"][receipt["receipt_sha256"]]
    public_path = run_root / "migration-report.public.json"
    public_report = json.loads(public_path.read_text(encoding="utf-8"))
    public_report["acceptance_budget"]["elapsed_milliseconds"] = 1000
    public_raw = (json.dumps(public_report, sort_keys=True) + "\n").encode("utf-8")
    public_path.write_bytes(public_raw)
    (run_root / "migration-report.json").write_bytes(public_raw)
    with pytest.raises(UpgradeLaneError, match="public migration report is stale"):
        verify_adoption_evidence(
            receipt,
            authority=_adoption_authority(capsule_authority, run_root),
            package=capsule_authority["authority"].package,
            registry=_registry(),
            selection=selection,
        )


@pytest.mark.parametrize(
    ("boundary", "entry", "message"),
    [
        (
            "C1",
            {
                "path": "wiki.config.yaml",
                "operation": "upsert",
                "mode": "100644",
                "sha256": "7" * 64,
                "source_mode": "100644",
                "source_sha256": "7" * 64,
            },
            "mixed into C1",
        ),
        (
            "C1",
            {
                "path": "memories/private-domain.md",
                "operation": "upsert",
                "mode": "100644",
                "sha256": "7" * 64,
                "source_mode": "100644",
                "source_sha256": "7" * 64,
            },
            "domain content is forbidden",
        ),
        (
            "C2",
            {
                "path": "memories/finance/ledger.md",
                "operation": "upsert",
                "mode": "100644",
                "sha256": "8" * 64,
                "generator_sha256": _digest("python3 scripts/wiki_build_demo.py"),
            },
            "domain content is forbidden",
        ),
        (
            "C3",
            {
                "path": "wiki_core/paths.py",
                "operation": "upsert",
                "mode": "100644",
                "sha256": "a" * 64,
            },
            "mixed into C3",
        ),
        (
            "C3",
            {
                "path": ".skills/wiki-viva/SKILL.md",
                "operation": "upsert",
                "mode": "100644",
                "sha256": "a" * 64,
            },
            "portable path mixed into C3",
        ),
        (
            "C3",
            {
                "path": "memories/private-domain.md",
                "operation": "upsert",
                "mode": "100644",
                "sha256": "a" * 64,
            },
            "domain content is forbidden",
        ),
    ],
)
def test_c1_c2_c3_reject_domain_or_ownership_mixing(
    boundary: str, entry: dict, message: str, capsule_authority: dict
) -> None:
    receipt, _identity_value, _capsule_value, _selection_value, _plan = _receipt(
        capsule_authority
    )
    boundaries = copy.deepcopy(receipt["boundaries"])
    boundaries[boundary] = [entry]
    with pytest.raises(UpgradeLaneError, match=message):
        validate_boundary_ownership(
            boundaries,
            _registry(),
            package=capsule_authority["authority"].package,
            consumer_c3_authority=_consumer_c3_authority(capsule_authority),
        )


def test_agent_routing_and_local_skills_are_consumer_owned_c3(
    capsule_authority: dict,
) -> None:
    receipt, _identity_value, _capsule_value, _selection_value, _plan = _receipt(
        capsule_authority
    )
    boundaries = copy.deepcopy(receipt["boundaries"])
    boundaries["C3"] = [
        {
            "path": ".skills/local-operator/SKILL.md",
            "operation": "upsert",
            "mode": "100644",
            "sha256": "b" * 64,
        },
        {
            "path": ".skills/README.md",
            "operation": "upsert",
            "mode": "100644",
            "sha256": "d" * 64,
        },
        {
            "path": "AGENTS.md",
            "operation": "upsert",
            "mode": "100644",
            "sha256": "c" * 64,
        },
    ]
    validate_boundary_ownership(
        boundaries,
        _registry(),
        package=capsule_authority["authority"].package,
        consumer_c3_authority=_consumer_c3_authority(capsule_authority),
    )


def test_toolkit_wiki_skill_remains_byte_equal_c1(capsule_authority: dict) -> None:
    receipt, _identity_value, _capsule_value, _selection_value, _plan = _receipt(
        capsule_authority
    )
    boundaries = copy.deepcopy(receipt["boundaries"])
    boundaries["C1"] = [
        {
            "path": ".skills/wiki-viva/SKILL.md",
            "operation": "upsert",
            "mode": "100644",
            "sha256": "d" * 64,
            "source_mode": "100644",
            "source_sha256": "d" * 64,
        }
    ]
    validate_boundary_ownership(
        boundaries,
        _registry(),
        package=capsule_authority["authority"].package,
        consumer_c3_authority=_consumer_c3_authority(capsule_authority),
    )


def test_c1_requires_byte_and_mode_equality_with_lane_a(
    capsule_authority: dict,
) -> None:
    receipt, _identity_value, _capsule_value, _selection_value, _plan = _receipt(
        capsule_authority
    )
    boundaries = copy.deepcopy(receipt["boundaries"])
    boundaries["C1"][0]["source_sha256"] = "f" * 64
    with pytest.raises(UpgradeLaneError, match="not byte-and-mode-equal"):
        validate_boundary_ownership(
            boundaries,
            _registry(),
            package=capsule_authority["authority"].package,
            consumer_c3_authority=_consumer_c3_authority(capsule_authority),
        )


def test_c1_rejects_registry_package_allowlist_drift(
    capsule_authority: dict,
) -> None:
    receipt, _identity_value, _capsule_value, _selection_value, _plan = _receipt(
        capsule_authority
    )
    package = copy.deepcopy(capsule_authority["authority"].package)
    package["portable_import"]["allow"].remove("wiki_core/**")
    with pytest.raises(UpgradeLaneError, match="differs from package portable"):
        validate_boundary_ownership(
            receipt["boundaries"],
            _registry(),
            package=package,
            consumer_c3_authority=_consumer_c3_authority(capsule_authority, package),
        )


def test_c1_projection_requires_exact_upserts_and_stale_deletions() -> None:
    package = {
        "portable_import": {
            "allow": ["wiki_core/**"],
            "block": ["memories/**"],
        }
    }
    source = {"wiki_core/config.py": {"mode": "100644", "sha256": "1" * 64}}
    before = {
        "wiki_core/config.py": {"mode": "100644", "sha256": "2" * 64},
        "wiki_core/stale.py": {"mode": "100755", "sha256": "3" * 64},
        "wiki.config.yaml": {"mode": "100644", "sha256": "4" * 64},
    }
    after = {
        "wiki_core/config.py": {"mode": "100644", "sha256": "1" * 64},
        "wiki.config.yaml": {"mode": "100644", "sha256": "4" * 64},
    }
    entries = [
        {
            "path": "wiki_core/config.py",
            "operation": "upsert",
            "mode": "100644",
            "sha256": "1" * 64,
            "source_mode": "100644",
            "source_sha256": "1" * 64,
        },
        {
            "path": "wiki_core/stale.py",
            "operation": "delete",
            "before_mode": "100755",
            "before_sha256": "3" * 64,
        },
    ]
    validate_c1_projection(
        entries,
        package=package,
        source_entries=source,
        before_entries=before,
        after_entries=after,
    )
    with pytest.raises(UpgradeLaneError, match="upserts and deletions"):
        validate_c1_projection(
            entries[:-1],
            package=package,
            source_entries=source,
            before_entries=before,
            after_entries=after,
        )


def test_c1_projection_supports_mode_only_portable_updates() -> None:
    package = {
        "portable_import": {
            "allow": ["wiki_core/**"],
            "block": ["memories/**"],
        }
    }
    digest = "1" * 64
    source = {"wiki_core/config.py": {"mode": "100755", "sha256": digest}}
    before = {"wiki_core/config.py": {"mode": "100644", "sha256": digest}}
    after = {"wiki_core/config.py": {"mode": "100755", "sha256": digest}}
    entry = {
        "path": "wiki_core/config.py",
        "operation": "upsert",
        "mode": "100755",
        "sha256": digest,
        "source_mode": "100755",
        "source_sha256": digest,
    }

    validate_c1_projection(
        [entry],
        package=package,
        source_entries=source,
        before_entries=before,
        after_entries=after,
    )
    forged = {**entry, "mode": "100644"}
    with pytest.raises(UpgradeLaneError, match="upserts and deletions"):
        validate_c1_projection(
            [forged],
            package=package,
            source_entries=source,
            before_entries=before,
            after_entries=after,
        )


def test_git_boundary_receipt_binds_mode_only_change_and_rejects_forged_mode(
    tmp_path: Path,
) -> None:
    consumer = tmp_path / "mode-consumer"
    consumer.mkdir()
    _git(consumer, "init", "-q", "-b", "main")
    _git(consumer, "config", "user.name", "Synthetic Consumer")
    _git(consumer, "config", "user.email", "consumer@example.invalid")
    _git(consumer, "config", "core.filemode", "true")

    config = consumer / "wiki.config.yaml"
    config.write_text("repo_id: synthetic\n", encoding="utf-8")
    config.chmod(0o644)
    _git(consumer, "add", ".")
    _git(consumer, "commit", "-q", "-m", "B0")
    b0 = _git(consumer, "rev-parse", "HEAD")

    portable = consumer / "wiki_core/config.py"
    portable.parent.mkdir()
    portable.write_text("PUBLIC = True\n", encoding="utf-8")
    _git(consumer, "add", ".")
    _git(consumer, "commit", "-q", "-m", "C1")
    c1 = _git(consumer, "rev-parse", "HEAD")

    generated = consumer / "apps/wiki-cockpit/public/sample-snapshot/snapshot.json"
    generated.parent.mkdir(parents=True)
    generated.write_text("{}\n", encoding="utf-8")
    _git(consumer, "add", ".")
    _git(consumer, "commit", "-q", "-m", "C2")
    c2 = _git(consumer, "rev-parse", "HEAD")

    config.chmod(0o755)
    _git(consumer, "add", ".")
    _git(consumer, "commit", "-q", "-m", "C3 mode only")
    c3 = _git(consumer, "rev-parse", "HEAD")
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    receipt = {
        "identity": {
            "source_sha": "1" * 40,
            "package_sha256": "2" * 64,
            "portable_tree_sha256": "3" * 64,
            "consumer_B0": b0,
            "consumer_C3": c3,
            "command_registry_sha256": "4" * 64,
            "toolchain_sha256": "5" * 64,
        },
        "boundary_commits": {"B0": b0, "C1": c1, "C2": c2, "C3": c3},
        "boundaries": {
            "C1": [
                {
                    "path": "wiki_core/config.py",
                    "operation": "upsert",
                    "mode": "100644",
                    "sha256": digest(portable),
                    "source_mode": "100644",
                    "source_sha256": digest(portable),
                }
            ],
            "C2": [
                {
                    "path": "apps/wiki-cockpit/public/sample-snapshot/snapshot.json",
                    "operation": "upsert",
                    "mode": "100644",
                    "sha256": digest(generated),
                    "generator_sha256": "6" * 64,
                }
            ],
            "C3": [
                {
                    "path": "wiki.config.yaml",
                    "operation": "upsert",
                    "mode": "100755",
                    "sha256": digest(config),
                }
            ],
        },
    }

    _verify_git_boundary_chain(consumer, receipt)
    forged = copy.deepcopy(receipt)
    forged["boundaries"]["C3"][0]["mode"] = "100644"
    with pytest.raises(UpgradeLaneError, match="mode/blob"):
        _verify_git_boundary_chain(consumer, forged)


def test_git_boundary_receipt_rejects_symlink_entry(tmp_path: Path) -> None:
    consumer = tmp_path / "symlink-consumer"
    consumer.mkdir()
    _git(consumer, "init", "-q", "-b", "main")
    _git(consumer, "config", "user.name", "Synthetic Consumer")
    _git(consumer, "config", "user.email", "consumer@example.invalid")
    (consumer / "baseline.txt").write_text("B0\n", encoding="utf-8")
    _git(consumer, "add", ".")
    _git(consumer, "commit", "-q", "-m", "B0")
    b0 = _git(consumer, "rev-parse", "HEAD")
    (consumer / "c1.txt").write_text("C1\n", encoding="utf-8")
    _git(consumer, "add", ".")
    _git(consumer, "commit", "-q", "-m", "C1")
    c1 = _git(consumer, "rev-parse", "HEAD")
    (consumer / "c2.txt").write_text("C2\n", encoding="utf-8")
    _git(consumer, "add", ".")
    _git(consumer, "commit", "-q", "-m", "C2")
    c2 = _git(consumer, "rev-parse", "HEAD")
    (consumer / "wiki.config.yaml").symlink_to("baseline.txt")
    _git(consumer, "add", ".")
    _git(consumer, "commit", "-q", "-m", "C3 symlink")
    c3 = _git(consumer, "rev-parse", "HEAD")
    digest = lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest()
    receipt = {
        "identity": {
            "source_sha": "1" * 40,
            "package_sha256": "2" * 64,
            "portable_tree_sha256": "3" * 64,
            "consumer_B0": b0,
            "consumer_C3": c3,
            "command_registry_sha256": "4" * 64,
            "toolchain_sha256": "5" * 64,
        },
        "boundary_commits": {"B0": b0, "C1": c1, "C2": c2, "C3": c3},
        "boundaries": {
            "C1": [
                {
                    "path": "c1.txt",
                    "operation": "upsert",
                    "mode": "100644",
                    "sha256": digest("C1\n"),
                    "source_mode": "100644",
                    "source_sha256": digest("C1\n"),
                }
            ],
            "C2": [
                {
                    "path": "c2.txt",
                    "operation": "upsert",
                    "mode": "100644",
                    "sha256": digest("C2\n"),
                    "generator_sha256": "6" * 64,
                }
            ],
            "C3": [
                {
                    "path": "wiki.config.yaml",
                    "operation": "upsert",
                    "mode": "100644",
                    "sha256": digest("baseline.txt"),
                }
            ],
        },
    }

    with pytest.raises(UpgradeLaneError, match="regular Git blob"):
        _verify_git_boundary_chain(consumer, receipt)


def test_c2_and_c3_deletions_have_explicit_before_and_generator_proof(
    capsule_authority: dict,
) -> None:
    receipt, _identity_value, _capsule_value, _selection_value, _plan = _receipt(
        capsule_authority
    )
    boundaries = copy.deepcopy(receipt["boundaries"])
    boundaries["C2"] = [
        {
            "path": "apps/wiki-cockpit/public/sample-snapshot/stale.json",
            "operation": "delete",
            "before_mode": "100644",
            "before_sha256": "8" * 64,
            "generator_sha256": _digest("python3 scripts/wiki_build_demo.py"),
        }
    ]
    boundaries["C3"] = [
        {
            "path": "wiki.templates.local.yaml",
            "operation": "delete",
            "before_mode": "100644",
            "before_sha256": "a" * 64,
        }
    ]
    validate_boundary_ownership(
        boundaries,
        _registry(),
        package=capsule_authority["authority"].package,
        consumer_c3_authority=_consumer_c3_authority(capsule_authority),
    )
    wrong_generator = copy.deepcopy(boundaries)
    wrong_generator["C2"][0]["generator_sha256"] = "f" * 64
    with pytest.raises(UpgradeLaneError, match="differs from package command"):
        validate_boundary_ownership(
            wrong_generator,
            _registry(),
            package=capsule_authority["authority"].package,
            consumer_c3_authority=_consumer_c3_authority(capsule_authority),
        )
    del boundaries["C2"][0]["before_sha256"]
    with pytest.raises(UpgradeLaneError, match="fields must be exact"):
        validate_boundary_ownership(
            boundaries,
            _registry(),
            package=capsule_authority["authority"].package,
            consumer_c3_authority=_consumer_c3_authority(capsule_authority),
        )


def test_receipt_rejects_missing_selected_gate_and_unverified_rollback(
    capsule_authority: dict,
) -> None:
    receipt, identity, capsule, selection, plan_sha256 = _receipt(capsule_authority)
    missing = copy.deepcopy(receipt)
    missing["gate_results"].pop()
    missing = _reseal(missing)
    with pytest.raises(UpgradeLaneError, match="exactly cover selected gates"):
        _verify(
            missing,
            identity,
            capsule,
            selection,
            plan_sha256,
            capsule_authority,
        )

    rollback = copy.deepcopy(receipt)
    rollback["rollback_verification"]["status"] = "described"
    rollback = _reseal(rollback)
    with pytest.raises(UpgradeLaneError, match="rollback_verification is not verified"):
        _verify(
            rollback,
            identity,
            capsule,
            selection,
            plan_sha256,
            capsule_authority,
        )
