from __future__ import annotations

import ast
import copy
import hashlib
import io
import json
import os
import re
import shlex
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from wiki_core.detectors import scan_text
from wiki_core.upgrade import (
    CONSUMER_INVENTORY_SCHEMA_VERSION,
    GATE_EVIDENCE_SCHEMA_VERSION,
    MIGRATION_EVIDENCE_SCHEMA_VERSION,
    MIGRATION_VALIDATOR_VERSION,
    TWO_LANE_UPGRADE_PACKAGE_SCHEMA_VERSION,
    UPGRADE_PACKAGE_SCHEMA_VERSION,
    _git_blob_payloads,
    build_preflight_report,
    canonical_json,
    compare_portable_files,
    compile_migration_report,
    deterministic_id,
    migration_evidence_template,
    package_is_pinned,
    portable_path_status,
    render_migration_report_markdown,
    upgrade_package_sha256,
    validate_consumer_inventory,
    validate_migration_evidence,
    validate_upgrade_package,
)


ROOT = Path(__file__).resolve().parents[1]


def test_wiki_core_has_only_the_declared_git_subject_scripts_boundary() -> None:
    """Keep repository operations behind the one reviewed core facade."""

    allowed = {
        ("wiki_core/release_receipt.py", "scripts._git_subject"),
    }
    violations: list[tuple[str, int, str]] = []
    for path in sorted((ROOT / "wiki_core").rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            for module in modules:
                if module == "scripts" or module.startswith("scripts."):
                    if (relative, module) not in allowed:
                        violations.append((relative, node.lineno, module))

    assert violations == []


def sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def package(*, pinned: bool = True, source_sha: str | None = None) -> dict:
    return {
        "schema_version": UPGRADE_PACKAGE_SCHEMA_VERSION,
        "release": {
            "id": "wiki-viva-v8-rc1",
            "status": "candidate",
            "source_sha": (source_sha or sha("public-kit"))
            if pinned
            else "REQUIRED_AT_RELEASE",
            "plan": "docs/references/proposals/v8.md",
        },
        "contract_versions": {
            "route": "wiki_world_route.v8",
            "snapshot": "wiki_web_snapshot.v2",
            "snapshot_envelope": "wiki_web_snapshot.v2",
            "blocks": "wiki_templates.v2",
            "visual_grammar": "wiki_visual_grammar.v8",
            "semantic_visual_tokens": "wiki_semantic_visual_tokens.v1",
            "appearance": "wiki_cockpit_appearance.v1",
            "runtime": "wiki_world_runtime.v8",
            "source_lifecycle": "wiki_source_lifecycle.v2",
            "freshness": "wiki_web_freshness.v1",
            "server": "wiki_web_server.v6",
            "activity_timeline": "activity_timeline.v1",
            "temporal_event": "wiki_temporal_event.v1",
            "temporal_graph": "wiki_temporal_graph.v1",
            "experience_pack": "wiki_experience_pack.v1",
            "experience_pack_registry": "wiki_experience_pack_registry.v1",
            "experience_pack_lock": "wiki_experience_pack_lock.v1",
            "experience_pack_composition": "wiki_experience_pack_composition.v1",
            "asset_manifest": "wiki_cockpit_asset_manifest.v1",
            "downstream_adapter_manifest": "wiki_downstream_adapter_manifest.v1",
        },
        "portable_import": {
            "allow": ["wiki_core/**", "scripts/wiki_*.py", "tests/**"],
            "block": [
                "memories/**",
                "wiki.config.yaml",
                "apps/wiki-cockpit/public/wiki-cockpit.config.json",
                "data/derived/**",
                "wiki.adapter-manifest.json",
                ".env*",
            ],
        },
        "preflight": {
            "branch_prefix": "wiki/",
            "required_gates": ["toolkit_drift", "audit", "diff_check"],
        },
        "migration": {
            "commit_boundaries": [
                "faithful_public_import",
                "regenerated_artifacts",
                "downstream_adaptations",
            ],
            "generated_artifact_patterns": ["tests/generated/**"],
            "required_gates": ["audit", "bundle", "diff_check"],
            "gate_commands": {
                gate_id: f"python3 scripts/wiki_{gate_id}.py --check"
                for gate_id in ("audit", "bundle", "diff_check")
            },
            "visual_profiles": ["desktop", "mobile", "fallback"],
        },
        "compatibility": [
            {
                "surface": "legacy_routes",
                "v8_behavior": "normalize",
                "warning_becomes_error": "v9-rc",
                "removal_target": "v9",
            }
        ],
    }


def consumer(*, privacy: str = "public_safe") -> dict:
    return {
        "id": "consumer-one",
        "repository": {
            "name": "consumer",
            "path": ".",
            "remote": "local",
            "owner": "test",
        },
        "consumer_type": "public_example",
        "current_kit_version": "v7",
        "current_layout": {
            "memory_root": "memories",
            "references_root": "docs/references",
        },
        "current_runtime": "compat",
        "local_operator": "localhost_operator",
        "local_templates": {"registry": "wiki.templates.yaml"},
        "privacy_risk": privacy,
        "evidence_redaction_required": privacy != "public_safe",
        "drift_status": {"state": "clean"},
        "upgrade_wave": "wave_1",
    }


def init_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "fixture@example.invalid"], cwd=root, check=True
    )
    subprocess.run(["git", "config", "user.name", "Fixture"], cwd=root, check=True)


def commit_all(root: Path, message: str = "fixture") -> str:
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", message], cwd=root, check=True)
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()


def repo_head(root: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()


def png_bytes(width: int = 16, height: int = 12, tone: int = 0) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", checksum)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    pixel = bytes([tone % 256, tone % 256, tone % 256])
    rows = b"".join(b"\x00" + (pixel * width) for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows, 9))
        + chunk(b"IEND", b"")
    )


def bind_migration_screenshots(root: Path, evidence: dict) -> None:
    final_head = evidence["evidence_context"]["captured_consumer_head"]
    for index, item in enumerate(evidence["visual_qa_evidence"], start=1):
        width, height = (int(value) for value in item["viewport"].split("x"))
        raw = png_bytes(width, height, tone=index)
        path = root / item["screenshot_ref"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        item.update(
            {
                "screenshot_sha256": hashlib.sha256(raw).hexdigest(),
                "screenshot_bytes": len(raw),
                "screenshot_dimensions": {
                    "width": width,
                    "height": height,
                },
                "captured_consumer_head": final_head,
            }
        )


def bind_migration_preflight(
    root: Path,
    evidence: dict,
    pkg: dict,
    report: dict,
) -> None:
    payload = {key: value for key, value in report.items() if key != "report_id"}
    expected_id = deterministic_id("preflight", payload)
    assert report["report_id"] == expected_id
    report_sha256 = hashlib.sha256(
        canonical_json(payload).encode("utf-8")
    ).hexdigest()
    report_ref = "output/wiki-upgrade/preflight-report.json"
    path = root / report_ref
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    before = evidence["consumer_before"]
    before["memory_root"] = report["layout"]["memory_root"]
    before["references_root"] = report["layout"]["references_root"]
    before["preflight"] = {
        "status": "ready",
        "report_id": expected_id,
        "report_sha256": report_sha256,
        "report_ref": report_ref,
        "package_sha256": upgrade_package_sha256(pkg),
        "consumer_head": before["head_sha"],
    }


def bind_gate_receipts(root: Path, evidence: dict) -> None:
    receipt_ref = "output/wiki-upgrade/gate-receipts.json"
    receipt = {
        "schema_version": "wiki_viva_migration_gate_receipts.v1",
        "captured_consumer_head": evidence["evidence_context"][
            "captured_consumer_head"
        ],
        "gates": [
            {
                "id": gate["id"],
                "command": gate["command"],
                "exit_code": 0,
                "output_sha256": hashlib.sha256(
                    f"gate-output-{gate['id']}".encode("utf-8")
                ).hexdigest(),
            }
            for gate in evidence["gates"]
        ],
    }
    path = root / receipt_ref
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    evidence["gates_receipt_ref"] = receipt_ref


def make_matching_repos(tmp_path: Path) -> tuple[Path, Path, str]:
    kit = tmp_path / "kit"
    target = tmp_path / "consumer"
    for root in (kit, target):
        (root / "wiki_core").mkdir(parents=True)
        (root / "wiki_core/core.py").write_text("VALUE = 1\n", encoding="utf-8")
    init_repo(kit)
    commit_all(kit, "public payload")
    (target / "data/derived/wiki/web-snapshot").mkdir(parents=True)
    (target / "data/derived/wiki/web-snapshot/manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "wiki_web_snapshot.v2",
                "snapshot_id": "fixture",
                "bundle_hash": "abc",
            }
        ),
        encoding="utf-8",
    )
    (target / "wiki.config.yaml").write_text(
        "repo_id: fixture\nlanguage: en\ncontexts: [example]\n",
        encoding="utf-8",
    )
    (target / ".gitignore").write_text("output/\n", encoding="utf-8")
    init_repo(target)
    head = commit_all(target)
    subprocess.run(
        ["git", "checkout", "-qb", "wiki/upgrade-v8"], cwd=target, check=True
    )
    return kit, target, head


def gate_evidence(head: str) -> dict:
    return {
        "schema_version": GATE_EVIDENCE_SCHEMA_VERSION,
        "consumer_head": head,
        "gates": [
            {
                "id": "toolkit_drift",
                "command": "python3 scripts/wiki_toolkit_drift.py --check",
                "status": "pass",
            },
            {
                "id": "audit",
                "command": "python3 scripts/wiki_audit.py --check",
                "status": "pass",
            },
            {"id": "diff_check", "command": "git diff --check", "status": "pass"},
        ],
    }


def migration_evidence(pkg: dict) -> dict:
    before_head = sha("consumer-before")
    final_head = sha("adaptation")
    return {
        "schema_version": MIGRATION_EVIDENCE_SCHEMA_VERSION,
        "evidence_context": {
            "package_sha256": upgrade_package_sha256(pkg),
            "validator_version": MIGRATION_VALIDATOR_VERSION,
            "captured_consumer_head": final_head,
        },
        "source": {
            "release": pkg["release"]["id"],
            "sha": pkg["release"]["source_sha"],
            "plan": pkg["release"]["plan"],
        },
        "consumer_before": {
            "repository": "public-fixture-consumer",
            "branch": "wiki/upgrade-v8",
            "head_sha": before_head,
            "kit_version": "v7",
            "gate_status": "pass",
            "memory_root": "memories",
            "references_root": "docs/references",
            "preflight": {
                "status": "ready",
                "report_id": f"preflight:{sha('preflight-id')[:20]}",
                "report_sha256": sha("preflight-report"),
                "report_ref": "output/wiki-upgrade/preflight-report.json",
                "package_sha256": upgrade_package_sha256(pkg),
                "consumer_head": before_head,
            },
        },
        "consumer_after": {
            "branch": "wiki/upgrade-v8",
            "import_commit_sha": sha("import"),
            "artifact_commit_sha": sha("artifact"),
            "adaptation_commit_sha": sha("adaptation"),
        },
        "omitted_boundaries": [],
        "files_imported": ["scripts/wiki_upgrade_report.py", "wiki_core/core.py"],
        "generated_artifacts": ["tests/generated/state.json"],
        "downstream_adaptations": ["wiki.config.yaml"],
        "local_overrides_kept": ["wiki.config.yaml", "memories/"],
        "warnings": [
            {
                "code": "legacy_route",
                "message": "normalized in compat",
                "owner": "consumer-maintainer",
                "removal_window": "v9 stable",
            }
        ],
        "fixtures_added": ["tests/fixtures/core-bug.yaml"],
        "gates": [
            {
                "id": gate_id,
                "command": f"python3 scripts/wiki_{gate_id}.py --check",
                "status": "pass",
                "exit_code": 0,
                "captured_consumer_head": final_head,
            }
            for gate_id in pkg["migration"]["required_gates"]
        ],
        "visual_qa_evidence": [
            {
                "profile": profile,
                "route_ref": "public-fixture:root",
                "center_ref": "public-fixture:root",
                "viewport": "390x844" if profile == "mobile" else "1440x1000",
                "browser": "webkit" if profile == "mobile" else "chromium",
                "screenshot_ref": f"output/wiki-upgrade/qa/{profile}.png",
                "screenshot_sha256": sha(f"screenshot-{profile}"),
                "screenshot_bytes": 1,
                "screenshot_dimensions": (
                    {"width": 390, "height": 844}
                    if profile == "mobile"
                    else {"width": 1440, "height": 1000}
                ),
                "captured_consumer_head": final_head,
                "console_status": "clean",
                "network_status": "clean",
                "sample_fallback": False,
            }
            for profile in pkg["migration"]["visual_profiles"]
        ],
        "rollback": {
            "previous_sha": sha("consumer-before"),
            "import_commit_sha": sha("import"),
            "command": (
                f"git revert --no-commit {sha('adaptation')} "
                f"{sha('artifact')} {sha('import')}"
            ),
            "preserves_local_paths": ["wiki.config.yaml", "memories"],
        },
    }


