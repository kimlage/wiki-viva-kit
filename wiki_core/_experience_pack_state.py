"""Installed pack lockfile validation and deterministic composition."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from wiki_core._experience_pack_common import (
    COMPOSITION_SCHEMA_VERSION,
    CORE_VERSION,
    DEFAULT_LOCK,
    INSTALLED_ROOT,
    LOCK_SCHEMA_VERSION,
    REGISTRY_SCHEMA_VERSION,
    _CAPABILITY_KEYS,
    _ID_RE,
    _SHA256_RE,
    _SLOT_KEYS,
    PackError,
    PackSource,
    _assert_no_symlink_chain,
    _load_yaml,
    _normalize_list,
    _safe_relative,
    _semver,
    _sha256_json,
    version_satisfies,
)
from wiki_core._experience_pack_validation import load_registry
from wiki_core._experience_pack_i18n import (
    PACK_PRESENTATION_DEFAULT_LOCALE,
    PACK_PRESENTATION_REQUIRED_LOCALES,
    load_installed_pack_presentation,
)


def list_packs(root: Path, *, registry_path: Path | None = None) -> dict[str, Any]:
    registry = load_registry(root, registry_path)
    rows = []
    lock = load_lock(root)
    for pack_id, record in sorted(registry["packs"].items()):
        installed = lock["packs"].get(pack_id)
        rows.append(
            {
                "id": pack_id,
                "default_version": record["default_version"],
                "versions": sorted(record["versions"], key=_semver_sort_key),
                "installed_version": installed.get("version")
                if isinstance(installed, dict)
                else None,
                "status": installed.get("status")
                if isinstance(installed, dict)
                else "not_installed",
            }
        )
    return {"schema_version": REGISTRY_SCHEMA_VERSION, "packs": rows}


def _semver_sort_key(value: str) -> tuple[int, int, int]:
    return _semver(value, label="version")


def _empty_lock() -> dict[str, Any]:
    return {
        "schema_version": LOCK_SCHEMA_VERSION,
        "core_version": CORE_VERSION,
        "packs": {},
    }


def load_lock(root: Path, lock_path: Path | None = None) -> dict[str, Any]:
    path = lock_path or (root / DEFAULT_LOCK)
    if not path.is_absolute():
        path = root / path
    try:
        path.resolve(strict=False).relative_to(root.resolve())
    except ValueError as exc:
        raise PackError("lock_outside_repository") from exc
    _assert_no_symlink_chain(root, path, label="pack lock")
    if not path.exists():
        return _empty_lock()
    data = _load_yaml(path, label="pack lock")
    if (
        set(data) != {"schema_version", "core_version", "packs"}
        or data.get("schema_version") != LOCK_SCHEMA_VERSION
    ):
        raise PackError("lock_schema_version_mismatch")
    if data.get("core_version") != CORE_VERSION or not isinstance(
        data.get("packs"), dict
    ):
        raise PackError("lock_core_or_packs_invalid")
    for pack_id, entry in data["packs"].items():
        if (
            not isinstance(pack_id, str)
            or not _ID_RE.fullmatch(pack_id)
            or not isinstance(entry, dict)
        ):
            raise PackError("invalid_lock_entry")
        required = {
            "version",
            "status",
            "manifest_sha256",
            "tree_sha256",
            "registry_path",
            "installed_path",
            "capabilities",
            "slots",
            "dependencies",
            "conflicts",
            "files",
            "receipts",
        }
        if set(entry) != required:
            raise PackError("invalid_lock_entry_fields", pack_id)
        _semver(entry.get("version"), label="lock.version")
        if entry.get("status") not in {"active", "disabled"}:
            raise PackError("invalid_lock_status", pack_id)
        for digest_key in ("manifest_sha256", "tree_sha256"):
            if not isinstance(entry.get(digest_key), str) or not _SHA256_RE.fullmatch(
                entry[digest_key]
            ):
                raise PackError("invalid_lock_hash", pack_id)
        _safe_relative(entry.get("registry_path"), label="lock.registry_path")
        installed_path = _safe_relative(
            entry.get("installed_path"), label="lock.installed_path"
        )
        expected_installed = (
            INSTALLED_ROOT / pack_id / str(entry["version"])
        ).as_posix()
        if installed_path != expected_installed:
            raise PackError("lock_installed_path_outside_pack_namespace", pack_id)
        capabilities = entry.get("capabilities")
        if not isinstance(capabilities, dict) or set(capabilities) != set(
            _CAPABILITY_KEYS
        ):
            raise PackError("invalid_lock_capabilities", pack_id)
        for key in _CAPABILITY_KEYS:
            values = _normalize_list(
                capabilities.get(key), label=f"lock.capabilities.{key}"
            )
            if key == "block_packages":
                continue
            prefix = (
                f"{pack_id.replace('-', '_')}_"
                if key == "page_types"
                else f"{pack_id}."
            )
            if any(not value.startswith(prefix) for value in values):
                raise PackError(
                    "lock_capability_namespace_mismatch", f"{pack_id}:{key}"
                )
        slots = entry.get("slots")
        if not isinstance(slots, dict) or set(slots) != set(_SLOT_KEYS):
            raise PackError("invalid_lock_slots", pack_id)
        capability_for_slot = {
            "views": "views",
            "commands": "commands",
            "operations": "operations",
            "timelines": "temporal_profiles",
        }
        for kind in _SLOT_KEYS:
            if not isinstance(slots[kind], list):
                raise PackError("invalid_lock_slots", pack_id)
            seen_slots: set[tuple[str, str]] = set()
            for row in slots[kind]:
                if (
                    not isinstance(row, dict)
                    or set(row) != {"slot", "contribution", "mode"}
                    or row.get("mode") not in {"append", "exclusive"}
                    or not isinstance(row.get("slot"), str)
                    or not isinstance(row.get("contribution"), str)
                ):
                    raise PackError("invalid_lock_slot_record", pack_id)
                if not row["slot"].startswith(f"{kind[:-1]}."):
                    raise PackError("invalid_lock_slot_name", f"{pack_id}:{kind}")
                if row["contribution"] not in capabilities[capability_for_slot[kind]]:
                    raise PackError(
                        "lock_slot_capability_not_declared", f"{pack_id}:{kind}"
                    )
                identity = (row["slot"], row["contribution"])
                if identity in seen_slots:
                    raise PackError(
                        "duplicate_lock_slot_contribution", f"{pack_id}:{kind}"
                    )
                seen_slots.add(identity)
        if not isinstance(entry.get("dependencies"), list) or not isinstance(
            entry.get("conflicts"), list
        ):
            raise PackError("invalid_lock_composition_contract", pack_id)
        dependency_ids: set[str] = set()
        for dependency in entry["dependencies"]:
            if not isinstance(dependency, dict) or set(dependency) != {"id", "version"}:
                raise PackError("invalid_lock_dependency", pack_id)
            dependency_id = dependency.get("id")
            if (
                not isinstance(dependency_id, str)
                or not _ID_RE.fullmatch(dependency_id)
                or dependency_id == pack_id
                or dependency_id in dependency_ids
            ):
                raise PackError("invalid_lock_dependency", pack_id)
            version_satisfies("0.0.0", str(dependency.get("version")))
            dependency_ids.add(dependency_id)
        conflict_ids: set[str] = set()
        for conflict in entry["conflicts"]:
            if (
                not isinstance(conflict, str)
                or not _ID_RE.fullmatch(conflict)
                or conflict == pack_id
                or conflict in conflict_ids
            ):
                raise PackError("invalid_lock_conflict", pack_id)
            conflict_ids.add(conflict)
        if dependency_ids & conflict_ids:
            raise PackError("lock_dependency_conflict_overlap", pack_id)
        if not isinstance(entry.get("files"), list) or not isinstance(
            entry.get("receipts"), list
        ):
            raise PackError("invalid_lock_inventory", pack_id)
        seen_files: set[str] = set()
        for file_record in entry["files"]:
            if not isinstance(file_record, dict) or set(file_record) != {
                "path",
                "sha256",
                "size",
            }:
                raise PackError("invalid_lock_file_record", pack_id)
            relative = _safe_relative(file_record.get("path"), label="lock file")
            if relative in seen_files:
                raise PackError("duplicate_lock_file", pack_id)
            seen_files.add(relative)
            if (
                not isinstance(file_record.get("sha256"), str)
                or not _SHA256_RE.fullmatch(file_record["sha256"])
                or not isinstance(file_record.get("size"), int)
                or file_record["size"] < 0
            ):
                raise PackError("invalid_lock_file_record", pack_id)
        if any(
            not isinstance(receipt, str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", receipt)
            for receipt in entry["receipts"]
        ) or len(set(entry["receipts"])) != len(entry["receipts"]):
            raise PackError("invalid_lock_receipts", pack_id)
    return data


def _entry_for(
    source: PackSource, *, receipts: list[str], status: str = "active"
) -> dict[str, Any]:
    return {
        "version": source.version,
        "status": status,
        "manifest_sha256": source.manifest_sha256,
        "tree_sha256": source.tree_sha256,
        "registry_path": source.registry_path,
        "installed_path": (INSTALLED_ROOT / source.pack_id / source.version).as_posix(),
        "capabilities": source.manifest["capabilities"],
        "slots": source.manifest["slots"],
        "dependencies": source.manifest["dependencies"],
        "conflicts": source.manifest["conflicts"],
        "files": [file.__dict__ for file in source.files],
        "receipts": receipts,
    }


def _active_entries(
    lock: dict[str, Any], *, excluding: str | None = None
) -> dict[str, dict[str, Any]]:
    return {
        pack_id: entry
        for pack_id, entry in sorted(lock["packs"].items())
        if pack_id != excluding and entry.get("status") == "active"
    }


def _assert_composable(
    candidate: PackSource, lock: dict[str, Any], *, replacing: str | None = None
) -> None:
    active = _active_entries(lock, excluding=replacing)
    candidate_manifest = candidate.manifest
    candidate_conflicts = set(candidate_manifest["conflicts"])
    for pack_id, entry in active.items():
        if pack_id in candidate_conflicts or candidate.pack_id in set(
            entry["conflicts"]
        ):
            raise PackError("pack_conflict", pack_id)
    for dependency in candidate_manifest["dependencies"]:
        installed = active.get(dependency["id"])
        if not installed or not version_satisfies(
            installed["version"], dependency["version"]
        ):
            raise PackError("dependency_not_satisfied", dependency["id"])
    for pack_id, entry in active.items():
        for dependency in entry["dependencies"]:
            if dependency["id"] == candidate.pack_id and not version_satisfies(
                candidate.version, dependency["version"]
            ):
                raise PackError("reverse_dependency_not_satisfied", pack_id)
    for capability in (
        "page_types",
        "blocks",
        "views",
        "commands",
        "operations",
        "temporal_profiles",
    ):
        candidate_values = set(candidate_manifest["capabilities"][capability])
        for pack_id, entry in active.items():
            overlap = candidate_values & set(entry["capabilities"][capability])
            if overlap:
                raise PackError("capability_conflict", f"{capability}:{pack_id}")
    occupied: dict[tuple[str, str], tuple[str, bool]] = {}
    for pack_id, entry in active.items():
        for kind in _SLOT_KEYS:
            for row in entry["slots"][kind]:
                key = (kind, row["slot"])
                prior = occupied.get(key)
                occupied[key] = (
                    prior[0] if prior else pack_id,
                    (prior[1] if prior else False) or row["mode"] == "exclusive",
                )
    for kind in _SLOT_KEYS:
        for row in candidate_manifest["slots"][kind]:
            current = occupied.get((kind, row["slot"]))
            if current and (current[1] or row["mode"] == "exclusive"):
                raise PackError("exclusive_slot_conflict", f"{kind}:{current[0]}")


def compose_active_packs(root: Path) -> dict[str, Any]:
    lock = load_lock(root)
    contributions = {kind: [] for kind in _SLOT_KEYS}
    active = _active_entries(lock)
    for pack_id, entry in active.items():
        for kind in _SLOT_KEYS:
            for row in sorted(
                entry["slots"][kind],
                key=lambda value: (value["slot"], value["contribution"]),
            ):
                contributions[kind].append({"pack": pack_id, **row})
    pack_versions = [
        {"id": pack_id, "version": entry["version"]}
        for pack_id, entry in active.items()
    ]
    block_packages = sorted(
        {
            package
            for entry in active.values()
            for package in entry["capabilities"]["block_packages"]
        }
    )
    presentation_locales: dict[str, dict[str, str]] = {
        locale: {} for locale in sorted(PACK_PRESENTATION_REQUIRED_LOCALES)
    }
    locale_contract: set[str] | None = None
    for pack_id, entry in active.items():
        pack_presentation = load_installed_pack_presentation(root, pack_id, entry)
        pack_locales = pack_presentation["locales"]
        current_locales = set(pack_locales)
        if locale_contract is None:
            locale_contract = current_locales
            presentation_locales = {locale: {} for locale in sorted(current_locales)}
        elif current_locales != locale_contract:
            raise PackError("pack_presentation_locale_set_mismatch", pack_id)
        for locale, labels in sorted(pack_locales.items()):
            overlap = set(presentation_locales[locale]) & set(labels)
            if overlap:
                raise PackError(
                    "pack_presentation_identifier_conflict", sorted(overlap)[0]
                )
            presentation_locales[locale].update(labels)
    presentation = {
        "default_locale": PACK_PRESENTATION_DEFAULT_LOCALE,
        "locales": {
            locale: dict(sorted(labels.items()))
            for locale, labels in sorted(presentation_locales.items())
        },
    }
    semantic_payload = {
        "packs": pack_versions,
        "block_packages": block_packages,
        "slots": contributions,
        "presentation": presentation,
    }
    return {
        "schema_version": COMPOSITION_SCHEMA_VERSION,
        "core_version": CORE_VERSION,
        "packs": pack_versions,
        "block_packages": block_packages,
        "slots": contributions,
        "presentation": presentation,
        "composition_sha256": _sha256_json(semantic_payload),
    }
