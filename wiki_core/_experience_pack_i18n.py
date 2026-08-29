"""Safe, deterministic presentation labels for installed experience packs.

Pack catalogs are data, never executable code.  This module re-opens the
hash-pinned installed bundle, validates locale parity and projects only short
plain-text labels keyed by canonical public identifiers.  The resulting map is
part of the composition hash, so the cockpit never has to read a pack file at
runtime or guess a technical identifier as user-facing copy.
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Any, Mapping

import yaml

from wiki_core._experience_pack_common import (
    _CAPABILITY_RE,
    _SHA256_RE,
    PackError,
    _assert_no_symlink_chain,
    _contained,
    _load_yaml,
    _safe_relative,
    _sha256_bytes,
    _sha256_json,
)
from wiki_core._experience_pack_validation import _pack_tree

PACK_I18N_SCHEMA_VERSION = "wiki_experience_pack_i18n.v1"
PACK_PRESENTATION_DEFAULT_LOCALE = "en"
PACK_PRESENTATION_REQUIRED_LOCALES = frozenset({"en", "es", "pt-BR"})
_COPY_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,95}$")
_LOCALE_RE = re.compile(r"^[a-z]{2}(?:-[A-Z]{2})?$")


def _copy_key(identifier: str, pack_id: str) -> str:
    if identifier == pack_id:
        return "title"
    dotted = f"{pack_id}."
    page_prefix = f"{pack_id.replace('-', '_')}_"
    if identifier.startswith(dotted):
        suffix = identifier[len(dotted) :]
    elif identifier.startswith(page_prefix):
        suffix = identifier[len(page_prefix) :]
    else:
        raise PackError("pack_presentation_identifier_not_namespaced", identifier)
    key = re.sub(r"[.-]+", "_", suffix)
    if not _COPY_KEY_RE.fullmatch(key):
        raise PackError("pack_presentation_copy_key_invalid", identifier)
    return key


def _plain_label(value: Any, *, locale: str, key: str) -> str:
    if not isinstance(value, str) or value != value.strip() or not 1 <= len(value) <= 96:
        raise PackError("pack_presentation_label_invalid", f"{locale}:{key}")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise PackError("pack_presentation_label_invalid", f"{locale}:{key}")
    return value


def _yaml_from_bytes(raw: bytes, *, label: str) -> dict[str, Any]:
    try:
        data = yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeError, yaml.YAMLError) as exc:
        raise PackError("invalid_yaml", label) from exc
    if not isinstance(data, dict):
        raise PackError("mapping_required", label)
    return data


def _verified_yaml(
    bundle: Path,
    relative: str,
    inventory: Mapping[str, Mapping[str, Any]],
    *,
    label: str,
) -> dict[str, Any]:
    path = _contained(bundle, relative, label=label)
    _assert_no_symlink_chain(bundle, path, label=label)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise PackError("installed_bundle_drift", relative)
            with os.fdopen(descriptor, "rb", closefd=False) as handle:
                raw = handle.read()
        finally:
            os.close(descriptor)
    except PackError:
        raise
    except OSError as exc:
        raise PackError("installed_bundle_drift", relative) from exc
    record = inventory.get(relative)
    if (
        not isinstance(record, Mapping)
        or record.get("size") != len(raw)
        or not isinstance(record.get("sha256"), str)
        or not _SHA256_RE.fullmatch(str(record["sha256"]))
        or _sha256_bytes(raw) != record["sha256"]
    ):
        raise PackError("installed_bundle_drift", relative)
    return _yaml_from_bytes(raw, label=label)


def _verified_bundle(
    root: Path,
    pack_id: str,
    entry: Mapping[str, Any],
) -> tuple[Path, dict[str, Any], dict[str, Mapping[str, Any]]]:
    bundle = _contained(root, entry.get("installed_path"), label="installed pack")
    _assert_no_symlink_chain(root, bundle, label="installed pack")
    file_rows = [row.__dict__ for row in _pack_tree(bundle)]
    if file_rows != entry.get("files") or _sha256_json(file_rows) != entry.get(
        "tree_sha256"
    ):
        raise PackError("installed_bundle_drift", pack_id)
    manifest_path = bundle / "pack.yaml"
    manifest_raw = manifest_path.read_bytes()
    inventory: dict[str, Mapping[str, Any]] = {
        str(row["path"]): row for row in file_rows
    }
    if (
        not isinstance(entry.get("manifest_sha256"), str)
        or not _SHA256_RE.fullmatch(str(entry["manifest_sha256"]))
        or _sha256_bytes(manifest_raw) != entry["manifest_sha256"]
        or inventory.get("pack.yaml", {}).get("sha256")
        != entry["manifest_sha256"]
    ):
        raise PackError("installed_manifest_drift", pack_id)
    manifest = _yaml_from_bytes(
        manifest_raw, label=f"installed manifest:{pack_id}"
    )
    if manifest.get("id") != pack_id or manifest.get("version") != entry.get("version"):
        raise PackError("installed_manifest_identity_mismatch", pack_id)
    return bundle, manifest, inventory


def _event_kind_identifiers(
    bundle: Path,
    manifest: Mapping[str, Any],
    *,
    pack_id: str,
    inventory: Mapping[str, Mapping[str, Any]] | None = None,
) -> set[str]:
    temporal_relative = _safe_relative(
        (manifest.get("artifacts") or {}).get("temporal"),
        label=f"installed temporal:{pack_id}",
    )
    temporal = (
        _verified_yaml(
            bundle,
            temporal_relative,
            inventory,
            label=f"installed temporal:{pack_id}",
        )
        if inventory is not None
        else _load_yaml(
            _contained(bundle, temporal_relative, label=f"pack temporal:{pack_id}"),
            label=f"pack temporal:{pack_id}",
        )
    )
    adapters = temporal.get("adapters")
    if not isinstance(adapters, Mapping) or not adapters:
        raise PackError("temporal_adapters_required", pack_id)
    event_kinds: set[str] = set()
    for adapter_id, record in sorted(adapters.items()):
        event_kind = record.get("event_kind") if isinstance(record, Mapping) else None
        if (
            not isinstance(event_kind, str)
            or not event_kind.startswith(f"{pack_id}.")
            or not _CAPABILITY_RE.fullmatch(event_kind)
            or event_kind in event_kinds
        ):
            raise PackError("temporal_adapter_event_kind_invalid", str(adapter_id))
        event_kinds.add(event_kind)
    return event_kinds


def load_installed_pack_presentation(
    root: Path,
    pack_id: str,
    entry: Mapping[str, Any],
) -> dict[str, Any]:
    """Return one pack's verified locale -> canonical identifier label map."""

    bundle, manifest, inventory = _verified_bundle(root, pack_id, entry)
    capabilities = entry.get("capabilities")
    return _presentation_from_bundle(
        bundle,
        manifest,
        pack_id=pack_id,
        capabilities=capabilities,
        inventory=inventory,
    )