def exact_three_boundary_fixture(
    tmp_path: Path,
    *,
    privacy: str = "public_safe",
) -> tuple[Path, Path, dict, dict, dict, str, list[str], bytes]:
    """Build a real import/artifact/adaptation chain from a reviewed preflight."""

    kit, target, _initial = make_matching_repos(tmp_path)
    generated_source = kit / "tests/generated/state.json"
    generated_source.parent.mkdir(parents=True)
    generated_source.write_text('{"generated":true}\n', encoding="utf-8")
    source_sha = commit_all(kit, "public source with generated artifact")

    (target / "wiki_core/core.py").write_text("VALUE = 0\n", encoding="utf-8")
    before_sha = commit_all(target, "consumer before upgrade")
    before_config = (target / "wiki.config.yaml").read_bytes()
    pkg = package(source_sha=source_sha)
    reviewed_gates = gate_evidence(before_sha)
    next(
        gate
        for gate in reviewed_gates["gates"]
        if gate["id"] == "toolkit_drift"
    )["status"] = "reviewed"
    preflight = build_preflight_report(
        kit_root=kit,
        consumer_root=target,
        package=pkg,
        consumer=consumer(privacy=privacy),
        gate_evidence=reviewed_gates,
        checked_on="2026-07-12",
        private_evidence_ref=(
            "output/wiki-upgrade/preflight-report.json"
            if privacy != "public_safe"
            else None
        ),
    )
    assert preflight["status"] == "ready"
    assert preflight["migration_partition"]["faithful_public_import"]["paths"] == [
        "wiki_core/core.py"
    ]
    assert preflight["migration_partition"]["regenerated_artifacts"]["paths"] == [
        "tests/generated/state.json"
    ]

    evidence = migration_evidence(pkg)
    evidence["consumer_before"]["head_sha"] = before_sha
    evidence["files_imported"] = ["wiki_core/core.py"]
    evidence["generated_artifacts"] = ["tests/generated/state.json"]
    evidence["downstream_adaptations"] = ["wiki.config.yaml"]
    bind_migration_preflight(target, evidence, pkg, preflight)

    (target / "wiki_core/core.py").write_bytes(
        (kit / "wiki_core/core.py").read_bytes()
    )
    import_sha = commit_all(target, "faithful public import")
    generated_target = target / "tests/generated/state.json"
    generated_target.parent.mkdir(parents=True)
    generated_target.write_bytes(generated_source.read_bytes())
    artifact_sha = commit_all(target, "regenerated artifacts")
    (target / "wiki.config.yaml").write_text(
        "repo_id: fixture\nlanguage: pt\ncontexts: [example]\n",
        encoding="utf-8",
    )
    adaptation_sha = commit_all(target, "downstream adaptations")
    commits = [import_sha, artifact_sha, adaptation_sha]

    evidence["consumer_after"].update(
        {
            "import_commit_sha": import_sha,
            "artifact_commit_sha": artifact_sha,
            "adaptation_commit_sha": adaptation_sha,
        }
    )
    evidence["evidence_context"]["captured_consumer_head"] = adaptation_sha
    for gate in evidence["gates"]:
        gate["captured_consumer_head"] = adaptation_sha
    for item in evidence["visual_qa_evidence"]:
        item["captured_consumer_head"] = adaptation_sha
    evidence["rollback"].update(
        {
            "previous_sha": before_sha,
            "import_commit_sha": import_sha,
            "command": (
                f"git revert --no-commit {adaptation_sha} {artifact_sha} {import_sha}"
            ),
        }
    )
    bind_migration_screenshots(target, evidence)
    bind_gate_receipts(target, evidence)
    return kit, target, pkg, evidence, preflight, before_sha, commits, before_config


def bind_boundary_commits(evidence: dict, commits: list[str]) -> None:
    import_sha, artifact_sha, adaptation_sha = commits
    evidence["consumer_after"].update(
        {
            "import_commit_sha": import_sha,
            "artifact_commit_sha": artifact_sha,
            "adaptation_commit_sha": adaptation_sha,
        }
    )
    evidence["evidence_context"]["captured_consumer_head"] = adaptation_sha
    for gate in evidence["gates"]:
        gate["captured_consumer_head"] = adaptation_sha
    for item in evidence["visual_qa_evidence"]:
        item["captured_consumer_head"] = adaptation_sha
    evidence["rollback"].update(
        {
            "import_commit_sha": import_sha,
            "command": (
                f"git revert --no-commit {adaptation_sha} {artifact_sha} {import_sha}"
            ),
        }
    )


def test_public_upgrade_package_and_inventory_are_valid() -> None:
    pkg = yaml.safe_load(
        (ROOT / "docs/references/upgrades/wiki-viva-v8/upgrade-package.yaml").read_text(
            encoding="utf-8"
        )
    )
    inventory = yaml.safe_load(
        (
            ROOT / "docs/references/upgrades/wiki-viva-v8/consumer-inventory.yaml"
        ).read_text(encoding="utf-8")
    )
    assert validate_upgrade_package(pkg) == []
    assert validate_consumer_inventory(inventory) == []
    assert inventory["schema_version"] == CONSUMER_INVENTORY_SCHEMA_VERSION
    assert package_is_pinned(pkg) is False
    assert pkg["release"]["status"] == "validation_pending"
    releasable = copy.deepcopy(pkg)
    releasable["release"]["status"] = "release_candidate"
    assert package_is_pinned(releasable) is True
    source_sha = pkg["release"]["source_sha"]
    assert subprocess.run(
        ["git", "cat-file", "-e", f"{source_sha}^{{commit}}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
    ).returncode == 0
    legacy_contracts = {
        "route": "wiki_world_route.v8",
        "snapshot": "wiki_web_snapshot.v2",
        "snapshot_envelope": "wiki_web_snapshot.v2",
        "blocks": "wiki_templates.v2+wiki_web_block_stacks.v1",
        "visual_grammar": "wiki_visual_grammar.v8",
        "runtime": "wiki_world_runtime.v8",
        "source_lifecycle": "wiki_source_lifecycle.v2",
        "freshness": "wiki_web_freshness.v1",
    }
    v2_contracts = {
        **legacy_contracts,
        "semantic_visual_tokens": "wiki_semantic_visual_tokens.v1",
        "appearance": "wiki_cockpit_appearance.v1",
        "server": "wiki_web_server.v6",
        "activity_timeline": "activity_timeline.v1",
        "temporal_event": "wiki_temporal_event.v1",
        "temporal_graph": "wiki_temporal_graph.v1",
        "experience_pack": "wiki_experience_pack.v1",
        "experience_pack_registry": "wiki_experience_pack_registry.v1",
        "experience_pack_lock": "wiki_experience_pack_lock.v1",
        "experience_pack_composition": "wiki_experience_pack_composition.v1",
        "asset_manifest": "wiki_cockpit_asset_manifest.v1",
        "downstream_adapter_manifest": "wiki_downstream_adapter_manifest.v1",
    }
    if pkg["schema_version"] == "wiki_viva_upgrade_package.v1":
        assert source_sha == "dbd158a482dca20ab823968467fec931d67ca050"
        assert pkg["contract_versions"] == legacy_contracts
    else:
        assert pkg["schema_version"] in {
            UPGRADE_PACKAGE_SCHEMA_VERSION,
            TWO_LANE_UPGRADE_PACKAGE_SCHEMA_VERSION,
        }
        assert pkg["contract_versions"] == v2_contracts
    assert pkg["migration"]["visual_profiles"] == [
        "desktop",
        "mobile",
        "fallback",
        "quadrant_collection_two_step",
    ]
    assert portable_path_status("apps/wiki-cockpit/.env.local", pkg)[0] is False
    expected_modern_portable = pkg["schema_version"] in {
        UPGRADE_PACKAGE_SCHEMA_VERSION,
        TWO_LANE_UPGRADE_PACKAGE_SCHEMA_VERSION,
    }
    assert (
        portable_path_status("packs/personal-finance/pack.yaml", pkg)[0]
        is expected_modern_portable
    )
    assert (
        portable_path_status(
            "docs/references/schemas/wiki-temporal-graph-v1.schema.json", pkg
        )[0]
        is expected_modern_portable
    )
    assert (
        portable_path_status("scripts/_git_subject.py", pkg)[0]
        is expected_modern_portable
    )
    assert portable_path_status("wiki.packs.lock.yaml", pkg)[0] is False
    assert portable_path_status("wiki.adapter-manifest.json", pkg)[0] is False
    assert portable_path_status(".wiki-viva/packs/personal-finance/0.1.0/pack.yaml", pkg)[0] is False
    assert (
        portable_path_status(
            "apps/wiki-cockpit/public/wiki-cockpit.config.json", pkg
        )[0]
        is False
    )


@pytest.mark.parametrize(
    "contract",
    [
        "route",
        "snapshot",
        "snapshot_envelope",
        "blocks",
        "visual_grammar",
        "semantic_visual_tokens",
        "appearance",
        "runtime",
        "source_lifecycle",
        "freshness",
        "server",
        "activity_timeline",
        "temporal_event",
        "temporal_graph",
        "experience_pack",
        "experience_pack_registry",
        "experience_pack_lock",
        "experience_pack_composition",
        "asset_manifest",
        "downstream_adapter_manifest",
    ],
)
def test_upgrade_package_requires_every_v8_runtime_contract(contract: str) -> None:
    pkg = package()
    del pkg["contract_versions"][contract]
    assert f"contract_versions.{contract} is required" in validate_upgrade_package(pkg)


def test_upgrade_package_requires_unique_safe_visual_profiles() -> None:
    missing = package()
    del missing["migration"]["visual_profiles"]
    assert "migration.visual_profiles cannot be empty" in validate_upgrade_package(
        missing
    )

    duplicate = package()
    duplicate["migration"]["visual_profiles"].append("desktop")
    assert "migration.visual_profiles must be unique" in validate_upgrade_package(
        duplicate
    )

    unsafe = package()
    unsafe["migration"]["visual_profiles"].append("../private")
    assert "migration.visual_profiles[3] is invalid" in validate_upgrade_package(
        unsafe
    )


def test_upgrade_package_commit_boundaries_are_canonical_and_v1_is_compatible() -> None:
    pkg = package()
    assert validate_upgrade_package(pkg) == []

    missing = copy.deepcopy(pkg)
    del missing["migration"]["commit_boundaries"]
    assert (
        "migration.commit_boundaries cannot be empty"
        in validate_upgrade_package(missing)
    )

    reversed_order = copy.deepcopy(pkg)
    reversed_order["migration"]["commit_boundaries"] = [
        "faithful_public_import",
        "downstream_adaptations",
        "regenerated_artifacts",
    ]
    assert (
        "migration.commit_boundaries must use canonical order"
        in validate_upgrade_package(reversed_order)
    )

    duplicate = copy.deepcopy(pkg)
    duplicate["migration"]["commit_boundaries"].append(
        "downstream_adaptations"
    )
    assert (
        "migration.commit_boundaries must be unique"
        in validate_upgrade_package(duplicate)
    )

    missing_import = copy.deepcopy(pkg)
    missing_import["migration"]["commit_boundaries"] = [
        "regenerated_artifacts",
        "downstream_adaptations",
    ]
    assert (
        "migration.commit_boundaries must begin with faithful_public_import"
        in validate_upgrade_package(missing_import)
    )

    legacy = copy.deepcopy(pkg)
    legacy["schema_version"] = "wiki_viva_upgrade_package.v1"
    del legacy["migration"]["commit_boundaries"]
    assert validate_upgrade_package(legacy) == []


def test_upgrade_package_requires_narrow_safe_generated_artifact_patterns() -> None:
    missing = package()
    del missing["migration"]["generated_artifact_patterns"]
    assert (
        "migration.generated_artifact_patterns is required when regenerated_artifacts is declared"
        in validate_upgrade_package(missing)
    )

    for unsafe_pattern in ("**/*", "../generated/**", "memories/**", ".env/**"):
        unsafe = package()
        unsafe["migration"]["generated_artifact_patterns"] = [unsafe_pattern]
        assert any(
            "migration.generated_artifact_patterns[0] is unsafe" in error
            for error in validate_upgrade_package(unsafe)
        )

    import_only = package()
    import_only["migration"]["commit_boundaries"] = ["faithful_public_import"]
    del import_only["migration"]["generated_artifact_patterns"]
    assert validate_upgrade_package(import_only) == []


def test_core_compile_fails_closed_for_invalid_v2_package() -> None:
    invalid = package()
    del invalid["migration"]["commit_boundaries"]
    report = compile_migration_report(migration_evidence(invalid), invalid)
    assert report["status"] == "blocked"
    assert "upgrade package contract is invalid" in report["validation_errors"]


def test_upgrade_package_reviewable_gate_is_narrow_and_bounded() -> None:
    pkg = package()
    pkg["preflight"]["required_gates"].append("semantic_inventory")
    pkg["preflight"]["reviewable_gates"] = {
        "semantic_inventory": {
            "required_boundary": "downstream_adaptations",
            "max_findings": 64,
        }
    }
    assert validate_upgrade_package(pkg) == []

    unsafe = copy.deepcopy(pkg)
    unsafe["preflight"]["reviewable_gates"] = {
        "audit": {
            "required_boundary": "downstream_adaptations",
            "max_findings": 64,
        }
    }
    errors = validate_upgrade_package(unsafe)
    assert any("may only declare semantic_inventory" in error for error in errors)


def test_portable_blocklist_wins_and_private_paths_are_not_importable() -> None:
    pkg = package()
    assert portable_path_status("wiki_core/core.py", pkg)[0] is True
    assert portable_path_status("scripts/wiki_upgrade_report.py", pkg)[0] is True
    assert portable_path_status("memories/private.md", pkg)[0] is False
    assert portable_path_status("wiki.config.yaml", pkg)[0] is False
    assert portable_path_status("wiki.adapter-manifest.json", pkg)[0] is False
    pkg["portable_import"]["allow"].append("**")
    allowed, reason = portable_path_status("wiki.adapter-manifest.json", pkg)
    assert allowed is False
    assert "consumer-owned manifest" in reason
    assert (
        portable_path_status(
            "apps/wiki-cockpit/public/wiki-cockpit.config.json", pkg
        )[0]
        is False
    )
    assert portable_path_status("random.txt", pkg)[0] is False


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "../../wiki_core/evil.py",
        "wiki_core/../evil.py",
        "wiki_core/./evil.py",
        "wiki_core//evil.py",
        "./wiki_core/evil.py",
        "/wiki_core/evil.py",
        "C:\\wiki_core\\evil.py",
        "wiki_core\\evil.py",
        "wiki_core/.ENV",
        "wiki_core/.Env.local",
        "wiki_core/Secrets.txt",
        "wiki_core/CREDENTIALS.JSON",
        "wiki_core/client_secret.yaml",
        "wiki_core/id_RSA",
    ],
)
def test_portable_paths_fail_closed_before_glob_matching(unsafe_path: str) -> None:
    allowed, reason = portable_path_status(unsafe_path, package())
    assert allowed is False
    assert reason in {
        "unsafe non-canonical path",
        "blocked by global sensitive-name policy",
    }


def test_sensitive_name_policy_does_not_block_descriptive_source_names() -> None:
    assert portable_path_status("wiki_core/secret_detector.py", package())[0] is True


