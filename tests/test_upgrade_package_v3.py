from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator

from wiki_core.upgrade import (
    boundary_operations_sha256,
    canonical_json,
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
        },
        "portable_import": {
            "allow": ["scripts/wiki_*.py", "wiki_core/**"],
            "block": ["memories/**", "wiki.config.yaml"],
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
            "boundary_operations": {
                "schema_version": "wiki_viva_upgrade_boundary_operations.v1",
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
                    "contract": "wiki_consumer_adaptation_plan.v1",
                    "owns_patterns": ["tests/**"],
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
    assert package["migration"]["required_gates"] == catalog_ids
    assert set(package["migration"]["gate_commands"]) == set(catalog_ids)
    assert set(package["migration"]["gate_policies"]) == set(catalog_ids)


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
