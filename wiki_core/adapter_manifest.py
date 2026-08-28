"""Deterministic identity contract for downstream-owned adapter files.

The public kit may attest that a consumer adopted one exact release, but the
consumer's local adapter identity must not be a self-asserted string.  This
module compiles and verifies a small tracked manifest whose hash is derived
from an ordered inventory of independently hashed adapter files.

The runtime config is deliberately excluded from the inventory because it
publishes the resulting hash and manifest path.  Including it would create a
hash cycle.  Memory, raw/derived state and secret-adjacent paths are excluded
because this is an operational identity boundary, not a publication vehicle.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping


ADAPTER_MANIFEST_SCHEMA_VERSION = "wiki_downstream_adapter_manifest.v1"
DEFAULT_ADAPTER_MANIFEST = "wiki.adapter-manifest.json"
MAX_ADAPTER_FILES = 256
MAX_ADAPTER_FILE_BYTES = 16 * 1024 * 1024
MAX_ADAPTER_TOTAL_BYTES = 64 * 1024 * 1024

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_SENSITIVE_NAME_RE = re.compile(
    r"(?:^|[._-])(?:secret|secrets|token|tokens|password|credentials?|cookie|session|private[-_]?key)(?:[._-]|$)"
)
_SENSITIVE_STEMS = {
    "authorization",
    "client_secret",
    "cookie",
    "credential",
    "credentials",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
    "password",
    "private_key",
    "secret",
    "secrets",
    "session",
    "token",
}
_BLOCKED_ROOTS = {
    ".git",
    ".wiki-viva",
    "data/raw",
    "data/derived",
    "memories",
    "memorias",
    "output",
    "private",
    "test-results",
}
_BLOCKED_SEGMENTS = {
    "__pycache__",
    ".playwright-cli",
    "coverage",
    "dist",
    "node_modules",
    "playwright-report",
    "test-results",
}


class AdapterManifestError(ValueError):
    """Fail-closed adapter-manifest error with a stable reason code."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_repo_path(value: Any, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
        or "\\" in value
        or value.startswith(("/", "./", "~"))
        or re.match(r"^[A-Za-z]:", value)
    ):
        raise AdapterManifestError("unsafe_path", label)
    raw_parts = value.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise AdapterManifestError("unsafe_path", label)
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise AdapterManifestError("unsafe_path", label)
    return path.as_posix()


def _sensitive_path(relative: str) -> bool:
    parts = [part.casefold() for part in relative.split("/")]
    prefix_one = parts[0]
    prefix_two = "/".join(parts[:2])
    if prefix_one in _BLOCKED_ROOTS or prefix_two in _BLOCKED_ROOTS:
        return True
    if any(part in _BLOCKED_SEGMENTS for part in parts):
        return True
    for part in parts:
        if part == ".env" or part.startswith(".env."):
            return True
        stem = part.lstrip(".").split(".", 1)[0]
        if stem in _SENSITIVE_STEMS or _SENSITIVE_NAME_RE.search(part):
            return True
    return False


def validate_adapter_path(
    value: Any, *, manifest_path: str = DEFAULT_ADAPTER_MANIFEST
) -> str:
    relative = _canonical_repo_path(value, label="adapter file")
    if relative == _canonical_repo_path(manifest_path, label="adapter manifest"):
        raise AdapterManifestError("self_reference", relative)
    if PurePosixPath(relative).name.casefold() == "wiki-cockpit.config.json":
        raise AdapterManifestError("runtime_config_cycle", relative)
    if _sensitive_path(relative):
        raise AdapterManifestError("blocked_adapter_path", relative)
    return relative


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )


def _require_tracked(root: Path, relative: str, *, label: str) -> None:
    tracked = _git(root, "ls-files", "--error-unmatch", "--", relative)
    if tracked.returncode != 0:
        raise AdapterManifestError("untracked", label)


def _require_clean(root: Path, relative: str, *, label: str) -> None:
    status = _git(root, "status", "--porcelain=v1", "--", relative)
    if status.returncode != 0 or status.stdout.strip():
        raise AdapterManifestError("not_clean", label)


def _safe_file_bytes(root: Path, relative: str, *, label: str) -> bytes:
    root = root.resolve(strict=True)
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        try:
            state = current.lstat()
        except OSError as exc:
            raise AdapterManifestError("missing_file", label) from exc
        if stat.S_ISLNK(state.st_mode):
            raise AdapterManifestError("symlink", label)
        if current != root / relative and not stat.S_ISDIR(state.st_mode):
            raise AdapterManifestError("unsafe_ancestor", label)
    state = current.lstat()
    if not stat.S_ISREG(state.st_mode):
        raise AdapterManifestError("not_regular", label)
    if state.st_nlink != 1:
        raise AdapterManifestError("hardlink", label)
    if state.st_size > MAX_ADAPTER_FILE_BYTES:
        raise AdapterManifestError("file_too_large", label)
    try:
        current.resolve(strict=True).relative_to(root)
    except (OSError, ValueError) as exc:
        raise AdapterManifestError("escaped_root", label) from exc
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(current, flags)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise AdapterManifestError("unsafe_file", label)
        payload = b""
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_ADAPTER_FILE_BYTES:
                raise AdapterManifestError("file_too_large", label)
            chunks.append(chunk)
        payload = b"".join(chunks)
        return payload
    finally:
        os.close(descriptor)


def _file_record(
    root: Path,
    relative: str,
    *,
    require_tracked: bool,
    require_clean: bool,
) -> dict[str, Any]:
    if require_tracked:
        _require_tracked(root, relative, label=relative)
    if require_clean:
        _require_clean(root, relative, label=relative)
    raw = _safe_file_bytes(root, relative, label=relative)
    return {"path": relative, "sha256": _sha256_bytes(raw), "bytes": len(raw)}