def test_portable_wildcard_directory_glob_honors_block_precedence() -> None:
    pkg = package()
    pkg["portable_import"] = {
        "allow": [".skills/wiki-*/**"],
        "block": [".skills/wiki-private*/**"],
    }

    assert portable_path_status(".skills/wiki-viva", pkg) == (
        True,
        "allowed by .skills/wiki-*/**",
    )
    assert portable_path_status(".skills/wiki-viva/SKILL.md", pkg) == (
        True,
        "allowed by .skills/wiki-*/**",
    )
    assert portable_path_status(".skills/wiki-viva/reference/setup.md", pkg)[0] is True
    assert portable_path_status(".skills/not-a-wiki-skill/SKILL.md", pkg)[0] is False
    assert portable_path_status(".skills/wiki-private-client/SKILL.md", pkg) == (
        False,
        "blocked by .skills/wiki-private*/**",
    )


def test_portable_skills_resolve_consumer_owned_paths_from_config() -> None:
    pkg = yaml.safe_load(
        (
            ROOT
            / "docs/references/upgrades/wiki-viva-v8/upgrade-package.yaml"
        ).read_text(encoding="utf-8")
    )
    skill_files = sorted((ROOT / ".skills").glob("wiki-*/**/*.md"))
    hardcoded_consumer_links: list[str] = []
    for path in skill_files:
        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), 1):
            for href in re.findall(r"\]\(([^)#]+)(?:#[^)]*)?\)", line):
                if "://" in href or href.startswith("mailto:"):
                    continue
                resolved = (path.parent / href).resolve()
                try:
                    rel = resolved.relative_to(ROOT).as_posix()
                except ValueError:
                    continue
                configurable = rel.startswith(
                    ("memories/", "docs/references/", "data/raw/", "data/derived/")
                )
                if configurable and not portable_path_status(rel, pkg)[0]:
                    hardcoded_consumer_links.append(
                        f"{path.relative_to(ROOT)}:{line_number}->{rel}"
                    )

    assert hardcoded_consumer_links == []


def test_portable_markdown_links_close_over_the_upgrade_package() -> None:
    pkg = yaml.safe_load(
        (
            ROOT
            / "docs/references/upgrades/wiki-viva-v8/upgrade-package.yaml"
        ).read_text(encoding="utf-8")
    )
    tracked = subprocess.check_output(
        ["git", "ls-files", "*.md"], cwd=ROOT, text=True
    ).splitlines()
    stable_consumer_files = {
        "README.md",
        "AGENTS.md",
        "wiki.config.yaml",
        "wiki.page-types.yaml",
        "wiki.templates.yaml",
        "wiki.targets.yaml",
        ".github/workflows/wiki.yml",
    }
    broken: list[str] = []
    for rel in tracked:
        if not portable_path_status(rel, pkg)[0]:
            continue
        path = ROOT / rel
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            for href in re.findall(r"\]\(([^)#]+)(?:#[^)]*)?\)", line):
                if "://" in href or href.startswith("mailto:"):
                    continue
                target = (path.parent / href).resolve()
                try:
                    target_rel = target.relative_to(ROOT).as_posix()
                except ValueError:
                    continue
                if not target.is_file():
                    broken.append(f"{rel}:{line_number}->missing:{target_rel}")
                    continue
                consumer_stable = (
                    target_rel in stable_consumer_files
                    or target_rel.startswith("tests/")
                )
                if not portable_path_status(target_rel, pkg)[0] and not consumer_stable:
                    broken.append(
                        f"{rel}:{line_number}->nonportable:{target_rel}"
                    )

    assert broken == []


def test_portable_literal_globstar_keeps_directory_semantics() -> None:
    pkg = package()
    pkg["portable_import"] = {"allow": ["packs/foo/**"], "block": []}

    assert portable_path_status("packs/foo", pkg)[0] is True
    assert portable_path_status("packs/foo/bar.txt", pkg)[0] is True
    assert portable_path_status("packs/foo/nested/bar.txt", pkg)[0] is True
    assert portable_path_status("packs/foobar/bar.txt", pkg)[0] is False


def test_portable_drift_is_byte_exact_and_ignore_never_erases_drift(
    tmp_path: Path,
) -> None:
    kit, target, _ = make_matching_repos(tmp_path)
    assert compare_portable_files(kit, target, package())["drift_total"] == 0
    (target / "wiki_core/core.py").write_text("VALUE = 2\n", encoding="utf-8")
    assert compare_portable_files(kit, target, package())["content_differs"] == [
        "wiki_core/core.py"
    ]
    (target / ".toolkit-drift-ignore").write_text(
        "wiki_core/core.py\n", encoding="utf-8"
    )
    ignored = compare_portable_files(kit, target, package())
    assert ignored["drift_total"] == 1
    assert ignored["content_differs"] == ["wiki_core/core.py"]
    assert ignored["ignored_per_repo"] == ["wiki_core/core.py"]
    assert ignored["ignored_matches"] == ["wiki_core/core.py"]
    assert ignored["unsafe_ignore_patterns"] == ["wiki_core/core.py"]


def test_preflight_blocks_ignore_patterns_aimed_at_portable_core(
    tmp_path: Path,
) -> None:
    kit, target, _ = make_matching_repos(tmp_path)
    (target / "wiki_core/core.py").write_text("VALUE = 9\n", encoding="utf-8")
    (target / ".toolkit-drift-ignore").write_text(
        "wiki_core/**\n", encoding="utf-8"
    )
    head = commit_all(target, "attempted hidden core drift")
    evidence = gate_evidence(head)
    next(gate for gate in evidence["gates"] if gate["id"] == "toolkit_drift")[
        "status"
    ] = "reviewed"

    report = build_preflight_report(
        kit_root=kit,
        consumer_root=target,
        package=package(source_sha=repo_head(kit)),
        consumer=consumer(),
        gate_evidence=evidence,
        checked_on="2026-07-11",
    )

    assert report["status"] == "blocked"
    assert "toolkit_ignore_policy" in report["blockers"]
    assert report["drift"]["drift_total"] == 1


def test_git_batch_drains_later_records_before_reporting_a_missing_blob(
    tmp_path: Path, monkeypatch
) -> None:
    missing = "0" * 40
    present = "f" * 40
    output = (
        f"{missing} missing\n{present} blob 7\npayload\n".encode("ascii")
    )

    class FakeBatchProcess:
        def __init__(self) -> None:
            self.stdin = io.BytesIO()
            self.stdout = io.BytesIO(output)
            self.stderr = io.BytesIO()
            self.terminated = False

        def wait(self, timeout: int | None = None) -> int:
            return 0

        def terminate(self) -> None:
            self.terminated = True

        def kill(self) -> None:
            self.terminated = True

    process = FakeBatchProcess()
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)

    with pytest.raises(ValueError, match=f"{missing}:missing"):
        _git_blob_payloads(tmp_path, {present, missing})

    assert process.stdout.tell() == len(output)
    assert process.terminated is False


def test_preflight_is_ready_only_with_pinned_release_clean_branch_current_gates_and_zero_drift(
    tmp_path: Path,
) -> None:
    kit, target, head = make_matching_repos(tmp_path)
    report = build_preflight_report(
        kit_root=kit,
        consumer_root=target,
        package=package(source_sha=repo_head(kit)),
        consumer=consumer(),
        gate_evidence=gate_evidence(head),
        checked_on="2026-07-09",
    )
    assert report["status"] == "ready"
    assert report["blockers"] == []
    assert report["drift"]["drift_total"] == 0
    assert report["snapshot"]["kind"] == "real"


def test_preflight_blocks_unpinned_dirty_drifted_or_unbound_private_consumer(
    tmp_path: Path,
) -> None:
    kit, target, head = make_matching_repos(tmp_path)
    (target / "wiki_core/core.py").write_text("VALUE = 9\n", encoding="utf-8")
    report = build_preflight_report(
        kit_root=kit,
        consumer_root=target,
        package=package(pinned=False),
        consumer=consumer(privacy="financial_personal"),
        gate_evidence=gate_evidence(head),
        checked_on="2026-07-09",
        redact=False,
    )
    assert report["status"] == "blocked"
    assert {
        "release_pinned",
        "clean_worktree",
        "toolkit_drift",
        "privacy_evidence",
    } <= set(report["blockers"])
    assert report["privacy"]["report_redacted"] is True
    assert "paths" not in report["migration_partition"]["faithful_public_import"]


def test_preflight_can_be_ready_with_clean_explicitly_reviewed_upgrade_drift(
    tmp_path: Path,
) -> None:
    kit, target, _ = make_matching_repos(tmp_path)
    (target / "wiki_core/core.py").write_text("VALUE = 9\n", encoding="utf-8")
    head = commit_all(target, "consumer drift")
    evidence = gate_evidence(head)
    next(gate for gate in evidence["gates"] if gate["id"] == "toolkit_drift")[
        "status"
    ] = "reviewed"
    # Replace the implicit missing drift receipt with the reviewed one while
    # keeping every current honesty gate at the exact current HEAD.
    report = build_preflight_report(
        kit_root=kit,
        consumer_root=target,
        package=package(source_sha=repo_head(kit)),
        consumer=consumer(),
        gate_evidence=evidence,
        checked_on="2026-07-09",
    )
    assert report["status"] == "ready"
    assert "toolkit_drift" in report["warnings"]


def test_validation_pending_preflight_blocks_promotion_but_keeps_real_drift(
    tmp_path: Path,
) -> None:
    kit, target, _ = make_matching_repos(tmp_path)
    (target / "wiki_core/core.py").write_text("VALUE = 9\n", encoding="utf-8")
    head = commit_all(target, "consumer drift")
    evidence = gate_evidence(head)
    next(gate for gate in evidence["gates"] if gate["id"] == "toolkit_drift")[
        "status"
    ] = "reviewed"
    pending = package(source_sha=repo_head(kit))
    pending["release"]["status"] = "validation_pending"

    report = build_preflight_report(
        kit_root=kit,
        consumer_root=target,
        package=pending,
        consumer=consumer(),
        gate_evidence=evidence,
        checked_on="2026-07-12",
    )
    checks = {item["id"]: item for item in report["checks"]}

    assert report["status"] == "blocked"
    assert report["blockers"] == ["release_pinned"]
    assert report["drift"]["drift_total"] == 1
    assert checks["release_pinned"]["evidence"] == (
        "release status is not releasable: validation_pending"
    )
    assert checks["release_source_available"]["status"] == "pass"
    assert checks["toolkit_drift"]["status"] == "warn"

    unpinned_id = copy.deepcopy(pending)
    unpinned_id["release"]["id"] = "main"
    unpinned_id["release"]["status"] = "release_candidate"
    id_report = build_preflight_report(
        kit_root=kit,
        consumer_root=target,
        package=unpinned_id,
        consumer=consumer(),
        gate_evidence=evidence,
        checked_on="2026-07-12",
    )
    id_checks = {item["id"]: item for item in id_report["checks"]}
    assert id_report["blockers"] == ["release_pinned"]
    assert id_checks["release_pinned"]["evidence"] == (
        "release id is not pinned: main"
    )
    assert id_checks["release_source_available"]["status"] == "pass"


def test_preflight_accepts_only_bounded_semantic_review_for_third_boundary(
    tmp_path: Path,
) -> None:
    kit, target, head = make_matching_repos(tmp_path)
    pkg = package(source_sha=repo_head(kit))
    pkg["preflight"]["required_gates"].append("semantic_inventory")
    pkg["preflight"]["reviewable_gates"] = {
        "semantic_inventory": {
            "required_boundary": "downstream_adaptations",
            "max_findings": 64,
        }
    }
    evidence = gate_evidence(head)
    evidence["gates"].append(
        {
            "id": "semantic_inventory",
            "command": "python3 scripts/wiki_semantic_inventory.py --check",
            "status": "reviewed",
            "finding_count": 10,
            "findings_sha256": sha("semantic-findings"),
            "planned_boundary": "downstream_adaptations",
            "note": "typed references require consumer-owned repair",
        }
    )

    report = build_preflight_report(
        kit_root=kit,
        consumer_root=target,
        package=pkg,
        consumer=consumer(),
        gate_evidence=evidence,
        checked_on="2026-07-12",
    )

    assert report["status"] == "ready"
    assert "semantic_inventory_adaptation" in report["warnings"]
    assert report["gate_evidence"]["reviews"]["semantic_inventory"] == {
        "finding_count": 10,
        "findings_sha256": sha("semantic-findings"),
        "planned_boundary": "downstream_adaptations",
    }

    for field, invalid_value in (
        ("finding_count", 65),
        ("findings_sha256", "not-a-hash"),
        ("planned_boundary", "faithful_public_import"),
        ("note", ""),
        ("command", ""),
    ):
        invalid = copy.deepcopy(evidence)
        next(
            gate
            for gate in invalid["gates"]
            if gate["id"] == "semantic_inventory"
        )[field] = invalid_value
        blocked = build_preflight_report(
            kit_root=kit,
            consumer_root=target,
            package=pkg,
            consumer=consumer(),
            gate_evidence=invalid,
            checked_on="2026-07-12",
        )
        assert blocked["status"] == "blocked"
        assert "current_gates" in blocked["blockers"]

    final_pkg = copy.deepcopy(pkg)
    final_pkg["migration"]["required_gates"].append("semantic_inventory")
    final_evidence = migration_evidence(final_pkg)
    next(
        gate
        for gate in final_evidence["gates"]
        if gate["id"] == "semantic_inventory"
    )["status"] = "reviewed"
    assert "migration gate did not pass: semantic_inventory" in validate_migration_evidence(
        final_evidence,
        final_pkg,
    )


def test_preflight_blocks_unknown_privacy_even_when_every_other_check_passes(
    tmp_path: Path,
) -> None:
    kit, target, head = make_matching_repos(tmp_path)
    unknown = consumer(privacy="unknown")
    report = build_preflight_report(
        kit_root=kit,
        consumer_root=target,
        package=package(source_sha=repo_head(kit)),
        consumer=unknown,
        gate_evidence=gate_evidence(head),
        checked_on="2026-07-09",
        redact=True,
    )
    assert report["status"] == "blocked"
    assert "privacy_evidence" in report["blockers"]