def _presentation_from_bundle(
    bundle: Path,
    manifest: Mapping[str, Any],
    *,
    pack_id: str,
    capabilities: Any,
    inventory: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    if not isinstance(capabilities, Mapping):
        raise PackError("invalid_lock_capabilities", pack_id)
    identifiers = {pack_id}
    for capability in (
        "page_types",
        "views",
        "commands",
        "operations",
        "temporal_profiles",
    ):
        values = capabilities.get(capability)
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise PackError("invalid_lock_capabilities", f"{pack_id}:{capability}")
        identifiers.update(values)
    identifiers.update(
        _event_kind_identifiers(
            bundle, manifest, pack_id=pack_id, inventory=inventory
        )
    )
    copy_key_by_identifier = {
        identifier: _copy_key(identifier, pack_id) for identifier in sorted(identifiers)
    }
    required_copy_keys = set(copy_key_by_identifier.values())

    i18n_contract = manifest.get("i18n")
    if not isinstance(i18n_contract, Mapping):
        raise PackError("i18n_contract_unknown_or_missing_field", pack_id)
    locales = i18n_contract.get("locales")
    if (
        not isinstance(locales, list)
        or not locales
        or any(not isinstance(locale, str) or not _LOCALE_RE.fullmatch(locale) for locale in locales)
        or len(set(locales)) != len(locales)
        or not PACK_PRESENTATION_REQUIRED_LOCALES.issubset(locales)
        or i18n_contract.get("default_locale") != PACK_PRESENTATION_DEFAULT_LOCALE
    ):
        raise PackError("pack_presentation_locale_contract_invalid", pack_id)
    i18n_relative = _safe_relative(
        (manifest.get("artifacts") or {}).get("i18n"),
        label=f"installed i18n:{pack_id}",
    )
    i18n_dir = _contained(bundle, i18n_relative, label=f"installed i18n:{pack_id}")

    localized: dict[str, dict[str, str]] = {}
    for locale in sorted(locales):
        catalog_relative = f"{i18n_relative}/{locale}.yaml"
        catalog = (
            _verified_yaml(
                bundle,
                catalog_relative,
                inventory,
                label=f"installed locale:{pack_id}:{locale}",
            )
            if inventory is not None
            else _load_yaml(
                _contained(
                    i18n_dir, f"{locale}.yaml", label=f"pack locale:{pack_id}"
                ),
                label=f"pack locale:{pack_id}:{locale}",
            )
        )
        if set(catalog) != {"schema_version", "locale", "pack", "copy"} or (
            catalog.get("schema_version") != PACK_I18N_SCHEMA_VERSION
            or catalog.get("locale") != locale
            or catalog.get("pack") != pack_id
            or not isinstance(catalog.get("copy"), Mapping)
        ):
            raise PackError("pack_presentation_catalog_invalid", f"{pack_id}:{locale}")
        copy = catalog["copy"]
        if set(copy) != required_copy_keys or any(
            not isinstance(key, str) or not _COPY_KEY_RE.fullmatch(key) for key in copy
        ):
            raise PackError("pack_presentation_catalog_key_mismatch", f"{pack_id}:{locale}")
        localized[locale] = {
            identifier: _plain_label(
                copy[copy_key], locale=locale, key=copy_key
            )
            for identifier, copy_key in copy_key_by_identifier.items()
        }
    reference_keys = set(localized[PACK_PRESENTATION_DEFAULT_LOCALE])
    if any(set(labels) != reference_keys for labels in localized.values()):
        raise PackError("pack_presentation_locale_parity_mismatch", pack_id)
    return {
        "default_locale": PACK_PRESENTATION_DEFAULT_LOCALE,
        "locales": localized,
    }


def validate_pack_presentation_source(
    pack_path: Path,
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate catalogs before lifecycle code performs any repository write."""

    pack_id = str(manifest.get("id") or "")
    return _presentation_from_bundle(
        pack_path,
        manifest,
        pack_id=pack_id,
        capabilities=manifest.get("capabilities"),
    )


__all__ = [
    "PACK_I18N_SCHEMA_VERSION",
    "PACK_PRESENTATION_DEFAULT_LOCALE",
    "PACK_PRESENTATION_REQUIRED_LOCALES",
    "load_installed_pack_presentation",
    "validate_pack_presentation_source",
]
