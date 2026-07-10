from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import yaml

from wiki_core.upgrade import (
    CONSUMER_INVENTORY_SCHEMA_VERSION,
    GATE_EVIDENCE_SCHEMA_VERSION,
    MIGRATION_EVIDENCE_SCHEMA_VERSION,
    UPGRADE_PACKAGE_SCHEMA_VERSION,
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
            "snapshot": "wiki_web_snapshot.v2",
            "blocks": "wiki_templates.v2",
            "visual_grammar": "wiki_visual_grammar.v8",
            "runtime": "wiki_world_runtime.v8",
            "source_lifecycle": "wiki_source_lifecycle.v2",
        },
        "portable_import": {
            "allow": ["wiki_core/**", "scripts/wiki_*.py", "tests/**"],
            "block": [
                "memories/**",
                "wiki.config.yaml",
                "apps/wiki-cockpit/public/wiki-cockpit.config.json",
                "data/derived/**",
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
    assert pkg["release"]["source_sha"] == "f7f95119778246d2c420523a143909eda8575dbd"
    assert portable_path_status("apps/wiki-cockpit/.env.local", pkg)[0] is False
    assert (
        portable_path_status(
            "apps/wiki-cockpit/public/wiki-cockpit.config.json", pkg
        )[0]
        is False
    )


def test_portable_blocklist_wins_and_private_paths_are_not_importable() -> None:
    pkg = package()
    assert portable_path_status("wiki_core/core.py", pkg)[0] is True
    assert portable_path_status("scripts/wiki_upgrade_report.py", pkg)[0] is True
    assert portable_path_status("memories/private.md", pkg)[0] is False
    assert portable_path_status("wiki.config.yaml", pkg)[0] is False
    assert (
        portable_path_status(
            "apps/wiki-cockpit/public/wiki-cockpit.config.json", pkg
        )[0]
        is False
    )
    assert portable_path_status("random.txt", pkg)[0] is False


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
    pkg["portable_import"] = {"allow": ["foo/**"], "block": []}

    assert portable_path_status("foo", pkg)[0] is True
    assert portable_path_status("foo/bar.txt", pkg)[0] is True
    assert portable_path_status("foo/nested/bar.txt", pkg)[0] is True
    assert portable_path_status("foobar/bar.txt", pkg)[0] is False


def test_portable_drift_is_byte_exact_and_honors_consumer_ignore(
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
    assert ignored["drift_total"] == 0
    assert ignored["ignored_per_repo"] == ["wiki_core/core.py"]


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
    assert "## Rollback" in markdown
    assert first["report_id"] in markdown


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
    evidence_path.write_text(
        yaml.safe_dump(migration_evidence(pkg), sort_keys=False), encoding="utf-8"
    )

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
