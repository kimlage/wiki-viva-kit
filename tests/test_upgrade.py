from __future__ import annotations

import copy
import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from wiki_core.detectors import scan_text
from wiki_core.upgrade import (
    CONSUMER_INVENTORY_SCHEMA_VERSION,
    GATE_EVIDENCE_SCHEMA_VERSION,
    MIGRATION_EVIDENCE_SCHEMA_VERSION,
    UPGRADE_PACKAGE_SCHEMA_VERSION,
    _git_blob_payloads,
    build_preflight_report,
    compare_portable_files,
    compile_migration_report,
    package_is_pinned,
    portable_path_status,
    render_migration_report_markdown,
    validate_consumer_inventory,
    validate_migration_evidence,
    validate_upgrade_package,
)


ROOT = Path(__file__).resolve().parents[1]


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
            "required_gates": ["audit", "bundle", "diff_check"],
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
        "current_layout": {"memory_root": "memories"},
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
    return {
        "schema_version": MIGRATION_EVIDENCE_SCHEMA_VERSION,
        "source": {
            "release": pkg["release"]["id"],
            "sha": pkg["release"]["source_sha"],
            "plan": pkg["release"]["plan"],
        },
        "consumer_before": {
            "repository": "public-fixture-consumer",
            "branch": "wiki/upgrade-v8",
            "head_sha": sha("consumer-before"),
            "kit_version": "v7",
            "gate_status": "pass",
        },
        "consumer_after": {
            "branch": "wiki/upgrade-v8",
            "import_commit_sha": sha("import"),
            "artifact_commit_sha": sha("artifact"),
            "adaptation_commit_sha": sha("adaptation"),
        },
        "files_imported": ["wiki_core/core.py", "scripts/wiki_upgrade_report.py"],
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
            {"id": gate_id, "command": f"run {gate_id}", "status": "pass"}
            for gate_id in pkg["migration"]["required_gates"]
        ],
        "visual_qa_evidence": [
            {
                "profile": profile,
                "route_ref": "public-fixture:root",
                "center_ref": "public-fixture:root",
                "viewport": "390x844" if profile == "mobile" else "1440x1000",
                "browser": "webkit" if profile == "mobile" else "chromium",
                "screenshot_ref": f"qa/{profile}.png",
                "console_status": "clean",
                "network_status": "clean",
                "sample_fallback": False,
            }
            for profile in ("desktop", "mobile", "fallback")
        ],
        "rollback": {
            "previous_sha": sha("consumer-before"),
            "import_commit_sha": sha("import"),
            "command": "git revert adaptation artifacts import",
            "preserves_local_paths": ["wiki.config.yaml", "memories/"],
        },
    }


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
    assert package_is_pinned(pkg) is True
    assert pkg["release"]["status"] == "release_candidate"
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
        assert pkg["schema_version"] == UPGRADE_PACKAGE_SCHEMA_VERSION
        assert pkg["contract_versions"] == v2_contracts
    assert portable_path_status("apps/wiki-cockpit/.env.local", pkg)[0] is False
    expected_v2_portable = pkg["schema_version"] == UPGRADE_PACKAGE_SCHEMA_VERSION
    assert portable_path_status("packs/personal-finance/pack.yaml", pkg)[0] is expected_v2_portable
    assert (
        portable_path_status(
            "docs/references/schemas/wiki-temporal-graph-v1.schema.json", pkg
        )[0]
        is expected_v2_portable
    )
    assert portable_path_status("scripts/_git_subject.py", pkg)[0] is expected_v2_portable
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


