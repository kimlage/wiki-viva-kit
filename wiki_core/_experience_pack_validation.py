"""Pack-source, manifest, asset, fixture and registry validation."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from wiki_core.detectors import scan_text
from wiki_core._experience_pack_temporal import normalize_temporal_document
from wiki_core.experience_pack_fixtures import validate_fixture_compiler_contract
from wiki_core._experience_pack_common import (
    ASSET_SCHEMA_VERSION,
    CORE_VERSION,
    COMMANDS_SCHEMA_VERSION,
    DEFAULT_REGISTRY,
    MIGRATION_SCHEMA_VERSION,
    PACK_SCHEMA_VERSION,
    OPERATIONS_SCHEMA_VERSION,
    REGISTRY_SCHEMA_VERSION,
    VIEWS_SCHEMA_VERSION,
    PackError,
    PackFile,
    PackSource,
    _ARTIFACT_KEYS,
    _BINARY_ASSET_EXTENSIONS,
    _CAPABILITY_KEYS,
    _CAPABILITY_RE,
    _FORBIDDEN_EXECUTABLE_EXTENSIONS,
    _ID_RE,
    _KNOWN_MANIFEST_KEYS,
    _MAX_ASSET_BYTES,
    _MAX_PACK_BYTES,
    _MAX_PACK_FILES,
    _SHA256_RE,
    _SLOT_KEYS,
    _TEXT_EXTENSIONS,
    _assert_no_symlink_chain,
    _contained,
    _load_yaml,
    _normalize_list,
    _safe_relative,
    _semver,
    _sha256_bytes,
    _sha256_json,
    version_satisfies,
)


def _validate_privacy(manifest: dict[str, Any]) -> None:
    privacy = manifest.get("privacy")
    if not isinstance(privacy, dict):
        raise PackError("privacy_contract_required")
    if set(privacy) != {
        "default_visibility",
        "public_fixture_only",
        "access_secrets",
        "pii_public_export",
    }:
        raise PackError("privacy_contract_unknown_or_missing_field")
    if privacy.get("default_visibility") not in {"private", "private_self", "internal"}:
        raise PackError("privacy_default_must_be_private")
    if privacy.get("public_fixture_only") is not True:
        raise PackError("public_fixture_contract_required")
    if privacy.get("access_secrets") != "block":
        raise PackError("core_secret_gate_cannot_be_weakened")
    if privacy.get("pii_public_export") != "block":
        raise PackError("core_public_privacy_gate_cannot_be_weakened")


_LICENSE_PROOF_MARKERS = {
    "MIT": ("MIT License", "Permission is hereby granted, free of charge"),
    "Apache-2.0": ("Apache License", "Version 2.0"),
}


def _validate_license(
    root: Path,
    pack_path: Path,
    license_id: Any,
) -> None:
    """Bind SPDX-like metadata to an applicable, versioned license text."""

    markers = _LICENSE_PROOF_MARKERS.get(str(license_id))
    if markers is None:
        raise PackError("unsupported_pack_license", str(license_id))
    candidates = [
        *(pack_path / name for name in ("LICENSE", "LICENSE.md", "LICENSE.txt")),
        *(root / name for name in ("LICENSE", "LICENSE.md", "LICENSE.txt")),
    ]
    for candidate in candidates:
        if not candidate.is_file() or candidate.is_symlink():
            continue
        try:
            text = candidate.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        if all(marker in text for marker in markers):
            return
    raise PackError("pack_license_not_proven", str(license_id))


def _validate_capabilities(manifest: dict[str, Any], core_packages: set[str]) -> None:
    capabilities = manifest.get("capabilities")
    if not isinstance(capabilities, dict) or set(capabilities) != set(_CAPABILITY_KEYS):
        raise PackError("capability_contract_unknown_or_missing_field")
    pack_id = str(manifest["id"])
    page_prefix = f"{pack_id.replace('-', '_')}_"
    for key in _CAPABILITY_KEYS:
        values = _normalize_list(capabilities.get(key), label=f"capabilities.{key}")
        if key == "block_packages":
            unknown = sorted(set(values) - core_packages)
            if unknown:
                raise PackError("unknown_core_block_package", unknown[0])
            continue
        for value in values:
            expected = page_prefix if key == "page_types" else f"{pack_id}."
            if not value.startswith(expected):
                raise PackError("capability_namespace_required", key)


def _validate_slots(manifest: dict[str, Any]) -> None:
    slots = manifest.get("slots")
    if not isinstance(slots, dict) or set(slots) != set(_SLOT_KEYS):
        raise PackError("slot_contract_unknown_or_missing_field")
    capability_for_slot = {
        "views": "views",
        "commands": "commands",
        "operations": "operations",
        "timelines": "temporal_profiles",
    }
    capabilities = manifest["capabilities"]
    for kind in _SLOT_KEYS:
        rows = slots.get(kind)
        if not isinstance(rows, list):
            raise PackError("list_required", f"slots.{kind}")
        seen: set[tuple[str, str]] = set()
        for row in rows:
            if not isinstance(row, dict) or set(row) != {
                "slot",
                "contribution",
                "mode",
            }:
                raise PackError("invalid_slot_record", kind)
            slot = row.get("slot")
            contribution = row.get("contribution")
            mode = row.get("mode")
            if not isinstance(slot, str) or not slot.startswith(f"{kind[:-1]}."):
                raise PackError("invalid_slot_name", kind)
            if contribution not in capabilities[capability_for_slot[kind]]:
                raise PackError("slot_capability_not_declared", kind)
            if mode not in {"append", "exclusive"}:
                raise PackError("invalid_slot_mode", kind)
            key = (slot, contribution)
            if key in seen:
                raise PackError("duplicate_slot_contribution", kind)
            seen.add(key)


def _core_block_packages(root: Path) -> set[str]:
    registry = root / "wiki.templates.yaml"
    if not registry.is_file() or registry.is_symlink():
        raise PackError("core_template_registry_missing")
    data = _load_yaml(registry, label="wiki.templates.yaml")
    packages = data.get("packages")
    if not isinstance(packages, dict):
        raise PackError("core_block_packages_missing")
    return {str(key) for key in packages if _CAPABILITY_RE.fullmatch(str(key))}


def _pack_tree(pack_path: Path) -> tuple[PackFile, ...]:
    if not pack_path.is_dir() or pack_path.is_symlink():
        raise PackError("pack_directory_missing")
    result: list[PackFile] = []
    total = 0
    for path in sorted(pack_path.rglob("*"), key=lambda value: value.as_posix()):
        relative = path.relative_to(pack_path).as_posix()
        _safe_relative(relative, label="pack artifact", allow_directory=path.is_dir())
        if path.is_symlink():
            raise PackError("symlink_blocked", relative)
        if path.is_dir():
            continue
        if not path.is_file():
            raise PackError("unsupported_pack_entry", relative)
        suffix = path.suffix.lower()
        if suffix in _FORBIDDEN_EXECUTABLE_EXTENSIONS:
            raise PackError("executable_pack_content_blocked", relative)
        if suffix not in _TEXT_EXTENSIONS | _BINARY_ASSET_EXTENSIONS:
            raise PackError("unsupported_pack_file_type", relative)
        if suffix in _BINARY_ASSET_EXTENSIONS | {".svg"} and not relative.startswith(
            "assets/"
        ):
            raise PackError("asset_must_stay_in_assets", relative)
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise PackError("pack_file_unreadable", relative) from exc
        total += len(raw)
        if len(result) >= _MAX_PACK_FILES or total > _MAX_PACK_BYTES:
            raise PackError("pack_budget_exceeded")
        if suffix in _TEXT_EXTENSIONS:
            try:
                text = raw.decode("utf-8")
            except UnicodeError as exc:
                raise PackError("pack_text_must_be_utf8", relative) from exc
            findings = [
                finding
                for finding in scan_text(text)
                if finding.category in {"secret", "pii", "entity"}
            ]
            if findings:
                finding = findings[0]
                raise PackError(
                    "pack_publication_privacy_blocked",
                    f"{relative}:{finding.category}:{finding.kind}",
                )
        result.append(PackFile(relative, _sha256_bytes(raw), len(raw)))
    if not result:
        raise PackError("empty_pack")
    return tuple(result)


def _validate_public_fixtures(pack_path: Path, fixtures: Any) -> list[str]:
    if not isinstance(fixtures, list) or not fixtures:
        raise PackError("fixture_contract_required")
    safe_paths: list[str] = []
    for index, raw_path in enumerate(fixtures):
        relative = _safe_relative(raw_path, label=f"fixtures[{index}]")
        fixture = _contained(pack_path, relative, label=f"fixtures[{index}]")
        if not fixture.exists() or fixture.is_symlink():
            raise PackError("fixture_missing", relative)
        scenario_path = fixture / "scenario.yaml" if fixture.is_dir() else fixture
        scenario = _load_yaml(scenario_path, label=f"fixture:{index}")
        paths = [fixture] if fixture.is_file() else sorted(fixture.rglob("*"))
        for path in paths:
            if path.is_symlink():
                raise PackError("symlink_blocked", relative)
            if not path.is_file() or path.suffix.lower() not in _TEXT_EXTENSIONS:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise PackError("fixture_unreadable", relative) from exc
            findings = [
                finding
                for finding in scan_text(text)
                if finding.category in {"secret", "pii", "entity"}
            ]
            if findings:
                kind = findings[0]
                artifact = path.relative_to(pack_path).as_posix()
                raise PackError(
                    "public_fixture_privacy_blocked",
                    f"{artifact}:{kind.category}:{kind.kind}",
                )
        if (
            scenario.get("schema_version") != "wiki_experience_pack_fixture.v1"
            or scenario.get("public_synthetic") is not True
        ):
            raise PackError("public_fixture_contract_invalid", relative)
        validate_fixture_compiler_contract(scenario)
        safe_paths.append(relative)
    return safe_paths


def _validate_assets(pack_path: Path, manifest: dict[str, Any]) -> None:
    assets = manifest.get("assets")
    if not isinstance(assets, dict) or set(assets) != {"manifest", "allow_remote"}:
        raise PackError("asset_contract_unknown_or_missing_field")
    if assets.get("allow_remote") is not False:
        raise PackError("remote_assets_blocked")
    relative = _safe_relative(assets.get("manifest"), label="assets.manifest")
    if not relative.startswith("assets/"):
        raise PackError("asset_manifest_must_stay_in_assets")
    path = _contained(pack_path, relative, label="assets.manifest")
    data = _load_yaml(path, label="assets.manifest")
    if data.get("schema_version") != ASSET_SCHEMA_VERSION:
        raise PackError("asset_schema_version_mismatch")
    rows = data.get("assets")
    if not isinstance(rows, list):
        raise PackError("list_required", "asset manifest")
    seen: set[str] = set()
    declared_paths: set[str] = set()
    total = 0
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "id",
            "path",
            "sha256",
            "license",
            "optional",
            "max_bytes",
        }:
            raise PackError("invalid_asset_record")
        asset_id = row.get("id")
        if (
            not isinstance(asset_id, str)
            or not _CAPABILITY_RE.fullmatch(asset_id)
            or asset_id in seen
        ):
            raise PackError("invalid_asset_id")
        seen.add(asset_id)
        asset_relative = _safe_relative(row.get("path"), label=f"asset:{asset_id}")
        if not asset_relative.startswith("assets/"):
            raise PackError("asset_must_stay_in_assets", asset_id)
        if asset_relative in declared_paths:
            raise PackError("duplicate_asset_path", asset_id)
        declared_paths.add(asset_relative)
        asset_path = _contained(pack_path, asset_relative, label=f"asset:{asset_id}")
        if not asset_path.is_file() or asset_path.is_symlink():
            raise PackError("asset_missing", asset_id)
        raw = asset_path.read_bytes()
        suffix = asset_path.suffix.lower()
        if suffix not in _BINARY_ASSET_EXTENSIONS | {".svg"}:
            raise PackError("unsupported_asset_file_type", asset_id)
        if suffix == ".svg":
            _validate_safe_svg(raw, asset_id=asset_id)
        max_bytes = row.get("max_bytes")
        if (
            not isinstance(max_bytes, int)
            or max_bytes <= 0
            or max_bytes > _MAX_ASSET_BYTES
        ):
            raise PackError("invalid_asset_budget", asset_id)
        if len(raw) > max_bytes:
            raise PackError("asset_budget_exceeded", asset_id)
        total += len(raw)
        if total > _MAX_PACK_BYTES:
            raise PackError("asset_budget_exceeded", "pack")
        if row.get("sha256") != _sha256_bytes(raw):
            raise PackError("asset_hash_mismatch", asset_id)
        if not isinstance(row.get("license"), str) or not row["license"].strip():
            raise PackError("asset_license_required", asset_id)
        if not isinstance(row.get("optional"), bool):
            raise PackError("asset_optional_flag_required", asset_id)

    assets_root = pack_path / "assets"
    actual_paths: set[str] = set()
    if assets_root.exists():
        if not assets_root.is_dir() or assets_root.is_symlink():
            raise PackError("asset_directory_invalid")
        for child in sorted(assets_root.rglob("*")):
            relative_child = child.relative_to(pack_path).as_posix()
            if child.is_symlink():
                raise PackError("symlink_blocked", relative_child)
            if not child.is_file() or relative_child == relative:
                continue
            actual_paths.add(relative_child)
    undeclared = sorted(actual_paths - declared_paths)
    missing = sorted(declared_paths - actual_paths)
    if undeclared:
        raise PackError("unmanifested_asset", undeclared[0])
    if missing:
        raise PackError("asset_missing", missing[0])


def _validate_safe_svg(raw: bytes, *, asset_id: str) -> None:
    """Reject active or remotely-referencing SVG before it reaches a renderer."""

    try:
        text = raw.decode("utf-8")
        root = ET.fromstring(text)
    except (UnicodeError, ET.ParseError) as exc:
        raise PackError("invalid_svg", asset_id) from exc
    blocked_elements = {"script", "foreignobject", "iframe", "object", "embed"}
    active_value = re.compile(
        r"(?:javascript\s*:|data\s*:\s*text/html|https?\s*:|(?<!:)//|url\s*\()",
        re.IGNORECASE,
    )
    for element in root.iter():
        local_tag = str(element.tag).rsplit("}", 1)[-1].lower()
        if local_tag in blocked_elements:
            raise PackError("active_svg_blocked", asset_id)
        for raw_name, raw_value in element.attrib.items():
            local_name = str(raw_name).rsplit("}", 1)[-1].lower()
            value = str(raw_value).strip()
            if local_name.startswith("on") or active_value.search(value):
                raise PackError("active_svg_blocked", asset_id)
            if local_name in {"href", "src"} and value and not value.startswith("#"):
                raise PackError("remote_svg_reference_blocked", asset_id)
        if element.text and active_value.search(element.text):
            raise PackError("active_svg_blocked", asset_id)


def _load_migration(path: Path, *, label: str) -> dict[str, Any]:
    data = _load_yaml(path, label=label)
    if set(data) != {
        "schema_version",
        "pack",
        "from_version",
        "to_version",
        "data_policy",
        "steps",
    }:
        raise PackError("migration_unknown_or_missing_field", label)
    if data.get("schema_version") != MIGRATION_SCHEMA_VERSION:
        raise PackError("migration_schema_version_mismatch", label)
    if not isinstance(data.get("pack"), str) or not _ID_RE.fullmatch(data["pack"]):
        raise PackError("migration_pack_id_invalid", label)
    if data.get("data_policy") != "preserve_user_content":
        raise PackError("migration_must_preserve_user_content", label)
    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        raise PackError("migration_steps_required", label)
    allowed = {
        "activate_pack_bundle",
        "register_capabilities",
        "deactivate_pack_bundle",
    }
    for step in steps:
        if (
            not isinstance(step, dict)
            or set(step) != {"action"}
            or step.get("action") not in allowed
        ):
            raise PackError("unsupported_migration_step", label)
    return data


def _artifact_document(
    pack_path: Path,
    manifest: dict[str, Any],
    key: str,
) -> dict[str, Any]:
    relative = _safe_relative(
        manifest["artifacts"].get(key), label=f"artifacts.{key}"
    )
    path = _contained(pack_path, relative, label=f"artifacts.{key}")
    if not path.is_file() or path.is_symlink():
        raise PackError("artifact_file_required", key)
    return _load_yaml(path, label=f"artifacts.{key}")


def _artifact_identifiers(
    value: Any,
    *,
    label: str,
    allow_empty: bool = False,
) -> list[str]:
    values = _normalize_list(value, label=label)
    if not values and not allow_empty:
        raise PackError("artifact_identifier_list_empty", label)
    return values


def _artifact_slot_map(
    manifest: dict[str, Any],
    *,
    slot_kind: str,
    capability: str,
) -> dict[str, str]:
    rows = manifest["slots"][slot_kind]
    result: dict[str, str] = {}
    for row in rows:
        contribution = str(row["contribution"])
        if contribution in result:
            raise PackError("artifact_contribution_has_multiple_slots", contribution)
        result[contribution] = str(row["slot"])
    declared = set(manifest["capabilities"][capability])
    if set(result) != declared:
        raise PackError("artifact_slot_capability_mismatch", capability)
    return result


def _validate_views_artifact(
    pack_path: Path,
    manifest: dict[str, Any],
) -> None:
    document = _artifact_document(pack_path, manifest, "views")
    pack_id = str(manifest["id"])
    if (
        set(document) != {"schema_version", "pack", "views"}
        or document.get("schema_version") != VIEWS_SCHEMA_VERSION
        or document.get("pack") != pack_id
        or not isinstance(document.get("views"), dict)
    ):
        raise PackError("views_artifact_contract_invalid", pack_id)
    views = document["views"]
    declared = set(manifest["capabilities"]["views"])
    if set(views) != declared:
        raise PackError("views_artifact_capability_mismatch", pack_id)
    slots = _artifact_slot_map(
        manifest, slot_kind="views", capability="views"
    )
    for view_id, record in sorted(views.items()):
        if not isinstance(record, dict) or set(record) not in (
            {"slot", "fallback", "empty_state"},
            {"slot", "fallback", "empty_state", "required_fields"},
        ):
            raise PackError("view_artifact_record_invalid", str(view_id))
        if record.get("slot") != slots.get(str(view_id)):
            raise PackError("view_artifact_slot_mismatch", str(view_id))
        for field in ("fallback", "empty_state"):
            if not isinstance(record.get(field), str) or not _CAPABILITY_RE.fullmatch(
                record[field]
            ):
                raise PackError("view_artifact_identifier_invalid", str(view_id))
        if "required_fields" in record:
            _artifact_identifiers(
                record["required_fields"],
                label=f"view:{view_id}:required_fields",
            )


def _validate_permissions(
    pack_id: str,
    permissions: Any,
) -> set[str]:
    if not isinstance(permissions, dict):
        raise PackError("operation_permissions_mapping_required", pack_id)
    result: set[str] = set()
    for permission_id, record in sorted(permissions.items()):
        if (
            not isinstance(permission_id, str)
            or not permission_id.startswith(f"{pack_id}.")
            or not _CAPABILITY_RE.fullmatch(permission_id)
            or not isinstance(record, dict)
            or set(record) != {"scope", "mode"}
            or not isinstance(record.get("scope"), str)
            or not _CAPABILITY_RE.fullmatch(record["scope"])
            or record.get("mode")
            not in {"read_only", "proposal_only", "human_approval_required"}
        ):
            raise PackError("operation_permission_invalid", str(permission_id))
        result.add(permission_id)
    if not result:
        raise PackError("operation_permissions_required", pack_id)
    return result


def _validate_commands_artifact(
    pack_path: Path,
    manifest: dict[str, Any],
    permission_ids: set[str],
) -> dict[str, dict[str, Any]]:
    document = _artifact_document(pack_path, manifest, "commands")
    pack_id = str(manifest["id"])
    if (
        set(document) != {"schema_version", "pack", "commands"}
        or document.get("schema_version") != COMMANDS_SCHEMA_VERSION
        or document.get("pack") != pack_id
        or not isinstance(document.get("commands"), dict)
    ):
        raise PackError("commands_artifact_contract_invalid", pack_id)
    commands = document["commands"]
    declared = set(manifest["capabilities"]["commands"])
    if set(commands) != declared:
        raise PackError("commands_artifact_capability_mismatch", pack_id)
    slots = _artifact_slot_map(
        manifest, slot_kind="commands", capability="commands"
    )
    for command_id, record in sorted(commands.items()):
        if not isinstance(record, dict) or set(record) != {
            "slot",
            "inputs",
            "outputs",
            "permissions",
            "mode",
            "dry_run",
            "human_gate",
        }:
            raise PackError("command_artifact_record_invalid", str(command_id))
        if record.get("slot") != slots.get(str(command_id)):
            raise PackError("command_artifact_slot_mismatch", str(command_id))
        _artifact_identifiers(record.get("inputs"), label=f"command:{command_id}:inputs")
        outputs = _artifact_identifiers(
            record.get("outputs"), label=f"command:{command_id}:outputs"
        )
        if not set(outputs).issubset(manifest["capabilities"]["page_types"]):
            raise PackError("command_artifact_output_unknown", str(command_id))
        permissions = _artifact_identifiers(
            record.get("permissions"), label=f"command:{command_id}:permissions"
        )
        if not set(permissions).issubset(permission_ids):
            raise PackError("command_artifact_permission_unknown", str(command_id))
        if (
            record.get("mode") != "proposal_only"
            or record.get("dry_run") is not True
            or record.get("human_gate") != "required"
        ):
            raise PackError("command_artifact_safety_contract_invalid", str(command_id))
    return commands


def _validate_skills(
    pack_id: str,
    skills: Any,
    permission_ids: set[str],
) -> None:
    if not isinstance(skills, dict) or set(skills) != {"human", "agent"}:
        raise PackError("operation_skills_contract_invalid", pack_id)
    seen: set[str] = set()
    for kind in ("human", "agent"):
        rows = skills[kind]
        if not isinstance(rows, list):
            raise PackError("operation_skills_contract_invalid", kind)
        for row in rows:
            if (
                not isinstance(row, dict)
                or set(row) != {"id", "permissions", "responsibility"}
                or not isinstance(row.get("id"), str)
                or not row["id"].startswith(f"{pack_id}.")
                or not _CAPABILITY_RE.fullmatch(row["id"])
                or row["id"] in seen
                or not isinstance(row.get("responsibility"), str)
                or not row["responsibility"].strip()
            ):
                raise PackError("operation_skill_invalid", kind)
            permissions = _artifact_identifiers(
                row.get("permissions"), label=f"skill:{row['id']}:permissions"
            )
            if not set(permissions).issubset(permission_ids):
                raise PackError("operation_skill_permission_unknown", row["id"])
            seen.add(row["id"])


def _validate_operations_artifact(
    pack_path: Path,
    manifest: dict[str, Any],
    commands: dict[str, dict[str, Any]],
) -> None:
    document = _artifact_document(pack_path, manifest, "operations")
    pack_id = str(manifest["id"])
    if (
        set(document)
        != {
            "schema_version",
            "pack",
            "write_policy",
            "permissions",
            "skills",
            "operations",
        }
        or document.get("schema_version") != OPERATIONS_SCHEMA_VERSION
        or document.get("pack") != pack_id
        or document.get("write_policy") != "proposal_branch_only"
        or not isinstance(document.get("operations"), dict)
    ):
        raise PackError("operations_artifact_contract_invalid", pack_id)
    permission_ids = _validate_permissions(pack_id, document["permissions"])
    _validate_skills(pack_id, document["skills"], permission_ids)
    operations = document["operations"]
    declared = set(manifest["capabilities"]["operations"])
    if set(operations) != declared:
        raise PackError("operations_artifact_capability_mismatch", pack_id)
    slots = _artifact_slot_map(
        manifest, slot_kind="operations", capability="operations"
    )
    for operation_id, record in sorted(operations.items()):
        if not isinstance(record, dict) or set(record) != {
            "slot",
            "command",
            "inputs",
            "outputs",
            "permissions",
            "dry_run",
            "human_gate",
            "policies",
        }:
            raise PackError("operation_artifact_record_invalid", str(operation_id))
        if record.get("slot") != slots.get(str(operation_id)):
            raise PackError("operation_artifact_slot_mismatch", str(operation_id))
        command_id = record.get("command")
        command = commands.get(str(command_id))
        if not isinstance(command, dict):
            raise PackError("operation_artifact_command_unknown", str(operation_id))
        inputs = _artifact_identifiers(
            record.get("inputs"), label=f"operation:{operation_id}:inputs"
        )
        outputs = _artifact_identifiers(
            record.get("outputs"), label=f"operation:{operation_id}:outputs"
        )
        permissions = _artifact_identifiers(
            record.get("permissions"), label=f"operation:{operation_id}:permissions"
        )
        if (
            inputs != command["inputs"]
            or outputs != command["outputs"]
            or permissions != command["permissions"]
        ):
            raise PackError("operation_command_contract_mismatch", str(operation_id))
        if not set(permissions).issubset(permission_ids):
            raise PackError("operation_artifact_permission_unknown", str(operation_id))
        if record.get("dry_run") is not True or record.get("human_gate") != "required":
            raise PackError("operation_artifact_safety_contract_invalid", str(operation_id))
        policies = record.get("policies")
        if not isinstance(policies, dict) or any(
            not isinstance(key, str)
            or not _CAPABILITY_RE.fullmatch(key)
            or not isinstance(value, (str, bool, int, float, list))
            for key, value in policies.items()
        ):
            raise PackError("operation_artifact_policies_invalid", str(operation_id))


def _validate_temporal_artifact(
    pack_path: Path,
    manifest: dict[str, Any],
) -> None:
    document = _artifact_document(pack_path, manifest, "temporal")
    pack_id = str(manifest["id"])
    slots = _artifact_slot_map(
        manifest, slot_kind="timelines", capability="temporal_profiles"
    )
    page_types_document = _artifact_document(pack_path, manifest, "page_types")
    page_types = page_types_document.get("page_types")
    if not isinstance(page_types, dict):
        raise PackError("temporal_adapter_page_types_invalid", pack_id)
    normalize_temporal_document(
        document,
        pack_id=pack_id,
        declared_profiles=manifest["capabilities"]["temporal_profiles"],
        profile_slots=slots,
        declared_page_types=manifest["capabilities"]["page_types"],
        page_type_fields={
            str(page_type): tuple(record.get("fields") or ())
            for page_type, record in page_types.items()
            if isinstance(record, Mapping)
        },
    )


def _validate_declarative_artifacts(
    pack_path: Path,
    manifest: dict[str, Any],
) -> None:
    operations = _artifact_document(pack_path, manifest, "operations")
    permission_ids = _validate_permissions(
        str(manifest["id"]), operations.get("permissions")
    )
    commands = _validate_commands_artifact(
        pack_path, manifest, permission_ids
    )
    _validate_views_artifact(pack_path, manifest)
    _validate_operations_artifact(pack_path, manifest, commands)
    _validate_temporal_artifact(pack_path, manifest)


def _validate_artifacts_and_migrations(
    pack_path: Path, manifest: dict[str, Any]
) -> None:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != set(_ARTIFACT_KEYS):
        raise PackError("artifact_contract_unknown_or_missing_field")
    for key in _ARTIFACT_KEYS:
        relative = _safe_relative(artifacts.get(key), label=f"artifacts.{key}")
        path = _contained(pack_path, relative, label=f"artifacts.{key}")
        if not path.exists() or path.is_symlink():
            raise PackError("artifact_missing", key)
    for key in ("templates", "i18n"):
        relative = _safe_relative(artifacts.get(key), label=f"artifacts.{key}")
        path = _contained(pack_path, relative, label=f"artifacts.{key}")
        if not path.is_dir() or path.is_symlink():
            raise PackError("artifact_directory_required", key)
    for key in set(_ARTIFACT_KEYS) - {"templates", "i18n"}:
        relative = _safe_relative(artifacts.get(key), label=f"artifacts.{key}")
        path = _contained(pack_path, relative, label=f"artifacts.{key}")
        if not path.is_file() or path.is_symlink():
            raise PackError("artifact_file_required", key)
    _validate_declarative_artifacts(pack_path, manifest)
    migrations = manifest.get("migrations")
    if not isinstance(migrations, dict) or set(migrations) != {"install", "upgrades"}:
        raise PackError("migration_contract_unknown_or_missing_field")
    install_relative = _safe_relative(
        migrations.get("install"), label="migrations.install"
    )
    install = _contained(pack_path, install_relative, label="migrations.install")
    data = _load_migration(install, label="migrations.install")
    if (
        data.get("pack") != manifest.get("id")
        or data.get("to_version") != manifest.get("version")
        or data.get("from_version") is not None
    ):
        raise PackError("install_migration_version_mismatch")
    upgrades_relative = _safe_relative(
        migrations.get("upgrades"), label="migrations.upgrades"
    )
    upgrades = _contained(pack_path, upgrades_relative, label="migrations.upgrades")
    if not upgrades.is_dir() or upgrades.is_symlink():
        raise PackError("upgrade_migration_directory_missing")


def validate_manifest(
    root: Path,
    pack_path: Path,
    manifest: dict[str, Any],
    *,
    core_contract_root: Path | None = None,
) -> None:
    if set(manifest) != _KNOWN_MANIFEST_KEYS:
        raise PackError("manifest_unknown_or_missing_field")
    if manifest.get("schema_version") != PACK_SCHEMA_VERSION:
        raise PackError("pack_schema_version_mismatch")
    pack_id = manifest.get("id")
    if not isinstance(pack_id, str) or not _ID_RE.fullmatch(pack_id):
        raise PackError("invalid_pack_id")
    _semver(manifest.get("version"), label="pack.version")
    for key in ("name", "description", "license", "compatible_core"):
        if not isinstance(manifest.get(key), str) or not manifest[key].strip():
            raise PackError("manifest_text_required", key)
    _validate_license(root, pack_path, manifest["license"])
    if not version_satisfies(CORE_VERSION, manifest["compatible_core"]):
        raise PackError("incompatible_core")
    _validate_privacy(manifest)
    _validate_capabilities(
        manifest,
        _core_block_packages(core_contract_root or root),
    )
    _validate_slots(manifest)
    dependencies = manifest.get("dependencies")
    if not isinstance(dependencies, list):
        raise PackError("list_required", "dependencies")
    seen_dependencies: set[str] = set()
    for dependency in dependencies:
        if not isinstance(dependency, dict) or set(dependency) != {"id", "version"}:
            raise PackError("invalid_dependency_record")
        dependency_id = dependency.get("id")
        if (
            not isinstance(dependency_id, str)
            or not _ID_RE.fullmatch(dependency_id)
            or dependency_id == pack_id
            or dependency_id in seen_dependencies
        ):
            raise PackError("invalid_dependency_id")
        version_satisfies("0.0.0", str(dependency.get("version")))
        seen_dependencies.add(dependency_id)
    conflicts = manifest.get("conflicts")
    if not isinstance(conflicts, list):
        raise PackError("list_required", "conflicts")
    seen_conflicts: set[str] = set()
    for conflict in conflicts:
        if (
            not isinstance(conflict, str)
            or not _ID_RE.fullmatch(conflict)
            or conflict == pack_id
            or conflict in seen_conflicts
        ):
            raise PackError("invalid_conflict_id")
        seen_conflicts.add(conflict)
    overlap = seen_dependencies & seen_conflicts
    if overlap:
        raise PackError("dependency_conflict_overlap", sorted(overlap)[0])
    _validate_assets(pack_path, manifest)
    _validate_public_fixtures(pack_path, manifest.get("fixtures"))
    _validate_artifacts_and_migrations(pack_path, manifest)
    tests = manifest.get("tests")
    if not isinstance(tests, dict) or set(tests) != {"contracts"}:
        raise PackError("test_contract_unknown_or_missing_field")
    contracts = _normalize_list(tests.get("contracts"), label="tests.contracts")
    required_contracts = {"pack_contract", "privacy_boundary", "lifecycle"}
    if not required_contracts.issubset(contracts):
        raise PackError("required_pack_contract_missing")
    i18n = manifest.get("i18n")
    if not isinstance(i18n, dict) or set(i18n) != {"locales", "default_locale"}:
        raise PackError("i18n_contract_unknown_or_missing_field")
    raw_locales = i18n.get("locales")
    if not isinstance(raw_locales, list) or any(
        not isinstance(locale, str)
        or not re.fullmatch(r"[a-z]{2}(?:-[A-Z]{2})?", locale)
        for locale in raw_locales
    ):
        raise PackError("invalid_locale")
    locales = list(dict.fromkeys(raw_locales))
    if len(locales) != len(raw_locales):
        raise PackError("duplicate_locale")
    if i18n.get("default_locale") not in locales or not {"en", "pt-BR"}.issubset(
        locales
    ):
        raise PackError("required_pack_locales_missing")
    # Local import avoids an import-time cycle: the presentation module reuses
    # this module's closed pack-tree reader for installed-state verification.
    # Source validation happens before install/upgrade writes any bundle, lock
    # or receipt, so a malformed catalog cannot create a broken installation.
    from wiki_core._experience_pack_i18n import validate_pack_presentation_source

    validate_pack_presentation_source(pack_path, manifest)


def _registry_file(root: Path, registry_path: Path | None = None) -> Path:
    path = registry_path or (root / DEFAULT_REGISTRY)
    if not path.is_absolute():
        path = root / path
    try:
        path.resolve(strict=False).relative_to(root.resolve())
    except ValueError as exc:
        raise PackError("registry_outside_repository") from exc
    _assert_no_symlink_chain(root, path, label="pack registry")
    return path


def load_registry(root: Path, registry_path: Path | None = None) -> dict[str, Any]:
    path = _registry_file(root, registry_path)
    data = _load_yaml(path, label="pack registry")
    if (
        set(data) != {"schema_version", "packs"}
        or data.get("schema_version") != REGISTRY_SCHEMA_VERSION
    ):
        raise PackError("registry_schema_version_mismatch")
    packs = data.get("packs")
    if not isinstance(packs, dict):
        raise PackError("registry_packs_mapping_required")
    for pack_id, record in sorted(packs.items()):
        if not isinstance(pack_id, str) or not _ID_RE.fullmatch(pack_id):
            raise PackError("invalid_registry_pack_id")
        if not isinstance(record, dict) or set(record) != {
            "default_version",
            "versions",
        }:
            raise PackError("invalid_registry_pack_record", pack_id)
        versions = record.get("versions")
        if not isinstance(versions, dict) or not versions:
            raise PackError("registry_versions_required", pack_id)
        if record.get("default_version") not in versions:
            raise PackError("registry_default_version_missing", pack_id)
        for version, version_record in sorted(versions.items()):
            _semver(version, label="registry version")
            if not isinstance(version_record, dict) or set(version_record) != {
                "path",
                "manifest_sha256",
                "tree_sha256",
            }:
                raise PackError("invalid_registry_version_record", pack_id)
            _safe_relative(version_record.get("path"), label=f"registry:{pack_id}")
            if not isinstance(
                version_record.get("manifest_sha256"), str
            ) or not _SHA256_RE.fullmatch(version_record["manifest_sha256"]):
                raise PackError("invalid_registry_manifest_hash", pack_id)
            if not isinstance(
                version_record.get("tree_sha256"), str
            ) or not _SHA256_RE.fullmatch(version_record["tree_sha256"]):
                raise PackError("invalid_registry_tree_hash", pack_id)
    return data


def resolve_pack(
    root: Path,
    pack_id: str,
    *,
    version: str | None = None,
    registry_path: Path | None = None,
    core_contract_root: Path | None = None,
) -> PackSource:
    if not _ID_RE.fullmatch(pack_id):
        raise PackError("invalid_pack_id")
    registry_file = _registry_file(root, registry_path)
    registry = load_registry(root, registry_file)
    record = registry["packs"].get(pack_id)
    if not isinstance(record, dict):
        raise PackError("pack_not_registered", pack_id)
    selected = version or str(record["default_version"])
    _semver(selected, label="pack.version")
    version_record = record["versions"].get(selected)
    if not isinstance(version_record, dict):
        raise PackError("pack_version_not_registered", pack_id)
    pack_path = _contained(
        registry_file.parent, version_record["path"], label=f"registry:{pack_id}"
    )
    _assert_no_symlink_chain(root, pack_path, label=f"pack:{pack_id}")
    manifest_path = pack_path / "pack.yaml"
    manifest = _load_yaml(manifest_path, label=f"manifest:{pack_id}")
    manifest_raw = manifest_path.read_bytes()
    manifest_sha = _sha256_bytes(manifest_raw)
    if manifest_sha != version_record["manifest_sha256"]:
        raise PackError("registry_manifest_hash_mismatch", pack_id)
    if manifest.get("id") != pack_id or manifest.get("version") != selected:
        raise PackError("registry_manifest_identity_mismatch", pack_id)
    validate_manifest(
        root,
        pack_path,
        manifest,
        core_contract_root=core_contract_root,
    )
    files = _pack_tree(pack_path)
    tree_sha = _sha256_json([file.__dict__ for file in files])
    if tree_sha != version_record["tree_sha256"]:
        raise PackError("registry_tree_hash_mismatch", pack_id)
    registry_relative = pack_path.relative_to(root).as_posix()
    return PackSource(
        pack_id=pack_id,
        version=selected,
        path=pack_path,
        registry_path=registry_relative,
        manifest=manifest,
        manifest_sha256=manifest_sha,
        tree_sha256=tree_sha,
        files=files,
    )


def inspect_pack(
    root: Path,
    pack_id: str,
    *,
    version: str | None = None,
    registry_path: Path | None = None,
) -> dict[str, Any]:
    source = resolve_pack(root, pack_id, version=version, registry_path=registry_path)
    manifest = source.manifest
    return {
        "schema_version": PACK_SCHEMA_VERSION,
        "id": source.pack_id,
        "name": manifest["name"],
        "description": manifest["description"],
        "version": source.version,
        "license": manifest["license"],
        "compatible_core": manifest["compatible_core"],
        "capabilities": manifest["capabilities"],
        "dependencies": manifest["dependencies"],
        "conflicts": manifest["conflicts"],
        "privacy": manifest["privacy"],
        "slots": manifest["slots"],
        "fixtures": manifest["fixtures"],
        "asset_policy": {
            "remote": "blocked",
            "manifest": manifest["assets"]["manifest"],
        },
        "manifest_sha256": source.manifest_sha256,
        "tree_sha256": source.tree_sha256,
        "file_count": len(source.files),
    }


def preview_pack(
    root: Path,
    pack_id: str,
    *,
    version: str | None = None,
    registry_path: Path | None = None,
) -> dict[str, Any]:
    source = resolve_pack(root, pack_id, version=version, registry_path=registry_path)
    fixtures = []
    for relative in source.manifest["fixtures"]:
        base = _contained(source.path, relative, label="fixture")
        scenario_path = base / "scenario.yaml" if base.is_dir() else base
        scenario = _load_yaml(
            scenario_path, label=f"fixture:{PurePosixPath(relative).name}"
        )
        fixtures.append(
            {
                "id": str(scenario.get("id") or PurePosixPath(relative).name),
                "story": str(scenario.get("story") or ""),
                "expected_state": str(scenario.get("expected_state") or "ready"),
                "path": relative,
            }
        )
    return {
        "schema_version": "wiki_experience_pack_preview.v1",
        "pack": source.pack_id,
        "version": source.version,
        "synthetic_only": True,
        "privacy_gate": "passed",
        "fixtures": sorted(fixtures, key=lambda row: row["id"]),
        "views": source.manifest["capabilities"]["views"],
        "operations": source.manifest["capabilities"]["operations"],
        "temporal_profiles": source.manifest["capabilities"]["temporal_profiles"],
    }
