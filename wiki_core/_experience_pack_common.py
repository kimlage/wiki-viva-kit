"""Shared contracts and safe primitives for declarative experience packs."""

from __future__ import annotations

import hashlib
import json
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

PACK_SCHEMA_VERSION = "wiki_experience_pack.v1"
REGISTRY_SCHEMA_VERSION = "wiki_experience_pack_registry.v1"
LOCK_SCHEMA_VERSION = "wiki_experience_pack_lock.v1"
RECEIPT_SCHEMA_VERSION = "wiki_experience_pack_receipt.v2"
COMPOSITION_SCHEMA_VERSION = "wiki_experience_pack_composition.v1"
ASSET_SCHEMA_VERSION = "wiki_experience_pack_assets.v1"
MIGRATION_SCHEMA_VERSION = "wiki_experience_pack_migration.v1"
VIEWS_SCHEMA_VERSION = "wiki_experience_pack_views.v1"
COMMANDS_SCHEMA_VERSION = "wiki_experience_pack_commands.v1"
OPERATIONS_SCHEMA_VERSION = "wiki_experience_pack_operations.v1"
TEMPORAL_PROFILES_SCHEMA_VERSION = "wiki_experience_pack_temporal_profiles.v2"
CORE_VERSION = "8.0.0"

DEFAULT_REGISTRY = Path("packs/registry.yaml")
DEFAULT_LOCK = Path("wiki.packs.lock.yaml")
STATE_ROOT = Path(".wiki-viva")
INSTALLED_ROOT = STATE_ROOT / "packs"
RECEIPT_ROOT = STATE_ROOT / "pack-receipts"
OPERATION_LOCK = STATE_ROOT / "pack-operation.lock"

_ID_RE = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
_CAPABILITY_RE = re.compile(r"[a-z][a-z0-9_.-]*")
_SEMVER_RE = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_BRANCH_RE = re.compile(r"wiki/[A-Za-z0-9._/-]+")

_CAPABILITY_KEYS = (
    "page_types",
    "blocks",
    "block_packages",
    "views",
    "commands",
    "operations",
    "temporal_profiles",
)
_SLOT_KEYS = ("views", "commands", "operations", "timelines")
_ARTIFACT_KEYS = (
    "page_types",
    "templates",
    "blocks",
    "views",
    "commands",
    "operations",
    "temporal",
    "i18n",
)
_KNOWN_MANIFEST_KEYS = {
    "schema_version",
    "id",
    "name",
    "description",
    "version",
    "license",
    "compatible_core",
    "capabilities",
    "dependencies",
    "conflicts",
    "privacy",
    "assets",
    "fixtures",
    "tests",
    "migrations",
    "artifacts",
    "slots",
    "i18n",
}
_TEXT_EXTENSIONS = {
    ".yaml",
    ".yml",
    ".json",
    ".md",
    ".txt",
    ".svg",
}
_BINARY_ASSET_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".woff2"}
_FORBIDDEN_EXECUTABLE_EXTENSIONS = {
    ".py",
    ".pyc",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".jsx",
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
    ".exe",
    ".dll",
    ".dylib",
    ".so",
    ".jar",
    ".wasm",
}
_MAX_PACK_FILES = 2_000
_MAX_PACK_BYTES = 32 * 1024 * 1024
_MAX_ASSET_BYTES = 8 * 1024 * 1024


class PackError(ValueError):
    """A fail-closed error whose code and detail are safe for public logs."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


@dataclass(frozen=True)
class PackFile:
    path: str
    sha256: str
    size: int


@dataclass(frozen=True)
class PackSource:
    pack_id: str
    version: str
    path: Path
    registry_path: str
    manifest: dict[str, Any]
    manifest_sha256: str
    tree_sha256: str
    files: tuple[PackFile, ...]


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(canonical_json(value).encode("utf-8"))


def _yaml_text(value: Any) -> str:
    return yaml.safe_dump(value, sort_keys=True, allow_unicode=True)


def _safe_relative(value: Any, *, label: str, allow_directory: bool = True) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise PackError("unsafe_path", label)
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise PackError("unsafe_path", label)
    if not allow_directory and value.endswith("/"):
        raise PackError("unsafe_path", label)
    return path.as_posix()


def _contained(root: Path, relative: str, *, label: str) -> Path:
    safe = _safe_relative(relative, label=label)
    root_resolved = root.resolve()
    candidate = root / safe
    try:
        candidate.resolve(strict=False).relative_to(root_resolved)
    except ValueError as exc:
        raise PackError("unsafe_path", label) from exc
    return candidate


def _assert_no_symlink_chain(root: Path, path: Path, *, label: str) -> None:
    """Reject symlinks in every existing component below ``root``."""

    root = root.resolve()
    candidate = path if path.is_absolute() else root / path
    try:
        relative = candidate.absolute().relative_to(root)
    except ValueError as exc:
        raise PackError("unsafe_path", label) from exc
    current = root
    for part in relative.parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise PackError("symlink_blocked", label)
    try:
        candidate.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise PackError("unsafe_path", label) from exc


def _load_yaml(path: Path, *, label: str) -> dict[str, Any]:
    _assert_no_symlink_chain(path.parent.resolve(), path, label=label)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise PackError("invalid_yaml", label) from exc
    if not isinstance(data, dict):
        raise PackError("mapping_required", label)
    return data


def _semver(value: Any, *, label: str) -> tuple[int, int, int]:
    text = str(value or "")
    match = _SEMVER_RE.fullmatch(text)
    if not match:
        raise PackError("invalid_semver", label)
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def version_satisfies(version: str, constraint: str) -> bool:
    """Evaluate the deliberately small, deterministic semver range vocabulary."""

    current = _semver(version, label="version")
    tokens = str(constraint or "").split()
    if not tokens:
        raise PackError("invalid_version_constraint", "empty")
    for token in tokens:
        match = re.fullmatch(r"(>=|<=|>|<|==|=)?(\d+)(?:\.(\d+))?(?:\.(\d+))?", token)
        if not match:
            raise PackError("invalid_version_constraint", "unsupported")
        operator = match.group(1) or "="
        parts = [
            int(match.group(2)),
            int(match.group(3) or 0),
            int(match.group(4) or 0),
        ]
        expected = tuple(parts)
        if operator == ">=" and not current >= expected:
            return False
        if operator == "<=" and not current <= expected:
            return False
        if operator == ">" and not current > expected:
            return False
        if operator == "<" and not current < expected:
            return False
        if operator in {"=", "=="} and not current == expected:
            return False
    return True


def _normalize_list(value: Any, *, label: str) -> list[str]:
    if not isinstance(value, list):
        raise PackError("list_required", label)
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not _CAPABILITY_RE.fullmatch(item):
            raise PackError("invalid_identifier", label)
        if item in result:
            raise PackError("duplicate_identifier", label)
        result.append(item)
    return result
