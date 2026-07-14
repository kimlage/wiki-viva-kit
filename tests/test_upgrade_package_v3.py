from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator

from wiki_core.upgrade import (
    CONFIG_BOUND_C3_ROLE_SPECS,
    boundary_operations_sha256,
    canonical_json,
    portable_path_status,
    validate_upgrade_package,
)
from wiki_core.upgrade_lanes import (
    NEVER_REUSABLE_GATES,
    load_mapping,
    verify_impact_registry,
)


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = (
    ROOT / "docs/references/schemas/wiki-upgrade-package-v3.schema.json"
)


def _schema_validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _command_digest(package: dict) -> str:
    migration = package["migration"]
    projection = sorted(
        (
            {
                "id": gate_id,
                "class": migration["gate_policies"][gate_id]["class"],
                "command": migration["gate_commands"][gate_id],
            }
            for gate_id in migration["required_gates"]
        ),
        key=lambda item: item["id"],
    )
    return hashlib.sha256(canonical_json(projection).encode("utf-8")).hexdigest()


def _package_v3() -> dict:
    gate_commands = {
        "audit": "python3 scripts/wiki_audit.py --check",
        "background_suite": "python3 -m pytest tests/",
        "bundle": "npm --prefix apps/wiki-cockpit run check:bundle",
        "focused_frontend": "npm --prefix apps/wiki-cockpit test",
        "real_canary": "npm --prefix apps/wiki-cockpit run test:e2e:operator",
    }
    gate_policies = {
        "audit": {
            "class": "consumer_always",
            "command_id": "audit",
            "asserts": ["secret_private_audit"],
            "reuse": "never",
            "depends_on": [],
            "resource_group": "python_readonly",
            "required_for_promotion": True,
        },
        "background_suite": {
            "class": "background_certification",
            "command_id": "background_suite",
            "asserts": ["consumer_python_suite"],
            "reuse": "never",
            "depends_on": ["real_canary"],
            "resource_group": "python_test",
            "required_for_promotion": True,
        },
        "bundle": {
            "class": "upstream_certified",
            "command_id": "bundle",
            "asserts": ["bundle_budget"],
            "reuse": "exact_capsule",
            "depends_on": [],
            "resource_group": "node_build",
            "required_for_promotion": True,
        },
        "focused_frontend": {
            "class": "affected",
            "command_id": "focused_frontend",
            "asserts": ["frontend_consumer_delta"],
            "reuse": "impact",
            "depends_on": ["audit"],
            "resource_group": "node_test",
            "required_for_promotion": True,
        },
        "real_canary": {
            "class": "canary",
            "command_id": "real_canary",
            "asserts": ["canary_real"],
            "reuse": "never",
            "depends_on": ["audit", "focused_frontend"],
            "resource_group": "browser_private",
            "required_for_promotion": True,
        },
    }
    package = {
        "schema_version": "wiki_viva_upgrade_package.v3",
        "release": {
            "id": "wiki-viva-v8-public-synthetic",
            "status": "candidate",
            "source_sha": "1" * 40,
            "plan": "docs/references/proposals/synthetic-v8.md",
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
            "consumer_c3_authority": "wiki_viva_upgrade_consumer_c3_authority.v1",
        },
        "portable_import": {
            "allow": [
                "apps/wiki-cockpit/**",
                "scripts/wiki_*.py",
                "wiki_core/**",
            ],
            # The broader block proves glob containment: every path owned by
            # the sample-snapshot C2 subtree is outside effective C1.
            "block": [
                "apps/wiki-cockpit/public/**",
                "memories/**",
                "wiki.config.yaml",
            ],
        },
        "preflight": {
            "branch_prefix": "wiki/",
            "required_gates": ["audit"],
            "gate_mapping": {"audit": "audit"},
        },
        "migration": {
            "commit_boundaries": [
                "faithful_public_import",
                "regenerated_artifacts",
                "downstream_adaptations",
            ],
            "generated_artifact_patterns": [
                "apps/wiki-cockpit/public/sample-snapshot/**"
            ],
            "required_gates": sorted(gate_commands),
            "gate_commands": gate_commands,
            "command_registry": {
                gate_id: {
                    "argv": ["sh", "-c", command],
                    "cwd": ".",
                    "timeout_seconds": 900,
                    "env_allowlist": [],
                }
                for gate_id, command in gate_commands.items()
            },
            "command_registry_sha256": "0" * 64,
            "impact_registry": {
                "schema_version": "wiki_viva_upgrade_impact_registry.v1",
                "path": "docs/references/upgrades/wiki-viva-v8/impact-registry.yaml",
                "sha256": "2" * 64,
            },
            "gate_policies": gate_policies,
            "acceptance_budget": {
                "schema_version": "wiki_viva_upgrade_acceptance_budget_policy.v1",
                "scope": "plan_to_real_canary",
                "limit_seconds": 1200,
                "enforcement": "promotion_blocking",
            },
            "boundary_operations": {
                "schema_version": "wiki_viva_upgrade_boundary_operations.v2",
                "c2_generators": [
                    {
                        "id": "demo_snapshot",
                        "command": "python3 scripts/wiki_build_demo.py",
                        "owns_patterns": [
                            "apps/wiki-cockpit/public/sample-snapshot/**"
                        ],
                    }
                ],
                "c3_adapter": {
                    "mode": "consumer_plan_commands",
                    "contract": "wiki_consumer_adaptation_plan.v2",
                    "owns_patterns": ["tests/**"],
                    "configured_ownership": {
                        "schema_version": "wiki_viva_config_bound_c3_policy.v1",
                        "config_path": "wiki.config.yaml",
                        "roles": [dict(item) for item in CONFIG_BOUND_C3_ROLE_SPECS],
                    },
                },
                "registry_sha256": "0" * 64,
            },
            "visual_profiles": ["desktop", "mobile", "fallback"],
        },
        "runtime_policy": {
            "rollout_modes": ["legacy", "compat", "v8"],
            "initial_downstream_mode": "compat",
            "rollback_first": "switch_to_compat_or_legacy",
            "rollback_second": "revert_reviewable_commits",
            "flags_must_not_weaken": [
                "route_grammar",
                "secret_scanning",
                "public_private_boundary",
            ],
        },
        "compatibility": [
            {
                "surface": "legacy_routes",
                "v8_behavior": "normalize_with_explicit_compat_identity",
                "warning_becomes_error": "future_evidence_based_release",
                "removal_target": "no_removal_without_replacement",
            }
        ],
        "privacy": {
            "default_public_report": "redacted",
            "never_publish": [
                "private_screenshots",
                "raw_private_visual_pixels",
                "secrets_or_credentials",
            ],
        },
        "known_limitations": [
            "This fixture is synthetic and grants no release authority."
        ],
    }
    package["migration"]["command_registry_sha256"] = _command_digest(package)
    boundary = package["migration"]["boundary_operations"]
    boundary["registry_sha256"] = boundary_operations_sha256(boundary)
    return package