def test_private_risk_has_private_authoritative_and_public_redacted_preflights(
    tmp_path: Path,
) -> None:
    kit, target, head = make_matching_repos(tmp_path)
    private_consumer = consumer(privacy="financial_personal")
    private_consumer["evidence_redaction_required"] = False

    unredacted = build_preflight_report(
        kit_root=kit,
        consumer_root=target,
        package=package(source_sha=repo_head(kit)),
        consumer=private_consumer,
        gate_evidence=gate_evidence(head),
        checked_on="2026-07-11",
        redact=False,
    )
    assert unredacted["status"] == "blocked"
    assert "privacy_evidence" in unredacted["blockers"]
    assert unredacted["privacy"]["redaction_required"] is True
    assert unredacted["privacy"]["report_redacted"] is True
    assert "paths" not in unredacted["migration_partition"]["faithful_public_import"]

    authoritative = build_preflight_report(
        kit_root=kit,
        consumer_root=target,
        package=package(source_sha=repo_head(kit)),
        consumer=private_consumer,
        gate_evidence=gate_evidence(head),
        checked_on="2026-07-11",
        redact=False,
        private_evidence_ref="output/wiki-upgrade/preflight-report.json",
    )
    assert authoritative["status"] == "ready"
    assert authoritative["privacy"]["report_redacted"] is False
    assert authoritative["privacy"]["authoritative_private"] is True
    assert "paths" in authoritative["migration_partition"]["faithful_public_import"]

    redacted = build_preflight_report(
        kit_root=kit,
        consumer_root=target,
        package=package(source_sha=repo_head(kit)),
        consumer=private_consumer,
        gate_evidence=gate_evidence(head),
        checked_on="2026-07-11",
        redact=True,
    )
    assert redacted["status"] == "ready"
    assert redacted["privacy"]["redaction_required"] is True
    assert redacted["privacy"]["report_redacted"] is True
    assert "paths" not in redacted["migration_partition"]["faithful_public_import"]


def test_redacted_preflight_never_emits_local_drift_or_status_paths(
    tmp_path: Path,
) -> None:
    kit, target, head = make_matching_repos(tmp_path)
    private_name = "client-secret-adapter.py"
    (target / "tests" / private_name).parent.mkdir(parents=True)
    (target / "tests" / private_name).write_text(
        "# private fixture name\n", encoding="utf-8"
    )
    private_layout_name = "knowledge/client-internal-project"
    (target / "wiki.config.yaml").write_text(
        "repo_id: fixture\npaths:\n  memory_root: "
        + private_layout_name
        + "\n",
        encoding="utf-8",
    )
    private_consumer = consumer(privacy="financial_personal")
    private_consumer["repository"]["name"] = "client-internal-project"
    report = build_preflight_report(
        kit_root=kit,
        consumer_root=target,
        package=package(source_sha=repo_head(kit)),
        consumer=private_consumer,
        gate_evidence=gate_evidence(head),
        checked_on="2026-07-09",
        redact=True,
    )
    serialized = json.dumps(report)
    assert private_name not in serialized
    assert private_layout_name not in serialized
    assert "client-internal-project" not in serialized
    assert str(target) not in serialized
    assert head not in serialized
    assert report["consumer_before"]["path"] == "<redacted-local-path>"
    assert report["consumer_before"]["head_sha"].startswith("consumer-head:sha256:")
    assert report["consumer_before"]["status_short"] == []
    assert report["consumer_before"]["status_entry_count"] == 2
    assert "only_in_consumer_count" in report["drift"]


def test_preflight_compares_the_pinned_release_tree_not_later_kit_head(
    tmp_path: Path,
) -> None:
    kit, target, consumer_head = make_matching_repos(tmp_path)
    pinned_sha = repo_head(kit)
    (kit / "wiki_core/core.py").write_text("VALUE = 2\n", encoding="utf-8")
    later_sha = commit_all(kit, "later unpinned payload")

    report = build_preflight_report(
        kit_root=kit,
        consumer_root=target,
        package=package(source_sha=pinned_sha),
        consumer=consumer(),
        gate_evidence=gate_evidence(consumer_head),
        checked_on="2026-07-10",
    )

    assert later_sha != pinned_sha
    assert report["status"] == "ready"
    assert report["drift"]["drift_total"] == 0
    assert report["drift"]["source_mode"] == "pinned_git_tree"
    assert report["drift"]["source_sha"] == pinned_sha


def test_preflight_detects_the_local_operator_runtime_config_as_an_override(
    tmp_path: Path,
) -> None:
    kit, target, _ = make_matching_repos(tmp_path)
    runtime_config = target / "apps/wiki-cockpit/public/wiki-cockpit.config.json"
    runtime_config.parent.mkdir(parents=True)
    runtime_config.write_text(
        '{"api_base":"/api","mode":"local_operator"}\n', encoding="utf-8"
    )
    consumer_head = commit_all(target, "local operator config")

    report = build_preflight_report(
        kit_root=kit,
        consumer_root=target,
        package=package(source_sha=repo_head(kit)),
        consumer=consumer(),
        gate_evidence=gate_evidence(consumer_head),
        checked_on="2026-07-10",
    )

    assert report["status"] == "ready"
    assert (
        "apps/wiki-cockpit/public/wiki-cockpit.config.json"
        in report["local_overrides"]["known_files"]
    )
    assert "local_overrides" in report["warnings"]


