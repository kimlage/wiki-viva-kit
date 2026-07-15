"""Deterministic downstream-upgrade contracts for Wiki Viva v8.

This module is intentionally read-only.  It inventories public package metadata,
compares portable files, compiles a preflight report and validates migration
evidence.  It never copies toolkit files or changes a consumer repository.
"""

from __future__ import annotations

import fnmatch
import hashlib
import io
import json
import math
import os
import re
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml
from jsonschema import Draft202012Validator

from wiki_core.detectors import scan_text


UPGRADE_PACKAGE_SCHEMA_VERSION = "wiki_viva_upgrade_package.v2"
TWO_LANE_UPGRADE_PACKAGE_SCHEMA_VERSION = "wiki_viva_upgrade_package.v3"
BOUNDARY_OPERATIONS_SCHEMA_VERSION = "wiki_viva_upgrade_boundary_operations.v2"
CONFIG_BOUND_C3_POLICY_SCHEMA_VERSION = "wiki_viva_config_bound_c3_policy.v1"
LEGACY_UPGRADE_PACKAGE_SCHEMA_VERSION = "wiki_viva_upgrade_package.v1"
CONSUMER_INVENTORY_SCHEMA_VERSION = "wiki_viva_consumer_inventory.v1"
PREFLIGHT_SCHEMA_VERSION = "wiki_viva_upgrade_preflight.v1"
GATE_EVIDENCE_SCHEMA_VERSION = "wiki_viva_gate_evidence.v1"
MIGRATION_EVIDENCE_SCHEMA_VERSION = "wiki_viva_migration_evidence.v2"
MIGRATION_REPORT_SCHEMA_VERSION = "wiki_viva_migration_report.v2"
MIGRATION_VALIDATOR_VERSION = "wiki_viva_upgrade_validator.v5"
MIGRATION_GATE_RECEIPTS_SCHEMA_VERSION = "wiki_viva_migration_gate_receipts.v1"
ROLLBACK_VERIFICATION_SCHEMA_VERSION = "wiki_viva_rollback_verification.v1"
UPGRADE_GATE_CLASSES = {
    "upstream_certified",
    "consumer_always",
    "affected",
    "canary",
    "background_certification",
}
UPGRADE_GATE_REUSE_POLICIES = {"exact_capsule", "impact", "never"}

# These are the only domain-root exceptions a certified v3 package may derive
# from a consumer's B0 configuration.  Keeping the complete role contract here
# prevents a package from turning an arbitrary config key into a broad C3
# ownership escape hatch.
CONFIG_BOUND_C3_ROLE_SPECS = (
    {
        "id": "command_reference_page",
        "kind": "exact_markdown",
        "path_key": "command_reference_page",
        "impact_contract": "wiki_consumer_command_reference.v1",
        "mode": "100644",
        "suffix": ".md",
    },
    {
        "id": "operational_pass_page",
        "kind": "exact_markdown",
        "path_key": "operational_pass_page",
        "impact_contract": "wiki_consumer_operational_pass.v1",
        "mode": "100644",
        "suffix": ".md",
    },
    {
        "id": "release_records",
        "kind": "inert_markdown_subtree",
        "path_key": "references_root",
        "subtree": "releases",
        "impact_contract": "wiki_consumer_release_record.v1",
        "mode": "100644",
        "suffix": ".md",
    },
)
# Capabilities are policy identities.  A package cannot evade a current-
# consumer invariant by renaming its gate.
NEVER_REUSABLE_GATE_ASSERTIONS = {
    "secret_private_audit",
    "public_evidence_redaction",
    "input_stage",
    "operational_pass_current",
    "semantic_inventory",
    "adapter_identity",
    "snapshot_contract",
    "canary_real",
    "diff_verification",
    "rollback_report_verification",
}
# The evidence schema is a runtime dependency of this module, so it lives in
# the portable docs/references/schemas/** surface and travels with every
# faithful public import (docs/references/upgrades/** is consumer-owned and
# blocked by the payload).
MIGRATION_EVIDENCE_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs/references/schemas/wiki-migration-evidence-v2.schema.json"
)

CONSUMER_TYPES = {
    "public_example",
    "private_operational_wiki",
    "client_internal_wiki",
    "pilot",
    "adapter_only",
    "unknown",
}
RUNTIMES = {"legacy", "compat", "v8", "no_cockpit", "unknown"}
OPERATORS = {
    "none",
    "static_demo",
    "localhost_operator",
    "source_sync",
    "codex_jobs",
    "unknown",
}
PRIVACY_RISKS = {
    "public_safe",
    "private_pii",
    "financial_personal",
    "client_internal",
    "secret_adjacent",
    "unknown",
}
UPGRADE_WAVES = {"public_kit", "pilot", "wave_1", "wave_2", "paused", "blocked"}

_SHA_RE = re.compile(r"[0-9a-f]{40,64}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_VISUAL_PROFILE_RE = re.compile(r"[a-z][a-z0-9_]{1,63}")
_PUBLIC_LOCAL_PATH_RE = re.compile(
    r"(?:/Users/|/home/|(?:^|[\s\"'=(:])/(?!/)[^\s\"',;]+|"
    r"[A-Za-z]:\\|file://|(?<![\w.-])~[/\\]|\\\\[^\\\s]+\\[^\\\s]+)"
)
_PUBLIC_PARENT_TRAVERSAL_RE = re.compile(r"(?:^|[\s\"'/:\\])\.\.(?:[/\\]|$)")
_PUBLIC_URL_QUERY_RE = re.compile(r"https?://[^\s\"']+\?[^\s\"']+")
_PUBLIC_CREDENTIAL_ASSIGNMENT_RE = re.compile(
    r"(?i)(?:api[_-]?key|secret|token|password|passwd|pwd|senha|authorization|"
    r"cookie|client[_-]?secret|refresh[_-]?token|access[_-]?token)"
    r"\s*[:=]\s*[^\s,;]+"
)
_PUBLIC_FIXTURE_REFS = {
    "public-fixture:canonical-root",
    "public-fixture:root",
}
_PUBLIC_ROUTE_HASH_RE = re.compile(r"route:sha256:[0-9a-f]{64}")
_PUBLIC_CENTER_HASH_RE = re.compile(r"center:sha256:[0-9a-f]{64}")
_PUBLIC_RELEASE_ID_RE = re.compile(r"wiki-viva-v[0-9]+(?:-[a-z0-9]+)*")
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_SENSITIVE_PORTABLE_BASENAMES = {
    "access_token",
    "client_secret",
    "cookie",
    "cookies",
    "credential",
    "credentials",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
    "password",
    "passwords",
    "private_key",
    "secret",
    "secrets",
    "token",
    "tokens",
}
_CONSUMER_OWNED_PORTABLE_PATHS = {"wiki.adapter-manifest.json"}
_PORTABLE_ROOT_FILES = {
    "requirements.txt",
    "scripts/README.md",
    "wiki.page-types.yaml",
    "wiki.templates.yaml",
}
_PORTABLE_ROOT_PREFIXES = (
    "wiki_core/",
    "scripts/",
    "tests/",
    "apps/wiki-cockpit/",
    ".github/workflows/",
    "packs/",
    "docs/references/guides/",
    "docs/references/releases/",
    "docs/references/schemas/",
    "docs/references/templates/deploy/",
    "docs/references/upgrades/wiki-viva-v8/",
    "docs/references/fixtures/demo-wiki/",
)
_PUBLIC_REDACTED_VALUE = "<redacted-public-value>"
_UNPINNED = {
    "",
    "head",
    "main",
    "unreleased",
    "required_at_release",
    "set_at_release",
    "unknown",
}
_RELEASABLE_STATUSES = {"candidate", "release_candidate", "ready", "released"}
_DEFAULT_MIGRATION_VISUAL_PROFILES = ("desktop", "mobile", "fallback")
_MIGRATION_COMMIT_BOUNDARIES = (
    ("faithful_public_import", "import_commit_sha"),
    ("regenerated_artifacts", "artifact_commit_sha"),
    ("downstream_adaptations", "adaptation_commit_sha"),
)
_MIGRATION_COMMIT_BOUNDARY_FIELDS = dict(_MIGRATION_COMMIT_BOUNDARIES)
_MIGRATION_COMMAND_PLACEHOLDER_RE = re.compile(
    r"(?i)(?:replace[_ -]?with|record exact|placeholder|\btodo\b|\btbd\b|"
    r"^\s*(?:run|execute)(?:\s+[^\s]+)?\s*$|"
    r"^\s*(?:true|:|exit\s+0)\s*$|<[^>]+>)"
)
_FORBIDDEN_ADAPTATION_PATTERNS = (
    ".git/**",
    ".wiki-viva/**",
    "data/raw/**",
    "data/derived/**",
    "private/**",
    "output/**",
    "test-results/**",
    "**/dist/**",
    "**/coverage/**",
    "**/test-results/**",
    "**/playwright-report/**",
    "**/.playwright-cli/**",
    "**/*.log",
    "**/*private-snapshot*",
)
_CONSUMER_OWNED_ADAPTATION_PATTERNS = (
    "requirements.txt",
    "wiki.page-types.yaml",
    "wiki.templates.yaml",
    "wiki.config.yaml",
    "wiki.targets.yaml",
    "wiki.templates.local.yaml",
    "wiki.page-types.local.yaml",
    "wiki.packs.lock.yaml",
    "wiki.adapter-manifest.json",
    ".toolkit-drift-ignore",
    "apps/wiki-cockpit/public/wiki-cockpit.config.json",
    "tests/**",
    ".github/workflows/**",
)
_SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "coverage",
    "test-results",
    "playwright-report",
    ".playwright-cli",
}


def load_mapping(path: Path) -> dict[str, Any]:
    """Load JSON or YAML and require a mapping root."""

    text = path.read_text(encoding="utf-8")
    data = json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping root")
    return data


def canonical_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _finite_json_value(value: Any, *, _active: set[int] | None = None, _depth: int = 0) -> bool:
    """Reject YAML-only scalars, recursive aliases and pathological depth."""

    if _depth > 128:
        return False
    if value is None or isinstance(value, (str, bool, int)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if not isinstance(value, (dict, list)):
        return False
    active = _active if _active is not None else set()
    identity = id(value)
    if identity in active:
        return False
    active.add(identity)
    try:
        if isinstance(value, dict):
            return all(
                isinstance(key, str)
                and _finite_json_value(item, _active=active, _depth=_depth + 1)
                for key, item in value.items()
            )
        return all(
            _finite_json_value(item, _active=active, _depth=_depth + 1)
            for item in value
        )
    finally:
        active.remove(identity)


def deterministic_id(prefix: str, data: Any) -> str:
    digest = hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}:{digest}"


def upgrade_package_sha256(package: dict[str, Any]) -> str:
    """Return a formatting-independent digest for the package under review."""

    return hashlib.sha256(canonical_json(package).encode("utf-8")).hexdigest()


def boundary_operations_sha256(boundary_operations: Mapping[str, Any]) -> str:
    """Bind the package-owned C2 generator and C3 adapter contract."""

    unsigned = dict(boundary_operations)
    unsigned.pop("registry_sha256", None)
    return hashlib.sha256(canonical_json(unsigned).encode("utf-8")).hexdigest()


def _migration_visual_profiles(package: dict[str, Any]) -> tuple[str, ...]:
    """Return the package-owned visual evidence contract.

    V2 packages declare the exact profiles they require.  The fallback keeps
    the v1 reader compatible without allowing a v2 package to advertise a
    profile that templates and validators silently omit.
    """

    migration = package.get("migration")
    values = (
        migration.get("visual_profiles") if isinstance(migration, dict) else None
    )
    if isinstance(values, list) and values:
        return tuple(str(value) for value in values)
    return _DEFAULT_MIGRATION_VISUAL_PROFILES


def _migration_commit_boundary_fields(package: dict[str, Any]) -> tuple[str, ...]:
    """Return consumer-after SHA fields declared by the package, in order."""

    migration = package.get("migration")
    values = (
        migration.get("commit_boundaries") if isinstance(migration, dict) else None
    )
    if not isinstance(values, list):
        return ("import_commit_sha",)
    return tuple(
        _MIGRATION_COMMIT_BOUNDARY_FIELDS[str(value)]
        for value in values
        if str(value) in _MIGRATION_COMMIT_BOUNDARY_FIELDS
    )


def _require_mapping(value: Any, name: str, errors: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        errors.append(f"{name} must be a mapping")
        return {}
    return value


def _require_list(value: Any, name: str, errors: list[str]) -> list[Any]:
    if not isinstance(value, list):
        errors.append(f"{name} must be a list")
        return []
    return value


def _safe_repo_pattern(value: Any) -> bool:
    """Return whether a package glob is bounded to one repository subtree."""

    raw = str(value or "")
    if (
        not raw
        or raw != raw.strip()
        or "\x00" in raw
        or raw.startswith(("/", "./", "~"))
        or "\\" in raw
        or _WINDOWS_DRIVE_RE.match(raw)
        or raw in {"*", "**", "**/*"}
    ):
        return False
    parts = raw.split("/")
    if any(not part or part in {".", ".."} for part in parts):
        return False
    literal = re.sub(r"[*?\[\]]", "", raw)
    if not literal or _portable_path_has_sensitive_name(literal):
        return False
    literal_head = re.split(r"[*?[]", raw, maxsplit=1)[0].rstrip("/")
    return bool(
        literal_head in _PORTABLE_ROOT_FILES
        or literal_head.startswith(_PORTABLE_ROOT_PREFIXES)
        or any(
            prefix.rstrip("/").startswith(f"{literal_head}/")
            for prefix in _PORTABLE_ROOT_PREFIXES
        )
        or literal_head.startswith(".skills/wiki-")
    )


def _safe_boundary_pattern(value: Any) -> bool:
    """Accept one bounded consumer-owned glob without admitting repo-wide rules."""

    raw = str(value or "")
    if (
        not raw
        or raw != raw.strip()
        or "\x00" in raw
        or raw.startswith(("/", "./", "~"))
        or "\\" in raw
        or _WINDOWS_DRIVE_RE.match(raw)
        or raw in {"*", "**", "**/*"}
    ):
        return False
    parts = raw.split("/")
    if any(not part or part in {".", ".."} for part in parts):
        return False
    literal = re.sub(r"[*?\[\]]", "", raw)
    return bool(literal and not _portable_path_has_sensitive_name(literal))


@lru_cache(maxsize=1)
def _migration_evidence_schema_validator() -> Draft202012Validator:
    if not MIGRATION_EVIDENCE_SCHEMA_PATH.is_file():
        raise FileNotFoundError(
            "migration evidence schema is missing: import "
            "docs/references/schemas/wiki-migration-evidence-v2.schema.json "
            "from the same kit source commit as wiki_core/upgrade.py"
        )
    schema = json.loads(MIGRATION_EVIDENCE_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _migration_evidence_schema_errors(evidence: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for error in _migration_evidence_schema_validator().iter_errors(evidence):
        location = "$" + "".join(f"[{part}]" for part in error.absolute_path)
        # Never include jsonschema's message: it may echo a rejected private
        # path, route, person or secret-shaped scalar into a public report.
        errors.append(
            f"migration evidence schema violation at {location}: {error.validator}"
        )
    return sorted(set(errors))


def _validate_two_lane_package(
    migration: Mapping[str, Any], migration_gates: Sequence[Any]
) -> list[str]:
    """Validate the executable v3 policy without weakening v1/v2 packages."""

    errors: list[str] = []
    gate_ids = [str(value) for value in migration_gates]
    if len(gate_ids) != len(set(gate_ids)):
        errors.append("migration.required_gates must be unique")
    expected = set(gate_ids)

    acceptance_budget = migration.get("acceptance_budget")
    expected_budget = {
        "schema_version": "wiki_viva_upgrade_acceptance_budget_policy.v1",
        "scope": "plan_to_real_canary",
        "limit_seconds": 1200,
        "enforcement": "promotion_blocking",
    }
    if acceptance_budget != expected_budget:
        errors.append(
            "migration.acceptance_budget must enforce plan-to-real-canary "
            "promotion blocking at exactly 1200 seconds"
        )

    command_registry_value = migration.get("command_registry")
    command_registry = (
        command_registry_value if isinstance(command_registry_value, Mapping) else {}
    )
    if command_registry_value is not None and not isinstance(
        command_registry_value, Mapping
    ):
        errors.append("migration.command_registry must be a mapping when present")
    if command_registry and set(str(key) for key in command_registry) != expected:
        errors.append(
            "migration.command_registry must cover exactly migration.required_gates"
        )
    for gate_id, raw_command in command_registry.items():
        prefix = f"migration.command_registry.{gate_id}"
        if not isinstance(raw_command, Mapping):
            errors.append(f"{prefix} must be a mapping")
            continue
        unknown = set(raw_command) - {
            "argv",
            "cwd",
            "timeout_seconds",
            "env_allowlist",
        }
        if unknown:
            errors.append(f"{prefix} has unknown fields")
        argv = raw_command.get("argv")
        if (
            not isinstance(argv, list)
            or not argv
            or any(
                not isinstance(value, str)
                or not value
                or "\x00" in value
                or "\n" in value
                for value in argv
            )
        ):
            errors.append(f"{prefix}.argv must be a non-empty string list")
        cwd = str(raw_command.get("cwd") or "")
        if (
            not cwd
            or cwd.startswith(("/", "~", "\\"))
            or _WINDOWS_DRIVE_RE.match(cwd)
            or ".." in Path(cwd).parts
        ):
            errors.append(f"{prefix}.cwd must stay inside the consumer")
        timeout = raw_command.get("timeout_seconds")
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, int)
            or not 1 <= timeout <= 86_400
        ):
            errors.append(f"{prefix}.timeout_seconds is invalid")
        env_allowlist = raw_command.get("env_allowlist", [])
        if (
            not isinstance(env_allowlist, list)
            or any(
                not isinstance(value, str)
                or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", value)
                for value in env_allowlist
            )
            or len(env_allowlist) != len(set(env_allowlist))
        ):
            errors.append(f"{prefix}.env_allowlist is invalid")

    policies = migration.get("gate_policies")
    if not isinstance(policies, Mapping):
        errors.append("migration.gate_policies must be a mapping")
        policies = {}
    if set(str(key) for key in policies) != expected:
        errors.append(
            "migration.gate_policies must cover exactly migration.required_gates"
        )
    dependencies: dict[str, list[str]] = {}
    for gate_id, raw_policy in policies.items():
        prefix = f"migration.gate_policies.{gate_id}"
        if not isinstance(raw_policy, Mapping):
            errors.append(f"{prefix} must be a mapping")
            continue
        unknown = set(raw_policy) - {
            "class",
            "command_id",
            "asserts",
            "reuse",
            "depends_on",
            "resource_group",
            "required_for_promotion",
        }
        if unknown:
            errors.append(f"{prefix} has unknown fields")
        gate_class = str(raw_policy.get("class") or "")
        reuse = str(raw_policy.get("reuse") or "")
        if gate_class not in UPGRADE_GATE_CLASSES:
            errors.append(f"{prefix}.class is invalid")
        if reuse not in UPGRADE_GATE_REUSE_POLICIES:
            errors.append(f"{prefix}.reuse is invalid")
        if str(raw_policy.get("command_id") or "") != str(gate_id):
            errors.append(f"{prefix}.command_id must equal its gate id")
        assertions = raw_policy.get("asserts")
        if (
            not isinstance(assertions, list)
            or not assertions
            or any(
                not isinstance(value, str)
                or not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", value)
                for value in assertions
            )
            or len(assertions) != len(set(assertions))
        ):
            errors.append(f"{prefix}.asserts is invalid")
            assertions = []
        if NEVER_REUSABLE_GATE_ASSERTIONS.intersection(assertions):
            if reuse != "never" or gate_class == "upstream_certified":
                errors.append(f"{prefix} contains a never-reusable assertion")
        expected_reuse = {
            "upstream_certified": "exact_capsule",
            "consumer_always": "never",
            "affected": "impact",
            "canary": "never",
            "background_certification": "never",
        }.get(gate_class)
        if expected_reuse and reuse != expected_reuse:
            errors.append(f"{prefix}.reuse contradicts its class")
        if "canary_real" in assertions and gate_class != "canary":
            errors.append(f"{prefix}.class must be canary for canary_real")
        depends_on = raw_policy.get("depends_on", [])
        if (
            not isinstance(depends_on, list)
            or any(str(value) not in expected for value in depends_on)
            or str(gate_id) in {str(value) for value in depends_on}
            or len(depends_on) != len(set(str(value) for value in depends_on))
        ):
            errors.append(f"{prefix}.depends_on is invalid")
            depends_on = []
        dependencies[str(gate_id)] = [str(value) for value in depends_on]
        resource_group = str(raw_policy.get("resource_group") or "")
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", resource_group):
            errors.append(f"{prefix}.resource_group is invalid")
        if not isinstance(raw_policy.get("required_for_promotion"), bool):
            errors.append(f"{prefix}.required_for_promotion must be boolean")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(gate_id: str) -> None:
        if gate_id in visiting:
            errors.append("migration.gate_policies dependency graph has a cycle")
            return
        if gate_id in visited:
            return
        visiting.add(gate_id)
        for dependency in dependencies.get(gate_id, []):
            visit(dependency)
        visiting.remove(gate_id)
        visited.add(gate_id)

    for gate_id in dependencies:
        visit(gate_id)

    gate_commands = migration.get("gate_commands")
    command_registry_sha256 = str(
        migration.get("command_registry_sha256") or ""
    )
    if (
        isinstance(gate_commands, Mapping)
        and set(str(key) for key in gate_commands) == expected
        and isinstance(policies, Mapping)
        and set(str(key) for key in policies) == expected
    ):
        projection = sorted(
            (
                {
                    "id": gate_id,
                    "class": str(policies[gate_id].get("class") or "")
                    if isinstance(policies[gate_id], Mapping)
                    else "",
                    "command": str(gate_commands[gate_id]),
                }
                for gate_id in expected
            ),
            key=lambda item: item["id"],
        )
        expected_command_digest = hashlib.sha256(
            canonical_json(projection).encode("utf-8")
        ).hexdigest()
        if command_registry_sha256 != expected_command_digest:
            errors.append(
                "migration.command_registry_sha256 does not bind gate commands/classes"
            )
    elif not _SHA256_RE.fullmatch(command_registry_sha256):
        errors.append("migration.command_registry_sha256 is invalid")

    impact = migration.get("impact_registry")
    if not isinstance(impact, Mapping):
        errors.append("migration.impact_registry must be a mapping")
    else:
        if (
            impact.get("schema_version")
            != "wiki_viva_upgrade_impact_registry.v1"
        ):
            errors.append("migration.impact_registry.schema_version is invalid")
        if not _SHA256_RE.fullmatch(str(impact.get("sha256") or "")):
            errors.append("migration.impact_registry.sha256 is invalid")
        path = str(impact.get("path") or "")
        if (
            not path
            or path.startswith(("/", "~", "\\"))
            or _WINDOWS_DRIVE_RE.match(path)
            or ".." in Path(path).parts
        ):
            errors.append("migration.impact_registry.path is unsafe")

    boundary_value = migration.get("boundary_operations")
    if not isinstance(boundary_value, Mapping):
        errors.append("migration.boundary_operations must be a mapping")
        boundary: Mapping[str, Any] = {}
    else:
        boundary = boundary_value
    expected_boundary_keys = {
        "schema_version",
        "c2_generators",
        "c3_adapter",
        "registry_sha256",
    }
    if boundary and set(boundary) != expected_boundary_keys:
        errors.append("migration.boundary_operations has unknown or missing fields")
    if boundary.get("schema_version") != BOUNDARY_OPERATIONS_SCHEMA_VERSION:
        errors.append("migration.boundary_operations.schema_version is invalid")

    generators = boundary.get("c2_generators")
    if not isinstance(generators, list) or not generators:
        errors.append("migration.boundary_operations.c2_generators must be non-empty")
        generators = []
    generator_ids: list[str] = []
    generated_owners: list[str] = []
    for index, raw_generator in enumerate(generators):
        prefix = f"migration.boundary_operations.c2_generators[{index}]"
        if not isinstance(raw_generator, Mapping):
            errors.append(f"{prefix} must be a mapping")
            continue
        if set(raw_generator) != {"id", "command", "owns_patterns"}:
            errors.append(f"{prefix} has unknown or missing fields")
        generator_id = str(raw_generator.get("id") or "")
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,127}", generator_id):
            errors.append(f"{prefix}.id is invalid")
        generator_ids.append(generator_id)
        command = raw_generator.get("command")
        if (
            not isinstance(command, str)
            or not command.strip()
            or _migration_command_is_placeholder(command)
        ):
            errors.append(f"{prefix}.command must be an exact command")
        owns = raw_generator.get("owns_patterns")
        if not isinstance(owns, list) or not owns:
            errors.append(f"{prefix}.owns_patterns must be non-empty")
            continue
        if len(owns) != len(set(str(value) for value in owns)):
            errors.append(f"{prefix}.owns_patterns must be unique")
        for owner_index, pattern in enumerate(owns):
            if not isinstance(pattern, str) or not _safe_repo_pattern(pattern):
                errors.append(f"{prefix}.owns_patterns[{owner_index}] is unsafe")
            generated_owners.append(str(pattern))
    if generator_ids != sorted(generator_ids) or len(generator_ids) != len(
        set(generator_ids)
    ):
        errors.append(
            "migration.boundary_operations.c2_generators must have unique sorted ids"
        )
    if len(generated_owners) != len(set(generated_owners)):
        errors.append(
            "migration.boundary_operations.c2_generators ownership overlaps"
        )
    if set(generated_owners) != {
        str(value) for value in migration.get("generated_artifact_patterns") or []
    }:
        errors.append(
            "migration.boundary_operations.c2_generators must own exactly "
            "migration.generated_artifact_patterns"
        )

    c3_value = boundary.get("c3_adapter")
    if not isinstance(c3_value, Mapping):
        errors.append("migration.boundary_operations.c3_adapter must be a mapping")
        c3: Mapping[str, Any] = {}
    else:
        c3 = c3_value
    if c3 and set(c3) != {
        "mode",
        "contract",
        "owns_patterns",
        "configured_ownership",
    }:
        errors.append(
            "migration.boundary_operations.c3_adapter has unknown or missing fields"
        )
    if c3.get("mode") != "consumer_plan_commands":
        errors.append("migration.boundary_operations.c3_adapter.mode is invalid")
    if not re.fullmatch(
        r"[a-z][a-z0-9_.:+-]{1,127}", str(c3.get("contract") or "")
    ):
        errors.append("migration.boundary_operations.c3_adapter.contract is invalid")
    c3_patterns = c3.get("owns_patterns")
    if not isinstance(c3_patterns, list) or not c3_patterns:
        errors.append(
            "migration.boundary_operations.c3_adapter.owns_patterns must be non-empty"
        )
        c3_patterns = []
    if len(c3_patterns) != len(set(str(value) for value in c3_patterns)):
        errors.append(
            "migration.boundary_operations.c3_adapter.owns_patterns must be unique"
        )
    for index, pattern in enumerate(c3_patterns):
        if not isinstance(pattern, str) or not _safe_boundary_pattern(pattern):
            errors.append(
                "migration.boundary_operations.c3_adapter."
                f"owns_patterns[{index}] is unsafe"
            )

    configured_value = c3.get("configured_ownership")
    if not isinstance(configured_value, Mapping):
        errors.append(
            "migration.boundary_operations.c3_adapter.configured_ownership "
            "must be a mapping"
        )
        configured: Mapping[str, Any] = {}
    else:
        configured = configured_value
    if configured and set(configured) != {
        "schema_version",
        "config_path",
        "roles",
    }:
        errors.append(
            "migration.boundary_operations.c3_adapter.configured_ownership "
            "has unknown or missing fields"
        )
    if (
        configured.get("schema_version")
        != CONFIG_BOUND_C3_POLICY_SCHEMA_VERSION
    ):
        errors.append(
            "migration.boundary_operations.c3_adapter.configured_ownership."
            "schema_version is invalid"
        )
    if configured.get("config_path") != "wiki.config.yaml":
        errors.append(
            "migration.boundary_operations.c3_adapter.configured_ownership."
            "config_path must be wiki.config.yaml"
        )
    configured_roles = configured.get("roles")
    if not isinstance(configured_roles, list):
        errors.append(
            "migration.boundary_operations.c3_adapter.configured_ownership.roles "
            "must be a list"
        )
    elif configured_roles != list(CONFIG_BOUND_C3_ROLE_SPECS):
        errors.append(
            "migration.boundary_operations.c3_adapter.configured_ownership.roles "
            "must declare the exact fail-closed role contract"
        )
    if set(str(value) for value in c3_patterns).intersection(generated_owners):
        errors.append("migration.boundary_operations C2 and C3 ownership overlaps")

    boundary_digest = str(boundary.get("registry_sha256") or "")
    if not _SHA256_RE.fullmatch(boundary_digest):
        errors.append("migration.boundary_operations.registry_sha256 is invalid")
    elif boundary_operations_sha256(boundary) != boundary_digest:
        errors.append("migration.boundary_operations.registry_sha256 is stale")
    return sorted(set(errors))