def _schema_errors(package: dict) -> list:
    return list(_schema_validator().iter_errors(package))


def test_public_synthetic_v3_matches_schema_and_semantic_validator() -> None:
    package = _package_v3()
    assert _schema_errors(package) == []
    assert validate_upgrade_package(package) == []


def test_v3_rejects_c2_not_provably_blocked_from_effective_c1() -> None:
    package = _package_v3()
    package["portable_import"]["block"] = [
        "apps/wiki-cockpit/public/other-generated-subtree/**",
        "memories/**",
        "wiki.config.yaml",
    ]

    assert _schema_errors(package) == []
    assert (
        "migration.generated_artifact_patterns[0] is not fully excluded from "
        "effective C1 by portable_import.block"
        in validate_upgrade_package(package)
    )


def test_project_v3_blocks_every_c2_pattern_from_effective_c1() -> None:
    package = load_mapping(
        ROOT / "docs/references/upgrades/wiki-viva-v8/upgrade-package.yaml"
    )
    assert validate_upgrade_package(package) == []

    for index, generated_pattern in enumerate(
        package["migration"]["generated_artifact_patterns"]
    ):
        concrete_path = generated_pattern.removesuffix("/**") + "/fixture.json"
        allowed, reason = portable_path_status(concrete_path, package)
        assert allowed is False
        assert reason.startswith("blocked by ")

        missing_block = copy.deepcopy(package)
        missing_block["portable_import"]["block"] = [
            pattern
            for pattern in missing_block["portable_import"]["block"]
            if pattern != generated_pattern
        ]
        assert (
            f"migration.generated_artifact_patterns[{index}] is not fully excluded "
            "from effective C1 by portable_import.block"
            in validate_upgrade_package(missing_block)
        )