def test_migration_report_is_complete_deterministic_and_renderable() -> None:
    pkg = package()
    evidence = migration_evidence(pkg)
    first = compile_migration_report(evidence, pkg, public_export=True)
    second = compile_migration_report(copy.deepcopy(evidence), pkg, public_export=True)
    assert first == second
    assert first["status"] == "complete"
    assert first["source"]["sha"] == pkg["release"]["source_sha"]
    assert first["consumer_before"]["head_sha"].startswith("consumer-head:sha256:")
    assert evidence["consumer_before"]["head_sha"] not in json.dumps(first)
    report_schema = json.loads(
        (
            ROOT
            / "docs/references/upgrades/wiki-viva-v8/migration-report.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert list(Draft202012Validator(report_schema).iter_errors(first)) == []
    markdown = render_migration_report_markdown(first)
    assert "Faithful public import" in markdown
    assert "## Warnings" in markdown
    assert "## Synthetic regression fixtures" in markdown
    assert "consumer-maintainer" not in markdown
    assert "v9 stable" not in markdown
    assert "tests/fixtures/core-bug.yaml" not in markdown
    assert "## Rollback" in markdown
    assert "Disposable rollback verification" in markdown
    assert "Screenshot" in markdown
    assert first["report_id"] in markdown

    private_markdown = render_migration_report_markdown(
        compile_migration_report(evidence, pkg, public_export=False)
    )
    assert "consumer-maintainer" in private_markdown
    assert "v9 stable" in private_markdown
    assert "tests/fixtures/core-bug.yaml" in private_markdown

    stale_shallow = {
        key: value
        for key, value in first.items()
        if key not in {"evidence_context", "omitted_boundaries", "rollback_verification"}
    }
    assert list(Draft202012Validator(report_schema).iter_errors(stale_shallow))

    legacy_evidence = copy.deepcopy(evidence)
    legacy_evidence["schema_version"] = "wiki_viva_migration_evidence.v1"
    legacy_report = compile_migration_report(legacy_evidence, pkg)
    assert legacy_report["status"] == "blocked"
    assert any(
        "schema_version must be wiki_viva_migration_evidence.v2" in error
        for error in legacy_report["validation_errors"]
    )


def test_migration_markdown_escapes_html_and_code_span_injection() -> None:
    pkg = package()
    evidence = migration_evidence(pkg)
    injection = "</code><script>alert(`client-alpha-redesign`)</script>"
    evidence["warnings"][0]["message"] = injection
    private_markdown = render_migration_report_markdown(
        compile_migration_report(evidence, pkg, public_export=False)
    )
    public_markdown = render_migration_report_markdown(
        compile_migration_report(evidence, pkg, public_export=True)
    )
    assert "<script>" not in private_markdown
    assert "</code>" not in private_markdown
    assert "&lt;script&gt;" in private_markdown
    assert "&#96;client-alpha-redesign&#96;" in private_markdown
    assert injection not in public_markdown


def test_public_migration_projection_hides_safe_private_names_and_paths() -> None:
    pkg = package()
    evidence = migration_evidence(pkg)
    before = evidence["consumer_before"]
    before["repository"] = "internal-repository"
    before["branch"] = "wiki/internal-before"
    before["memory_root"] = "knowledge/internal"
    before["references_root"] = "knowledge/references"
    before["preflight"]["report_ref"] = (
        "output/wiki-upgrade/internal-preflight.json"
    )
    evidence["consumer_after"]["branch"] = "wiki/internal-after"
    evidence["rollback"]["preserves_local_paths"] = [
        "wiki.config.yaml",
        "knowledge/internal",
    ]
    private_screenshot_refs: list[str] = []
    for index, item in enumerate(evidence["visual_qa_evidence"]):
        ref = f"output/wiki-upgrade/qa/internal-capture-{index}.png"
        item["screenshot_ref"] = ref
        private_screenshot_refs.append(ref)

    public_report = compile_migration_report(evidence, pkg, public_export=True)
    private_report = compile_migration_report(evidence, pkg, public_export=False)
    assert public_report["status"] == "complete"
    assert private_report["status"] == "complete"
    assert public_report["consumer_before"]["repository"] == "<redacted-public-value>"
    assert public_report["consumer_before"]["branch"] == "<redacted-public-value>"
    assert public_report["consumer_before"]["memory_root"] == "<redacted-public-value>"
    assert (
        public_report["consumer_before"]["references_root"]
        == "<redacted-public-value>"
    )
    assert (
        public_report["consumer_before"]["preflight"]["report_ref"]
        == "<redacted-public-value>"
    )
    assert public_report["consumer_after"]["branch"] == "<redacted-public-value>"
    assert public_report["rollback"]["preserves_local_paths"] == []
    assert public_report["files_imported"] == []
    assert public_report["generated_artifacts"] == []
    assert public_report["downstream_adaptations"] == []
    assert public_report["local_overrides_kept"] == []
    assert public_report["fixtures_added"] == []
    assert public_report["warnings"] == []
    assert {
        item["command"] for item in public_report["gates"]
    } == {"<redacted-public-value>"}
    assert {
        item["screenshot_ref"] for item in public_report["visual_qa_evidence"]
    } == {"qa/redacted.png"}
    public_text = json.dumps(public_report, ensure_ascii=False)
    for raw in (
        "internal-repository",
        "wiki/internal-before",
        "wiki/internal-after",
        "knowledge/internal",
        "knowledge/references",
        "output/wiki-upgrade/internal-preflight.json",
        *private_screenshot_refs,
    ):
        assert raw not in public_text
    assert private_report["consumer_before"]["repository"] == "internal-repository"
    assert private_report["files_imported"] == evidence["files_imported"]
    assert private_report["generated_artifacts"] == evidence["generated_artifacts"]
    assert (
        private_report["downstream_adaptations"]
        == evidence["downstream_adaptations"]
    )
    assert (
        private_report["consumer_before"]["preflight"]["report_ref"]
        == "output/wiki-upgrade/internal-preflight.json"
    )


def test_public_gate_projection_never_hashes_secret_commands() -> None:
    pkg = package()
    first = migration_evidence(pkg)
    second = copy.deepcopy(first)
    first["gates"][0]["command"] = "tool --password low-entropy-alpha"
    second["gates"][0]["command"] = "tool --password low-entropy-beta"
    first_report = compile_migration_report(first, pkg, public_export=True)
    second_report = compile_migration_report(second, pkg, public_export=True)
    assert first_report["gates"][0]["command"] == "<redacted-public-value>"
    assert second_report["gates"][0]["command"] == "<redacted-public-value>"
    assert first_report["gates"] == second_report["gates"]


def test_migration_visual_profiles_are_package_owned_and_cannot_be_omitted() -> None:
    pkg = package()
    pkg["migration"]["visual_profiles"].append("quadrant_collection_two_step")

    template = migration_evidence_template(pkg)
    assert [item["profile"] for item in template["visual_qa_evidence"]] == [
        "desktop",
        "mobile",
        "fallback",
        "quadrant_collection_two_step",
    ]

    evidence = migration_evidence(pkg)
    assert validate_migration_evidence(evidence, pkg) == []
    evidence_schema = json.loads(
        (
            ROOT
            / "docs/references/schemas/wiki-migration-evidence-v2.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert list(Draft202012Validator(evidence_schema).iter_errors(evidence)) == []
    report = compile_migration_report(evidence, pkg, public_export=True)
    report_schema = json.loads(
        (
            ROOT
            / "docs/references/upgrades/wiki-viva-v8/migration-report.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert list(Draft202012Validator(report_schema).iter_errors(report)) == []

    missing = copy.deepcopy(evidence)
    missing["visual_qa_evidence"] = [
        item
        for item in missing["visual_qa_evidence"]
        if item["profile"] != "quadrant_collection_two_step"
    ]
    assert (
        "visual_qa_evidence missing profile: quadrant_collection_two_step"
        in validate_migration_evidence(missing, pkg)
    )

    undeclared = copy.deepcopy(evidence)
    undeclared["visual_qa_evidence"].append(
        {
            **undeclared["visual_qa_evidence"][0],
            "profile": "unreviewed_extra",
            "screenshot_ref": "qa/unreviewed_extra.png",
        }
    )
    assert any(
        "profile is invalid" in error
        for error in validate_migration_evidence(undeclared, pkg)
    )

    reused = copy.deepcopy(evidence)
    reused["visual_qa_evidence"][1]["screenshot_ref"] = reused[
        "visual_qa_evidence"
    ][0]["screenshot_ref"]
    reused["visual_qa_evidence"][1]["screenshot_sha256"] = reused[
        "visual_qa_evidence"
    ][0]["screenshot_sha256"]
    reused_errors = validate_migration_evidence(reused, pkg)
    assert "visual_qa_evidence screenshot refs must be unique" in reused_errors
    assert "visual_qa_evidence screenshot hashes must be unique" in reused_errors

    wrong_dimensions = copy.deepcopy(evidence)
    wrong_dimensions["visual_qa_evidence"][0]["screenshot_dimensions"] = {
        "width": 1,
        "height": 1,
    }
    assert any(
        "screenshot_dimensions must equal its viewport" in error
        for error in validate_migration_evidence(wrong_dimensions, pkg)
    )


def test_package_declared_migration_boundaries_require_every_sha() -> None:
    pkg = package()
    template = migration_evidence_template(pkg)
    assert template["evidence_context"]["validator_version"] == (
        "wiki_viva_upgrade_validator.v5"
    )
    assert template["omitted_boundaries"] == []
    assert all(
        template["consumer_after"][field]
        for field in (
            "import_commit_sha",
            "artifact_commit_sha",
            "adaptation_commit_sha",
        )
    )
    assert all(
        {"exit_code", "captured_consumer_head"} <= set(gate)
        for gate in template["gates"]
    )
    assert template["consumer_before"]["memory_root"] == (
        "REPLACE_WITH_CONSUMER_MEMORY_ROOT"
    )
    assert template["consumer_before"]["references_root"] == (
        "REPLACE_WITH_CONSUMER_REFERENCES_ROOT"
    )
    assert template["consumer_before"]["preflight"]["report_ref"].startswith(
        "output/wiki-upgrade/"
    )

    evidence = migration_evidence(pkg)
    evidence["consumer_after"]["artifact_commit_sha"] = None
    evidence["omitted_boundaries"] = [
        {
            "boundary": "artifact_commit_sha",
            "reason": "Attempted omission despite the package contract.",
        }
    ]
    errors = validate_migration_evidence(evidence, pkg)
    assert any(
        "artifact_commit_sha is required by migration.commit_boundaries" in error
        for error in errors
    )
    assert (
        "omitted_boundaries cannot omit package-declared artifact_commit_sha"
        in errors
    )

    import_only = package()
    import_only["migration"]["commit_boundaries"] = ["faithful_public_import"]
    import_evidence = migration_evidence(import_only)
    import_sha = import_evidence["consumer_after"]["import_commit_sha"]
    import_evidence["consumer_after"].update(
        {"artifact_commit_sha": None, "adaptation_commit_sha": None}
    )
    import_evidence["generated_artifacts"] = []
    import_evidence["downstream_adaptations"] = []
    import_evidence["omitted_boundaries"] = [
        {
            "boundary": "artifact_commit_sha",
            "reason": "Not declared by this import-only package.",
        },
        {
            "boundary": "adaptation_commit_sha",
            "reason": "Not declared by this import-only package.",
        },
    ]
    import_evidence["evidence_context"]["captured_consumer_head"] = import_sha
    for gate in import_evidence["gates"]:
        gate["captured_consumer_head"] = import_sha
    for item in import_evidence["visual_qa_evidence"]:
        item["captured_consumer_head"] = import_sha
    import_evidence["rollback"]["command"] = f"git revert --no-commit {import_sha}"
    assert validate_migration_evidence(import_evidence, import_only) == []

    legacy = copy.deepcopy(import_only)
    legacy["schema_version"] = "wiki_viva_upgrade_package.v1"
    del legacy["migration"]["commit_boundaries"]
    del legacy["migration"]["generated_artifact_patterns"]
    legacy_evidence = migration_evidence(legacy)
    legacy_import_sha = legacy_evidence["consumer_after"]["import_commit_sha"]
    legacy_evidence["consumer_after"].update(
        {"artifact_commit_sha": None, "adaptation_commit_sha": None}
    )
    del legacy_evidence["generated_artifacts"]
    del legacy_evidence["downstream_adaptations"]
    legacy_evidence["omitted_boundaries"] = copy.deepcopy(
        import_evidence["omitted_boundaries"]
    )
    legacy_evidence["evidence_context"][
        "captured_consumer_head"
    ] = legacy_import_sha
    for gate in legacy_evidence["gates"]:
        gate["captured_consumer_head"] = legacy_import_sha
    for item in legacy_evidence["visual_qa_evidence"]:
        item["captured_consumer_head"] = legacy_import_sha
    legacy_evidence["rollback"]["command"] = (
        f"git revert --no-commit {legacy_import_sha}"
    )
    assert validate_migration_evidence(legacy_evidence, legacy) == []


def test_migration_preflight_and_gate_claims_fail_closed_without_git() -> None:
    pkg = package()
    evidence = migration_evidence(pkg)

    blocked_status = copy.deepcopy(evidence)
    blocked_status["consumer_before"]["preflight"]["status"] = "blocked"
    assert (
        "consumer_before.preflight.status must be ready"
        in validate_migration_evidence(blocked_status, pkg)
    )

    bad_report_id = copy.deepcopy(evidence)
    bad_report_id["consumer_before"]["preflight"]["report_id"] = "pending"
    assert (
        "consumer_before.preflight.report_id is invalid"
        in validate_migration_evidence(bad_report_id, pkg)
    )

    bad_report_digest = copy.deepcopy(evidence)
    bad_report_digest["consumer_before"]["preflight"]["report_sha256"] = "pending"
    assert any(
        "preflight.report_sha256 must be an exact SHA-256" in error
        for error in validate_migration_evidence(bad_report_digest, pkg)
    )

    placeholder_ref = copy.deepcopy(evidence)
    placeholder_ref["consumer_before"]["preflight"]["report_ref"] = (
        "REPLACE_WITH_PREFLIGHT.json"
    )
    assert any(
        "preflight.report_ref must be a safe repo-relative JSON path" in error
        for error in validate_migration_evidence(placeholder_ref, pkg)
    )

    unsafe_references_root = copy.deepcopy(evidence)
    unsafe_references_root["consumer_before"]["references_root"] = (
        "../docs/references"
    )
    assert any(
        "consumer_before.references_root must be a safe repo-relative path"
        in error
        for error in validate_migration_evidence(unsafe_references_root, pkg)
    )

    wrong_package = copy.deepcopy(evidence)
    wrong_package["consumer_before"]["preflight"]["package_sha256"] = "f" * 64
    assert any(
        "preflight.package_sha256 must match" in error
        for error in validate_migration_evidence(wrong_package, pkg)
    )

    wrong_consumer = copy.deepcopy(evidence)
    wrong_consumer["consumer_before"]["preflight"]["consumer_head"] = sha(
        "different-consumer"
    )
    assert any(
        "preflight.consumer_head must match" in error
        for error in validate_migration_evidence(wrong_consumer, pkg)
    )

    missing_memory_preservation = copy.deepcopy(evidence)
    missing_memory_preservation["rollback"]["preserves_local_paths"] = [
        "wiki.config.yaml"
    ]
    assert any(
        "preserves_local_paths must contain consumer_before.memory_root" in error
        for error in validate_migration_evidence(missing_memory_preservation, pkg)
    )

    gate_exit = copy.deepcopy(evidence)
    gate_exit["gates"][0]["exit_code"] = 1
    assert any(
        "gates[0].exit_code must be 0" in error
        for error in validate_migration_evidence(gate_exit, pkg)
    )

    gate_head = copy.deepcopy(evidence)
    gate_head["gates"][0]["captured_consumer_head"] = sha("stale-gate-head")
    assert any(
        "gates[0].captured_consumer_head must match" in error
        for error in validate_migration_evidence(gate_head, pkg)
    )

    gate_placeholder = copy.deepcopy(evidence)
    gate_placeholder["gates"][0]["command"] = "record exact audit command"
    assert any(
        "gates[0].command must be exact, not a placeholder" in error
        for error in validate_migration_evidence(gate_placeholder, pkg)
    )
    no_op_gate = copy.deepcopy(evidence)
    no_op_gate["gates"][0]["command"] = "true"
    assert any(
        "gates[0].command must be exact, not a placeholder" in error
        for error in validate_migration_evidence(no_op_gate, pkg)
    )


def test_migration_boundaries_must_be_distinct_existing_and_ancestry_ordered(
    tmp_path: Path,
) -> None:
    (
        kit,
        target,
        pkg,
        evidence,
        preflight_report,
        before_sha,
        commits,
        preserved_config,
    ) = exact_three_boundary_fixture(tmp_path)
    assert subprocess.check_output(
        [
            "git",
            "ls-tree",
            "-r",
            "--name-only",
            commits[0],
            "--",
            evidence["consumer_before"]["preflight"]["report_ref"],
        ],
        cwd=target,
        text=True,
    ).strip() == ""

    assert validate_migration_evidence(
        evidence,
        pkg,
        consumer_root=target,
        kit_root=kit,
        require_git_commits=True,
    ) == []

    preflight_path = (
        target / evidence["consumer_before"]["preflight"]["report_ref"]
    )
    altered_preflight = copy.deepcopy(preflight_report)
    altered_preflight["status"] = "blocked"
    preflight_path.write_text(
        json.dumps(altered_preflight, sort_keys=True), encoding="utf-8"
    )
    altered_errors = validate_migration_evidence(
        evidence,
        pkg,
        consumer_root=target,
        kit_root=kit,
        require_git_commits=True,
    )
    assert any("report_sha256 does not match report_ref" in error for error in altered_errors)
    assert "referenced preflight report status must be ready" in altered_errors
    bind_migration_preflight(target, evidence, pkg, preflight_report)

    unsafe_preflight = copy.deepcopy(evidence)
    unsafe_preflight["consumer_before"]["preflight"]["report_ref"] = (
        "../preflight-report.json"
    )
    assert any(
        "preflight.report_ref" in error
        for error in validate_migration_evidence(
            unsafe_preflight,
            pkg,
        consumer_root=target,
        kit_root=kit,
        require_git_commits=True,
        )
    )

    unignored_preflight_path = target / "preflight-report.json"
    unignored_preflight_path.write_text(
        json.dumps(preflight_report, sort_keys=True), encoding="utf-8"
    )
    unignored_preflight = copy.deepcopy(evidence)
    unignored_preflight["consumer_before"]["preflight"]["report_ref"] = (
        "preflight-report.json"
    )
    assert (
        "consumer_before.preflight.report_ref must be ignored and untracked"
        in validate_migration_evidence(
            unignored_preflight,
            pkg,
        consumer_root=target,
        kit_root=kit,
        require_git_commits=True,
        )
    )
    unignored_preflight_path.unlink()

    wrong_source_report = copy.deepcopy(preflight_report)
    wrong_source_report["source_package"]["release"] = "wrong-release"
    wrong_source_payload = {
        key: value for key, value in wrong_source_report.items() if key != "report_id"
    }
    wrong_source_report["report_id"] = deterministic_id(
        "preflight", wrong_source_payload
    )
    preflight_path.write_text(
        json.dumps(wrong_source_report, sort_keys=True), encoding="utf-8"
    )
    wrong_source_evidence = copy.deepcopy(evidence)
    wrong_source_binding = wrong_source_evidence["consumer_before"]["preflight"]
    wrong_source_binding["report_id"] = wrong_source_report["report_id"]
    wrong_source_binding["report_sha256"] = hashlib.sha256(
        canonical_json(wrong_source_payload).encode("utf-8")
    ).hexdigest()
    assert (
        "referenced preflight release does not match the upgrade package"
        in validate_migration_evidence(
            wrong_source_evidence,
            pkg,
        consumer_root=target,
        kit_root=kit,
        require_git_commits=True,
        )
    )
    bind_migration_preflight(target, evidence, pkg, preflight_report)

    wrong_memory_root = copy.deepcopy(evidence)
    wrong_memory_root["consumer_before"]["memory_root"] = "memorias"
    wrong_memory_root["rollback"]["preserves_local_paths"].append("memorias")
    assert (
        "consumer_before.memory_root does not match the configured consumer layout"
        in validate_migration_evidence(
            wrong_memory_root,
            pkg,
        consumer_root=target,
        kit_root=kit,
        require_git_commits=True,
        )
    )

    wrong_before_branch = copy.deepcopy(evidence)
    wrong_before_branch["consumer_before"]["branch"] = "wiki/self-attested-before"
    assert (
        "referenced preflight consumer branch does not match consumer_before.branch"
        in validate_migration_evidence(
            wrong_before_branch,
            pkg,
            consumer_root=target,
            kit_root=kit,
            require_git_commits=True,
        )
    )

    wrong_references_root = copy.deepcopy(evidence)
    wrong_references_root["consumer_before"]["references_root"] = (
        "docs/referencias"
    )
    wrong_references_errors = validate_migration_evidence(
        wrong_references_root,
        pkg,
        consumer_root=target,
        kit_root=kit,
        require_git_commits=True,
    )
    assert (
        "consumer_before.references_root does not match the configured consumer layout"
        in wrong_references_errors
    )
    assert (
        "referenced preflight references root does not match consumer_before.references_root"
        in wrong_references_errors
    )

    wrong_after_branch = copy.deepcopy(evidence)
    wrong_after_branch["consumer_after"]["branch"] = "wiki/self-attested-after"
    assert (
        "consumer_after.branch does not match the checked consumer branch"
        in validate_migration_evidence(
            wrong_after_branch,
            pkg,
            consumer_root=target,
            kit_root=kit,
            require_git_commits=True,
        )
    )

    verified = compile_migration_report(
        evidence,
        pkg,
        consumer_root=target,
        kit_root=kit,
        require_git_commits=True,
        verify_rollback_execution=True,
    )
    assert verified["status"] == "complete"
    assert verified["rollback_verification"]["status"] == "pass"
    assert verified["rollback_verification"]["tree_matches_before"] is True
    assert verified["rollback_verification"]["worktree_matches_index"] is True

    unchecked_rollback = compile_migration_report(
        evidence,
        pkg,
        consumer_root=target,
        kit_root=kit,
        require_git_commits=True,
    )
    assert unchecked_rollback["status"] == "blocked"
    assert any(
        "requires disposable rollback verification" in error
        for error in unchecked_rollback["validation_errors"]
    )

    mismatched_image = copy.deepcopy(evidence)
    mismatched_image["visual_qa_evidence"][0]["screenshot_sha256"] = "f" * 64
    assert any(
        "screenshot hash/bytes/dimensions do not match" in error
        for error in validate_migration_evidence(
            mismatched_image,
            pkg,
        consumer_root=target,
        kit_root=kit,
        require_git_commits=True,
        )
    )

    source_screenshot = target / evidence["visual_qa_evidence"][0]["screenshot_ref"]
    unignored_screenshot_path = target / "qa/desktop.png"
    unignored_screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    unignored_screenshot_path.write_bytes(source_screenshot.read_bytes())
    unignored_image = copy.deepcopy(evidence)
    unignored_image["visual_qa_evidence"][0]["screenshot_ref"] = "qa/desktop.png"
    assert any(
        "screenshot_ref must be ignored and untracked" in error
        for error in validate_migration_evidence(
            unignored_image,
            pkg,
        consumer_root=target,
        kit_root=kit,
        require_git_commits=True,
        )
    )
    unignored_screenshot_path.unlink()

    symlink_path = target / "output/wiki-upgrade/qa/symlink.png"
    symlink_path.symlink_to("desktop.png")
    symlink_image = copy.deepcopy(evidence)
    symlink_image["visual_qa_evidence"][0]["screenshot_ref"] = (
        "output/wiki-upgrade/qa/symlink.png"
    )
    assert any(
        "screenshot_ref is missing or unsafe" in error
        for error in validate_migration_evidence(
            symlink_image,
            pkg,
        consumer_root=target,
        kit_root=kit,
        require_git_commits=True,
        )
    )
    symlink_path.unlink()

    hardlink_path = target / "output/wiki-upgrade/qa/hardlink.png"
    os.link(target / evidence["visual_qa_evidence"][0]["screenshot_ref"], hardlink_path)
    hardlink_image = copy.deepcopy(evidence)
    hardlink_image["visual_qa_evidence"][0]["screenshot_ref"] = (
        "output/wiki-upgrade/qa/hardlink.png"
    )
    assert any(
        "screenshot_ref is missing or unsafe" in error
        for error in validate_migration_evidence(
            hardlink_image,
            pkg,
        consumer_root=target,
        kit_root=kit,
        require_git_commits=True,
        )
    )
    hardlink_path.unlink()

    rollback_run = subprocess.run(
        shlex.split(evidence["rollback"]["command"]),
        cwd=target,
        text=True,
        capture_output=True,
        check=False,
    )
    assert rollback_run.returncode == 0, rollback_run.stderr + rollback_run.stdout
    assert subprocess.run(
        ["git", "diff", "--quiet", before_sha, "--", "."],
        cwd=target,
        check=False,
    ).returncode == 0
    assert (target / "wiki.config.yaml").read_bytes() == preserved_config

    wrong_rollback = copy.deepcopy(evidence)
    wrong_rollback["rollback"]["command"] = (
        f"git revert --no-commit {commits[0]} {commits[1]} {commits[2]}"
    )
    assert any(
        "exactly revert every non-null migration commit SHA" in error
        for error in validate_migration_evidence(wrong_rollback, pkg)
    )

    injected_rollback = copy.deepcopy(evidence)
    injected_rollback["rollback"]["command"] += " && echo bypass"
    assert any(
        "exactly revert every non-null migration commit SHA" in error
        for error in validate_migration_evidence(injected_rollback, pkg)
    )

    duplicate = copy.deepcopy(evidence)
    duplicate["consumer_after"]["artifact_commit_sha"] = commits[0]
    assert "migration commit boundaries must be distinct" in validate_migration_evidence(
        duplicate,
        pkg,
        consumer_root=target,
        kit_root=kit,
        require_git_commits=True,
    )

    reversed_order = copy.deepcopy(evidence)
    reversed_order["consumer_after"]["artifact_commit_sha"] = commits[2]
    reversed_order["consumer_after"]["adaptation_commit_sha"] = commits[1]
    assert any(
        "migration commit order is invalid" in error
        for error in validate_migration_evidence(
            reversed_order,
            pkg,
            consumer_root=target,
            kit_root=kit,
            require_git_commits=True,
        )
    )

    unavailable = copy.deepcopy(evidence)
    unavailable["consumer_after"]["adaptation_commit_sha"] = sha("not-in-repo")
    assert any(
        "is not available in the consumer repository" in error
        for error in validate_migration_evidence(
            unavailable,
            pkg,
            consumer_root=target,
            kit_root=kit,
            require_git_commits=True,
        )
    )


@pytest.mark.parametrize(
    ("field", "paths", "expected"),
    [
        (
            "files_imported",
            ["tests/generated/state.json", "wiki_core/core.py"],
            "authoritative preflight partition",
        ),
        (
            "downstream_adaptations",
            ["wiki_core/core.py"],
            "must not modify a portable path",
        ),
        (
            "downstream_adaptations",
            ["output/wiki-upgrade/runtime.json"],
            "forbidden runtime or raw evidence",
        ),
    ],
)
def test_checked_migration_rejects_mixed_portable_and_runtime_evidence_paths(
    tmp_path: Path,
    field: str,
    paths: list[str],
    expected: str,
) -> None:
    kit, target, pkg, evidence, _preflight, _before, _commits, _config = (
        exact_three_boundary_fixture(tmp_path)
    )
    evidence[field] = paths
    errors = validate_migration_evidence(
        evidence,
        pkg,
        consumer_root=target,
        kit_root=kit,
        require_git_commits=True,
    )
    assert any(expected in error for error in errors)


@pytest.mark.parametrize(
    "history_kind", ["dummy", "extra", "wrong_blob", "wrong_mode", "merge"]
)
def test_checked_migration_rejects_nonsemantic_boundary_histories(
    tmp_path: Path,
    history_kind: str,
) -> None:
    kit, target, pkg, evidence, _preflight, before, _commits, _config = (
        exact_three_boundary_fixture(tmp_path)
    )
    subprocess.run(
        ["git", "checkout", "-qB", "wiki/adversarial", before],
        cwd=target,
        check=True,
    )

    (target / "wiki_core/core.py").write_bytes(
        b"VALUE = 999\n"
        if history_kind == "wrong_blob"
        else (kit / "wiki_core/core.py").read_bytes()
    )
    if history_kind == "wrong_mode":
        (target / "wiki_core/core.py").chmod(0o755)
    import_sha = commit_all(target, "faithful public import")

    if history_kind == "dummy":
        subprocess.run(
            ["git", "commit", "--allow-empty", "-qm", "artifact marker"],
            cwd=target,
            check=True,
        )
        artifact_sha = repo_head(target)
    elif history_kind == "merge":
        subprocess.run(
            ["git", "checkout", "-qb", "wiki/generated-side", import_sha],
            cwd=target,
            check=True,
        )
        generated_target = target / "tests/generated/state.json"
        generated_target.parent.mkdir(parents=True, exist_ok=True)
        generated_target.write_bytes((kit / "tests/generated/state.json").read_bytes())
        side_sha = commit_all(target, "generated side")
        subprocess.run(
            ["git", "checkout", "-qB", "wiki/adversarial", import_sha],
            cwd=target,
            check=True,
        )
        (target / "wiki.targets.yaml").write_text("targets: []\n", encoding="utf-8")
        commit_all(target, "unrecorded intermediate")
        subprocess.run(
            ["git", "merge", "--no-ff", "-qm", "artifact merge", side_sha],
            cwd=target,
            check=True,
        )
        artifact_sha = repo_head(target)
    else:
        if history_kind == "extra":
            (target / "wiki.targets.yaml").write_text(
                "targets: []\n", encoding="utf-8"
            )
            commit_all(target, "unrecorded intermediate")
        generated_target = target / "tests/generated/state.json"
        generated_target.parent.mkdir(parents=True, exist_ok=True)
        generated_target.write_bytes((kit / "tests/generated/state.json").read_bytes())
        artifact_sha = commit_all(target, "regenerated artifacts")

    (target / "wiki.config.yaml").write_text(
        "repo_id: fixture\nlanguage: pt\ncontexts: [example]\n",
        encoding="utf-8",
    )
    adaptation_sha = commit_all(target, "downstream adaptations")
    bind_boundary_commits(evidence, [import_sha, artifact_sha, adaptation_sha])
    bind_migration_screenshots(target, evidence)
    bind_gate_receipts(target, evidence)

    errors = validate_migration_evidence(
        evidence,
        pkg,
        consumer_root=target,
        kit_root=kit,
        require_git_commits=True,
    )
    if history_kind in {"extra", "merge"}:
        assert any("direct single-parent commit" in error for error in errors)
    elif history_kind == "dummy":
        assert any(
            "generated_artifacts does not exactly match" in error for error in errors
        )
    else:
        assert any("postimages do not match" in error for error in errors)


def test_checked_migration_requires_public_kit_root(tmp_path: Path) -> None:
    _kit, target, pkg, evidence, _preflight, _before, _commits, _config = (
        exact_three_boundary_fixture(tmp_path)
    )
    errors = validate_migration_evidence(
        evidence,
        pkg,
        consumer_root=target,
        require_git_commits=True,
    )
    assert "public kit Git verification root is required for a checked report" in errors


def test_checked_migration_requires_clean_index_and_worktree(tmp_path: Path) -> None:
    kit, target, pkg, evidence, _preflight, _before, _commits, _config = (
        exact_three_boundary_fixture(tmp_path)
    )
    (target / "untracked-local-marker.txt").write_text("dirty\n", encoding="utf-8")
    errors = validate_migration_evidence(
        evidence,
        pkg,
        consumer_root=target,
        kit_root=kit,
        require_git_commits=True,
    )
    assert "checked migration requires a clean consumer index and worktree" in errors


@pytest.mark.parametrize("flag", ["--assume-unchanged", "--skip-worktree"])
def test_checked_migration_rejects_hidden_index_flags(
    tmp_path: Path,
    flag: str,
) -> None:
    kit, target, pkg, evidence, _preflight, _before, _commits, _config = (
        exact_three_boundary_fixture(tmp_path)
    )
    subprocess.run(
        ["git", "update-index", flag, "wiki.config.yaml"],
        cwd=target,
        check=True,
    )
    with (target / "wiki.config.yaml").open("a", encoding="utf-8") as handle:
        handle.write("# hidden runtime mutation\n")
    assert subprocess.check_output(
        ["git", "status", "--porcelain=v1"], cwd=target, text=True
    ).strip() == ""
    errors = validate_migration_evidence(
        evidence,
        pkg,
        consumer_root=target,
        kit_root=kit,
        require_git_commits=True,
    )
    assert "checked migration could not bind an exact Git subject" in errors


def test_private_consumer_uses_ignored_unredacted_authoritative_preflight(
    tmp_path: Path,
) -> None:
    kit, target, pkg, evidence, preflight, _before, _commits, _config = (
        exact_three_boundary_fixture(tmp_path, privacy="financial_personal")
    )
    assert preflight["status"] == "ready"
    assert preflight["privacy"]["report_redacted"] is False
    assert preflight["privacy"]["redaction_required"] is True
    assert preflight["migration_partition"]["portable_drift"]["path_count"] == 2
    assert validate_migration_evidence(
        evidence,
        pkg,
        consumer_root=target,
        kit_root=kit,
        require_git_commits=True,
    ) == []


def test_localized_release_record_is_allowed_but_secret_content_is_blocked(
    tmp_path: Path,
) -> None:
    kit, target, _initial = make_matching_repos(tmp_path)
    generated_source = kit / "tests/generated/state.json"
    generated_source.parent.mkdir(parents=True)
    generated_source.write_text('{"generated":true}\n', encoding="utf-8")
    source_sha = commit_all(kit, "public generated source")

    (target / "wiki_core/core.py").write_text("VALUE = 0\n", encoding="utf-8")
    (target / "wiki.config.yaml").write_text(
        "repo_id: fixture\nlanguage: pt-BR\ncontexts: [pessoal]\n"
        "paths:\n  memory_root: memorias\n"
        "  references_root: docs/referencias\n",
        encoding="utf-8",
    )
    before_sha = commit_all(target, "wiki privada antes da migração")

    pkg = package(source_sha=source_sha)
    current_gates = gate_evidence(before_sha)
    next(
        gate
        for gate in current_gates["gates"]
        if gate["id"] == "toolkit_drift"
    )["status"] = "reviewed"
    preflight = build_preflight_report(
        kit_root=kit,
        consumer_root=target,
        package=pkg,
        consumer=consumer(privacy="financial_personal"),
        gate_evidence=current_gates,
        checked_on="2026-07-12",
        private_evidence_ref="output/wiki-upgrade/preflight-report.json",
    )
    assert preflight["status"] == "ready"

    evidence = migration_evidence(pkg)
    evidence["consumer_before"]["head_sha"] = before_sha
    evidence["files_imported"] = ["wiki_core/core.py"]
    evidence["generated_artifacts"] = ["tests/generated/state.json"]
    evidence["downstream_adaptations"] = ["docs/referencias/releases/rc.md"]
    evidence["rollback"]["preserves_local_paths"] = [
        "wiki.config.yaml",
        "memorias",
    ]
    evidence["rollback"]["previous_sha"] = before_sha
    bind_migration_preflight(target, evidence, pkg, preflight)

    (target / "wiki_core/core.py").write_bytes(
        (kit / "wiki_core/core.py").read_bytes()
    )
    import_sha = commit_all(target, "faithful public import")
    generated_target = target / "tests/generated/state.json"
    generated_target.parent.mkdir(parents=True)
    generated_target.write_bytes(generated_source.read_bytes())
    artifact_sha = commit_all(target, "regenerated artifacts")
    release_record = target / "docs/referencias/releases/rc.md"
    release_record.parent.mkdir(parents=True)
    release_record.write_text(
        "# Wiki Viva v8 rc\n\nDecisões downstream reconciliadas.\n",
        encoding="utf-8",
    )
    adaptation_sha = commit_all(target, "adaptações downstream localizadas")
    bind_boundary_commits(evidence, [import_sha, artifact_sha, adaptation_sha])
    bind_migration_screenshots(target, evidence)
    bind_gate_receipts(target, evidence)

    assert validate_migration_evidence(
        evidence,
        pkg,
        consumer_root=target,
        kit_root=kit,
        require_git_commits=True,
    ) == []
    public_report = compile_migration_report(evidence, pkg, public_export=True)
    assert "docs/referencias/releases/rc.md" not in json.dumps(public_report)
    assert public_report["migration_summary"]["downstream_adaptations"] == {
        "path_count": 1,
        "validated_count": 0,
        "blocked_count": 0,
        "unverified_count": 1,
    }

    release_record.chmod(0o755)
    subprocess.run(["git", "add", str(release_record)], cwd=target, check=True)
    subprocess.run(
        ["git", "commit", "--amend", "--no-edit", "-q"], cwd=target, check=True
    )
    executable_adaptation_sha = repo_head(target)
    bind_boundary_commits(
        evidence,
        [import_sha, artifact_sha, executable_adaptation_sha],
    )
    bind_migration_screenshots(target, evidence)
    bind_gate_receipts(target, evidence)
    executable_errors = validate_migration_evidence(
        evidence,
        pkg,
        consumer_root=target,
        kit_root=kit,
        require_git_commits=True,
    )
    assert (
        "downstream release record postimages must be non-executable Markdown files"
        in executable_errors
    )

    release_record.chmod(0o644)
    release_record.write_text(
        "# Wiki Viva v8 rc\n\napi_key: sk-live-private-secret-value-1234567890\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", str(release_record)], cwd=target, check=True)
    subprocess.run(
        ["git", "commit", "--amend", "--no-edit", "-q"], cwd=target, check=True
    )
    secret_adaptation_sha = repo_head(target)
    bind_boundary_commits(
        evidence,
        [import_sha, artifact_sha, secret_adaptation_sha],
    )
    bind_migration_screenshots(target, evidence)
    bind_gate_receipts(target, evidence)
    secret_errors = validate_migration_evidence(
        evidence,
        pkg,
        consumer_root=target,
        kit_root=kit,
        require_git_commits=True,
    )
    assert any(
        "secret-shaped or unsupported binary content" in error
        for error in secret_errors
    )
    assert "sk-live-private" not in json.dumps(secret_errors)


def test_references_root_only_allows_release_descendants_as_adaptations() -> None:
    pkg = package()
    evidence = migration_evidence(pkg)
    evidence["consumer_before"]["references_root"] = "docs/referencias"

    accepted = copy.deepcopy(evidence)
    accepted["downstream_adaptations"] = ["docs/referencias/releases/rc.md"]
    assert validate_migration_evidence(accepted, pkg) == []

    sibling = copy.deepcopy(evidence)
    sibling["downstream_adaptations"] = ["docs/referencias/notes.md"]
    assert any(
        "is not a declared consumer-owned path" in error
        for error in validate_migration_evidence(sibling, pkg)
    )

    executable = copy.deepcopy(evidence)
    executable["downstream_adaptations"] = [
        "docs/referencias/releases/postinstall.sh"
    ]
    assert any(
        "release record must be a Markdown .md file" in error
        for error in validate_migration_evidence(executable, pkg)
    )

    overlapping_roots = copy.deepcopy(evidence)
    overlapping_roots["consumer_before"]["memory_root"] = "docs"
    overlapping_roots["consumer_before"]["references_root"] = "docs/referencias"
    overlapping_roots["rollback"]["preserves_local_paths"] = [
        "docs",
        "wiki.config.yaml",
    ]
    assert any(
        "memory_root and references_root must be disjoint" in error
        for error in validate_migration_evidence(overlapping_roots, pkg)
    )

    portable_pkg = copy.deepcopy(pkg)
    portable_pkg["portable_import"]["allow"].append(
        "docs/references/releases/**"
    )
    portable = migration_evidence(portable_pkg)
    portable["downstream_adaptations"] = ["docs/references/releases/rc.md"]
    assert any(
        "must not modify a portable path" in error
        for error in validate_migration_evidence(portable, portable_pkg)
    )


def test_localized_memory_root_remains_an_allowed_adaptation_surface() -> None:
    pkg = package()
    evidence = migration_evidence(pkg)
    evidence["consumer_before"]["memory_root"] = "memorias"
    evidence["downstream_adaptations"] = ["memorias/system/operacoes.md"]
    evidence["rollback"]["preserves_local_paths"] = [
        "memorias",
        "wiki.config.yaml",
    ]

    assert validate_migration_evidence(evidence, pkg) == []


def test_consumer_owned_dependency_merge_surface_is_allowed(tmp_path: Path) -> None:
    kit, target, pkg, evidence, _preflight, _before, commits, _config = (
        exact_three_boundary_fixture(tmp_path)
    )
    import_sha, artifact_sha, _old_adaptation = commits
    subprocess.run(
        ["git", "checkout", "-qB", "wiki/dependency-adaptation", artifact_sha],
        cwd=target,
        check=True,
    )
    (target / "requirements.txt").write_text("PyYAML>=6\n", encoding="utf-8")
    adaptation_sha = commit_all(target, "merge consumer dependencies")
    evidence["downstream_adaptations"] = ["requirements.txt"]
    evidence["consumer_after"]["branch"] = "wiki/dependency-adaptation"
    bind_boundary_commits(evidence, [import_sha, artifact_sha, adaptation_sha])
    bind_migration_screenshots(target, evidence)
    bind_gate_receipts(target, evidence)
    assert validate_migration_evidence(
        evidence,
        pkg,
        consumer_root=target,
        kit_root=kit,
        require_git_commits=True,
    ) == []


@pytest.mark.parametrize("adaptation_kind", ["symlink", "deletion"])
def test_checked_adaptation_requires_regular_postimage(
    tmp_path: Path,
    adaptation_kind: str,
) -> None:
    kit, target, pkg, evidence, _preflight, _before, commits, _config = (
        exact_three_boundary_fixture(tmp_path)
    )
    import_sha, artifact_sha, _old_adaptation = commits
    subprocess.run(
        ["git", "checkout", "-qB", "wiki/unsafe-adaptation", artifact_sha],
        cwd=target,
        check=True,
    )
    config_path = target / "wiki.config.yaml"
    config_path.unlink()
    if adaptation_kind == "symlink":
        config_path.symlink_to("../outside-config.yaml")
    adaptation_sha = commit_all(target, f"unsafe {adaptation_kind} adaptation")
    evidence["consumer_after"]["branch"] = "wiki/unsafe-adaptation"
    bind_boundary_commits(evidence, [import_sha, artifact_sha, adaptation_sha])
    bind_migration_screenshots(target, evidence)
    bind_gate_receipts(target, evidence)
    errors = validate_migration_evidence(
        evidence,
        pkg,
        consumer_root=target,
        kit_root=kit,
        require_git_commits=True,
    )
    assert any(
        "secret-shaped or unsupported binary content" in error for error in errors
    )


def test_migration_report_rejects_local_imports_missing_profiles_and_fake_success() -> (
    None
):
    pkg = package()
    evidence = migration_evidence(pkg)
    evidence["files_imported"].append("memories/private.md")
    evidence["visual_qa_evidence"] = evidence["visual_qa_evidence"][:1]
    evidence["gates"][0]["status"] = "fail"
    errors = validate_migration_evidence(evidence, pkg)
    assert any("non-portable path" in error for error in errors)
    assert any("missing profile: mobile" in error for error in errors)
    assert any("gate did not pass" in error for error in errors)


def test_public_migration_report_rejects_absolute_paths_and_unredacted_routes() -> None:
    pkg = package()
    evidence = migration_evidence(pkg)
    evidence["visual_qa_evidence"][0]["screenshot_ref"] = "/Users/example/private.png"
    evidence["visual_qa_evidence"][0]["route_ref"] = "/w?center=private-person"
    errors = validate_migration_evidence(evidence, pkg, public_export=True)
    assert "public migration evidence contains an absolute local path" in errors
    assert any("route_ref is not public-safe" in error for error in errors)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("route_ref", "route:sha256:private-finance-project"),
        ("center_ref", "center:sha256:client-internal-project"),
        ("route_ref", "public-fixture:client-internal-project"),
        ("center_ref", "public-fixture:private-finance-project"),
    ],
)
def test_public_visual_refs_require_closed_hash_or_fixture_ids(
    field: str,
    value: str,
) -> None:
    pkg = package()
    evidence = migration_evidence(pkg)
    evidence["visual_qa_evidence"][0][field] = value
    errors = validate_migration_evidence(evidence, pkg, public_export=True)
    assert any(f"{field} is not public-safe" in error for error in errors)

    report = compile_migration_report(evidence, pkg, public_export=True)
    assert value not in json.dumps(report)
    assert (
        report["visual_qa_evidence"][0][field]
        == "<redacted-public-value>"
    )


def test_blocked_public_report_is_a_fail_closed_sanitized_projection() -> None:
    pkg = package()
    evidence = migration_evidence(pkg)
    raw_secret = "sk-" + "A1b2C3d4E5f6G7h8J9k0L1m2"
    raw_cpf = "529" + ".982.247-25"
    raw_email = "private.owner" + "@example.com"
    raw_path = "/Users/" + f"private.owner/Documents/{raw_cpf}.md"
    raw_other_path = "/var/" + "private-wiki/operator.json"
    raw_short_credential = "password=" + "not-public"
    raw_url = "https://private.example.invalid/view?token=" + raw_secret
    safe_semantic_name = "client-alpha-redesign"

    evidence["source"]["release"] = safe_semantic_name
    evidence["source"]["plan"] = raw_path
    evidence["consumer_before"]["repository"] = raw_email
    evidence["consumer_before"]["kit_version"] = safe_semantic_name
    evidence["omitted_boundaries"] = [
        {"boundary": "artifact_commit_sha", "reason": safe_semantic_name}
    ]
    evidence["files_imported"].append(raw_path)
    evidence["local_overrides_kept"].append(raw_url)
    evidence["fixtures_added"].append("../../" + raw_cpf + ".yaml")
    evidence["warnings"][0]["message"] = (
        raw_secret + " " + raw_short_credential
    )
    evidence["warnings"][0]["removal_window"] = raw_email
    evidence["gates"][0]["command"] = f"run --config {raw_path} --token {raw_secret}"
    evidence["gates"][0]["status"] = safe_semantic_name
    evidence["visual_qa_evidence"][0]["route_ref"] = raw_url
    evidence["visual_qa_evidence"][0]["profile"] = safe_semantic_name
    evidence["visual_qa_evidence"][0]["browser"] = safe_semantic_name
    evidence["visual_qa_evidence"][0]["viewport"] = safe_semantic_name
    evidence["visual_qa_evidence"][0]["screenshot_sha256"] = safe_semantic_name
    evidence["visual_qa_evidence"][0]["center_ref"] = (
        "public-fixture:" + raw_email
    )
    evidence["visual_qa_evidence"][0]["screenshot_ref"] = raw_path
    evidence["rollback"]["command"] += f" && cat {raw_path} {raw_other_path}"
    evidence["rollback"]["command"] += " " + safe_semantic_name
    evidence["rollback"]["preserves_local_paths"].append(raw_path)

    report = compile_migration_report(evidence, pkg, public_export=True)
    json_output = json.dumps(report, ensure_ascii=False, sort_keys=True)
    markdown_output = render_migration_report_markdown(report)
    exported = json_output + markdown_output

    assert report["status"] == "blocked"
    assert "<redacted-public-value>" in exported
    for forbidden in (
        raw_secret,
        raw_cpf,
        raw_email,
        raw_path,
        raw_other_path,
        raw_short_credential,
        raw_url,
        safe_semantic_name,
    ):
        assert forbidden not in exported
    assert not any(
        finding.category in {"secret", "pii", "entity"}
        for finding in scan_text(exported)
    )
    assert "/Users/" not in exported
    assert "../" not in exported
    assert "?token=" not in exported
    assert any("non-portable path" in error for error in report["validation_errors"])


def test_blocked_public_cli_artifacts_stdout_and_stderr_never_echo_rejected_values(
    tmp_path: Path,
) -> None:
    pkg = package()
    evidence = migration_evidence(pkg)
    raw_secret = "sk-" + "Z9y8X7w6V5u4T3s2R1q0P9o8"
    raw_cpf = "529" + ".982.247-25"
    raw_path = "/Users/" + f"private.owner/Documents/{raw_cpf}.md"
    raw_email = "private.owner" + "@example.com"
    evidence["consumer_before"]["repository"] = raw_email
    evidence["files_imported"].append(raw_path)
    evidence["warnings"][0]["message"] = raw_secret
    evidence["visual_qa_evidence"][0]["screenshot_ref"] = raw_path

    package_path = tmp_path / "package.yaml"
    evidence_path = tmp_path / "migration.yaml"
    json_out = tmp_path / "public-report.json"
    markdown_out = tmp_path / "public-report.md"
    package_path.write_text(yaml.safe_dump(pkg, sort_keys=False), encoding="utf-8")
    evidence_path.write_text(
        yaml.safe_dump(evidence, sort_keys=False), encoding="utf-8"
    )

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/wiki_upgrade_report.py"),
            "--package",
            str(package_path),
            "--evidence",
            str(evidence_path),
            "--public-export",
            "--json-out",
            str(json_out),
            "--markdown-out",
            str(markdown_out),
            "--check",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert json.loads(json_out.read_text(encoding="utf-8"))["status"] == "blocked"
    exported = (
        result.stdout
        + result.stderr
        + json_out.read_text(encoding="utf-8")
        + markdown_out.read_text(encoding="utf-8")
    )
    for forbidden in (raw_secret, raw_cpf, raw_email, raw_path):
        assert forbidden not in exported
    assert not any(
        finding.category in {"secret", "pii", "entity"}
        for finding in scan_text(exported)
    )
    assert result.stderr == ""


def test_public_cli_load_error_does_not_echo_private_input_path(tmp_path: Path) -> None:
    pkg = package()
    raw_cpf = "529" + ".982.247-25"
    private_name = "private-" + raw_cpf + ".yaml"
    package_path = tmp_path / "package.yaml"
    invalid_evidence_path = tmp_path / private_name
    package_path.write_text(yaml.safe_dump(pkg, sort_keys=False), encoding="utf-8")
    invalid_evidence_path.write_text("- not-a-mapping\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/wiki_upgrade_report.py"),
            "--package",
            str(package_path),
            "--evidence",
            str(invalid_evidence_path),
            "--public-export",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert json.loads(result.stdout)["status"] == "invalid"
    assert raw_cpf not in result.stdout + result.stderr
    assert private_name not in result.stdout + result.stderr
    assert str(invalid_evidence_path) not in result.stdout + result.stderr
    assert result.stderr == ""


@pytest.mark.parametrize(
    "raw_payload",
    [
        b"source:\n  plan: [sk-private-client-secret-1234567890\n",
        b"source:\n  plan: /Users/private/client.yaml\n\xff\xfe",
        b"schema_version: wiki_viva_migration_evidence.v2\nclient-alpha-redesign: 2026-07-12\n",
        b"schema_version: wiki_viva_migration_evidence.v2\ncycle: &self\n  nested: *self\n",
    ],
)
def test_public_cli_non_json_yaml_or_utf8_never_echoes_input(
    tmp_path: Path,
    raw_payload: bytes,
) -> None:
    pkg = package()
    package_path = tmp_path / "package.yaml"
    evidence_path = tmp_path / "client-alpha-redesign.yaml"
    package_path.write_text(yaml.safe_dump(pkg, sort_keys=False), encoding="utf-8")
    evidence_path.write_bytes(raw_payload)
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/wiki_upgrade_report.py"),
            "--package",
            str(package_path),
            "--evidence",
            str(evidence_path),
            "--public-export",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    exported = result.stdout + result.stderr
    assert result.returncode == 2
    assert json.loads(result.stdout)["status"] == "invalid"
    assert "sk-private" not in exported
    assert "/Users/private" not in exported
    assert "client-alpha-redesign" not in exported
    assert result.stderr == ""


def test_placeholder_shas_cannot_complete_a_migration_report() -> None:
    pkg = package()
    evidence = migration_evidence(pkg)
    evidence["source"]["sha"] = "0" * 40
    errors = validate_migration_evidence(evidence, pkg)
    assert any("source.sha must be an exact" in error for error in errors)


def test_unpinned_public_package_cannot_produce_a_complete_migration_report() -> None:
    pkg = package(pinned=False)
    evidence = migration_evidence(package())
    evidence["source"]["release"] = pkg["release"]["id"]
    evidence["source"]["plan"] = pkg["release"]["plan"]
    report = compile_migration_report(evidence, pkg)
    assert report["status"] == "blocked"
    assert (
        "upgrade package release is blocked or source_sha is not pinned"
        in report["validation_errors"]
    )


def test_upgrade_cli_entrypoints_execute_end_to_end_on_synthetic_consumer(
    tmp_path: Path,
) -> None:
    kit, target, _initial = make_matching_repos(tmp_path)
    generated_source = kit / "tests/generated/state.json"
    generated_source.parent.mkdir(parents=True)
    generated_source.write_text('{"generated":true}\n', encoding="utf-8")
    source_sha = commit_all(kit, "public generated source")
    (target / "wiki_core/core.py").write_text("VALUE = 0\n", encoding="utf-8")
    head = commit_all(target, "consumer before upgrade")
    pkg = package(source_sha=source_sha)
    inventory = {
        "schema_version": CONSUMER_INVENTORY_SCHEMA_VERSION,
        "verified_on": "2026-07-09",
        "consumers": [consumer()],
    }
    package_path = tmp_path / "package.yaml"
    inventory_path = tmp_path / "inventory.yaml"
    gates_path = tmp_path / "gates.json"
    evidence_path = tmp_path / "migration.yaml"
    package_path.write_text(yaml.safe_dump(pkg, sort_keys=False), encoding="utf-8")
    inventory_path.write_text(
        yaml.safe_dump(inventory, sort_keys=False), encoding="utf-8"
    )
    current_gates = gate_evidence(head)
    next(
        gate
        for gate in current_gates["gates"]
        if gate["id"] == "toolkit_drift"
    )["status"] = "reviewed"
    gates_path.write_text(json.dumps(current_gates), encoding="utf-8")

    inventory_run = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/wiki_upgrade_inventory.py"),
            "--inventory",
            str(inventory_path),
            "--check",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert inventory_run.returncode == 0, inventory_run.stderr + inventory_run.stdout

    preflight_run = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/wiki_upgrade_preflight.py"),
            "--kit-root",
            str(kit),
            "--consumer-root",
            str(target),
            "--consumer-id",
            "consumer-one",
            "--package",
            str(package_path),
            "--inventory",
            str(inventory_path),
            "--gate-evidence",
            str(gates_path),
            "--checked-on",
            "2026-07-09",
            "--check",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert preflight_run.returncode == 0, preflight_run.stderr + preflight_run.stdout
    preflight_report = json.loads(preflight_run.stdout)
    assert preflight_report["status"] == "ready"

    migration = migration_evidence(pkg)
    migration["consumer_before"]["head_sha"] = head
    migration["files_imported"] = ["wiki_core/core.py"]
    migration["generated_artifacts"] = ["tests/generated/state.json"]
    migration["downstream_adaptations"] = ["wiki.config.yaml"]
    bind_migration_preflight(target, migration, pkg, preflight_report)

    (target / "wiki_core/core.py").write_bytes(
        (kit / "wiki_core/core.py").read_bytes()
    )
    import_sha = commit_all(target, "faithful public import")
    generated_target = target / "tests/generated/state.json"
    generated_target.parent.mkdir(parents=True)
    generated_target.write_bytes(generated_source.read_bytes())
    artifact_sha = commit_all(target, "regenerated artifacts")
    (target / "wiki.config.yaml").write_text(
        "repo_id: fixture\nlanguage: pt\ncontexts: [example]\n",
        encoding="utf-8",
    )
    adaptation_sha = commit_all(target, "downstream adaptations")
    migration_commits = [import_sha, artifact_sha, adaptation_sha]
    migration["consumer_after"].update(
        {
            "import_commit_sha": migration_commits[0],
            "artifact_commit_sha": migration_commits[1],
            "adaptation_commit_sha": migration_commits[2],
        }
    )
    migration["evidence_context"]["captured_consumer_head"] = migration_commits[2]
    for gate in migration["gates"]:
        gate["captured_consumer_head"] = migration_commits[2]
    for item in migration["visual_qa_evidence"]:
        item["captured_consumer_head"] = migration_commits[2]
    migration["rollback"].update(
        {
            "previous_sha": head,
            "import_commit_sha": migration_commits[0],
            "command": (
                f"git revert --no-commit {migration_commits[2]} {migration_commits[1]} "
                f"{migration_commits[0]}"
            ),
        }
    )
    bind_migration_screenshots(target, migration)
    bind_gate_receipts(target, migration)
    evidence_path.write_text(
        yaml.safe_dump(migration, sort_keys=False), encoding="utf-8"
    )

    json_out = tmp_path / "migration-report.json"
    markdown_out = tmp_path / "migration-report.md"
    missing_kit_run = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/wiki_upgrade_report.py"),
            "--package",
            str(package_path),
            "--evidence",
            str(evidence_path),
            "--consumer-root",
            str(target),
            "--public-export",
            "--check",
            "--verify-rollback",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert missing_kit_run.returncode == 1
    missing_kit_report = json.loads(missing_kit_run.stdout)
    assert missing_kit_report["status"] == "blocked"
    assert any(
        "public kit Git verification root is required" in error
        for error in missing_kit_report["validation_errors"]
    )

    report_run = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/wiki_upgrade_report.py"),
            "--package",
            str(package_path),
            "--evidence",
            str(evidence_path),
            "--consumer-root",
            str(target),
            "--kit-root",
            str(kit),
            "--public-export",
            "--json-out",
            str(json_out),
            "--markdown-out",
            str(markdown_out),
            "--check",
            "--verify-rollback",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert report_run.returncode == 0, report_run.stderr + report_run.stdout
    checked_report = json.loads(json_out.read_text(encoding="utf-8"))
    assert checked_report["status"] == "complete"
    assert checked_report["migration_summary"]["downstream_adaptations"] == {
        "path_count": 1,
        "validated_count": 1,
        "blocked_count": 0,
        "unverified_count": 0,
    }
    assert "## Rollback" in markdown_out.read_text(encoding="utf-8")


def _preflight_cli_args(
    *,
    kit: Path,
    target: Path,
    package_path: Path,
    inventory_path: Path,
    gates_path: Path,
) -> list[str]:
    return [
        sys.executable,
        str(ROOT / "scripts/wiki_upgrade_preflight.py"),
        "--kit-root",
        str(kit),
        "--consumer-root",
        str(target),
        "--consumer-id",
        "consumer-one",
        "--package",
        str(package_path),
        "--inventory",
        str(inventory_path),
        "--gate-evidence",
        str(gates_path),
        "--checked-on",
        "2026-07-12",
    ]


def test_preflight_cli_private_sidecar_is_authoritative_and_never_echoed(
    tmp_path: Path,
) -> None:
    kit, target, head = make_matching_repos(tmp_path)
    source_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=kit,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    pkg = package(source_sha=source_sha)
    inventory = {
        "schema_version": CONSUMER_INVENTORY_SCHEMA_VERSION,
        "verified_on": "2026-07-12",
        "consumers": [consumer(privacy="financial_personal")],
    }
    package_path = tmp_path / "package.yaml"
    inventory_path = tmp_path / "inventory.yaml"
    gates_path = tmp_path / "gates.json"
    package_path.write_text(yaml.safe_dump(pkg, sort_keys=False), encoding="utf-8")
    inventory_path.write_text(
        yaml.safe_dump(inventory, sort_keys=False), encoding="utf-8"
    )
    current_gates = gate_evidence(head)
    gates_path.write_text(json.dumps(current_gates), encoding="utf-8")
    base_args = _preflight_cli_args(
        kit=kit,
        target=target,
        package_path=package_path,
        inventory_path=inventory_path,
        gates_path=gates_path,
    )
    sidecar_ref = "output/wiki-upgrade/preflight-report.json"
    sidecar_path = target / sidecar_ref

    accepted = subprocess.run(
        [*base_args, "--private-evidence-ref", sidecar_ref, "--check"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert accepted.returncode == 0, accepted.stderr + accepted.stdout
    # The unredacted authority payload lives only in the ignored sidecar.
    assert accepted.stdout == ""
    written = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert written["status"] == "ready"
    assert written["privacy"]["authoritative_private"] is True
    assert written["privacy"]["authoritative_ref"] == sidecar_ref
    assert written["privacy"]["report_redacted"] is False
    ignored = subprocess.run(
        ["git", "check-ignore", "--quiet", sidecar_ref],
        cwd=target,
        check=False,
    )
    assert ignored.returncode == 0

    tracked_ref = "wiki.config.yaml"
    rejected = subprocess.run(
        [*base_args, "--private-evidence-ref", tracked_ref],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert rejected.returncode == 2
    rejection = json.loads(rejected.stdout)
    assert rejection["status"] == "invalid"
    assert "authoritative sidecar" in rejection["errors"][0]
    # The tracked file must keep its original content: nothing was written.
    assert "repo_id: fixture" in (target / tracked_ref).read_text(encoding="utf-8")

    contradictory = subprocess.run(
        [*base_args, "--private-evidence-ref", sidecar_ref, "--redact"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert contradictory.returncode == 2
    assert "cannot be combined with --redact" in contradictory.stderr

    out_path = tmp_path / "preflight-out.json"
    redacted_out = subprocess.run(
        [*base_args, "--redact", "--out", str(out_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert redacted_out.returncode == 0, redacted_out.stderr + redacted_out.stdout
    # --out writes the file without echoing the report to stdout.
    assert redacted_out.stdout == ""
    projected = json.loads(out_path.read_text(encoding="utf-8"))
    assert projected["privacy"]["report_redacted"] is True


def test_upgrade_package_requires_exact_gate_command_registry() -> None:
    missing = package()
    del missing["migration"]["gate_commands"]
    assert (
        "migration.gate_commands must register the exact command for "
        "every required gate"
    ) in validate_upgrade_package(missing)

    partial = package()
    del partial["migration"]["gate_commands"]["bundle"]
    assert (
        "migration.gate_commands must cover exactly migration.required_gates"
    ) in validate_upgrade_package(partial)

    placeholder = package()
    placeholder["migration"]["gate_commands"]["audit"] = "record exact audit command"
    assert any(
        "migration.gate_commands.audit must be an exact command" in error
        for error in validate_upgrade_package(placeholder)
    )

    free_text = package()
    evidence = migration_evidence(free_text)
    evidence["gates"][0]["command"] = "python3 scripts/my_own_wrapper.py"
    assert any(
        "does not match the package gate command registry" in error
        for error in validate_migration_evidence(evidence, free_text)
    )


def test_checked_migration_gates_require_executed_receipts(tmp_path: Path) -> None:
    kit, target, pkg, evidence, _preflight, _before, _commits, _cfg = (
        exact_three_boundary_fixture(tmp_path)
    )

    def checked_errors(current: dict) -> list[str]:
        return validate_migration_evidence(
            current,
            pkg,
            consumer_root=target,
            kit_root=kit,
            require_git_commits=True,
        )

    assert checked_errors(evidence) == []
    receipt_path = target / evidence["gates_receipt_ref"]
    original = receipt_path.read_text(encoding="utf-8")

    without_ref = json.loads(json.dumps(evidence))
    del without_ref["gates_receipt_ref"]
    assert (
        "checked migration evidence requires gates_receipt_ref: an ignored "
        "untracked receipt of the executed gate commands"
    ) in checked_errors(without_ref)

    tracked = json.loads(json.dumps(evidence))
    tracked["gates_receipt_ref"] = "data/derived/wiki/web-snapshot/manifest.json"
    assert (
        "gates_receipt_ref must be ignored and untracked in the consumer"
    ) in checked_errors(tracked)

    unregistered = json.loads(original)
    unregistered["gates"][0]["command"] = "python3 scripts/my_own_wrapper.py"
    receipt_path.write_text(
        json.dumps(unregistered, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    assert any(
        "gate receipt command does not match the package registry" in error
        for error in checked_errors(evidence)
    )

    failed_run = json.loads(original)
    failed_run["gates"][1]["exit_code"] = 1
    receipt_path.write_text(
        json.dumps(failed_run, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    assert any(
        "gate receipt exit_code must be 0" in error
        for error in checked_errors(evidence)
    )

    unhashed = json.loads(original)
    unhashed["gates"][2]["output_sha256"] = "not-a-hash"
    receipt_path.write_text(
        json.dumps(unhashed, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    assert any(
        "gate receipt output_sha256 must be a lowercase sha256" in error
        for error in checked_errors(evidence)
    )

    stale = json.loads(original)
    stale["captured_consumer_head"] = sha("stale-receipt-head")
    receipt_path.write_text(
        json.dumps(stale, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    assert (
        "gate receipts captured_consumer_head must match the final "
        "migration boundary"
    ) in checked_errors(evidence)

    receipt_path.write_text(original, encoding="utf-8")
    assert checked_errors(evidence) == []