def validate_upgrade_package(package: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    schema_version = package.get("schema_version")
    if schema_version not in {
        LEGACY_UPGRADE_PACKAGE_SCHEMA_VERSION,
        UPGRADE_PACKAGE_SCHEMA_VERSION,
        TWO_LANE_UPGRADE_PACKAGE_SCHEMA_VERSION,
    }:
        errors.append(
            "schema_version must be "
            f"{LEGACY_UPGRADE_PACKAGE_SCHEMA_VERSION}, "
            f"{UPGRADE_PACKAGE_SCHEMA_VERSION} or "
            f"{TWO_LANE_UPGRADE_PACKAGE_SCHEMA_VERSION}"
        )
    release = _require_mapping(package.get("release"), "release", errors)
    for field in ("id", "status", "source_sha", "plan"):
        if field not in release:
            errors.append(f"release.{field} is required")
    portable = _require_mapping(
        package.get("portable_import"), "portable_import", errors
    )
    allow = _require_list(portable.get("allow"), "portable_import.allow", errors)
    block = _require_list(portable.get("block"), "portable_import.block", errors)
    if not allow:
        errors.append("portable_import.allow cannot be empty")
    if not block:
        errors.append("portable_import.block cannot be empty")
    for group, values in (("allow", allow), ("block", block)):
        for value in values:
            if (
                not isinstance(value, str)
                or not value.strip()
                or value.startswith("/")
                or value.startswith(("./", "~"))
                or "\\" in value
                or _WINDOWS_DRIVE_RE.match(value)
                or ".." in Path(value).parts
            ):
                errors.append(
                    f"portable_import.{group} contains an unsafe pattern: {value!r}"
                )
    schemas = _require_mapping(
        package.get("contract_versions"), "contract_versions", errors
    )
    legacy_contracts = (
        "route",
        "snapshot",
        "snapshot_envelope",
        "blocks",
        "visual_grammar",
        "runtime",
        "source_lifecycle",
        "freshness",
    )
    v2_contracts = (
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
    )
    v3_contracts = ("consumer_c3_authority",)
    required_contracts = (
        (*legacy_contracts, *v2_contracts, *v3_contracts)
        if schema_version == TWO_LANE_UPGRADE_PACKAGE_SCHEMA_VERSION
        else (*legacy_contracts, *v2_contracts)
        if schema_version == UPGRADE_PACKAGE_SCHEMA_VERSION
        else legacy_contracts
    )
    for field in required_contracts:
        if not str(schemas.get(field) or "").strip():
            errors.append(f"contract_versions.{field} is required")
    if (
        schema_version == TWO_LANE_UPGRADE_PACKAGE_SCHEMA_VERSION
        and schemas.get("consumer_c3_authority")
        != "wiki_viva_upgrade_consumer_c3_authority.v1"
    ):
        errors.append(
            "contract_versions.consumer_c3_authority must be "
            "wiki_viva_upgrade_consumer_c3_authority.v1"
        )
    compatibility = _require_list(package.get("compatibility"), "compatibility", errors)
    for index, entry in enumerate(compatibility):
        row = _require_mapping(entry, f"compatibility[{index}]", errors)
        for field in (
            "surface",
            "v8_behavior",
            "warning_becomes_error",
            "removal_target",
        ):
            if not str(row.get(field) or "").strip():
                errors.append(f"compatibility[{index}].{field} is required")
    preflight = _require_mapping(package.get("preflight"), "preflight", errors)
    required_gates = _require_list(
        preflight.get("required_gates"), "preflight.required_gates", errors
    )
    if not required_gates:
        errors.append("preflight.required_gates cannot be empty")
    if schema_version == TWO_LANE_UPGRADE_PACKAGE_SCHEMA_VERSION:
        if required_gates != ["diff_check"]:
            errors.append(
                "preflight.required_gates must be exactly ['diff_check'] for "
                "a legacy-safe v3 B0"
            )
        if "reviewable_gates" in preflight:
            errors.append(
                "preflight.reviewable_gates is forbidden for v3; domain repair "
                "must precede a fresh B0"
            )
    reviewable_gates = preflight.get("reviewable_gates") or {}
    if not isinstance(reviewable_gates, dict):
        errors.append("preflight.reviewable_gates must be a mapping")
        reviewable_gates = {}
    for gate_id, raw_policy in reviewable_gates.items():
        if gate_id != "semantic_inventory":
            errors.append(
                "preflight.reviewable_gates may only declare semantic_inventory"
            )
        if gate_id not in required_gates:
            errors.append(
                f"preflight.reviewable_gates.{gate_id} must also be required"
            )
        policy = _require_mapping(
            raw_policy, f"preflight.reviewable_gates.{gate_id}", errors
        )
        if policy.get("required_boundary") != "downstream_adaptations":
            errors.append(
                f"preflight.reviewable_gates.{gate_id}.required_boundary "
                "must be downstream_adaptations"
            )
        max_findings = policy.get("max_findings")
        if (
            isinstance(max_findings, bool)
            or not isinstance(max_findings, int)
            or not 1 <= max_findings <= 10_000
        ):
            errors.append(
                f"preflight.reviewable_gates.{gate_id}.max_findings is invalid"
            )
    migration = _require_mapping(package.get("migration"), "migration", errors)
    raw_commit_boundaries = migration.get("commit_boundaries")
    commit_boundaries = (
        []
        if schema_version == LEGACY_UPGRADE_PACKAGE_SCHEMA_VERSION
        and raw_commit_boundaries is None
        else _require_list(
            raw_commit_boundaries, "migration.commit_boundaries", errors
        )
    )
    if schema_version in {
        UPGRADE_PACKAGE_SCHEMA_VERSION,
        TWO_LANE_UPGRADE_PACKAGE_SCHEMA_VERSION,
    } and not commit_boundaries:
        errors.append("migration.commit_boundaries cannot be empty")
    normalized_boundaries = [str(value) for value in commit_boundaries]
    if len(normalized_boundaries) != len(set(normalized_boundaries)):
        errors.append("migration.commit_boundaries must be unique")
    canonical_ids = [boundary for boundary, _field in _MIGRATION_COMMIT_BOUNDARIES]
    for index, value in enumerate(commit_boundaries):
        if not isinstance(value, str) or value not in canonical_ids:
            errors.append(f"migration.commit_boundaries[{index}] is invalid")
    known_boundaries = [
        value for value in normalized_boundaries if value in canonical_ids
    ]
    if known_boundaries != sorted(
        known_boundaries, key=canonical_ids.index
    ):
        errors.append("migration.commit_boundaries must use canonical order")
    if (
        schema_version
        in {UPGRADE_PACKAGE_SCHEMA_VERSION, TWO_LANE_UPGRADE_PACKAGE_SCHEMA_VERSION}
        and normalized_boundaries
        and normalized_boundaries[0] != "faithful_public_import"
    ):
        errors.append(
            "migration.commit_boundaries must begin with faithful_public_import"
        )
    generated_patterns_value = migration.get("generated_artifact_patterns")
    generated_patterns = (
        []
        if generated_patterns_value is None
        else _require_list(
            generated_patterns_value,
            "migration.generated_artifact_patterns",
            errors,
        )
    )
    if (
        schema_version
        in {UPGRADE_PACKAGE_SCHEMA_VERSION, TWO_LANE_UPGRADE_PACKAGE_SCHEMA_VERSION}
        and "regenerated_artifacts" in normalized_boundaries
        and not generated_patterns
    ):
        errors.append(
            "migration.generated_artifact_patterns is required when "
            "regenerated_artifacts is declared"
        )
    normalized_generated_patterns = [str(value) for value in generated_patterns]
    if len(normalized_generated_patterns) != len(set(normalized_generated_patterns)):
        errors.append("migration.generated_artifact_patterns must be unique")
    for index, value in enumerate(generated_patterns):
        if not isinstance(value, str) or not _safe_repo_pattern(value):
            errors.append(
                f"migration.generated_artifact_patterns[{index}] is unsafe"
            )
    if schema_version == TWO_LANE_UPGRADE_PACKAGE_SCHEMA_VERSION:
        errors.extend(
            _effective_c1_c2_disjoint_errors(
                allow=allow,
                block=block,
                generated_patterns=generated_patterns,
            )
        )
    migration_gates = _require_list(
        migration.get("required_gates"), "migration.required_gates", errors
    )
    if not migration_gates:
        errors.append("migration.required_gates cannot be empty")
    gate_commands_value = migration.get("gate_commands")
    if gate_commands_value is not None and not isinstance(gate_commands_value, dict):
        errors.append("migration.gate_commands must be a mapping")
    gate_commands = (
        gate_commands_value if isinstance(gate_commands_value, dict) else {}
    )
    if schema_version in {
        UPGRADE_PACKAGE_SCHEMA_VERSION,
        TWO_LANE_UPGRADE_PACKAGE_SCHEMA_VERSION,
    } and migration_gates:
        # The package is the command registry: evidence may only claim gate
        # runs whose exact command the package registered up front.
        if not gate_commands:
            errors.append(
                "migration.gate_commands must register the exact command for "
                "every required gate"
            )
        elif {str(key) for key in gate_commands} != {
            str(value) for value in migration_gates
        }:
            errors.append(
                "migration.gate_commands must cover exactly migration.required_gates"
            )
        for gate_id, command in gate_commands.items():
            if (
                not isinstance(command, str)
                or not command.strip()
                or _migration_command_is_placeholder(command)
            ):
                errors.append(
                    f"migration.gate_commands.{gate_id} must be an exact command"
                )
    visual_profiles = _require_list(
        migration.get("visual_profiles"), "migration.visual_profiles", errors
    )
    if schema_version in {
        UPGRADE_PACKAGE_SCHEMA_VERSION,
        TWO_LANE_UPGRADE_PACKAGE_SCHEMA_VERSION,
    } and not visual_profiles:
        errors.append("migration.visual_profiles cannot be empty")
    normalized_profiles = [str(value) for value in visual_profiles]
    if len(normalized_profiles) != len(set(normalized_profiles)):
        errors.append("migration.visual_profiles must be unique")
    for index, value in enumerate(visual_profiles):
        if not isinstance(value, str) or not _VISUAL_PROFILE_RE.fullmatch(value):
            errors.append(f"migration.visual_profiles[{index}] is invalid")
    if schema_version == TWO_LANE_UPGRADE_PACKAGE_SCHEMA_VERSION:
        gate_mapping_value = preflight.get("gate_mapping")
        if not isinstance(gate_mapping_value, Mapping):
            errors.append("preflight.gate_mapping must be a mapping")
        else:
            preflight_ids = {str(value) for value in required_gates}
            if set(str(key) for key in gate_mapping_value) != preflight_ids:
                errors.append(
                    "preflight.gate_mapping must cover exactly preflight.required_gates"
                )
            migration_ids = {str(value) for value in migration_gates}
            if any(
                not isinstance(value, str) or value not in migration_ids
                for value in gate_mapping_value.values()
            ):
                errors.append(
                    "preflight.gate_mapping values must name migration.required_gates"
                )
            if dict(gate_mapping_value) != {"diff_check": "diff_check"}:
                errors.append(
                    "preflight.gate_mapping must be exactly "
                    "{'diff_check': 'diff_check'} for a legacy-safe v3 B0"
                )
        errors.extend(_validate_two_lane_package(migration, migration_gates))
    return errors


def package_is_pinned(package: dict[str, Any]) -> bool:
    release = package.get("release") if isinstance(package.get("release"), dict) else {}
    sha = str(release.get("source_sha") or "").strip().lower()
    release_id = str(release.get("id") or "").strip().lower()
    status = str(release.get("status") or "").strip().lower()
    return bool(
        _valid_sha(sha)
        and release_id not in _UNPINNED
        and status in _RELEASABLE_STATUSES
    )


def validate_consumer_inventory(inventory: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if inventory.get("schema_version") != CONSUMER_INVENTORY_SCHEMA_VERSION:
        errors.append(f"schema_version must be {CONSUMER_INVENTORY_SCHEMA_VERSION}")
    if not _DATE_RE.fullmatch(str(inventory.get("verified_on") or "")):
        errors.append("verified_on must be YYYY-MM-DD")
    consumers = _require_list(inventory.get("consumers"), "consumers", errors)
    seen: set[str] = set()
    for index, value in enumerate(consumers):
        prefix = f"consumers[{index}]"
        consumer = _require_mapping(value, prefix, errors)
        consumer_id = str(consumer.get("id") or "")
        if not consumer_id:
            errors.append(f"{prefix}.id is required")
        elif consumer_id in seen:
            errors.append(f"duplicate consumer id: {consumer_id}")
        seen.add(consumer_id)
        repository = _require_mapping(
            consumer.get("repository"), f"{prefix}.repository", errors
        )
        for field in ("name", "path", "remote", "owner"):
            if not str(repository.get(field) or "").strip():
                errors.append(f"{prefix}.repository.{field} is required")
        if consumer.get("consumer_type") not in CONSUMER_TYPES:
            errors.append(
                f"{prefix}.consumer_type must be one of {sorted(CONSUMER_TYPES)}"
            )
        if consumer.get("current_runtime") not in RUNTIMES:
            errors.append(f"{prefix}.current_runtime must be one of {sorted(RUNTIMES)}")
        if consumer.get("local_operator") not in OPERATORS:
            errors.append(f"{prefix}.local_operator must be one of {sorted(OPERATORS)}")
        if consumer.get("privacy_risk") not in PRIVACY_RISKS:
            errors.append(
                f"{prefix}.privacy_risk must be one of {sorted(PRIVACY_RISKS)}"
            )
        if consumer.get("upgrade_wave") not in UPGRADE_WAVES:
            errors.append(
                f"{prefix}.upgrade_wave must be one of {sorted(UPGRADE_WAVES)}"
            )
        for field in (
            "current_kit_version",
            "current_layout",
            "local_templates",
            "drift_status",
        ):
            if field not in consumer:
                errors.append(f"{prefix}.{field} is required")
    return errors


def consumer_from_inventory(
    inventory: dict[str, Any], consumer_id: str
) -> dict[str, Any]:
    for consumer in inventory.get("consumers") or []:
        if isinstance(consumer, dict) and consumer.get("id") == consumer_id:
            return consumer
    raise KeyError(f"consumer not found in inventory: {consumer_id}")


def _matches(path: str, pattern: str) -> bool:
    normalized = path
    candidate = pattern
    if candidate.endswith("/**"):
        prefix = candidate[:-3].rstrip("/")
        # ``foo/**`` is a directory contract, so it includes both ``foo`` and
        # every descendant. Match the prefix as a glob as well: portable
        # package entries such as ``.skills/wiki-*/**`` otherwise fall into
        # this branch and are incorrectly treated as a literal directory.
        return fnmatch.fnmatchcase(normalized, prefix) or fnmatch.fnmatchcase(
            normalized, candidate
        )
    if candidate.endswith("/"):
        return normalized.startswith(candidate)
    return normalized == candidate or fnmatch.fnmatchcase(normalized, candidate)


def _segment_pattern_contains(container: str, contained: str) -> bool:
    """Conservatively prove containment for one repository path segment.

    This deliberately returns ``False`` for relationships it cannot prove.
    Equality, a full-segment wildcard and literal members of a glob are enough
    for the bounded subtree contracts used by upgrade packages.
    """

    if container == contained or container in {"*", "**"}:
        return True
    if not re.search(r"[*?[]", contained):
        return fnmatch.fnmatchcase(contained, container)
    return False


def _repo_pattern_contains(container: str, contained: str) -> bool:
    """Conservatively prove that one package glob contains another.

    A trailing ``/**`` owns its directory and every descendant.  For other
    patterns, both sides must have the same segment arity and each contained
    segment must be provably inside the corresponding container segment.  The
    fail-closed result is intentional: uncertain glob-language relationships
    cannot authorize boundary reuse.
    """

    if container == contained:
        return True
    container_parts = container.split("/")
    contained_parts = contained.split("/")
    container_tree = len(container_parts) > 1 and container_parts[-1] == "**"
    contained_tree = len(contained_parts) > 1 and contained_parts[-1] == "**"
    container_prefix = container_parts[:-1] if container_tree else container_parts
    contained_prefix = contained_parts[:-1] if contained_tree else contained_parts
    if container_tree:
        if len(contained_prefix) < len(container_prefix):
            return False
        return all(
            _segment_pattern_contains(owner, candidate)
            for owner, candidate in zip(container_prefix, contained_prefix)
        )
    if contained_tree or len(container_prefix) != len(contained_prefix):
        return False
    return all(
        _segment_pattern_contains(owner, candidate)
        for owner, candidate in zip(container_prefix, contained_prefix)
    )


def _effective_c1_c2_disjoint_errors(
    *,
    allow: Sequence[Any],
    block: Sequence[Any],
    generated_patterns: Sequence[Any],
) -> list[str]:
    """Require an explicit, provable block for every C2 ownership glob.

    C1 is ``allow - block``.  Requiring each complete C2 language to be
    contained by a block rule proves that no generated path can enter the
    effective byte-equal C1 projection, including when a broad allow rule also
    contains it.  Invalid patterns are reported by the caller and cannot be
    used as proof here.
    """

    safe_allow = [str(value) for value in allow if isinstance(value, str)]
    safe_block = [str(value) for value in block if isinstance(value, str)]
    errors: list[str] = []
    for index, raw_pattern in enumerate(generated_patterns):
        if not isinstance(raw_pattern, str) or not _safe_repo_pattern(raw_pattern):
            continue
        # Evaluate allow containment as part of the effective-C1 proof.  The
        # result does not weaken the explicit-block requirement: C2 ownership
        # must remain visible and reviewable even if today's allowlist narrows.
        allowed_by_c1 = any(
            _repo_pattern_contains(pattern, raw_pattern)
            for pattern in safe_allow
        )
        block_proves_disjoint = any(
            _repo_pattern_contains(pattern, raw_pattern)
            for pattern in safe_block
        )
        effective_c1_overlap = allowed_by_c1 and not block_proves_disjoint
        error = (
            "migration.generated_artifact_patterns"
            f"[{index}] is not fully excluded from effective C1 by "
            "portable_import.block"
        )
        if effective_c1_overlap:
            errors.append(error)
        elif not block_proves_disjoint:
            # An explicit C2 reservation is still required outside today's
            # allowlist so a later C1 expansion cannot silently claim it.
            errors.append(error)
    return errors


def _canonical_portable_path(path: str) -> tuple[str | None, str]:
    """Require one canonical repository-relative POSIX path.

    Matching is deliberately downstream of this parser.  Globs must never be
    allowed to normalize traversal, platform separators or absolute paths into
    an allowlisted spelling.
    """

    raw = str(path)
    if not raw or raw != raw.strip() or "\x00" in raw:
        return None, "unsafe non-canonical path"
    if (
        raw.startswith(("/", "./", "~"))
        or "\\" in raw
        or _WINDOWS_DRIVE_RE.match(raw)
    ):
        return None, "unsafe non-canonical path"
    parts = raw.split("/")
    if any(not part or part in {".", ".."} for part in parts):
        return None, "unsafe non-canonical path"
    return "/".join(parts), ""


def _portable_path_has_sensitive_name(path: str) -> bool:
    for part in path.split("/"):
        folded = part.casefold()
        if folded == ".env" or folded.startswith(".env."):
            return True
        basename = folded.lstrip(".").split(".", 1)[0]
        if basename in _SENSITIVE_PORTABLE_BASENAMES:
            return True
    return False


def portable_path_status(path: str, package: dict[str, Any]) -> tuple[bool, str]:
    normalized, error = _canonical_portable_path(path)
    if normalized is None:
        return False, error
    if _portable_path_has_sensitive_name(normalized):
        return False, "blocked by global sensitive-name policy"
    if normalized in _CONSUMER_OWNED_PORTABLE_PATHS:
        return False, "blocked by global consumer-owned manifest policy"
    if not (
        normalized in _PORTABLE_ROOT_FILES
        or normalized.startswith(_PORTABLE_ROOT_PREFIXES)
        or normalized.startswith(".skills/wiki-")
    ):
        return False, "blocked by global portable-surface policy"
    portable = package.get("portable_import") or {}
    for pattern in portable.get("block") or []:
        if _matches(normalized, str(pattern)):
            return False, f"blocked by {pattern}"
    for pattern in portable.get("allow") or []:
        if _matches(normalized, str(pattern)):
            return True, f"allowed by {pattern}"
    return False, "not in portable allowlist"


def _generated_artifact_path_status(
    path: str, package: dict[str, Any]
) -> tuple[bool, str]:
    """Return whether ``path`` belongs exclusively to the package C2 surface."""

    normalized, error = _canonical_portable_path(path)
    if normalized is None:
        return False, error
    if _portable_path_has_sensitive_name(normalized):
        return False, "blocked by global sensitive-name policy"
    if normalized in _CONSUMER_OWNED_PORTABLE_PATHS:
        return False, "blocked by global consumer-owned manifest policy"
    if not (
        normalized in _PORTABLE_ROOT_FILES
        or normalized.startswith(_PORTABLE_ROOT_PREFIXES)
        or normalized.startswith(".skills/wiki-")
    ):
        return False, "blocked by global portable-surface policy"
    migration = package.get("migration") or {}
    patterns = migration.get("generated_artifact_patterns") or []
    if not any(_matches(normalized, str(pattern)) for pattern in patterns):
        return False, "not in generated artifact ownership"
    if (
        package.get("schema_version") == TWO_LANE_UPGRADE_PACKAGE_SCHEMA_VERSION
        and portable_path_status(normalized, package)[0]
    ):
        return False, "generated artifact overlaps effective C1"
    return True, "owned by generated artifact C2"


def _migration_subject_path_status(
    path: str, package: dict[str, Any]
) -> tuple[bool, str]:
    """Select the complete migration subject while keeping C1 and C2 disjoint."""

    portable = portable_path_status(path, package)
    if portable[0]:
        return portable
    generated = _generated_artifact_path_status(path, package)
    if generated[0]:
        return generated
    return portable


def _iter_files(root: Path) -> Iterable[str]:
    if not root.exists():
        return []
    files: list[str] = []
    for path in root.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        files.append(rel.as_posix())
    return sorted(files)


def _ignore_patterns(root: Path) -> list[str]:
    path = root / ".toolkit-drift-ignore"
    if not path.exists():
        return []
    return sorted(
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def _unsafe_ignore_patterns(patterns: Sequence[str]) -> list[str]:
    """Refuse ignore intent aimed at portable executable/verification surfaces."""

    critical_prefixes = (
        ".github/workflows",
        "apps/wiki-cockpit",
        "scripts",
        "tests",
        "wiki_core",
    )
    critical_files = {"requirements.txt", "wiki.page-types.yaml", "wiki.templates.yaml"}
    unsafe: list[str] = []
    for raw in patterns:
        pattern = raw.replace("\\", "/").lstrip("./")
        literal_head = re.split(r"[*?[]", pattern, maxsplit=1)[0].rstrip("/")
        if (
            pattern in {"*", "**", "**/*"}
            or pattern in critical_files
            or any(
                literal_head == prefix
                or literal_head.startswith(f"{prefix}/")
                or prefix.startswith(f"{literal_head}/")
                for prefix in critical_prefixes
                if literal_head
            )
        ):
            unsafe.append(raw)
    return sorted(set(unsafe))


def compare_portable_files(
    kit_root: Path,
    consumer_root: Path,
    package: dict[str, Any],
    *,
    source_sha: str | None = None,
    git_no_replace_objects: bool = False,
) -> dict[str, Any]:
    """Compare allowlisted files byte-for-byte.

    When ``source_sha`` is supplied, the public side comes from that exact Git
    tree rather than the kit checkout's working tree.  This matters for release
    metadata commits made after the payload they pin: preflight must never
    silently compare a consumer with later, unpinned files on disk.
    """

    ignored_patterns = _ignore_patterns(consumer_root)

    def selected(root: Path) -> set[str]:
        return {
            rel
            for rel in _iter_files(root)
            if _migration_subject_path_status(rel, package)[0]
        }

    source_blobs: dict[str, str] = {}
    if source_sha:
        source_blobs = _git_tree_blobs(
            kit_root,
            source_sha,
            no_replace_objects=git_no_replace_objects,
        )
        kit_files = {
            rel
            for rel in source_blobs
            if _migration_subject_path_status(rel, package)[0]
        }
    else:
        kit_files = selected(kit_root)
    consumer_files = selected(consumer_root)
    shared = kit_files & consumer_files
    if source_sha:
        blob_payloads = _git_blob_payloads(
            kit_root,
            {source_blobs[rel] for rel in shared},
            no_replace_objects=git_no_replace_objects,
        )
        differing = sorted(
            rel
            for rel in shared
            if blob_payloads[source_blobs[rel]] != (consumer_root / rel).read_bytes()
        )
    else:
        differing = sorted(
            rel
            for rel in shared
            if (kit_root / rel).read_bytes() != (consumer_root / rel).read_bytes()
        )
    report = {
        "only_in_kit": sorted(kit_files - consumer_files),
        "only_in_consumer": sorted(consumer_files - kit_files),
        "content_differs": differing,
        "ignored_per_repo": ignored_patterns,
        "ignored_matches": sorted(
            rel
            for rel in kit_files | consumer_files
            if any(_matches(rel, pattern) for pattern in ignored_patterns)
        ),
        "unsafe_ignore_patterns": _unsafe_ignore_patterns(ignored_patterns),
        "source_mode": "pinned_git_tree" if source_sha else "working_tree",
        "source_sha": source_sha or "",
    }
    report["drift_total"] = sum(
        len(report[key])
        for key in ("only_in_kit", "only_in_consumer", "content_differs")
    )
    return report


def _git_commit_available(root: Path, sha: str) -> bool:
    if not sha:
        return False
    try:
        subprocess.run(
            ["git", "cat-file", "-e", f"{sha}^{{commit}}"],
            cwd=root,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


def _git_tree_blobs(
    root: Path,
    sha: str,
    *,
    no_replace_objects: bool = False,
) -> dict[str, str]:
    """Return repository-relative blob paths for one exact Git tree."""

    try:
        raw = subprocess.check_output(
            ["git", "ls-tree", "-r", "-z", sha],
            cwd=root,
            stderr=subprocess.DEVNULL,
            env=_git_subprocess_env(no_replace_objects),
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"release source_sha is unavailable in kit checkout: {sha}") from exc
    blobs: dict[str, str] = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        metadata, separator, raw_path = record.partition(b"\t")
        parts = metadata.split()
        if not separator or len(parts) != 3 or parts[1] != b"blob":
            continue
        path = raw_path.decode("utf-8", errors="surrogateescape")
        blobs[path] = parts[2].decode("ascii")
    return blobs


def _git_tree_entries(root: Path, sha: str) -> dict[str, tuple[str, str]]:
    """Return blob mode and object id for every file in one committed tree."""

    try:
        raw = subprocess.check_output(
            ["git", "ls-tree", "-r", "-z", sha],
            cwd=root,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"Git tree is unavailable: {sha}") from exc
    entries: dict[str, tuple[str, str]] = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        metadata, separator, raw_path = record.partition(b"\t")
        parts = metadata.split()
        if not separator or len(parts) != 3 or parts[1] != b"blob":
            continue
        entries[raw_path.decode("utf-8", errors="surrogateescape")] = (
            parts[0].decode("ascii"),
            parts[2].decode("ascii"),
        )
    return entries


def _git_subprocess_env(no_replace_objects: bool) -> dict[str, str] | None:
    if not no_replace_objects:
        return None
    return {**os.environ, "GIT_NO_REPLACE_OBJECTS": "1"}


def _git_blob_payloads(
    root: Path,
    object_ids: set[str],
    *,
    no_replace_objects: bool = False,
) -> dict[str, bytes]:
    """Read many Git blobs through one batch process."""

    if not object_ids:
        return {}
    ordered = sorted(object_ids)
    with subprocess.Popen(
        ["git", "cat-file", "--batch"],
        cwd=root,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_git_subprocess_env(no_replace_objects),
    ) as process:
        stdout_raw, stderr_raw = process.communicate(
            "".join(f"{oid}\n" for oid in ordered).encode("ascii")
        )
        return_code = process.returncode

    payloads: dict[str, bytes] = {}
    batch_errors: list[str] = []
    fatal_error = ""
    with io.BytesIO(stdout_raw) as stdout:
        for requested in ordered:
            header = stdout.readline().decode("ascii", errors="replace").strip()
            parts = header.split()
            if len(parts) == 2 and parts[1] in {
                "missing",
                "ambiguous",
                "dangling",
                "loop",
                "notdir",
            }:
                # ``git cat-file --batch`` reports object-level failures on
                # stdout and may continue writing later records.  Drain the
                # complete batch before raising so a later large blob cannot
                # fill the pipe and deadlock the reader during process exit.
                batch_errors.append(f"{requested}:{parts[1]}")
                continue
            if len(parts) != 3:
                fatal_error = f"invalid batch header for {requested}"
                break
            try:
                size = int(parts[2])
            except ValueError:
                fatal_error = f"invalid batch size for {requested}"
                break
            payload = stdout.read(size)
            terminator = stdout.read(1)
            if len(payload) != size or terminator != b"\n":
                fatal_error = f"truncated release blob {requested}"
                break
            if parts[1] != "blob":
                batch_errors.append(f"{requested}:unexpected-{parts[1]}")
                continue
            payloads[requested] = payload
    stderr = stderr_raw.decode("utf-8", errors="replace").strip()
    if fatal_error:
        raise ValueError(f"could not read release blobs: {fatal_error}")
    if return_code != 0:
        raise ValueError(f"could not read release blobs: {stderr or return_code}")
    if batch_errors:
        raise ValueError(
            "could not read release blobs: " + ", ".join(sorted(batch_errors))
        )
    return payloads


def _portable_git_tree_comparison(
    kit_root: Path,
    source_sha: str,
    consumer_root: Path,
    consumer_sha: str,
    package: dict[str, Any],
) -> dict[str, Any]:
    """Compare two committed trees without consulting either working tree."""

    source_all = _git_tree_entries(kit_root, source_sha)
    consumer_all = _git_tree_entries(consumer_root, consumer_sha)
    source = {
        path: oid
        for path, oid in source_all.items()
        if _migration_subject_path_status(path, package)[0]
    }
    consumer = {
        path: oid
        for path, oid in consumer_all.items()
        if _migration_subject_path_status(path, package)[0]
    }
    shared = set(source) & set(consumer)
    source_payloads = _git_blob_payloads(
        kit_root, {source[path][1] for path in shared}
    )
    consumer_payloads = _git_blob_payloads(
        consumer_root, {consumer[path][1] for path in shared}
    )
    differing = sorted(
        path
        for path in shared
        if source[path][0] != consumer[path][0]
        or source_payloads[source[path][1]] != consumer_payloads[consumer[path][1]]
    )
    report = {
        "only_in_kit": sorted(set(source) - set(consumer)),
        "only_in_consumer": sorted(set(consumer) - set(source)),
        "content_differs": differing,
        "source_mode": "pinned_git_tree",
        "source_sha": source_sha,
        "consumer_sha": consumer_sha,
    }
    report["drift_total"] = sum(
        len(report[key])
        for key in ("only_in_kit", "only_in_consumer", "content_differs")
    )
    return report


def _portable_drift_paths(drift: Mapping[str, Any]) -> list[str]:
    return sorted(
        {
            str(path)
            for key in ("only_in_kit", "only_in_consumer", "content_differs")
            for path in (drift.get(key) or [])
        }
    )


def _path_digest(paths: Sequence[str]) -> str:
    return hashlib.sha256(
        canonical_json(sorted(set(paths))).encode("utf-8")
    ).hexdigest()


def _source_projection_digest(
    kit_root: Path,
    source_sha: str,
    paths: Sequence[str],
) -> str:
    """Bind public source bytes (and expected deletions) with SHA-256."""

    source_entries = _git_tree_entries(kit_root, source_sha)
    selected = {path: source_entries.get(path) for path in sorted(set(paths))}
    payloads = _git_blob_payloads(
        kit_root, {entry[1] for entry in selected.values() if entry is not None}
    )
    projection = [
        {
            "path": path,
            "mode": entry[0] if entry is not None else None,
            "sha256": (
                hashlib.sha256(payloads[entry[1]]).hexdigest()
                if entry is not None
                else None
            ),
        }
        for path, entry in selected.items()
    ]
    return hashlib.sha256(canonical_json(projection).encode("utf-8")).hexdigest()


def _partition_portable_drift(
    *,
    drift: Mapping[str, Any],
    package: dict[str, Any],
    kit_root: Path,
    source_sha: str,
    include_paths: bool,
) -> dict[str, Any]:
    paths = _portable_drift_paths(drift)
    migration = package.get("migration")
    migration = migration if isinstance(migration, dict) else {}
    patterns = [str(value) for value in migration.get("generated_artifact_patterns") or []]
    generated = sorted(
        path for path in paths if any(_matches(path, pattern) for pattern in patterns)
    )
    generated_set = set(generated)
    imported = sorted(path for path in paths if path not in generated_set)

    def summary(values: list[str]) -> dict[str, Any]:
        result: dict[str, Any] = {
            "path_count": len(values),
            "paths_sha256": _path_digest(values),
            "source_projection_sha256": _source_projection_digest(
                kit_root, source_sha, values
            ),
        }
        if include_paths:
            result["paths"] = values
        return result

    return {
        "portable_drift": {
            "path_count": len(paths),
            "paths_sha256": _path_digest(paths),
        },
        "faithful_public_import": summary(imported),
        "regenerated_artifacts": summary(generated),
    }


def _git_diff_paths(root: Path, parent: str, child: str) -> list[str]:
    try:
        raw = subprocess.check_output(
            [
                "git",
                "diff-tree",
                "--no-commit-id",
                "--name-only",
                "--no-renames",
                "-r",
                "-z",
                parent,
                child,
            ],
            cwd=root,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    return sorted(
        part.decode("utf-8", errors="surrogateescape")
        for part in raw.split(b"\0")
        if part
    )


def _git_commit_parents(root: Path, sha: str) -> list[str]:
    raw = _git(root, "rev-list", "--parents", "-n", "1", sha)
    parts = raw.split()
    return parts[1:] if parts and parts[0] == sha else []


def _tree_paths_match_source_bytes(
    *,
    kit_root: Path,
    source_sha: str,
    consumer_root: Path,
    consumer_sha: str,
    paths: Sequence[str],
) -> bool:
    source = _git_tree_entries(kit_root, source_sha)
    consumer = _git_tree_entries(consumer_root, consumer_sha)
    source_oids = {source[path][1] for path in paths if path in source}
    consumer_oids = {consumer[path][1] for path in paths if path in consumer}
    source_payloads = _git_blob_payloads(kit_root, source_oids)
    consumer_payloads = _git_blob_payloads(consumer_root, consumer_oids)
    for path in paths:
        source_entry = source.get(path)
        consumer_entry = consumer.get(path)
        if (source_entry is None) != (consumer_entry is None):
            return False
        if source_entry is not None and consumer_entry is not None:
            source_mode, source_oid = source_entry
            consumer_mode, consumer_oid = consumer_entry
            if source_mode != consumer_mode:
                return False
            if source_payloads[source_oid] != consumer_payloads[consumer_oid]:
                return False
    return True


def _tree_paths_are_secret_safe(
    *,
    root: Path,
    sha: str,
    paths: Sequence[str],
) -> bool:
    """Scan committed adaptation text without ever returning its private value."""

    entries = _git_tree_entries(root, sha)
    if any(path not in entries for path in paths):
        return False
    selected_entries = {path: entries[path] for path in paths if path in entries}
    if any(mode not in {"100644", "100755"} for mode, _oid in selected_entries.values()):
        return False
    selected = {path: entry[1] for path, entry in selected_entries.items()}
    payloads = _git_blob_payloads(root, set(selected.values()))
    for oid in selected.values():
        raw = payloads[oid]
        if b"\x00" in raw:
            return False
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return False
        if any(finding.category == "secret" for finding in scan_text(text)):
            return False
    return True


def _tree_release_records_are_non_executable_markdown(
    *,
    root: Path,
    sha: str,
    paths: Sequence[str],
    references_root: str,
) -> bool:
    """Keep consumer release records as inert Markdown data in the checked tree."""

    prefix = f"{references_root.rstrip('/')}/releases/"
    release_records = [path for path in paths if path.startswith(prefix)]
    entries = _git_tree_entries(root, sha)
    return all(
        path.endswith(".md")
        and path in entries
        and entries[path][0] == "100644"
        for path in release_records
    )


def _git(root: Path, *args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=root, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def git_state(root: Path) -> dict[str, Any]:
    status = _git(root, "status", "--porcelain=v1")
    entries = sorted(line for line in status.splitlines() if line)
    return {
        "head_sha": _git(root, "rev-parse", "HEAD"),
        "branch": _git(root, "branch", "--show-current"),
        "status_short": entries,
        "dirty_count": len(entries),
    }


def _safe_config(root: Path) -> dict[str, Any]:
    config_path = root / "wiki.config.yaml"
    if config_path.is_symlink() or not config_path.is_file():
        return {}
    try:
        config_path.resolve(strict=True).relative_to(root.resolve())
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def configured_layout(root: Path) -> dict[str, Any]:
    config = _safe_config(root)
    paths = config.get("paths") if isinstance(config.get("paths"), dict) else {}
    contexts = config.get("contexts") or []
    if isinstance(contexts, str):
        contexts = [item.strip() for item in contexts.split(",") if item.strip()]
    if not isinstance(contexts, list):
        contexts = []
    return {
        "language": str(config.get("language") or "en"),
        "context_count": len(contexts),
        "memory_root": str(paths.get("memory_root") or "memories"),
        "references_root": str(paths.get("references_root") or "docs/references"),
        "derived_root": str(paths.get("derived_root") or "data/derived/wiki"),
        "cockpit_root": "apps/wiki-cockpit"
        if (root / "apps/wiki-cockpit").is_dir()
        else "",
    }


def discover_local_overrides(root: Path) -> dict[str, Any]:
    known = [
        "wiki.config.yaml",
        "wiki.targets.yaml",
        "wiki.templates.local.yaml",
        "wiki.page-types.yaml",
        "wiki.page-types.local.yaml",
        "apps/wiki-cockpit/public/wiki-cockpit.config.json",
        ".toolkit-drift-ignore",
    ]
    present = [rel for rel in known if (root / rel).exists()]
    secret_adjacent = sum(
        1 for rel in (".env", ".env.local", ".env.production") if (root / rel).exists()
    )
    source_adapter_count = (
        sum(
            1
            for path in (root / "scripts").glob("wiki_*source*.py")
            if path.is_file() and not path.is_symlink()
        )
        if (root / "scripts").is_dir()
        else 0
    )
    return {
        "known_files": present,
        "source_adapter_count": source_adapter_count,
        "secret_adjacent_file_count": secret_adjacent,
    }


def _snapshot_state(
    root: Path, layout: dict[str, Any], allow_sample: bool
) -> dict[str, Any]:
    derived = (
        root
        / str(layout.get("derived_root") or "data/derived/wiki")
        / "web-snapshot"
        / "manifest.json"
    )
    sample = root / "apps/wiki-cockpit/public/sample-snapshot/manifest.json"
    candidate: Path | None = (
        derived
        if derived.exists()
        else sample
        if allow_sample and sample.exists()
        else None
    )
    if candidate is None:
        return {"available": False, "kind": "missing", "manifest": ""}
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "available": False,
            "kind": "invalid",
            "manifest": candidate.relative_to(root).as_posix(),
        }
    return {
        "available": True,
        "kind": "real" if candidate == derived else "public_sample",
        "manifest": candidate.relative_to(root).as_posix(),
        "schema_version": str(payload.get("schema_version") or ""),
        "snapshot_id": str(payload.get("snapshot_id") or ""),
        "bundle_hash": str(payload.get("bundle_hash") or ""),
    }


def validate_gate_evidence(
    evidence: dict[str, Any],
    required: list[str],
    head_sha: str,
    *,
    reviewable: Mapping[str, Any] | None = None,
) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    if evidence.get("schema_version") != GATE_EVIDENCE_SCHEMA_VERSION:
        errors.append(
            f"gate evidence schema_version must be {GATE_EVIDENCE_SCHEMA_VERSION}"
        )
    if str(evidence.get("consumer_head") or "") != head_sha:
        errors.append(
            "gate evidence consumer_head does not match the current consumer HEAD"
        )
    gates = evidence.get("gates") if isinstance(evidence.get("gates"), list) else []
    by_id = {
        str(item.get("id")): item
        for item in gates
        if isinstance(item, dict) and item.get("id")
    }
    reviewable = reviewable if isinstance(reviewable, Mapping) else {}
    accepted_reviews: dict[str, dict[str, Any]] = {}
    for gate_id in required:
        gate = by_id.get(str(gate_id))
        if gate is None:
            errors.append(f"missing required gate evidence: {gate_id}")
            continue
        status = gate.get("status")
        if gate_id == "toolkit_drift":
            if status not in {"pass", "reviewed"}:
                errors.append("toolkit_drift evidence must be pass or reviewed")
        elif status == "reviewed":
            policy = reviewable.get(gate_id)
            policy = policy if isinstance(policy, Mapping) else {}
            finding_count = gate.get("finding_count")
            max_findings = policy.get("max_findings")
            planned_boundary = str(gate.get("planned_boundary") or "")
            required_boundary = str(policy.get("required_boundary") or "")
            valid_count = (
                not isinstance(finding_count, bool)
                and isinstance(finding_count, int)
                and isinstance(max_findings, int)
                and 1 <= finding_count <= max_findings
            )
            if (
                not policy
                or not valid_count
                or not _valid_sha256(gate.get("findings_sha256"))
                or not required_boundary
                or planned_boundary != required_boundary
                or not str(gate.get("note") or "").strip()
            ):
                errors.append(
                    f"reviewed gate evidence is incomplete or unauthorized: {gate_id}"
                )
            else:
                accepted_reviews[gate_id] = {
                    "finding_count": finding_count,
                    "findings_sha256": str(gate.get("findings_sha256")),
                    "planned_boundary": planned_boundary,
                }
        elif status != "pass":
            errors.append(f"required gate did not pass: {gate_id}")
        if not str(gate.get("command") or "").strip():
            errors.append(f"required gate has no recorded command: {gate_id}")
    return errors, {
        "required": required,
        "recorded": sorted(by_id),
        "statuses": {
            gate_id: str(by_id[gate_id].get("status") or "")
            for gate_id in sorted(by_id)
        },
        "reviews": accepted_reviews,
        "all_pass": not errors,
    }


def _redacted_identifier(kind: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"{kind}:sha256:{digest}"


def _check(
    check_id: str, status: str, evidence: str, blocking: bool = True
) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": status,
        "blocking": blocking,
        "evidence": evidence,
    }


def build_preflight_report(
    *,
    kit_root: Path,
    consumer_root: Path,
    package: dict[str, Any],
    consumer: dict[str, Any],
    gate_evidence: dict[str, Any] | None,
    checked_on: str,
    redact: bool = False,
    private_evidence_ref: str | None = None,
) -> dict[str, Any]:
    """Compile a deterministic, read-only preflight report for one consumer."""

    package_errors = validate_upgrade_package(package)
    if package_errors:
        raise ValueError("invalid upgrade package: " + "; ".join(package_errors))
    if not _DATE_RE.fullmatch(checked_on):
        raise ValueError("checked_on must be YYYY-MM-DD")
    if not consumer_root.is_dir():
        raise ValueError(f"consumer root does not exist: {consumer_root}")

    privacy_risk = str(consumer.get("privacy_risk") or "unknown")
    redaction_required = privacy_risk != "public_safe" or bool(
        consumer.get("evidence_redaction_required", False)
    )
    private_ref = str(private_evidence_ref or "")
    canonical_private_ref, _private_ref_error = _canonical_portable_path(private_ref)
    authoritative_private = bool(
        not redact
        and private_ref
        and canonical_private_ref == private_ref
        and Path(private_ref).suffix.lower() == ".json"
        and not _portable_path_has_sensitive_name(private_ref)
        and _git_path_is_ignored_and_untracked(consumer_root.resolve(), private_ref)
    )
    # A private-risk request without an explicitly ignored sidecar is forced
    # through the redacted projection even when the caller forgot --redact.
    # It remains blocked below so stdout can never become an authority channel.
    effective_redact = bool(redact or (redaction_required and not authoritative_private))

    state = git_state(consumer_root)
    layout = configured_layout(consumer_root)
    overrides = discover_local_overrides(consumer_root)
    release_pinned = package_is_pinned(package)
    release_sha = str((package.get("release") or {}).get("source_sha") or "")
    release_status = str(
        (package.get("release") or {}).get("status") or ""
    ).strip().lower()
    release_id = (
        str((package.get("release") or {}).get("id") or "").strip().lower()
    )
    # Promotion state and source-tree availability are separate facts. A
    # validation-pending candidate must still expose its real drift while the
    # release_pinned check keeps migration/promotion blocked.
    release_source_available = _valid_sha(release_sha) and _git_commit_available(
        kit_root, release_sha
    )
    if release_source_available:
        if state["dirty_count"] == 0 and _valid_sha(state["head_sha"]):
            drift = _portable_git_tree_comparison(
                kit_root,
                release_sha,
                consumer_root,
                state["head_sha"],
                package,
            )
            ignored_patterns = _ignore_patterns(consumer_root)
            drift.update(
                {
                    "ignored_per_repo": ignored_patterns,
                    "ignored_matches": sorted(
                        path
                        for path in _portable_drift_paths(drift)
                        if any(_matches(path, pattern) for pattern in ignored_patterns)
                    ),
                    "unsafe_ignore_patterns": _unsafe_ignore_patterns(
                        ignored_patterns
                    ),
                }
            )
        else:
            drift = compare_portable_files(
                kit_root, consumer_root, package, source_sha=release_sha
            )
        migration_partition = _partition_portable_drift(
            drift=drift,
            package=package,
            kit_root=kit_root,
            source_sha=release_sha,
            include_paths=not effective_redact,
        )
    else:
        drift = {
            "only_in_kit": [],
            "only_in_consumer": [],
            "content_differs": [],
            "ignored_per_repo": _ignore_patterns(consumer_root),
            "ignored_matches": [],
            "unsafe_ignore_patterns": _unsafe_ignore_patterns(
                _ignore_patterns(consumer_root)
            ),
            "drift_total": 0,
            "source_mode": "pinned_git_tree",
            "source_sha": release_sha,
        }
        empty_digest = _path_digest([])
        migration_partition = {
            "portable_drift": {
                "path_count": 0,
                "paths_sha256": empty_digest,
            },
            "faithful_public_import": {
                "path_count": 0,
                "paths_sha256": empty_digest,
                "source_projection_sha256": empty_digest,
                **({"paths": []} if not effective_redact else {}),
            },
            "regenerated_artifacts": {
                "path_count": 0,
                "paths_sha256": empty_digest,
                "source_projection_sha256": empty_digest,
                **({"paths": []} if not effective_redact else {}),
            },
        }
    allow_sample = consumer.get("local_operator") == "static_demo"
    snapshot = _snapshot_state(consumer_root, layout, allow_sample=allow_sample)
    required_gates = [
        str(value)
        for value in (package.get("preflight") or {}).get("required_gates") or []
    ]
    reviewable_gates = (
        (package.get("preflight") or {}).get("reviewable_gates") or {}
    )
    gate_errors, gate_summary = validate_gate_evidence(
        gate_evidence or {},
        required_gates,
        state["head_sha"],
        reviewable=reviewable_gates,
    )

    checks: list[dict[str, Any]] = []
    checks.append(
        _check(
            "release_pinned",
            "pass" if release_pinned else "fail",
            "exact public release and SHA"
            if release_pinned
            else (
                "release source_sha is not pinned"
                if not _valid_sha(release_sha)
                else (
                    f"release id is not pinned: {release_id or 'missing'}"
                    if release_id in _UNPINNED
                    else f"release status is not releasable: {release_status or 'missing'}"
                )
            ),
        )
    )
    checks.append(
        _check(
            "release_source_available",
            "pass" if release_source_available else "fail",
            f"pinned Git tree available: {release_sha}"
            if release_source_available
            else f"pinned Git tree unavailable: {release_sha or 'missing'}",
        )
    )
    branch_prefix = str(
        (package.get("preflight") or {}).get("branch_prefix") or "wiki/"
    )
    branch_ok = bool(state["branch"] and state["branch"].startswith(branch_prefix))
    checks.append(
        _check(
            "upgrade_branch",
            "pass" if branch_ok else "fail",
            state["branch"] or "detached/unknown",
        )
    )
    checks.append(
        _check(
            "clean_worktree",
            "pass" if state["dirty_count"] == 0 else "fail",
            f"dirty_count={state['dirty_count']}",
        )
    )
    checks.append(
        _check(
            "current_gates",
            "pass" if not gate_errors else "fail",
            "; ".join(gate_errors)
            if gate_errors
            else "all required gates passed or have bounded reviews at current HEAD",
        )
    )
    semantic_review = (gate_summary.get("reviews") or {}).get(
        "semantic_inventory"
    )
    if isinstance(semantic_review, dict):
        checks.append(
            _check(
                "semantic_inventory_adaptation",
                "warn",
                "finding_count="
                f"{semantic_review['finding_count']}; findings_sha256="
                f"{semantic_review['findings_sha256']}; planned_boundary="
                f"{semantic_review['planned_boundary']}",
                blocking=False,
            )
        )
    drift_evidence_status = str(
        (gate_summary.get("statuses") or {}).get("toolkit_drift") or ""
    )
    unsafe_ignore_patterns = list(drift.get("unsafe_ignore_patterns") or [])
    if unsafe_ignore_patterns:
        checks.append(
            _check(
                "toolkit_ignore_policy",
                "fail",
                "ignore patterns target portable core/tooling verification surfaces",
            )
        )
    elif drift.get("ignored_per_repo"):
        checks.append(
            _check(
                "toolkit_ignore_policy",
                "warn",
                "ignore patterns are inventory hints only; exact drift remains counted",
                blocking=False,
            )
        )
    else:
        checks.append(
            _check(
                "toolkit_ignore_policy",
                "pass",
                "no per-repository drift ignore patterns",
            )
        )
    if not release_source_available:
        checks.append(
            _check(
                "toolkit_drift",
                "fail",
                "cannot compare drift because the pinned release tree is unavailable",
            )
        )
    elif drift["drift_total"] == 0 and drift_evidence_status == "pass":
        checks.append(_check("toolkit_drift", "pass", "drift_total=0"))
    elif drift["drift_total"] > 0 and drift_evidence_status == "reviewed":
        checks.append(
            _check(
                "toolkit_drift",
                "warn",
                f"drift_total={drift['drift_total']}; explicitly reviewed for import/adaptation",
                blocking=False,
            )
        )
    else:
        checks.append(
            _check(
                "toolkit_drift",
                "fail",
                f"drift_total={drift['drift_total']}; evidence_status={drift_evidence_status or 'missing'}",
            )
        )
    snapshot_required = consumer.get("current_runtime") not in {"no_cockpit", "unknown"}
    snapshot_ok = snapshot["available"] or not snapshot_required
    checks.append(
        _check(
            "current_snapshot",
            "pass" if snapshot_ok else "fail",
            f"kind={snapshot['kind']}",
            blocking=snapshot_required,
        )
    )
    target_snapshot = str(
        (package.get("contract_versions") or {}).get("snapshot") or ""
    )
    current_snapshot = str(snapshot.get("schema_version") or "")
    if (
        snapshot["available"]
        and target_snapshot
        and current_snapshot != target_snapshot
    ):
        checks.append(
            _check(
                "snapshot_schema_migration",
                "warn",
                f"current={current_snapshot or 'unknown'}; target={target_snapshot}",
                blocking=False,
            )
        )
    # Most restrictive wins. Private unredacted evidence is accepted only for
    # one explicitly ignored/untracked JSON sidecar; every stdout/default path
    # stays redacted and non-authoritative.
    privacy_ok = privacy_risk not in {"unknown", "secret_adjacent"} and (
        not redaction_required or redact or authoritative_private
    )
    checks.append(
        _check(
            "privacy_evidence",
            "pass" if privacy_ok else "fail",
            "risk="
            f"{privacy_risk}; redacted={effective_redact}; "
            f"authoritative_private={authoritative_private}",
        )
    )
    if overrides["known_files"] or overrides["source_adapter_count"]:
        checks.append(
            _check(
                "local_overrides",
                "warn",
                "local overrides require reviewed adaptation",
                blocking=False,
            )
        )

    blockers = [
        item["id"] for item in checks if item["status"] == "fail" and item["blocking"]
    ]
    warnings = [item["id"] for item in checks if item["status"] == "warn"]
    status_paths = state["status_short"]
    status_entry_count = len(status_paths)
    consumer_head = state["head_sha"]
    if effective_redact:
        # A hash per private path is still linkable and vulnerable to guessing
        # from a small set of likely repository filenames. Public evidence only
        # needs the aggregate dirty count; detailed paths stay in the private
        # consumer-side report.
        status_paths = []
        consumer_head = (
            _redacted_identifier("consumer-head", consumer_head)
            if consumer_head
            else ""
        )
        if snapshot.get("snapshot_id"):
            snapshot["snapshot_id"] = _redacted_identifier(
                "snapshot", str(snapshot["snapshot_id"])
            )
    repository = (
        consumer.get("repository")
        if isinstance(consumer.get("repository"), dict)
        else {}
    )
    report_layout = layout
    report_checks = checks
    consumer_id = str(consumer.get("id") or "")
    repository_name = str(repository.get("name") or consumer_root.name)
    consumer_branch = state["branch"]
    if effective_redact:
        report_layout = {
            "language": str(layout.get("language") or ""),
            "context_count": int(layout.get("context_count") or 0),
            "memory_root": _PUBLIC_REDACTED_VALUE,
            "references_root": _PUBLIC_REDACTED_VALUE,
            "derived_root": _PUBLIC_REDACTED_VALUE,
            "cockpit_root": _PUBLIC_REDACTED_VALUE,
        }
        report_checks = [
            {
                **item,
                "evidence": _PUBLIC_REDACTED_VALUE,
            }
            for item in checks
        ]
        consumer_id = _PUBLIC_REDACTED_VALUE
        repository_name = _PUBLIC_REDACTED_VALUE
        consumer_branch = _PUBLIC_REDACTED_VALUE
        if snapshot.get("manifest"):
            snapshot["manifest"] = _PUBLIC_REDACTED_VALUE
    report = {
        "schema_version": PREFLIGHT_SCHEMA_VERSION,
        "checked_on": checked_on,
        "status": "ready" if not blockers else "blocked",
        "source_package": {
            "release": str((package.get("release") or {}).get("id") or ""),
            "source_sha": str((package.get("release") or {}).get("source_sha") or ""),
            "plan": str((package.get("release") or {}).get("plan") or ""),
            "package_sha256": upgrade_package_sha256(package),
        },
        "consumer_before": {
            "id": consumer_id,
            "repository": repository_name,
            "path": (
                "<redacted-local-path>"
                if effective_redact
                else str(consumer_root.resolve())
            ),
            "branch": consumer_branch,
            "head_sha": consumer_head,
            "current_kit_version": str(
                consumer.get("current_kit_version") or "untracked"
            ),
            "status_short": status_paths,
            "status_entry_count": status_entry_count,
        },
        "layout": report_layout,
        "runtime": str(consumer.get("current_runtime") or "unknown"),
        "local_operator": str(consumer.get("local_operator") or "unknown"),
        "local_overrides": overrides,
        "privacy": {
            "risk": privacy_risk,
            "redaction_required": redaction_required,
            "report_redacted": effective_redact,
            "authoritative_private": authoritative_private,
            "authoritative_ref": private_ref if authoritative_private else "",
        },
        "drift": drift
        if not effective_redact
        else {
            "drift_total": drift["drift_total"],
            "only_in_kit_count": len(drift["only_in_kit"]),
            "only_in_consumer_count": len(drift["only_in_consumer"]),
            "content_differs_count": len(drift["content_differs"]),
            "ignored_per_repo_count": len(drift["ignored_per_repo"]),
        },
        "migration_partition": migration_partition,
        "snapshot": snapshot,
        "gate_evidence": gate_summary,
        "checks": report_checks,
        "blockers": blockers,
        "warnings": warnings,
    }
    report["report_id"] = deterministic_id("preflight", report)
    return report


def migration_evidence_template(package: dict[str, Any]) -> dict[str, Any]:
    required_gates = [
        str(value)
        for value in (package.get("migration") or {}).get("required_gates") or []
    ]
    package_digest = upgrade_package_sha256(package)
    declared_fields = _migration_commit_boundary_fields(package) or (
        "import_commit_sha",
    )
    boundary_placeholders = {
        "import_commit_sha": "REPLACE_WITH_IMPORT_COMMIT_SHA",
        "artifact_commit_sha": "REPLACE_WITH_ARTIFACT_COMMIT_SHA",
        "adaptation_commit_sha": "REPLACE_WITH_ADAPTATION_COMMIT_SHA",
    }
    final_head_placeholder = boundary_placeholders[declared_fields[-1]]
    return {
        "schema_version": MIGRATION_EVIDENCE_SCHEMA_VERSION,
        "evidence_context": {
            "package_sha256": package_digest,
            "validator_version": MIGRATION_VALIDATOR_VERSION,
            "captured_consumer_head": final_head_placeholder,
        },
        "source": {
            "release": str((package.get("release") or {}).get("id") or ""),
            "sha": "REPLACE_WITH_PINNED_PUBLIC_SHA",
            "plan": str((package.get("release") or {}).get("plan") or ""),
        },
        "consumer_before": {
            "repository": "consumer-id",
            "branch": "wiki/upgrade-v8",
            "head_sha": "REPLACE_WITH_PREVIOUS_CONSUMER_SHA",
            "kit_version": "untracked",
            "gate_status": "pass",
            "memory_root": "REPLACE_WITH_CONSUMER_MEMORY_ROOT",
            "references_root": "REPLACE_WITH_CONSUMER_REFERENCES_ROOT",
            "preflight": {
                "status": "ready",
                "report_id": "REPLACE_WITH_PREFLIGHT_REPORT_ID",
                "report_sha256": "REPLACE_WITH_PREFLIGHT_REPORT_SHA256",
                "report_ref": "output/wiki-upgrade/REPLACE_WITH_PREFLIGHT_REPORT_REF.json",
                "package_sha256": package_digest,
                "consumer_head": "REPLACE_WITH_PREVIOUS_CONSUMER_SHA",
            },
        },
        "consumer_after": {
            "branch": "wiki/upgrade-v8",
            **{
                field: boundary_placeholders[field]
                if field in declared_fields
                else None
                for _boundary, field in _MIGRATION_COMMIT_BOUNDARIES
            },
        },
        "omitted_boundaries": [
            {
                "boundary": field,
                "reason": "This boundary is not declared by the upgrade package.",
            }
            for field in ("artifact_commit_sha", "adaptation_commit_sha")
            if field not in declared_fields
        ],
        "files_imported": ["wiki_core/upgrade.py"],
        "generated_artifacts": (
            ["REPLACE_WITH_GENERATED_ARTIFACT_PATH"]
            if "artifact_commit_sha" in declared_fields
            else []
        ),
        "downstream_adaptations": (
            ["REPLACE_WITH_DOWNSTREAM_ADAPTATION_PATH"]
            if "adaptation_commit_sha" in declared_fields
            else []
        ),
        "local_overrides_kept": ["wiki.config.yaml", "wiki.targets.yaml"],
        "warnings": [],
        "fixtures_added": [],
        "gates_receipt_ref": (
            "output/wiki-upgrade/REPLACE_WITH_GATE_RECEIPTS_REF.json"
        ),
        "gates": [
            {
                "id": gate_id,
                "command": str(
                    ((package.get("migration") or {}).get("gate_commands") or {}).get(
                        gate_id
                    )
                    or f"record exact {gate_id} command"
                ),
                "status": "pass",
                "exit_code": 0,
                "captured_consumer_head": final_head_placeholder,
            }
            for gate_id in required_gates
        ],
        "visual_qa_evidence": [
            {
                "profile": profile,
                "route_ref": "public-fixture:canonical-root",
                "center_ref": "public-fixture:root",
                "viewport": (
                    "390x844"
                    if profile in {"mobile", "fallback"}
                    else "1440x1000"
                ),
                "browser": "webkit" if profile == "mobile" else "chromium",
                "screenshot_ref": f"output/wiki-upgrade/qa/{profile}.png",
                "screenshot_sha256": "REPLACE_WITH_SCREENSHOT_SHA256",
                "screenshot_bytes": 0,
                "screenshot_dimensions": {"width": 0, "height": 0},
                "captured_consumer_head": final_head_placeholder,
                "console_status": "clean",
                "network_status": "clean",
                "sample_fallback": False,
            }
            for profile in _migration_visual_profiles(package)
        ],
        "rollback": {
            "previous_sha": "REPLACE_WITH_PREVIOUS_CONSUMER_SHA",
            "import_commit_sha": "REPLACE_WITH_IMPORT_COMMIT_SHA",
            "command": "git revert --no-commit "
            + " ".join(
                boundary_placeholders[field] for field in reversed(declared_fields)
            ),
            "preserves_local_paths": [
                "wiki.config.yaml",
                "wiki.targets.yaml",
                "REPLACE_WITH_CONSUMER_MEMORY_ROOT",
            ],
        },
    }


def _valid_sha(value: Any) -> bool:
    sha = str(value or "").lower()
    return bool(_SHA_RE.fullmatch(sha) and len(set(sha)) >= 4)


def _valid_sha256(value: Any) -> bool:
    return bool(_SHA256_RE.fullmatch(str(value or "").lower()))


def _positive_int(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value > 0


def _migration_command_is_placeholder(value: Any) -> bool:
    command = str(value or "").strip()
    return not command or bool(_MIGRATION_COMMAND_PLACEHOLDER_RE.search(command))


def _git_path_is_ignored_and_untracked(root: Path, relative: str) -> bool:
    ignored = subprocess.run(
        ["git", "check-ignore", "--quiet", "--", relative],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", relative],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0
    return ignored and not tracked


def _canonical_preflight_payload(report: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in report.items() if key != "report_id"}


def _validate_preflight_report_binding(
    *,
    kit_root: Path,
    consumer_root: Path,
    before: dict[str, Any],
    package: dict[str, Any],
    errors: list[str],
) -> dict[str, Any] | None:
    """Bind checked migration evidence to one immutable preflight JSON file."""

    preflight = before.get("preflight")
    preflight = preflight if isinstance(preflight, dict) else {}
    report_ref = str(preflight.get("report_ref") or "")
    if not _git_path_is_ignored_and_untracked(consumer_root, report_ref):
        errors.append(
            "consumer_before.preflight.report_ref must be ignored and untracked"
        )
    try:
        from wiki_core.release_receipt import (
            ReleaseReceiptError,
            _read_safe_evidence_file,
        )

        _relative, raw = _read_safe_evidence_file(
            consumer_root,
            report_ref,
            label="migration preflight report",
        )
        loaded = json.loads(raw.decode("utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("preflight report root must be a mapping")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        del exc
        errors.append("consumer_before.preflight.report_ref is missing or unsafe")
        return None
    except ReleaseReceiptError:
        errors.append("consumer_before.preflight.report_ref is missing or unsafe")
        return None

    payload = _canonical_preflight_payload(loaded)
    expected_id = deterministic_id("preflight", payload)
    expected_sha256 = hashlib.sha256(
        canonical_json(payload).encode("utf-8")
    ).hexdigest()
    if loaded.get("report_id") != expected_id:
        errors.append("preflight report_id is not canonical for its content")
    if preflight.get("report_id") != expected_id:
        errors.append("consumer_before.preflight.report_id does not match report_ref")
    if preflight.get("report_sha256") != expected_sha256:
        errors.append(
            "consumer_before.preflight.report_sha256 does not match report_ref"
        )
    if loaded.get("status") != "ready":
        errors.append("referenced preflight report status must be ready")
    if loaded.get("blockers") != []:
        errors.append("referenced preflight report blockers must be empty")

    source_package = loaded.get("source_package")
    source_package = source_package if isinstance(source_package, dict) else {}
    release = package.get("release")
    release = release if isinstance(release, dict) else {}
    if source_package.get("release") != release.get("id"):
        errors.append("referenced preflight release does not match the upgrade package")
    if source_package.get("source_sha") != release.get("source_sha"):
        errors.append(
            "referenced preflight source_sha does not match the upgrade package"
        )
    if source_package.get("package_sha256") != upgrade_package_sha256(package):
        errors.append(
            "referenced preflight package_sha256 does not match the upgrade package"
        )
    report_before = loaded.get("consumer_before")
    report_before = report_before if isinstance(report_before, dict) else {}
    if report_before.get("head_sha") != before.get("head_sha"):
        errors.append(
            "referenced preflight consumer HEAD does not match consumer_before.head_sha"
        )
    if report_before.get("branch") != before.get("branch"):
        errors.append(
            "referenced preflight consumer branch does not match consumer_before.branch"
        )
    report_layout = loaded.get("layout")
    report_layout = report_layout if isinstance(report_layout, dict) else {}
    if str(report_layout.get("memory_root") or "").rstrip("/") != str(
        before.get("memory_root") or ""
    ).rstrip("/"):
        errors.append(
            "referenced preflight memory root does not match consumer_before.memory_root"
        )
    if str(report_layout.get("references_root") or "").rstrip("/") != str(
        before.get("references_root") or ""
    ).rstrip("/"):
        errors.append(
            "referenced preflight references root does not match consumer_before.references_root"
        )
    privacy = loaded.get("privacy")
    privacy = privacy if isinstance(privacy, dict) else {}
    if privacy.get("report_redacted") is not False:
        errors.append("referenced migration preflight must be authoritative and unredacted")
    if (
        privacy.get("risk") != "public_safe"
        and privacy.get("authoritative_private") is not True
    ):
        errors.append(
            "referenced private migration preflight lacks ignored-sidecar authority"
        )
    if (
        privacy.get("risk") != "public_safe"
        and privacy.get("authoritative_ref") != report_ref
    ):
        errors.append(
            "referenced private migration preflight authority does not match report_ref"
        )

    source_sha = str(release.get("source_sha") or "")
    before_sha = str(before.get("head_sha") or "")
    if _valid_sha(source_sha) and _valid_sha(before_sha):
        try:
            drift = _portable_git_tree_comparison(
                kit_root,
                source_sha,
                consumer_root,
                before_sha,
                package,
            )
            expected_partition = _partition_portable_drift(
                drift=drift,
                package=package,
                kit_root=kit_root,
                source_sha=source_sha,
                include_paths=True,
            )
            if loaded.get("migration_partition") != expected_partition:
                errors.append(
                    "referenced preflight portable migration partition does not match committed trees"
                )
        except ValueError:
            errors.append(
                "referenced preflight portable migration partition could not be recomputed"
            )
    return loaded


def _final_migration_sha(after: dict[str, Any]) -> str:
    for field in (
        "adaptation_commit_sha",
        "artifact_commit_sha",
        "import_commit_sha",
    ):
        value = str(after.get(field) or "")
        if value:
            return value
    return ""


def _validate_visual_file_binding(
    *,
    consumer_root: Path,
    item: dict[str, Any],
    index: int,
    errors: list[str],
) -> None:
    """Verify one screenshot from content, never from its declared path alone."""

    try:
        # Lazy import avoids the historical release_receipt -> upgrade import
        # edge at module initialization while still sharing the hardened file
        # reader and strict PNG parser.
        from wiki_core.release_receipt import visual_evidence_file_metadata

        actual = visual_evidence_file_metadata(
            consumer_root,
            item.get("screenshot_ref"),
            label=f"migration screenshot {index}",
        )
    except (OSError, ValueError):
        errors.append(
            f"visual_qa_evidence[{index}].screenshot_ref is missing or unsafe"
        )
        return
    declared = {
        "path": str(item.get("screenshot_ref") or ""),
        "sha256": str(item.get("screenshot_sha256") or ""),
        "bytes": item.get("screenshot_bytes"),
        "dimensions": item.get("screenshot_dimensions"),
    }
    if actual != declared:
        errors.append(
            f"visual_qa_evidence[{index}] screenshot hash/bytes/dimensions do not match"
        )


def _validate_gate_receipts_binding(
    *,
    evidence: dict[str, Any],
    required_gates: list[str],
    gate_commands: dict[str, str],
    consumer_root: Path | None,
    final_migration_sha: str,
    errors: list[str],
) -> None:
    """Bind checked gate claims to one immutable executed-run receipt file."""

    ref = str(evidence.get("gates_receipt_ref") or "")
    if not ref:
        errors.append(
            "checked migration evidence requires gates_receipt_ref: an ignored "
            "untracked receipt of the executed gate commands"
        )
        return
    canonical, _canonical_error = _canonical_portable_path(ref)
    if (
        canonical is None
        or canonical != ref
        or Path(ref).suffix.lower() != ".json"
        or _portable_path_has_sensitive_name(ref)
    ):
        errors.append("gates_receipt_ref must be a safe repo-relative .json path")
        return
    if consumer_root is None:
        errors.append(
            "consumer Git verification root is required to bind gates_receipt_ref"
        )
        return
    root = consumer_root.resolve()
    if not _git_path_is_ignored_and_untracked(root, canonical):
        errors.append("gates_receipt_ref must be ignored and untracked in the consumer")
    try:
        from wiki_core.release_receipt import (
            ReleaseReceiptError,
            _read_safe_evidence_file,
        )

        _relative, raw = _read_safe_evidence_file(
            root,
            canonical,
            label="migration gate receipts",
        )
        loaded = json.loads(raw.decode("utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("gate receipts root must be a mapping")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        del exc
        errors.append("gates_receipt_ref is missing or unsafe")
        return
    except ReleaseReceiptError:
        errors.append("gates_receipt_ref is missing or unsafe")
        return

    if loaded.get("schema_version") != MIGRATION_GATE_RECEIPTS_SCHEMA_VERSION:
        errors.append(
            f"gate receipts schema_version must be "
            f"{MIGRATION_GATE_RECEIPTS_SCHEMA_VERSION}"
        )
    if loaded.get("captured_consumer_head") != final_migration_sha:
        errors.append(
            "gate receipts captured_consumer_head must match the final "
            "migration boundary"
        )
    receipt_items = loaded.get("gates")
    receipt_items = receipt_items if isinstance(receipt_items, list) else []
    receipts_by_id: dict[str, dict[str, Any]] = {}
    for item in receipt_items:
        if not isinstance(item, dict):
            errors.append("gate receipts entries must be mappings")
            continue
        receipt_id = str(item.get("id") or "")
        if receipt_id in receipts_by_id:
            errors.append(f"gate receipts contain duplicate id: {receipt_id}")
        receipts_by_id[receipt_id] = item
    for gate_id in required_gates:
        receipt = receipts_by_id.get(gate_id)
        if receipt is None:
            errors.append(f"missing executed gate receipt: {gate_id}")
            continue
        registered_command = gate_commands.get(gate_id)
        if registered_command is not None and (
            receipt.get("command") != registered_command
        ):
            errors.append(
                f"gate receipt command does not match the package registry: {gate_id}"
            )
        exit_code = receipt.get("exit_code")
        if isinstance(exit_code, bool) or exit_code != 0:
            errors.append(f"gate receipt exit_code must be 0: {gate_id}")
        output_sha = str(receipt.get("output_sha256") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", output_sha):
            errors.append(
                f"gate receipt output_sha256 must be a lowercase sha256: {gate_id}"
            )


def validate_migration_evidence(
    evidence: dict[str, Any],
    package: dict[str, Any],
    *,
    public_export: bool = False,
    consumer_root: Path | None = None,
    kit_root: Path | None = None,
    require_git_commits: bool = False,
) -> list[str]:
    if not _finite_json_value(package):
        return ["upgrade package contract is invalid"]
    if not _finite_json_value(evidence):
        return ["migration evidence must contain only finite JSON-compatible values"]
    schema_evidence = evidence
    if package.get("schema_version") == LEGACY_UPGRADE_PACKAGE_SCHEMA_VERSION:
        # V1 packages predate the explicit artifact/adaptation path arrays.
        # Normalize only for schema validation; the caller's evidence remains
        # immutable and report projection still emits deterministic empties.
        schema_evidence = dict(evidence)
        schema_evidence.setdefault("generated_artifacts", [])
        schema_evidence.setdefault("downstream_adaptations", [])
    errors: list[str] = _migration_evidence_schema_errors(schema_evidence)
    if validate_upgrade_package(package):
        # Do not copy package validation prose here: malformed package values
        # can contain private names and this list crosses public projections.
        errors.append("upgrade package contract is invalid")
    if not package_is_pinned(package):
        errors.append("upgrade package release is blocked or source_sha is not pinned")
    if evidence.get("schema_version") != MIGRATION_EVIDENCE_SCHEMA_VERSION:
        errors.append(f"schema_version must be {MIGRATION_EVIDENCE_SCHEMA_VERSION}")
    evidence_context = _require_mapping(
        evidence.get("evidence_context"), "evidence_context", errors
    )
    if evidence_context.get("package_sha256") != upgrade_package_sha256(package):
        errors.append("evidence_context.package_sha256 does not match the upgrade package")
    if evidence_context.get("validator_version") != MIGRATION_VALIDATOR_VERSION:
        errors.append(
            f"evidence_context.validator_version must be {MIGRATION_VALIDATOR_VERSION}"
        )
    if not _valid_sha(evidence_context.get("captured_consumer_head")):
        errors.append("evidence_context.captured_consumer_head must be an exact Git SHA")
    source = _require_mapping(evidence.get("source"), "source", errors)
    if not str(source.get("release") or "").strip():
        errors.append("source.release is required")
    if not _valid_sha(source.get("sha")):
        errors.append("source.sha must be an exact 40-64 character Git SHA")
    if not str(source.get("plan") or "").strip():
        errors.append("source.plan is required")
    package_sha = str((package.get("release") or {}).get("source_sha") or "")
    package_release = str((package.get("release") or {}).get("id") or "")
    package_plan = str((package.get("release") or {}).get("plan") or "")
    if source.get("release") != package_release:
        errors.append("source.release does not match the upgrade package")
    if _valid_sha(package_sha) and source.get("sha") != package_sha:
        errors.append("source.sha does not match the pinned upgrade package")
    if source.get("plan") != package_plan:
        errors.append("source.plan does not match the upgrade package")

    before = _require_mapping(
        evidence.get("consumer_before"), "consumer_before", errors
    )
    for field in ("repository", "branch", "kit_version", "gate_status"):
        if not str(before.get(field) or "").strip():
            errors.append(f"consumer_before.{field} is required")
    if not _valid_sha(before.get("head_sha")):
        errors.append("consumer_before.head_sha must be an exact Git SHA")
    memory_root = str(before.get("memory_root") or "")
    normalized_memory_root_input = (
        memory_root[:-1] if memory_root.endswith("/") else memory_root
    )
    normalized_memory_root, _memory_root_error = _canonical_portable_path(
        normalized_memory_root_input
    )
    if (
        normalized_memory_root is None
        or memory_root
        not in {normalized_memory_root, f"{normalized_memory_root}/"}
        or _migration_command_is_placeholder(memory_root)
    ):
        errors.append("consumer_before.memory_root must be a safe repo-relative path")
    references_root = str(before.get("references_root") or "")
    normalized_references_root_input = (
        references_root[:-1] if references_root.endswith("/") else references_root
    )
    normalized_references_root, _references_root_error = _canonical_portable_path(
        normalized_references_root_input
    )
    if (
        normalized_references_root is None
        or references_root
        not in {normalized_references_root, f"{normalized_references_root}/"}
        or _migration_command_is_placeholder(references_root)
    ):
        errors.append(
            "consumer_before.references_root must be a safe repo-relative path"
        )
    if (
        normalized_memory_root
        and normalized_references_root
        and (
            normalized_memory_root == normalized_references_root
            or normalized_memory_root.startswith(f"{normalized_references_root}/")
            or normalized_references_root.startswith(f"{normalized_memory_root}/")
        )
    ):
        errors.append(
            "consumer_before.memory_root and references_root must be disjoint repository roots"
        )
    preflight = _require_mapping(
        before.get("preflight"), "consumer_before.preflight", errors
    )
    if preflight.get("status") != "ready":
        errors.append("consumer_before.preflight.status must be ready")
    if not re.fullmatch(
        r"preflight:[0-9a-f]{20}", str(preflight.get("report_id") or "")
    ):
        errors.append("consumer_before.preflight.report_id is invalid")
    if not _valid_sha256(preflight.get("report_sha256")):
        errors.append(
            "consumer_before.preflight.report_sha256 must be an exact SHA-256"
        )
    report_ref = str(preflight.get("report_ref") or "")
    canonical_report_ref, _report_ref_error = _canonical_portable_path(report_ref)
    if (
        canonical_report_ref != report_ref
        or Path(report_ref).suffix.lower() != ".json"
        or _portable_path_has_sensitive_name(report_ref)
        or _migration_command_is_placeholder(report_ref)
    ):
        errors.append(
            "consumer_before.preflight.report_ref must be a safe repo-relative JSON path"
        )
    if preflight.get("package_sha256") != evidence_context.get("package_sha256"):
        errors.append(
            "consumer_before.preflight.package_sha256 must match evidence_context.package_sha256"
        )
    if preflight.get("consumer_head") != before.get("head_sha"):
        errors.append(
            "consumer_before.preflight.consumer_head must match consumer_before.head_sha"
        )
    after = _require_mapping(evidence.get("consumer_after"), "consumer_after", errors)
    if not str(after.get("branch") or "").startswith("wiki/"):
        errors.append("consumer_after.branch must use the wiki/ prefix")
    declared_boundary_fields = _migration_commit_boundary_fields(package)
    for field in (
        "import_commit_sha",
        "artifact_commit_sha",
        "adaptation_commit_sha",
    ):
        value = after.get(field)
        if field in declared_boundary_fields:
            if not _valid_sha(value):
                errors.append(
                    f"consumer_after.{field} is required by migration.commit_boundaries "
                    "and must be an exact Git SHA"
                )
        elif value not in (None, ""):
            errors.append(
                f"consumer_after.{field} must be null because the upgrade package "
                "does not declare its boundary"
            )
    final_migration_sha = _final_migration_sha(after)
    if evidence_context.get("captured_consumer_head") != final_migration_sha:
        errors.append(
            "evidence_context.captured_consumer_head must match the final non-null migration boundary"
        )

    imported = _require_list(evidence.get("files_imported"), "files_imported", errors)
    legacy_package = (
        package.get("schema_version") == LEGACY_UPGRADE_PACKAGE_SCHEMA_VERSION
    )
    generated = (
        []
        if legacy_package and "generated_artifacts" not in evidence
        else _require_list(
            evidence.get("generated_artifacts"), "generated_artifacts", errors
        )
    )
    adaptations = (
        []
        if legacy_package and "downstream_adaptations" not in evidence
        else _require_list(
            evidence.get("downstream_adaptations"),
            "downstream_adaptations",
            errors,
        )
    )
    migration_config = package.get("migration")
    migration_config = migration_config if isinstance(migration_config, dict) else {}
    generated_patterns = [
        str(value)
        for value in migration_config.get("generated_artifact_patterns") or []
    ]
    for label, values in (
        ("files_imported", imported),
        ("generated_artifacts", generated),
        ("downstream_adaptations", adaptations),
    ):
        normalized_values = [str(value) for value in values]
        if len(normalized_values) != len(set(normalized_values)):
            errors.append(f"{label} must contain unique paths")
        if normalized_values != sorted(normalized_values):
            errors.append(f"{label} must use canonical sorted order")
        for index, rel in enumerate(normalized_values):
            canonical, _reason = _canonical_portable_path(rel)
            if canonical != rel or rel.endswith("/"):
                errors.append(f"{label}[{index}] must be a canonical file path")

    if "faithful_public_import" in (
        migration_config.get("commit_boundaries") or []
    ) and not imported:
        errors.append("files_imported cannot be empty for faithful_public_import")
    if "regenerated_artifacts" in (
        migration_config.get("commit_boundaries") or []
    ) and not generated:
        errors.append("generated_artifacts cannot be empty for regenerated_artifacts")
    if "regenerated_artifacts" not in (
        migration_config.get("commit_boundaries") or []
    ) and generated:
        errors.append(
            "generated_artifacts must be empty when regenerated_artifacts is not declared"
        )
    if "downstream_adaptations" in (
        migration_config.get("commit_boundaries") or []
    ) and not adaptations:
        errors.append("downstream_adaptations cannot be empty for downstream_adaptations")
    if "downstream_adaptations" not in (
        migration_config.get("commit_boundaries") or []
    ) and adaptations:
        errors.append(
            "downstream_adaptations must be empty when downstream_adaptations is not declared"
        )

    for index, rel in enumerate(imported):
        allowed, _reason = portable_path_status(str(rel), package)
        if not allowed:
            errors.append(f"files_imported[{index}] contains a non-portable path")
    for index, rel in enumerate(generated):
        rel = str(rel)
        allowed, _reason = _generated_artifact_path_status(rel, package)
        if not allowed:
            errors.append(
                f"generated_artifacts[{index}] contains a non-generated C2 path"
            )

    screenshot_refs = {
        str(item.get("screenshot_ref") or "")
        for item in evidence.get("visual_qa_evidence") or []
        if isinstance(item, dict)
    }
    forbidden_refs = screenshot_refs | {report_ref}
    for index, rel_value in enumerate(adaptations):
        rel = str(rel_value)
        allowed, _reason = portable_path_status(rel, package)
        if allowed:
            errors.append(
                f"downstream_adaptations[{index}] must not modify a portable path"
            )
        in_configured_memory = bool(
            normalized_memory_root
            and (
                rel == normalized_memory_root
                or rel.startswith(f"{normalized_memory_root}/")
            )
        )
        in_configured_release_subtree = bool(
            normalized_references_root
            and rel.startswith(f"{normalized_references_root}/releases/")
        )
        in_configured_release_records = bool(
            in_configured_release_subtree and rel.endswith(".md")
        )
        if in_configured_release_subtree and not rel.endswith(".md"):
            errors.append(
                f"downstream_adaptations[{index}] release record must be a Markdown .md file"
            )
        if not in_configured_memory and not in_configured_release_records and not any(
            _matches(rel, pattern)
            for pattern in _CONSUMER_OWNED_ADAPTATION_PATTERNS
        ):
            errors.append(
                f"downstream_adaptations[{index}] is not a declared consumer-owned path"
            )
        if _portable_path_has_sensitive_name(rel):
            errors.append(
                f"downstream_adaptations[{index}] contains a sensitive path"
            )
        if rel in forbidden_refs:
            errors.append(
                f"downstream_adaptations[{index}] cannot contain migration evidence"
            )
        if any(_matches(rel, pattern) for pattern in _FORBIDDEN_ADAPTATION_PATTERNS):
            errors.append(
                f"downstream_adaptations[{index}] contains forbidden runtime or raw evidence"
            )

    omitted = _require_list(
        evidence.get("omitted_boundaries"), "omitted_boundaries", errors
    )
    omitted_by_boundary: dict[str, dict[str, Any]] = {}
    for index, value in enumerate(omitted):
        item = _require_mapping(value, f"omitted_boundaries[{index}]", errors)
        boundary = str(item.get("boundary") or "")
        reason = str(item.get("reason") or "").strip()
        if boundary not in {"artifact_commit_sha", "adaptation_commit_sha"}:
            errors.append(f"omitted_boundaries[{index}].boundary is invalid")
            continue
        if boundary in omitted_by_boundary:
            errors.append(f"omitted_boundaries contains duplicate boundary: {boundary}")
        omitted_by_boundary[boundary] = item
        if not reason:
            errors.append(f"omitted_boundaries[{index}].reason is required")
    for field in ("artifact_commit_sha", "adaptation_commit_sha"):
        is_omitted = after.get(field) in (None, "")
        if field in declared_boundary_fields and field in omitted_by_boundary:
            errors.append(
                f"omitted_boundaries cannot omit package-declared {field}"
            )
        if is_omitted and field not in omitted_by_boundary:
            errors.append(f"omitted_boundaries must explain null {field}")
        if not is_omitted and field in omitted_by_boundary:
            errors.append(f"omitted_boundaries cannot list non-null {field}")

    commit_boundaries = [
        ("consumer_before.head_sha", str(before.get("head_sha") or "")),
        (
            "consumer_after.import_commit_sha",
            str(after.get("import_commit_sha") or ""),
        ),
        *[
            (f"consumer_after.{field}", str(after.get(field) or ""))
            for field in declared_boundary_fields[1:]
        ],
    ]
    valid_boundary_shas = [sha for _label, sha in commit_boundaries if _valid_sha(sha)]
    if len(valid_boundary_shas) != len(set(valid_boundary_shas)):
        errors.append("migration commit boundaries must be distinct")
    if require_git_commits and consumer_root is None:
        errors.append("consumer Git verification root is required for a checked report")
    if require_git_commits and kit_root is None:
        errors.append("public kit Git verification root is required for a checked report")
    if consumer_root is not None:
        root = consumer_root.resolve()
        if not _git(root, "rev-parse", "--is-inside-work-tree"):
            errors.append("consumer Git verification root is not a repository")
        else:
            if evidence_context.get("captured_consumer_head") != _git(
                root, "rev-parse", "HEAD"
            ):
                errors.append(
                    "evidence_context.captured_consumer_head does not match consumer HEAD"
                )
            if require_git_commits:
                if after.get("branch") != git_state(root)["branch"]:
                    errors.append(
                        "consumer_after.branch does not match the checked consumer branch"
                    )
                try:
                    # Import through the core-owned receipt facade.  The
                    # standard-library helper intentionally lives under
                    # scripts for the Node-only release path, but upgrade
                    # validation must not create a second wiki_core -> scripts
                    # architecture exception.
                    from .release_receipt import (
                        ReleaseReceiptError,
                        collect_git_subject as collect_exact_git_subject,
                    )

                    exact_subject = collect_exact_git_subject(root)
                except (OSError, ReleaseReceiptError):
                    exact_subject = None
                    errors.append(
                        "checked migration could not bind an exact Git subject"
                    )
                if exact_subject is not None and exact_subject.get("dirty"):
                    errors.append(
                        "checked migration requires a clean consumer index and worktree"
                    )
                configured_memory_root = str(
                    configured_layout(root).get("memory_root") or ""
                ).rstrip("/")
                if normalized_memory_root != configured_memory_root:
                    errors.append(
                        "consumer_before.memory_root does not match the configured consumer layout"
                    )
                configured_references_root = str(
                    configured_layout(root).get("references_root") or ""
                ).rstrip("/")
                if normalized_references_root != configured_references_root:
                    errors.append(
                        "consumer_before.references_root does not match the configured consumer layout"
                    )
                if kit_root is not None:
                    resolved_kit_root = kit_root.resolve()
                    if not _git(resolved_kit_root, "rev-parse", "--is-inside-work-tree"):
                        errors.append("public kit Git verification root is not a repository")
                        bound_preflight = None
                    else:
                        bound_preflight = _validate_preflight_report_binding(
                            kit_root=resolved_kit_root,
                            consumer_root=root,
                            before=before,
                            package=package,
                            errors=errors,
                        )
                else:
                    resolved_kit_root = None
                    bound_preflight = None
            for label, sha in commit_boundaries:
                if _valid_sha(sha) and not _git_commit_available(root, sha):
                    errors.append(f"{label} is not available in the consumer repository")
            for (left_label, left), (right_label, right) in zip(
                commit_boundaries,
                commit_boundaries[1:],
                strict=False,
            ):
                if not (_valid_sha(left) and _valid_sha(right)):
                    continue
                ancestry = subprocess.run(
                    ["git", "merge-base", "--is-ancestor", left, right],
                    cwd=root,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                if ancestry.returncode != 0:
                    errors.append(
                        f"migration commit order is invalid: {left_label} must precede {right_label}"
                    )

            if require_git_commits and all(
                _valid_sha(sha) and _git_commit_available(root, sha)
                for _label, sha in commit_boundaries
            ):
                for (left_label, left), (right_label, right) in zip(
                    commit_boundaries,
                    commit_boundaries[1:],
                    strict=False,
                ):
                    parents = _git_commit_parents(root, right)
                    if parents != [left]:
                        errors.append(
                            "migration boundary must be a direct single-parent commit: "
                            f"{right_label} must have only {left_label} as parent"
                        )

                declared_path_sets: list[tuple[str, list[str]]] = [
                    ("files_imported", [str(value) for value in imported])
                ]
                for field, values in (
                    ("artifact_commit_sha", generated),
                    ("adaptation_commit_sha", adaptations),
                ):
                    if field in declared_boundary_fields:
                        declared_path_sets.append(
                            (
                                "generated_artifacts"
                                if field == "artifact_commit_sha"
                                else "downstream_adaptations",
                                [str(value) for value in values],
                            )
                        )
                for index, ((_, left), (_, right)) in enumerate(
                    zip(commit_boundaries, commit_boundaries[1:], strict=False)
                ):
                    field_name, declared_paths = declared_path_sets[index]
                    actual_paths = _git_diff_paths(root, left, right)
                    if actual_paths != declared_paths:
                        errors.append(
                            f"{field_name} does not exactly match its migration commit diff"
                        )

                if isinstance(bound_preflight, dict):
                    partition = bound_preflight.get("migration_partition")
                    partition = partition if isinstance(partition, dict) else {}
                    imported_partition = partition.get("faithful_public_import")
                    imported_partition = (
                        imported_partition
                        if isinstance(imported_partition, dict)
                        else {}
                    )
                    generated_partition = partition.get("regenerated_artifacts")
                    generated_partition = (
                        generated_partition
                        if isinstance(generated_partition, dict)
                        else {}
                    )
                    if imported_partition.get("paths") != [
                        str(value) for value in imported
                    ]:
                        errors.append(
                            "files_imported does not match the authoritative preflight partition"
                        )
                    if generated_partition.get("paths") != [
                        str(value) for value in generated
                    ]:
                        errors.append(
                            "generated_artifacts does not match the authoritative preflight partition"
                        )

                if resolved_kit_root is not None:
                    source_sha = str(
                        (package.get("release") or {}).get("source_sha") or ""
                    )
                    import_sha = str(after.get("import_commit_sha") or "")
                    artifact_sha = str(after.get("artifact_commit_sha") or "")
                    try:
                        if not _tree_paths_match_source_bytes(
                            kit_root=resolved_kit_root,
                            source_sha=source_sha,
                            consumer_root=root,
                            consumer_sha=import_sha,
                            paths=[str(value) for value in imported],
                        ):
                            errors.append(
                                "faithful public import postimages do not match the pinned source tree bytes"
                            )
                        if generated and not _tree_paths_match_source_bytes(
                            kit_root=resolved_kit_root,
                            source_sha=source_sha,
                            consumer_root=root,
                            consumer_sha=artifact_sha,
                            paths=[str(value) for value in generated],
                        ):
                            errors.append(
                                "regenerated artifact postimages do not match the pinned source tree bytes"
                            )
                        final_drift = _portable_git_tree_comparison(
                            resolved_kit_root,
                            source_sha,
                            root,
                            final_migration_sha,
                            package,
                        )
                        if final_drift.get("drift_total") != 0:
                            errors.append(
                                "final migration tree retains portable toolkit drift"
                            )
                        if adaptations and not _tree_paths_are_secret_safe(
                            root=root,
                            sha=final_migration_sha,
                            paths=[str(value) for value in adaptations],
                        ):
                            errors.append(
                                "downstream adaptation postimages contain secret-shaped or unsupported binary content"
                            )
                        if adaptations and not _tree_release_records_are_non_executable_markdown(
                            root=root,
                            sha=final_migration_sha,
                            paths=[str(value) for value in adaptations],
                            references_root=normalized_references_root or "",
                        ):
                            errors.append(
                                "downstream release record postimages must be non-executable Markdown files"
                            )
                    except ValueError:
                        errors.append(
                            "pinned source tree bytes could not be verified for migration boundaries"
                        )

    _require_list(evidence.get("local_overrides_kept"), "local_overrides_kept", errors)
    warnings = _require_list(evidence.get("warnings"), "warnings", errors)
    for index, value in enumerate(warnings):
        warning = _require_mapping(value, f"warnings[{index}]", errors)
        for field in ("code", "message", "owner", "removal_window"):
            if not str(warning.get(field) or "").strip():
                errors.append(f"warnings[{index}].{field} is required")
    _require_list(evidence.get("fixtures_added"), "fixtures_added", errors)

    gates = _require_list(evidence.get("gates"), "gates", errors)
    evidence_gate_commands = {
        str(key): str(value)
        for key, value in (
            (package.get("migration") or {}).get("gate_commands") or {}
        ).items()
    }
    by_gate: dict[str, dict[str, Any]] = {}
    for index, value in enumerate(gates):
        gate = _require_mapping(value, f"gates[{index}]", errors)
        gate_id = str(gate.get("id") or "")
        if gate_id:
            if gate_id in by_gate:
                errors.append(f"gates contains duplicate id: {gate_id}")
            by_gate[gate_id] = gate
        command = str(gate.get("command") or "")
        if _migration_command_is_placeholder(command):
            errors.append(f"gates[{index}].command must be exact, not a placeholder")
        if evidence_gate_commands and gate_id:
            registered_command = evidence_gate_commands.get(gate_id)
            if registered_command is None:
                errors.append(
                    f"gates[{index}].id is not in the package gate command registry"
                )
            elif command != registered_command:
                errors.append(
                    f"gates[{index}].command does not match the package gate "
                    "command registry"
                )
        exit_code = gate.get("exit_code")
        if isinstance(exit_code, bool) or exit_code != 0:
            errors.append(f"gates[{index}].exit_code must be 0")
        if gate.get("captured_consumer_head") != final_migration_sha:
            errors.append(
                f"gates[{index}].captured_consumer_head must match the final migration boundary"
            )
    required_gates = [
        str(value)
        for value in (package.get("migration") or {}).get("required_gates") or []
    ]
    for gate_id in required_gates:
        gate = by_gate.get(gate_id)
        if gate is None:
            errors.append(f"missing migration gate: {gate_id}")
        elif gate.get("status") != "pass":
            errors.append(f"migration gate did not pass: {gate_id}")
        elif _migration_command_is_placeholder(gate.get("command")):
            errors.append(f"migration gate has no exact command: {gate_id}")
    if require_git_commits:
        # Checked reports never complete on self-declared gate claims: each
        # required gate must be backed by an executed-run receipt in an
        # ignored untracked sidecar, bound to the final migration boundary.
        _validate_gate_receipts_binding(
            evidence=evidence,
            required_gates=required_gates,
            gate_commands=evidence_gate_commands,
            consumer_root=consumer_root,
            final_migration_sha=final_migration_sha,
            errors=errors,
        )

    visual = _require_list(
        evidence.get("visual_qa_evidence"), "visual_qa_evidence", errors
    )
    profile_values = [
        str(item.get("profile")) for item in visual if isinstance(item, dict)
    ]
    profiles = set(profile_values)
    if len(profile_values) != len(profiles):
        errors.append("visual_qa_evidence profiles must be unique")
    screenshot_refs = [
        str(item.get("screenshot_ref") or "")
        for item in visual
        if isinstance(item, dict)
    ]
    if len(screenshot_refs) != len(set(screenshot_refs)):
        errors.append("visual_qa_evidence screenshot refs must be unique")
    screenshot_hashes = [
        str(item.get("screenshot_sha256") or "")
        for item in visual
        if isinstance(item, dict)
    ]
    if len(screenshot_hashes) != len(set(screenshot_hashes)):
        errors.append("visual_qa_evidence screenshot hashes must be unique")
    required_profiles = _migration_visual_profiles(package)
    for required_profile in required_profiles:
        if required_profile not in profiles:
            errors.append(f"visual_qa_evidence missing profile: {required_profile}")
    for index, value in enumerate(visual):
        item = _require_mapping(value, f"visual_qa_evidence[{index}]", errors)
        for field in (
            "route_ref",
            "center_ref",
            "viewport",
            "browser",
            "screenshot_ref",
        ):
            if not str(item.get(field) or "").strip():
                errors.append(f"visual_qa_evidence[{index}].{field} is required")
        if item.get("profile") not in set(required_profiles):
            errors.append(f"visual_qa_evidence[{index}].profile is invalid")
        if item.get("browser") not in {"chromium", "firefox", "webkit"}:
            errors.append(f"visual_qa_evidence[{index}].browser is invalid")
        if not re.fullmatch(r"[1-9][0-9]{2,4}x[1-9][0-9]{2,4}", str(item.get("viewport") or "")):
            errors.append(f"visual_qa_evidence[{index}].viewport is invalid")
        screenshot_ref = str(item.get("screenshot_ref") or "")
        canonical_screenshot, _reason = _canonical_portable_path(screenshot_ref)
        if (
            canonical_screenshot != screenshot_ref
            or Path(screenshot_ref).suffix.lower() != ".png"
            or _portable_path_has_sensitive_name(screenshot_ref)
        ):
            errors.append(
                f"visual_qa_evidence[{index}].screenshot_ref must be a safe repo-relative PNG"
            )
        if not _valid_sha256(item.get("screenshot_sha256")):
            errors.append(
                f"visual_qa_evidence[{index}].screenshot_sha256 must be an exact SHA-256"
            )
        if (
            not _positive_int(item.get("screenshot_bytes"))
            or int(item.get("screenshot_bytes") or 0) > 64 * 1024 * 1024
        ):
            errors.append(
                f"visual_qa_evidence[{index}].screenshot_bytes must be a positive integer"
            )
        dimensions = _require_mapping(
            item.get("screenshot_dimensions"),
            f"visual_qa_evidence[{index}].screenshot_dimensions",
            errors,
        )
        if set(dimensions) != {"width", "height"} or any(
            not _positive_int(dimensions.get(axis))
            or int(dimensions.get(axis) or 0) > 16_384
            for axis in ("width", "height")
        ):
            errors.append(
                f"visual_qa_evidence[{index}].screenshot_dimensions is invalid"
            )
        viewport_match = re.fullmatch(
            r"([1-9][0-9]{2,4})x([1-9][0-9]{2,4})",
            str(item.get("viewport") or ""),
        )
        if viewport_match and dimensions != {
            "width": int(viewport_match.group(1)),
            "height": int(viewport_match.group(2)),
        }:
            errors.append(
                f"visual_qa_evidence[{index}].screenshot_dimensions must equal its viewport"
            )
        if item.get("captured_consumer_head") != final_migration_sha:
            errors.append(
                f"visual_qa_evidence[{index}].captured_consumer_head must match the final migration boundary"
            )
        if item.get("sample_fallback") is not False:
            errors.append(f"visual_qa_evidence[{index}].sample_fallback must be false")
        if item.get("console_status") != "clean":
            errors.append(f"visual_qa_evidence[{index}].console_status must be clean")
        if item.get("network_status") != "clean":
            errors.append(f"visual_qa_evidence[{index}].network_status must be clean")
        if consumer_root is not None and require_git_commits:
            if not _git_path_is_ignored_and_untracked(
                consumer_root.resolve(), screenshot_ref
            ):
                errors.append(
                    f"visual_qa_evidence[{index}].screenshot_ref must be ignored and untracked"
                )
            _validate_visual_file_binding(
                consumer_root=consumer_root.resolve(),
                item=item,
                index=index,
                errors=errors,
            )

    rollback = _require_mapping(evidence.get("rollback"), "rollback", errors)
    if not _valid_sha(rollback.get("previous_sha")):
        errors.append("rollback.previous_sha must be an exact Git SHA")
    if not _valid_sha(rollback.get("import_commit_sha")):
        errors.append("rollback.import_commit_sha must be an exact Git SHA")
    if rollback.get("previous_sha") != before.get("head_sha"):
        errors.append("rollback.previous_sha must match consumer_before.head_sha")
    if rollback.get("import_commit_sha") != after.get("import_commit_sha"):
        errors.append(
            "rollback.import_commit_sha must match consumer_after.import_commit_sha"
        )
    command = str(rollback.get("command") or "")
    rollback_targets = [
        str(after.get(field) or "")
        for field in (
            "adaptation_commit_sha",
            "artifact_commit_sha",
            "import_commit_sha",
        )
        if after.get(field) not in (None, "")
    ]
    expected_command = "git revert --no-commit " + " ".join(rollback_targets)
    if command != expected_command:
        errors.append(
            "rollback.command must exactly revert every non-null migration "
            "commit SHA in reverse boundary order with --no-commit"
        )
    preserved = _require_list(
        rollback.get("preserves_local_paths"), "rollback.preserves_local_paths", errors
    )
    if not preserved:
        errors.append("rollback.preserves_local_paths cannot be empty")
    preserved_roots = {str(value).rstrip("/") for value in preserved}
    if normalized_memory_root and normalized_memory_root not in preserved_roots:
        errors.append(
            "rollback.preserves_local_paths must contain consumer_before.memory_root"
        )

    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    findings = scan_text(serialized)
    for finding in findings:
        if finding.category == "secret":
            errors.append(
                f"migration evidence contains access-secret pattern: {finding.kind}"
            )
        if public_export and finding.category in {"pii", "entity"}:
            errors.append(
                f"public migration evidence contains personal-data pattern: {finding.kind}"
            )
    if public_export:
        if _PUBLIC_LOCAL_PATH_RE.search(serialized):
            errors.append("public migration evidence contains an absolute local path")
        if _PUBLIC_PARENT_TRAVERSAL_RE.search(serialized):
            errors.append("public migration evidence contains parent-path traversal")
        if _PUBLIC_URL_QUERY_RE.search(serialized):
            errors.append(
                "public migration evidence contains a URL with query parameters"
            )
        for index, value in enumerate(visual):
            if not isinstance(value, dict):
                continue
            route = str(value.get("route_ref") or "")
            center = str(value.get("center_ref") or "")
            if not _public_route_ref_is_safe(route):
                errors.append(
                    f"visual_qa_evidence[{index}].route_ref is not public-safe"
                )
            if not _public_center_ref_is_safe(center):
                errors.append(
                    f"visual_qa_evidence[{index}].center_ref is not public-safe"
                )
    return sorted(set(errors))


def verify_migration_rollback(
    evidence: dict[str, Any], consumer_root: Path
) -> dict[str, Any]:
    """Execute the declared rollback in a disposable clone and bind the tree.

    The command is reconstructed from validated commit fields and passed as an
    argv list; evidence text is never executed by a shell.  Success means the
    resulting index tree equals ``consumer_before.head_sha^{tree}`` byte for
    byte and the disposable worktree contains no unstaged divergence.
    """

    before = evidence.get("consumer_before")
    after = evidence.get("consumer_after")
    rollback = evidence.get("rollback")
    before = before if isinstance(before, dict) else {}
    after = after if isinstance(after, dict) else {}
    rollback = rollback if isinstance(rollback, dict) else {}
    previous_sha = str(before.get("head_sha") or "")
    final_sha = _final_migration_sha(after)
    targets = [
        str(after.get(field) or "")
        for field in (
            "adaptation_commit_sha",
            "artifact_commit_sha",
            "import_commit_sha",
        )
        if after.get(field) not in (None, "")
    ]
    canonical_command = "git revert --no-commit " + " ".join(targets)
    receipt: dict[str, Any] = {
        "schema_version": ROLLBACK_VERIFICATION_SCHEMA_VERSION,
        "status": "failed",
        "failure_code": "precondition_failed",
        "previous_sha": previous_sha,
        "checked_consumer_head": _git(consumer_root.resolve(), "rev-parse", "HEAD"),
        "final_migration_sha": final_sha,
        "command_sha256": hashlib.sha256(
            canonical_command.encode("utf-8")
        ).hexdigest(),
        "previous_tree_sha": "",
        "rollback_tree_sha": "",
        "tree_matches_before": False,
        "worktree_matches_index": False,
        "preserved_path_count": len(rollback.get("preserves_local_paths") or []),
    }
    if (
        not _valid_sha(previous_sha)
        or not _valid_sha(final_sha)
        or not targets
        or rollback.get("command") != canonical_command
    ):
        return receipt

    root = consumer_root.resolve()
    try:
        with tempfile.TemporaryDirectory(prefix="wiki-viva-rollback-") as temporary:
            clone = Path(temporary) / "consumer"
            cloned = subprocess.run(
                [
                    "git",
                    "clone",
                    "--quiet",
                    "--no-local",
                    "--no-hardlinks",
                    str(root),
                    str(clone),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            if cloned.returncode != 0:
                receipt["failure_code"] = "clone_failed"
                return receipt
            checked_out = subprocess.run(
                ["git", "checkout", "--quiet", "--detach", final_sha],
                cwd=clone,
                text=True,
                capture_output=True,
                check=False,
            )
            if checked_out.returncode != 0:
                receipt["failure_code"] = "checkout_failed"
                return receipt
            reverted = subprocess.run(
                ["git", "revert", "--no-commit", *targets],
                cwd=clone,
                text=True,
                capture_output=True,
                check=False,
            )
            if reverted.returncode != 0:
                receipt["failure_code"] = "revert_failed"
                return receipt
            previous_tree = _git(clone, "rev-parse", f"{previous_sha}^{{tree}}")
            rollback_tree = _git(clone, "write-tree")
            worktree_matches_index = (
                subprocess.run(
                    ["git", "diff", "--quiet", "--", "."],
                    cwd=clone,
                    check=False,
                ).returncode
                == 0
            )
            receipt.update(
                {
                    "previous_tree_sha": previous_tree,
                    "rollback_tree_sha": rollback_tree,
                    "tree_matches_before": bool(
                        previous_tree and previous_tree == rollback_tree
                    ),
                    "worktree_matches_index": worktree_matches_index,
                }
            )
            if receipt["tree_matches_before"] and worktree_matches_index:
                receipt["status"] = "pass"
                receipt["failure_code"] = ""
            else:
                receipt["failure_code"] = "tree_mismatch"
    except OSError:
        receipt["failure_code"] = "git_unavailable"
    return receipt


def _public_value_is_safe(value: str) -> bool:
    """Return whether one scalar may cross the public report boundary.

    This intentionally treats informational entities such as email addresses
    as personal data at the export boundary. Relative repository paths remain
    allowed; absolute/home/traversal paths and URLs carrying query parameters
    do not.
    """

    if any(
        finding.category in {"secret", "pii", "entity"}
        for finding in scan_text(value)
    ):
        return False
    return not (
        _PUBLIC_LOCAL_PATH_RE.search(value)
        or _PUBLIC_PARENT_TRAVERSAL_RE.search(value)
        or _PUBLIC_URL_QUERY_RE.search(value)
        or _PUBLIC_CREDENTIAL_ASSIGNMENT_RE.search(value)
    )


def _public_text(value: Any) -> str:
    text = str(value or "")
    return text if _public_value_is_safe(text) else _PUBLIC_REDACTED_VALUE


def _public_commit_id(kind: str, value: Any) -> str | None:
    """Project a private commit identity without hashing arbitrary secrets."""

    if value in (None, ""):
        return None
    text = str(value)
    if not _valid_sha(text):
        return _PUBLIC_REDACTED_VALUE
    return _redacted_identifier(kind, text)


def _public_route_ref_is_safe(value: str) -> bool:
    return value in _PUBLIC_FIXTURE_REFS or bool(_PUBLIC_ROUTE_HASH_RE.fullmatch(value))


def _public_center_ref_is_safe(value: str) -> bool:
    return value in _PUBLIC_FIXTURE_REFS or bool(_PUBLIC_CENTER_HASH_RE.fullmatch(value))


def _public_string_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return sorted(set(_public_text(value) for value in values))


def _public_portable_files(values: Any, package: dict[str, Any]) -> list[str]:
    if not isinstance(values, list):
        return []
    projected: set[str] = set()
    for value in values:
        text = str(value)
        allowed, _reason = portable_path_status(text, package)
        if allowed and not text.endswith("/") and _public_value_is_safe(text):
            projected.add(text)
        else:
            projected.add(_PUBLIC_REDACTED_VALUE)
    return sorted(projected)


def _migration_path_summary(
    evidence: dict[str, Any],
    package: dict[str, Any],
    *,
    kit_root: Path | None,
    errors: Sequence[str],
    verified: bool,
) -> dict[str, Any]:
    imported = sorted(set(str(value) for value in evidence.get("files_imported") or []))
    generated = sorted(
        set(str(value) for value in evidence.get("generated_artifacts") or [])
    )
    adaptations = sorted(
        set(str(value) for value in evidence.get("downstream_adaptations") or [])
    )
    source_sha = str((package.get("release") or {}).get("source_sha") or "")

    def source_digest(paths: list[str]) -> str | None:
        if kit_root is None or not _valid_sha(source_sha):
            return None
        try:
            return _source_projection_digest(kit_root.resolve(), source_sha, paths)
        except ValueError:
            return None

    blocked = bool(errors)
    validated_count = len(adaptations) if verified and not blocked else 0
    blocked_count = len(adaptations) if blocked else 0
    unverified_count = (
        len(adaptations) if not blocked and not verified else 0
    )
    return {
        "faithful_public_import": {
            "path_count": len(imported),
            "paths_sha256": _path_digest(imported),
            "source_projection_sha256": source_digest(imported),
        },
        "regenerated_artifacts": {
            "path_count": len(generated),
            "paths_sha256": _path_digest(generated),
            "source_projection_sha256": source_digest(generated),
        },
        "downstream_adaptations": {
            "path_count": len(adaptations),
            "validated_count": validated_count,
            "blocked_count": blocked_count,
            "unverified_count": unverified_count,
        },
    }


def _public_migration_projection(
    evidence: dict[str, Any],
    package: dict[str, Any],
    errors: list[str],
    rollback_verification: dict[str, Any],
    migration_summary: dict[str, Any],
) -> dict[str, Any]:
    """Build the only migration-report shape allowed to cross publicly.

    The projection is schema-aware and never copies arbitrary mappings from
    evidence. Every scalar is checked before inclusion; rejected portable paths
    are represented by a constant marker rather than echoed. A final whole-
    payload scan below provides a fail-closed backstop for cross-field detector
    shapes.
    """

    evidence_context = (
        evidence.get("evidence_context")
        if isinstance(evidence.get("evidence_context"), dict)
        else {}
    )
    before = (
        evidence.get("consumer_before")
        if isinstance(evidence.get("consumer_before"), dict)
        else {}
    )
    after = (
        evidence.get("consumer_after")
        if isinstance(evidence.get("consumer_after"), dict)
        else {}
    )
    rollback = evidence.get("rollback") if isinstance(evidence.get("rollback"), dict) else {}

    before_sha = str(before.get("head_sha") or "")
    projected_before_sha = _public_commit_id("consumer-head", before_sha)
    projected_after_shas: dict[str, str | None] = {}
    replacements: dict[str, str] = {}
    if before_sha and projected_before_sha:
        replacements[before_sha] = projected_before_sha
    for field in ("import_commit_sha", "artifact_commit_sha", "adaptation_commit_sha"):
        raw = str(after.get(field) or "")
        projected = _public_commit_id(
            f"consumer-{field.removesuffix('_sha')}", raw
        )
        projected_after_shas[field] = projected
        if raw and projected:
            replacements[raw] = projected

    projected_omitted: list[dict[str, str]] = []
    for value in evidence.get("omitted_boundaries") or []:
        if not isinstance(value, dict):
            continue
        projected_omitted.append(
            {
                "boundary": (
                    str(value.get("boundary"))
                    if value.get("boundary")
                    in {"artifact_commit_sha", "adaptation_commit_sha"}
                    else _PUBLIC_REDACTED_VALUE
                ),
                "reason": _PUBLIC_REDACTED_VALUE,
            }
        )

    # Warning prose/owners and consumer-local filenames stay private even when
    # they do not trigger generic PII detectors.
    projected_warnings: list[dict[str, str]] = []

    projected_gates: list[dict[str, Any]] = []
    public_gate_ids = {
        str(value)
        for value in (package.get("migration") or {}).get("required_gates") or []
    }
    for value in evidence.get("gates") or []:
        if not isinstance(value, dict):
            continue
        gate_id = str(value.get("id") or "")
        if gate_id not in public_gate_ids:
            continue
        projected_gates.append(
            {
                "id": gate_id,
                "command": _PUBLIC_REDACTED_VALUE,
                "status": (
                    "pass"
                    if value.get("status") == "pass"
                    else _PUBLIC_REDACTED_VALUE
                ),
                "exit_code": (
                    value.get("exit_code")
                    if isinstance(value.get("exit_code"), int)
                    and not isinstance(value.get("exit_code"), bool)
                    else None
                ),
                "captured_consumer_head": replacements.get(
                    str(value.get("captured_consumer_head") or "")
                )
                or _public_commit_id(
                    "gate-consumer-head", value.get("captured_consumer_head")
                ),
            }
        )

    projected_visual: list[dict[str, Any]] = []
    allowed_profiles = set(_migration_visual_profiles(package))
    for value in evidence.get("visual_qa_evidence") or []:
        if not isinstance(value, dict):
            continue
        route = str(value.get("route_ref") or "")
        center = str(value.get("center_ref") or "")
        viewport = str(value.get("viewport") or "")
        browser = str(value.get("browser") or "")
        dimensions = value.get("screenshot_dimensions")
        dimensions = dimensions if isinstance(dimensions, dict) else {}
        valid_dimensions = all(
            _positive_int(dimensions.get(axis))
            and int(dimensions.get(axis) or 0) <= 16_384
            for axis in ("width", "height")
        )
        projected_visual.append(
            {
                "profile": (
                    str(value.get("profile"))
                    if value.get("profile") in allowed_profiles
                    else _PUBLIC_REDACTED_VALUE
                ),
                "route_ref": (
                    _public_text(route)
                    if _public_route_ref_is_safe(route)
                    else _PUBLIC_REDACTED_VALUE
                ),
                "center_ref": (
                    _public_text(center)
                    if _public_center_ref_is_safe(center)
                    else _PUBLIC_REDACTED_VALUE
                ),
                "viewport": (
                    viewport
                    if re.fullmatch(r"[1-9][0-9]{2,4}x[1-9][0-9]{2,4}", viewport)
                    else _PUBLIC_REDACTED_VALUE
                ),
                "browser": (
                    browser
                    if browser in {"chromium", "firefox", "webkit"}
                    else _PUBLIC_REDACTED_VALUE
                ),
                "screenshot_ref": "qa/redacted.png",
                "screenshot_sha256": (
                    str(value.get("screenshot_sha256"))
                    if _valid_sha256(value.get("screenshot_sha256"))
                    else _PUBLIC_REDACTED_VALUE
                ),
                "screenshot_bytes": (
                    value.get("screenshot_bytes")
                    if _positive_int(value.get("screenshot_bytes"))
                    else None
                ),
                "screenshot_dimensions": {
                    "width": (
                        dimensions.get("width") if valid_dimensions else None
                    ),
                    "height": (
                        dimensions.get("height") if valid_dimensions else None
                    ),
                },
                "captured_consumer_head": replacements.get(
                    str(value.get("captured_consumer_head") or "")
                )
                or _public_commit_id(
                    "visual-consumer-head", value.get("captured_consumer_head")
                ),
                "console_status": (
                    "clean"
                    if value.get("console_status") == "clean"
                    else _PUBLIC_REDACTED_VALUE
                ),
                "network_status": (
                    "clean"
                    if value.get("network_status") == "clean"
                    else _PUBLIC_REDACTED_VALUE
                ),
                "sample_fallback": (
                    value.get("sample_fallback")
                    if isinstance(value.get("sample_fallback"), bool)
                    else None
                ),
            }
        )

    rollback_previous = str(rollback.get("previous_sha") or "")
    rollback_import = str(rollback.get("import_commit_sha") or "")
    projected_previous = replacements.get(rollback_previous) or _public_commit_id(
        "rollback-previous", rollback_previous
    )
    projected_import = replacements.get(rollback_import) or _public_commit_id(
        "rollback-import-commit", rollback_import
    )
    def projected_verification_sha(kind: str, field: str) -> str | None:
        raw = rollback_verification.get(field)
        return _public_commit_id(kind, raw) if raw else None

    projected_verification = {
        "schema_version": _public_text(
            rollback_verification.get("schema_version")
        ),
        "status": _public_text(rollback_verification.get("status")),
        "failure_code": _public_text(
            rollback_verification.get("failure_code")
        ),
        "previous_sha": replacements.get(
            str(rollback_verification.get("previous_sha") or "")
        )
        or projected_verification_sha("rollback-previous", "previous_sha"),
        "checked_consumer_head": replacements.get(
            str(rollback_verification.get("checked_consumer_head") or "")
        )
        or projected_verification_sha(
            "rollback-checked-head", "checked_consumer_head"
        ),
        "final_migration_sha": replacements.get(
            str(rollback_verification.get("final_migration_sha") or "")
        )
        or projected_verification_sha(
            "rollback-final-head", "final_migration_sha"
        ),
        "command_sha256": _public_text(
            rollback_verification.get("command_sha256")
        ),
        "previous_tree_sha": projected_verification_sha(
            "rollback-previous-tree", "previous_tree_sha"
        ),
        "rollback_tree_sha": projected_verification_sha(
            "rollback-result-tree", "rollback_tree_sha"
        ),
        "tree_matches_before": bool(
            rollback_verification.get("tree_matches_before")
        ),
        "worktree_matches_index": bool(
            rollback_verification.get("worktree_matches_index")
        ),
        "preserved_path_count": int(
            rollback_verification.get("preserved_path_count") or 0
        ),
    }

    package_release = package.get("release")
    package_release = package_release if isinstance(package_release, dict) else {}
    package_release_id = str(package_release.get("id") or "")
    package_source_sha = str(package_release.get("source_sha") or "")
    package_plan = str(package_release.get("plan") or "")
    canonical_plan, _plan_error = _canonical_portable_path(package_plan)
    public_release_id = (
        package_release_id
        if _PUBLIC_RELEASE_ID_RE.fullmatch(package_release_id)
        else _PUBLIC_REDACTED_VALUE
    )
    public_source_sha = (
        package_source_sha if _valid_sha(package_source_sha) else _PUBLIC_REDACTED_VALUE
    )
    public_plan = (
        package_plan
        if canonical_plan == package_plan
        and package_plan.startswith("docs/references/proposals/")
        else _PUBLIC_REDACTED_VALUE
    )

    projected_targets = [
        projected_after_shas[field]
        for field in (
            "adaptation_commit_sha",
            "artifact_commit_sha",
            "import_commit_sha",
        )
        if projected_after_shas.get(field)
    ]
    projected_rollback_command = (
        "git revert --no-commit " + " ".join(str(value) for value in projected_targets)
        if projected_targets
        else _PUBLIC_REDACTED_VALUE
    )

    payload: dict[str, Any] = {
        "schema_version": MIGRATION_REPORT_SCHEMA_VERSION,
        "status": "complete" if not errors else "blocked",
        "public_export": True,
        "evidence_context": {
            "package_sha256": upgrade_package_sha256(package),
            "validator_version": (
                MIGRATION_VALIDATOR_VERSION
                if evidence_context.get("validator_version")
                == MIGRATION_VALIDATOR_VERSION
                else _PUBLIC_REDACTED_VALUE
            ),
            "captured_consumer_head": replacements.get(
                str(evidence_context.get("captured_consumer_head") or "")
            )
            or _public_commit_id(
                "captured-consumer-head",
                evidence_context.get("captured_consumer_head"),
            ),
        },
        "source": {
            "release": public_release_id,
            "sha": public_source_sha,
            "plan": public_plan,
        },
        "consumer_before": {
            "repository": _PUBLIC_REDACTED_VALUE,
            "branch": _PUBLIC_REDACTED_VALUE,
            "head_sha": projected_before_sha,
            "kit_version": _PUBLIC_REDACTED_VALUE,
            "gate_status": (
                "pass"
                if before.get("gate_status") == "pass"
                else _PUBLIC_REDACTED_VALUE
            ),
            "memory_root": _PUBLIC_REDACTED_VALUE,
            "references_root": _PUBLIC_REDACTED_VALUE,
            "preflight": {
                "status": (
                    "ready"
                    if isinstance(before.get("preflight"), dict)
                    and (before.get("preflight") or {}).get("status") == "ready"
                    else _PUBLIC_REDACTED_VALUE
                ),
                "report_id": (
                    str((before.get("preflight") or {}).get("report_id"))
                    if isinstance(before.get("preflight"), dict)
                    and re.fullmatch(
                        r"preflight:[0-9a-f]{20}",
                        str((before.get("preflight") or {}).get("report_id") or ""),
                    )
                    else _PUBLIC_REDACTED_VALUE
                ),
                "report_sha256": (
                    str((before.get("preflight") or {}).get("report_sha256"))
                    if isinstance(before.get("preflight"), dict)
                    and _valid_sha256(
                        (before.get("preflight") or {}).get("report_sha256")
                    )
                    else _PUBLIC_REDACTED_VALUE
                ),
                "report_ref": _PUBLIC_REDACTED_VALUE,
                "package_sha256": upgrade_package_sha256(package),
                "consumer_head": projected_before_sha,
            },
        },
        "consumer_after": {
            "branch": _PUBLIC_REDACTED_VALUE,
            **projected_after_shas,
        },
        "omitted_boundaries": projected_omitted,
        # Public reports expose only aggregate, deterministic summaries. Exact
        # path arrays remain in the ignored private report/preflight.
        "files_imported": [],
        "generated_artifacts": [],
        "downstream_adaptations": [],
        "migration_summary": migration_summary,
        "local_overrides_kept": [],
        "warnings": projected_warnings,
        "fixtures_added": [],
        "gates": projected_gates,
        "visual_qa_evidence": projected_visual,
        "rollback": {
            "previous_sha": projected_previous,
            "import_commit_sha": projected_import,
            "command": projected_rollback_command,
            "preserves_local_paths": [],
        },
        "rollback_verification": projected_verification,
        "validation_errors": sorted(set(_public_text(error) for error in errors)),
    }

    serialized = canonical_json(payload)
    if not _public_value_is_safe(serialized):
        # A whole-object detector can see credential shapes that per-field
        # scans cannot. Return the required report schema with no evidence
        # values instead of risking a partially sanitized public artifact.
        payload = {
            "schema_version": MIGRATION_REPORT_SCHEMA_VERSION,
            "status": "blocked",
            "public_export": True,
            "evidence_context": {
                "package_sha256": None,
                "validator_version": None,
                "captured_consumer_head": None,
            },
            "source": {"release": None, "sha": None, "plan": None},
            "consumer_before": {
                "repository": None,
                "branch": None,
                "head_sha": None,
                "kit_version": None,
                "gate_status": None,
                "memory_root": None,
                "references_root": None,
                "preflight": {
                    "status": None,
                    "report_id": None,
                    "report_sha256": None,
                    "report_ref": None,
                    "package_sha256": None,
                    "consumer_head": None,
                },
            },
            "consumer_after": {
                "branch": None,
                "import_commit_sha": None,
                "artifact_commit_sha": None,
                "adaptation_commit_sha": None,
            },
            "omitted_boundaries": [],
            "files_imported": [],
            "generated_artifacts": [],
            "downstream_adaptations": [],
            "migration_summary": {
                "faithful_public_import": {
                    "path_count": 0,
                    "paths_sha256": None,
                    "source_projection_sha256": None,
                },
                "regenerated_artifacts": {
                    "path_count": 0,
                    "paths_sha256": None,
                    "source_projection_sha256": None,
                },
                "downstream_adaptations": {
                    "path_count": 0,
                    "validated_count": 0,
                    "blocked_count": 0,
                    "unverified_count": 0,
                },
            },
            "local_overrides_kept": [],
            "warnings": [],
            "fixtures_added": [],
            "gates": [],
            "visual_qa_evidence": [],
            "rollback": {
                "previous_sha": None,
                "import_commit_sha": None,
                "command": None,
                "preserves_local_paths": [],
            },
            "rollback_verification": {
                "schema_version": ROLLBACK_VERIFICATION_SCHEMA_VERSION,
                "status": "failed",
                "failure_code": "public_projection_unsafe",
                "previous_sha": None,
                "checked_consumer_head": None,
                "final_migration_sha": None,
                "command_sha256": None,
                "previous_tree_sha": None,
                "rollback_tree_sha": None,
                "tree_matches_before": False,
                "worktree_matches_index": False,
                "preserved_path_count": 0,
            },
            "validation_errors": [
                "public export projection remained unsafe after sanitization"
            ],
        }
    return payload


def _rollback_verification_not_run(
    evidence: dict[str, Any], *, failure_code: str = "not_requested"
) -> dict[str, Any]:
    before = evidence.get("consumer_before")
    after = evidence.get("consumer_after")
    rollback = evidence.get("rollback")
    before = before if isinstance(before, dict) else {}
    after = after if isinstance(after, dict) else {}
    rollback = rollback if isinstance(rollback, dict) else {}
    command = str(rollback.get("command") or "")
    return {
        "schema_version": ROLLBACK_VERIFICATION_SCHEMA_VERSION,
        "status": "not_run" if failure_code == "not_requested" else "failed",
        "failure_code": failure_code,
        "previous_sha": str(before.get("head_sha") or ""),
        "checked_consumer_head": "",
        "final_migration_sha": _final_migration_sha(after),
        "command_sha256": hashlib.sha256(command.encode("utf-8")).hexdigest(),
        "previous_tree_sha": "",
        "rollback_tree_sha": "",
        "tree_matches_before": False,
        "worktree_matches_index": False,
        "preserved_path_count": len(rollback.get("preserves_local_paths") or []),
    }


def compile_migration_report(
    evidence: dict[str, Any],
    package: dict[str, Any],
    *,
    public_export: bool = False,
    consumer_root: Path | None = None,
    kit_root: Path | None = None,
    require_git_commits: bool = False,
    verify_rollback_execution: bool = False,
) -> dict[str, Any]:
    evidence_is_json = _finite_json_value(evidence)
    package_is_json = _finite_json_value(package)
    errors = validate_migration_evidence(
        evidence,
        package,
        public_export=public_export,
        consumer_root=consumer_root,
        kit_root=kit_root,
        require_git_commits=require_git_commits,
    )
    report_evidence = evidence if evidence_is_json else {}
    report_package = package if package_is_json else {}
    rollback_verification = _rollback_verification_not_run(report_evidence)
    if require_git_commits and not verify_rollback_execution:
        errors.append("checked migration report requires disposable rollback verification")
    if verify_rollback_execution:
        if consumer_root is None:
            errors.append("rollback verification requires a consumer Git root")
            rollback_verification = _rollback_verification_not_run(
                report_evidence, failure_code="consumer_root_missing"
            )
        elif errors:
            rollback_verification = _rollback_verification_not_run(
                report_evidence, failure_code="validation_failed"
            )
        else:
            rollback_verification = verify_migration_rollback(
                report_evidence, consumer_root
            )
            if rollback_verification.get("status") != "pass":
                errors.append(
                    "disposable rollback verification did not restore the previous tree"
                )
    errors = sorted(set(errors))
    migration_summary = _migration_path_summary(
        report_evidence,
        report_package,
        kit_root=kit_root,
        errors=errors,
        verified=bool(
            require_git_commits
            and verify_rollback_execution
            and consumer_root is not None
            and kit_root is not None
            and not errors
        ),
    )
    if public_export:
        payload = _public_migration_projection(
            report_evidence,
            report_package,
            errors,
            rollback_verification,
            migration_summary,
        )
    else:
        payload = {
            "schema_version": MIGRATION_REPORT_SCHEMA_VERSION,
            "status": "complete" if not errors else "blocked",
            "public_export": False,
            "evidence_context": json.loads(
                json.dumps(report_evidence.get("evidence_context") or {})
            ),
            "source": report_evidence.get("source") or {},
            "consumer_before": json.loads(
                json.dumps(report_evidence.get("consumer_before") or {})
            ),
            "consumer_after": json.loads(
                json.dumps(report_evidence.get("consumer_after") or {})
            ),
            "omitted_boundaries": json.loads(
                json.dumps(report_evidence.get("omitted_boundaries") or [])
            ),
            "files_imported": sorted(
                set(
                    str(value)
                    for value in report_evidence.get("files_imported") or []
                )
            ),
            "generated_artifacts": sorted(
                set(
                    str(value)
                    for value in report_evidence.get("generated_artifacts") or []
                )
            ),
            "downstream_adaptations": sorted(
                set(
                    str(value)
                    for value in report_evidence.get("downstream_adaptations") or []
                )
            ),
            "migration_summary": migration_summary,
            "local_overrides_kept": sorted(
                set(
                    str(value)
                    for value in report_evidence.get("local_overrides_kept") or []
                )
            ),
            "warnings": report_evidence.get("warnings") or [],
            "fixtures_added": sorted(
                set(
                    str(value)
                    for value in report_evidence.get("fixtures_added") or []
                )
            ),
            "gates": report_evidence.get("gates") or [],
            "visual_qa_evidence": report_evidence.get("visual_qa_evidence") or [],
            "rollback": json.loads(
                json.dumps(report_evidence.get("rollback") or {})
            ),
            "rollback_verification": rollback_verification,
            "validation_errors": errors,
        }
    payload["report_id"] = deterministic_id("migration", payload)
    return payload


def _md(value: Any) -> str:
    text = str(value if value not in (None, "") else "—")
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("`", "&#96;")
        .replace("|", "\\|")
        .replace("\r", " ")
        .replace("\n", " ")
    )


def render_migration_report_markdown(report: dict[str, Any]) -> str:
    evidence_context = report.get("evidence_context") or {}
    source = report.get("source") or {}
    before = report.get("consumer_before") or {}
    after = report.get("consumer_after") or {}
    rollback = report.get("rollback") or {}
    rollback_verification = report.get("rollback_verification") or {}
    preflight = before.get("preflight") or {}
    migration_summary = report.get("migration_summary") or {}
    import_summary = migration_summary.get("faithful_public_import") or {}
    artifact_summary = migration_summary.get("regenerated_artifacts") or {}
    adaptation_summary = migration_summary.get("downstream_adaptations") or {}
    lines = [
        "# Wiki Viva v8 downstream migration report",
        "",
        f"- Report: `{_md(report.get('report_id'))}`",
        f"- Status: `{_md(report.get('status'))}`",
        f"- Source: `{_md(source.get('release'))}` at `{_md(source.get('sha'))}`",
        f"- Consumer: `{_md(before.get('repository'))}`",
        f"- Package digest: `{_md(evidence_context.get('package_sha256'))}`",
        f"- Validator: `{_md(evidence_context.get('validator_version'))}`",
        f"- Captured consumer HEAD: `{_md(evidence_context.get('captured_consumer_head'))}`",
        f"- Memory root: `{_md(before.get('memory_root'))}`",
        f"- References root: `{_md(before.get('references_root'))}`",
        f"- Preflight: `{_md(preflight.get('status'))}` · `{_md(preflight.get('report_id'))}`",
        f"- Preflight report digest: `sha256:{_md(preflight.get('report_sha256'))}`",
        f"- Preflight report ref: `{_md(preflight.get('report_ref'))}`",
        f"- Preflight package digest: `sha256:{_md(preflight.get('package_sha256'))}`",
        f"- Preflight consumer HEAD: `{_md(preflight.get('consumer_head'))}`",
        f"- Faithful import paths: `{_md(import_summary.get('path_count'))}` · digest `{_md(import_summary.get('paths_sha256'))}`",
        f"- Regenerated artifact paths: `{_md(artifact_summary.get('path_count'))}` · digest `{_md(artifact_summary.get('paths_sha256'))}`",
        f"- Downstream adaptation paths: `{_md(adaptation_summary.get('path_count'))}` · validated `{_md(adaptation_summary.get('validated_count'))}` · blocked `{_md(adaptation_summary.get('blocked_count'))}` · unverified `{_md(adaptation_summary.get('unverified_count'))}`",
        "",
        "```mermaid",
        "flowchart LR",
        '    Before["Consumer before"] --> Import["Faithful public import"]',
        '    Import --> Artifacts["Regenerated artifacts"]',
        '    Artifacts --> Adapt["Local adaptations"]',
        '    Adapt --> Gates["Gates and redacted QA"]',
        '    Gates --> Review["Human PR gate"]',
        "```",
        "",
        "## Commit boundary",
        "",
        "| Boundary | SHA / value |",
        "| --- | --- |",
        f"| Before HEAD | `{_md(before.get('head_sha'))}` |",
        f"| Import commit | `{_md(after.get('import_commit_sha'))}` |",
        f"| Artifact commit | `{_md(after.get('artifact_commit_sha'))}` |",
        f"| Adaptation commit | `{_md(after.get('adaptation_commit_sha'))}` |",
        "",
        "### Intentionally omitted boundaries",
        "",
        "| Boundary | Reason |",
        "| --- | --- |",
    ]
    omitted = report.get("omitted_boundaries") or []
    if omitted:
        for item in omitted:
            lines.append(
                f"| `{_md(item.get('boundary'))}` | {_md(item.get('reason'))} |"
            )
    else:
        lines.append("| `none` | Every optional boundary was materialized. |")
    lines.extend(
        [
        "",
        "## Imported portable files",
        "",
        ]
    )
    lines.extend(
        f"- `{_md(value)}`" for value in report.get("files_imported") or ["None"]
    )
    lines.extend(["", "## Local overrides kept", ""])
    lines.extend(
        f"- `{_md(value)}`" for value in report.get("local_overrides_kept") or ["None"]
    )
    lines.extend(["", "## Synthetic regression fixtures", ""])
    lines.extend(
        f"- `{_md(value)}`" for value in report.get("fixtures_added") or ["None"]
    )
    lines.extend(
        [
            "",
            "## Warnings",
            "",
            "| Code | Message | Owner | Removal window |",
            "| --- | --- | --- | --- |",
        ]
    )
    warnings = report.get("warnings") or []
    if warnings:
        for warning in warnings:
            lines.append(
                f"| `{_md(warning.get('code'))}` | {_md(warning.get('message'))} | "
                f"`{_md(warning.get('owner'))}` | `{_md(warning.get('removal_window'))}` |"
            )
    else:
        lines.append("| `none` | No migration warnings recorded. | `—` | `—` |")
    lines.extend(
        [
            "",
            "## Gates",
            "",
            "| Gate | Status / exit | Captured consumer HEAD | Command |",
            "| --- | --- | --- | --- |",
        ]
    )
    for gate in report.get("gates") or []:
        lines.append(
            f"| `{_md(gate.get('id'))}` | `{_md(gate.get('status'))}` / `{_md(gate.get('exit_code'))}` | "
            f"`{_md(gate.get('captured_consumer_head'))}` | `{_md(gate.get('command'))}` |"
        )
    lines.extend(
        [
            "",
            "## Visual QA evidence",
            "",
            "| Profile | Route / center | Viewport / capture | Browser | Screenshot | Console / network | Sample fallback |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for item in report.get("visual_qa_evidence") or []:
        dimensions = item.get("screenshot_dimensions") or {}
        lines.append(
            f"| `{_md(item.get('profile'))}` | `{_md(item.get('route_ref'))}` / `{_md(item.get('center_ref'))}` | "
            f"`{_md(item.get('viewport'))}` / `{_md(dimensions.get('width'))}x{_md(dimensions.get('height'))}` | "
            f"`{_md(item.get('browser'))}` | `{_md(item.get('screenshot_ref'))}` · "
            f"`sha256:{_md(item.get('screenshot_sha256'))}` · `{_md(item.get('screenshot_bytes'))} B` · "
            f"HEAD `{_md(item.get('captured_consumer_head'))}` | "
            f"`{_md(item.get('console_status'))}` / `{_md(item.get('network_status'))}` | "
            f"`{_md(item.get('sample_fallback'))}` |"
        )
    lines.extend(
        [
            "",
            "## Rollback",
            "",
            f"- Previous SHA: `{_md(rollback.get('previous_sha'))}`",
            f"- Import SHA: `{_md(rollback.get('import_commit_sha'))}`",
            f"- Command: `{_md(rollback.get('command'))}`",
            f"- Preserved local paths: {', '.join(f'`{_md(value)}`' for value in rollback.get('preserves_local_paths') or [])}",
            "",
            "### Disposable rollback verification",
            "",
            f"- Status: `{_md(rollback_verification.get('status'))}`",
            f"- Failure code: `{_md(rollback_verification.get('failure_code'))}`",
            f"- Checked consumer HEAD: `{_md(rollback_verification.get('checked_consumer_head'))}`",
            f"- Previous tree: `{_md(rollback_verification.get('previous_tree_sha'))}`",
            f"- Rollback tree: `{_md(rollback_verification.get('rollback_tree_sha'))}`",
            f"- Tree matches before: `{_md(rollback_verification.get('tree_matches_before'))}`",
            f"- Worktree matches index: `{_md(rollback_verification.get('worktree_matches_index'))}`",
            f"- Preserved-path declarations: `{_md(rollback_verification.get('preserved_path_count'))}`",
        ]
    )
    if report.get("validation_errors"):
        lines.extend(["", "## Blocking validation errors", ""])
        lines.extend(f"- {_md(value)}" for value in report["validation_errors"])
    return "\n".join(lines).rstrip() + "\n"