def test_manual_v2_evidence_example_is_not_bound_to_project_v3_release() -> None:
    example_path = (
        ROOT
        / "docs/references/upgrades/wiki-viva-v8/migration-evidence.example.yaml"
    )
    example_text = example_path.read_text(encoding="utf-8")
    example = load_mapping(example_path)
    package = load_mapping(
        ROOT / "docs/references/upgrades/wiki-viva-v8/upgrade-package.yaml"
    )

    assert example["schema_version"] == "wiki_viva_migration_evidence.v2"
    assert package["schema_version"] == "wiki_viva_upgrade_package.v3"
    assert example["source"] == {
        "release": "HISTORICAL_V2_RELEASE_ID",
        "sha": "REPLACE_WITH_HISTORICAL_V2_PINNED_PUBLIC_SHA",
        "plan": "docs/references/proposals/HISTORICAL_V2_PLAN.md",
    }
    assert package["release"]["id"] not in example_text
    assert re.search(r"wiki-viva-v8-rc\d+", example_text) is None
    assert example["downstream_adaptations"][0] == (
        "docs/references/releases/HISTORICAL_V2_RELEASE_RECORD.md"
    )
    assert "HISTORICAL REFERENCE ONLY" in example_text
    assert "manual v2 migration-evidence template" in example_text
    assert "New v3 adoptions MUST NOT hand-author or copy this file" in example_text
    assert "python3 scripts/wiki_upgrade.py adopt" in example_text


def test_project_v3_keeps_operational_pass_current_in_every_consumer() -> None:
    package = load_mapping(
        ROOT / "docs/references/upgrades/wiki-viva-v8/upgrade-package.yaml"
    )
    registry = load_mapping(
        ROOT / "docs/references/upgrades/wiki-viva-v8/impact-registry.yaml"
    )
    migration = package["migration"]
    policy = migration["gate_policies"]["operational_pass"]
    catalog = {item["id"]: item for item in registry["gate_catalog"]}

    assert validate_upgrade_package(package) == []
    assert verify_impact_registry(registry) == registry["registry_sha256"]
    assert "operational_pass" in NEVER_REUSABLE_GATES
    assert "operational_pass" in migration["required_gates"]
    assert migration["gate_commands"]["operational_pass"] == (
        "python3 scripts/wiki_operational_pass.py --check"
    )
    assert policy["class"] == "consumer_always"
    assert policy["reuse"] == "never"
    assert policy["required_for_promotion"] is True
    assert "operational_pass" in migration["gate_policies"]["real_canary"][
        "depends_on"
    ]
    assert catalog["operational_pass"] == {
        "id": "operational_pass",
        "class": "consumer_always",
        "command": "python3 scripts/wiki_operational_pass.py --check",
    }
    assert "operational_pass" in registry["full_matrix_gates"]
    assert any(
        "operational_pass" in surface["gates"]
        for surface in registry["surfaces"]
    )


def test_v3_rejects_mismatched_command_registry_digest() -> None:
    package = _package_v3()
    package["migration"]["command_registry_sha256"] = "f" * 64
    assert _schema_errors(package) == []
    assert (
        "migration.command_registry_sha256 does not bind gate commands/classes"
        in validate_upgrade_package(package)
    )


def test_v3_rejects_invalid_gate_class_in_schema_and_validator() -> None:
    package = _package_v3()
    package["migration"]["gate_policies"]["bundle"]["class"] = "trusted_once"
    assert _schema_errors(package)
    assert (
        "migration.gate_policies.bundle.class is invalid"
        in validate_upgrade_package(package)
    )