def adapter_semantic_payload(files: list[dict[str, Any]]) -> dict[str, Any]:
    return {"schema_version": ADAPTER_MANIFEST_SCHEMA_VERSION, "files": files}


def adapter_sha256(files: list[dict[str, Any]]) -> str:
    return _sha256_bytes(
        canonical_json(adapter_semantic_payload(files)).encode("utf-8")
    )


def build_adapter_manifest(
    root: Path,
    files: Iterable[str],
    *,
    manifest_path: str = DEFAULT_ADAPTER_MANIFEST,
    require_tracked: bool = True,
) -> dict[str, Any]:
    root = root.resolve(strict=True)
    manifest_relative = _canonical_repo_path(manifest_path, label="adapter manifest")
    if manifest_relative != DEFAULT_ADAPTER_MANIFEST:
        raise AdapterManifestError("manifest_location", DEFAULT_ADAPTER_MANIFEST)
    normalized = [
        validate_adapter_path(value, manifest_path=manifest_relative) for value in files
    ]
    if not normalized:
        raise AdapterManifestError(
            "empty_manifest", "at least one adapter file is required"
        )
    if len(normalized) > MAX_ADAPTER_FILES:
        raise AdapterManifestError("too_many_files", str(len(normalized)))
    if len(normalized) != len(set(normalized)):
        raise AdapterManifestError("duplicate_path")
    ordered = sorted(normalized)
    records = [
        _file_record(
            root,
            relative,
            require_tracked=require_tracked,
            require_clean=False,
        )
        for relative in ordered
    ]
    if sum(record["bytes"] for record in records) > MAX_ADAPTER_TOTAL_BYTES:
        raise AdapterManifestError("manifest_too_large")
    return {
        **adapter_semantic_payload(records),
        "adapter_sha256": adapter_sha256(records),
    }


def _validate_manifest_shape(payload: Any) -> tuple[list[dict[str, Any]], str]:
    if not isinstance(payload, Mapping) or set(payload) != {
        "schema_version",
        "files",
        "adapter_sha256",
    }:
        raise AdapterManifestError("manifest_shape")
    if payload.get("schema_version") != ADAPTER_MANIFEST_SCHEMA_VERSION:
        raise AdapterManifestError("schema_version")
    files = payload.get("files")
    if not isinstance(files, list) or not files or len(files) > MAX_ADAPTER_FILES:
        raise AdapterManifestError("file_inventory")
    normalized: list[dict[str, Any]] = []
    for index, record in enumerate(files):
        if not isinstance(record, Mapping) or set(record) != {
            "path",
            "sha256",
            "bytes",
        }:
            raise AdapterManifestError("file_record_shape", str(index))
        relative = validate_adapter_path(record.get("path"))
        digest = str(record.get("sha256") or "")
        size = record.get("bytes")
        if not _SHA256_RE.fullmatch(digest):
            raise AdapterManifestError("file_hash", relative)
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise AdapterManifestError("file_size", relative)
        normalized.append({"path": relative, "sha256": digest, "bytes": size})
    if normalized != sorted(normalized, key=lambda item: item["path"]):
        raise AdapterManifestError("noncanonical_order")
    if len({record["path"] for record in normalized}) != len(normalized):
        raise AdapterManifestError("duplicate_path")
    digest = str(payload.get("adapter_sha256") or "")
    if not _SHA256_RE.fullmatch(digest) or digest != adapter_sha256(normalized):
        raise AdapterManifestError("adapter_hash")
    return normalized, digest


def load_and_verify_adapter_manifest(
    root: Path,
    *,
    manifest_path: str = DEFAULT_ADAPTER_MANIFEST,
    expected_hash: str | None = None,
    require_tracked: bool = True,
) -> dict[str, Any]:
    root = root.resolve(strict=True)
    manifest_relative = _canonical_repo_path(manifest_path, label="adapter manifest")
    if manifest_relative != DEFAULT_ADAPTER_MANIFEST:
        raise AdapterManifestError("manifest_location", DEFAULT_ADAPTER_MANIFEST)
    if require_tracked:
        _require_tracked(root, manifest_relative, label="adapter manifest")
        _require_clean(root, manifest_relative, label="adapter manifest")
    raw = _safe_file_bytes(root, manifest_relative, label="adapter manifest")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdapterManifestError("invalid_json") from exc
    records, digest = _validate_manifest_shape(payload)
    actual = [
        _file_record(
            root,
            record["path"],
            require_tracked=require_tracked,
            require_clean=require_tracked,
        )
        for record in records
    ]
    if actual != records:
        raise AdapterManifestError("stale_file_inventory")
    if expected_hash is not None and str(expected_hash).lower() != digest:
        raise AdapterManifestError("expected_hash_mismatch")
    return {
        "schema_version": ADAPTER_MANIFEST_SCHEMA_VERSION,
        "manifest": manifest_relative,
        "adapter_sha256": digest,
        "file_count": len(records),
        "files": records,
    }


def serialize_adapter_manifest(payload: Mapping[str, Any]) -> str:
    _validate_manifest_shape(payload)
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


__all__ = [
    "ADAPTER_MANIFEST_SCHEMA_VERSION",
    "AdapterManifestError",
    "DEFAULT_ADAPTER_MANIFEST",
    "adapter_sha256",
    "build_adapter_manifest",
    "canonical_json",
    "load_and_verify_adapter_manifest",
    "serialize_adapter_manifest",
    "validate_adapter_path",
]