def test_preflight_blocks_unpinned_dirty_drifted_or_unredacted_private_consumer(
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


def test_private_risk_cannot_opt_out_of_required_redaction(tmp_path: Path) -> None:
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


def test_redacted_preflight_never_emits_local_drift_or_status_paths(
    tmp_path: Path,
) -> None:
    kit, target, head = make_matching_repos(tmp_path)
    private_name = "client-secret-adapter.py"
    (target / "tests" / private_name).parent.mkdir(parents=True)
    (target / "tests" / private_name).write_text(
        "# private fixture name\n", encoding="utf-8"
    )
    report = build_preflight_report(
        kit_root=kit,
        consumer_root=target,
        package=package(source_sha=repo_head(kit)),
        consumer=consumer(privacy="financial_personal"),
        gate_evidence=gate_evidence(head),
        checked_on="2026-07-09",
        redact=True,
    )
    serialized = json.dumps(report)
    assert private_name not in serialized
    assert str(target) not in serialized
    assert head not in serialized
    assert report["consumer_before"]["path"] == "<redacted-local-path>"
    assert report["consumer_before"]["head_sha"].startswith("consumer-head:sha256:")
    assert report["consumer_before"]["status_short"] == []
    assert report["consumer_before"]["status_entry_count"] == 1
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
    markdown = render_migration_report_markdown(first)
    assert "Faithful public import" in markdown
    assert "## Warnings" in markdown
    assert "consumer-maintainer" in markdown
    assert "v9 stable" in markdown
    assert "## Rollback" in markdown
    assert first["report_id"] in markdown


def test_migration_boundaries_must_be_distinct_existing_and_ancestry_ordered(
    tmp_path: Path,
) -> None:
    kit, target, before_sha = make_matching_repos(tmp_path)
    boundary = target / "migration-boundary.txt"
    commits: list[str] = []
    for stage in ("import", "artifacts", "adaptation"):
        boundary.write_text(f"{stage}\n", encoding="utf-8")
        commits.append(commit_all(target, stage))

    pkg = package(source_sha=repo_head(kit))
    evidence = migration_evidence(pkg)
    evidence["consumer_before"]["head_sha"] = before_sha
    evidence["consumer_after"].update(
        {
            "import_commit_sha": commits[0],
            "artifact_commit_sha": commits[1],
            "adaptation_commit_sha": commits[2],
        }
    )
    evidence["rollback"].update(
        {
            "previous_sha": before_sha,
            "import_commit_sha": commits[0],
            "command": f"git revert {commits[2]} {commits[1]} {commits[0]}",
        }
    )

    assert validate_migration_evidence(
        evidence,
        pkg,
        consumer_root=target,
        require_git_commits=True,
    ) == []

    duplicate = copy.deepcopy(evidence)
    duplicate["consumer_after"]["artifact_commit_sha"] = commits[0]
    assert "migration commit boundaries must be distinct" in validate_migration_evidence(
        duplicate,
        pkg,
        consumer_root=target,
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
            require_git_commits=True,
        )
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

    evidence["source"]["plan"] = raw_path
    evidence["consumer_before"]["repository"] = raw_email
    evidence["files_imported"].append(raw_path)
    evidence["local_overrides_kept"].append(raw_url)
    evidence["fixtures_added"].append("../../" + raw_cpf + ".yaml")
    evidence["warnings"][0]["message"] = (
        raw_secret + " " + raw_short_credential
    )
    evidence["warnings"][0]["removal_window"] = raw_email
    evidence["gates"][0]["command"] = f"run --config {raw_path} --token {raw_secret}"
    evidence["visual_qa_evidence"][0]["route_ref"] = raw_url
    evidence["visual_qa_evidence"][0]["center_ref"] = (
        "public-fixture:" + raw_email
    )
    evidence["visual_qa_evidence"][0]["screenshot_ref"] = raw_path
    evidence["rollback"]["command"] += f" && cat {raw_path} {raw_other_path}"
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
    kit, target, head = make_matching_repos(tmp_path)
    pkg = package(source_sha=repo_head(kit))
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
    gates_path.write_text(json.dumps(gate_evidence(head)), encoding="utf-8")

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
    assert json.loads(preflight_run.stdout)["status"] == "ready"

    boundary = target / "migration-boundary.txt"
    migration_commits: list[str] = []
    for stage in ("import", "artifacts", "adaptation"):
        boundary.write_text(f"{stage}\n", encoding="utf-8")
        migration_commits.append(commit_all(target, stage))
    migration = migration_evidence(pkg)
    migration["consumer_before"]["head_sha"] = head
    migration["consumer_after"].update(
        {
            "import_commit_sha": migration_commits[0],
            "artifact_commit_sha": migration_commits[1],
            "adaptation_commit_sha": migration_commits[2],
        }
    )
    migration["rollback"].update(
        {
            "previous_sha": head,
            "import_commit_sha": migration_commits[0],
            "command": (
                f"git revert {migration_commits[2]} {migration_commits[1]} "
                f"{migration_commits[0]}"
            ),
        }
    )
    evidence_path.write_text(
        yaml.safe_dump(migration, sort_keys=False), encoding="utf-8"
    )

    json_out = tmp_path / "migration-report.json"
    markdown_out = tmp_path / "migration-report.md"
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
    assert report_run.returncode == 0, report_run.stderr + report_run.stdout
    assert json.loads(json_out.read_text(encoding="utf-8"))["status"] == "complete"
    assert "## Rollback" in markdown_out.read_text(encoding="utf-8")