def test_v3_never_reusable_assertion_cannot_claim_capsule_reuse() -> None:
    package = _package_v3()
    policy = package["migration"]["gate_policies"]["audit"]
    policy["class"] = "upstream_certified"
    policy["reuse"] = "exact_capsule"
    package["migration"]["command_registry_sha256"] = _command_digest(package)
    assert _schema_errors(package)
    assert (
        "migration.gate_policies.audit contains a never-reusable assertion"
        in validate_upgrade_package(package)
    )


def test_v3_rejects_gate_dependency_cycle_semantically() -> None:
    package = _package_v3()
    package["migration"]["gate_policies"]["audit"]["depends_on"] = [
        "background_suite"
    ]
    assert _schema_errors(package) == []
    assert (
        "migration.gate_policies dependency graph has a cycle"
        in validate_upgrade_package(package)
    )


def test_v3_rejects_wrong_impact_registry_schema() -> None:
    package = _package_v3()
    package["migration"]["impact_registry"][
        "schema_version"
    ] = "wiki_viva_upgrade_impact_registry.v2"
    assert _schema_errors(package)
    assert (
        "migration.impact_registry.schema_version is invalid"
        in validate_upgrade_package(package)
    )


def test_v3_preflight_mapping_is_total_and_targets_registered_gates() -> None:
    package = _package_v3()
    package["preflight"]["gate_mapping"] = {"different": "audit"}
    assert _schema_errors(package) == []
    assert (
        "preflight.gate_mapping must cover exactly preflight.required_gates"
        in validate_upgrade_package(package)
    )

    package = _package_v3()
    package["preflight"]["gate_mapping"]["audit"] = "missing_gate"
    assert _schema_errors(package) == []
    assert (
        "preflight.gate_mapping values must name migration.required_gates"
        in validate_upgrade_package(package)
    )


def test_v3_boundary_operations_digest_and_ownership_fail_closed() -> None:
    package = _package_v3()
    package["migration"]["boundary_operations"]["registry_sha256"] = "f" * 64
    assert _schema_errors(package) == []
    assert (
        "migration.boundary_operations.registry_sha256 is stale"
        in validate_upgrade_package(package)
    )


def test_v3_acceptance_budget_is_exact_and_promotion_blocking() -> None:
    package = _package_v3()
    assert _schema_errors(package) == []
    assert validate_upgrade_package(package) == []

    missing = _package_v3()
    del missing["migration"]["acceptance_budget"]
    assert _schema_errors(missing)
    assert any(
        "migration.acceptance_budget" in error
        for error in validate_upgrade_package(missing)
    )

    enlarged = _package_v3()
    enlarged["migration"]["acceptance_budget"]["limit_seconds"] = 1201
    assert _schema_errors(enlarged)
    assert any(
        "exactly 1200 seconds" in error
        for error in validate_upgrade_package(enlarged)
    )

    shortened = _package_v3()
    shortened["migration"]["acceptance_budget"]["limit_seconds"] = 1199
    assert _schema_errors(shortened)
    assert any(
        "exactly 1200 seconds" in error
        for error in validate_upgrade_package(shortened)
    )

    weakened = _package_v3()
    weakened["migration"]["acceptance_budget"]["enforcement"] = "advisory"
    assert _schema_errors(weakened)
    assert any(
        "promotion blocking" in error
        for error in validate_upgrade_package(weakened)
    )

    package = _package_v3()
    boundary = package["migration"]["boundary_operations"]
    boundary["c2_generators"][0]["owns_patterns"] = [
        "docs/references/fixtures/demo-wiki/memories/**"
    ]
    boundary["registry_sha256"] = boundary_operations_sha256(boundary)
    assert _schema_errors(package) == []
    assert (
        "migration.boundary_operations.c2_generators must own exactly "
        "migration.generated_artifact_patterns"
        in validate_upgrade_package(package)
    )


def test_v3_rejects_placeholder_boundary_generator() -> None:
    package = _package_v3()
    boundary = package["migration"]["boundary_operations"]
    boundary["c2_generators"][0]["command"] = "TODO manual"
    boundary["registry_sha256"] = boundary_operations_sha256(boundary)
    assert _schema_errors(package)
    assert (
        "migration.boundary_operations.c2_generators[0].command must be an exact command"
        in validate_upgrade_package(package)
    )


def test_project_registry_covers_every_agents_promotion_command() -> None:
    package = load_mapping(
        ROOT / "docs/references/upgrades/wiki-viva-v8/upgrade-package.yaml"
    )
    registry = load_mapping(
        ROOT / "docs/references/upgrades/wiki-viva-v8/impact-registry.yaml"
    )
    gates_section = re.search(
        r"## Gates .*?```sh\n(?P<commands>.*?)```",
        (ROOT / "AGENTS.md").read_text(encoding="utf-8"),
        flags=re.DOTALL,
    )
    assert gates_section is not None
    promotion_commands = {
        line.strip()
        for line in gates_section.group("commands").splitlines()
        if line.strip()
    }
    catalog_commands = {item["command"] for item in registry["gate_catalog"]}
    catalog_ids = [item["id"] for item in registry["gate_catalog"]]

    assert promotion_commands <= catalog_commands
    assert "python3 scripts/wiki_operational_pass.py --check" in promotion_commands
    assert "python3 -m pytest -q -W error tests/" in promotion_commands
    assert "python3 -m pytest tests/" not in promotion_commands
    assert package["migration"]["required_gates"] == catalog_ids
    assert set(package["migration"]["gate_commands"]) == set(catalog_ids)
    assert set(package["migration"]["gate_policies"]) == set(catalog_ids)


def test_published_upstream_certification_commands_use_public_safe_reporters() -> None:
    package = load_mapping(
        ROOT / "docs/references/upgrades/wiki-viva-v8/upgrade-package.yaml"
    )
    registry = load_mapping(
        ROOT / "docs/references/upgrades/wiki-viva-v8/impact-registry.yaml"
    )
    expected = {
        "frontend": "npm --prefix apps/wiki-cockpit test -- --reporter=tap",
        "portable_python": "python3 -m pytest -q -W error tests/",
    }
    catalog = {item["id"]: item for item in registry["gate_catalog"]}

    assert {
        gate_id: package["migration"]["gate_commands"][gate_id]
        for gate_id in expected
    } == expected
    assert {gate_id: catalog[gate_id]["command"] for gate_id in expected} == expected
    assert all(catalog[gate_id]["class"] == "upstream_certified" for gate_id in expected)
    assert package["migration"]["command_registry_sha256"] == _command_digest(package)
    assert verify_impact_registry(registry) == registry["registry_sha256"]
    assert package["migration"]["impact_registry"]["sha256"] == registry[
        "registry_sha256"
    ]


def test_v1_and_v2_packages_remain_valid_without_two_lane_fields() -> None:
    modern = _package_v3()
    modern["schema_version"] = "wiki_viva_upgrade_package.v2"
    for field in (
        "command_registry",
        "command_registry_sha256",
        "impact_registry",
        "gate_policies",
    ):
        del modern["migration"][field]
    assert validate_upgrade_package(modern) == []

    legacy = copy.deepcopy(modern)
    legacy["schema_version"] = "wiki_viva_upgrade_package.v1"
    for field in (
        "semantic_visual_tokens",
        "appearance",
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
    ):
        del legacy["contract_versions"][field]
    assert validate_upgrade_package(legacy) == []


def test_v3_requires_the_exact_consumer_c3_authority_contract_version() -> None:
    missing = _package_v3()
    del missing["contract_versions"]["consumer_c3_authority"]
    assert list(_schema_validator().iter_errors(missing))
    assert any(
        "contract_versions.consumer_c3_authority is required" in error
        for error in validate_upgrade_package(missing)
    )

    wrong = _package_v3()
    wrong["contract_versions"]["consumer_c3_authority"] = (
        "wiki_viva_upgrade_consumer_c3_authority.v999"
    )
    assert list(_schema_validator().iter_errors(wrong))
    assert any(
        "contract_versions.consumer_c3_authority must be" in error
        for error in validate_upgrade_package(wrong)
    )
