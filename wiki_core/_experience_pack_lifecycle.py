"""Review-branch lifecycle and bounded filesystem mutation for packs."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

try:  # POSIX is the supported mutation surface; absence must fail closed.
    import fcntl
except ImportError:  # pragma: no cover - exercised only on unsupported hosts
    fcntl = None  # type: ignore[assignment]

import yaml

from wiki_core._experience_pack_common import (
    CORE_VERSION,
    DEFAULT_LOCK,
    INSTALLED_ROOT,
    LOCK_SCHEMA_VERSION,
    OPERATION_LOCK,
    RECEIPT_ROOT,
    RECEIPT_SCHEMA_VERSION,
    STATE_ROOT,
    _BRANCH_RE,
    _ID_RE,
    _SLOT_KEYS,
    PackError,
    PackSource,
    _assert_no_symlink_chain,
    _contained,
    _semver,
    _sha256_bytes,
    _sha256_json,
    _yaml_text,
    version_satisfies,
)
from wiki_core._experience_pack_state import (
    _active_entries,
    _assert_composable,
    _entry_for,
    compose_active_packs,
    load_lock,
)
from wiki_core._experience_pack_validation import (
    _load_migration,
    resolve_pack,
    validate_manifest,
)


def _receipt(
    *,
    action: str,
    pack_id: str,
    version: str,
    previous_lock: dict[str, Any],
    next_lock: dict[str, Any],
    changes: list[dict[str, str]],
    branch: str | None,
) -> dict[str, Any]:
    next_lock_projection = _receipt_lock_projection(next_lock)
    identity = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "action": action,
        "pack": pack_id,
        "version": version,
        "previous_lock_sha256": _sha256_json(previous_lock),
        # The projection deliberately removes every receipt chain. This makes
        # the next-state binding non-recursive while retaining every semantic
        # pack, capability, version, status, path and pinned file hash.
        "next_lock_projection": next_lock_projection,
        "next_lock_sha256": _sha256_json(next_lock_projection),
        "review_branch": branch or "not_recorded",
        "mutation_scope": [
            INSTALLED_ROOT.as_posix(),
            RECEIPT_ROOT.as_posix(),
            DEFAULT_LOCK.as_posix(),
        ],
        "data_preservation": "user_content_untouched",
        "privacy_gate": "core_secret_and_public_pii_rules_preserved",
        "changes": sorted(changes, key=lambda row: (row["action"], row["path"])),
    }
    return {
        "receipt_id": f"sha256:{_sha256_json(identity)}",
        **identity,
    }


def _receipt_lock_projection(lock: dict[str, Any]) -> dict[str, Any]:
    """Return the canonical non-recursive next-lock receipt projection."""

    packs = lock.get("packs")
    if not isinstance(packs, dict):
        raise PackError("invalid_next_lock_projection")
    projected_packs: dict[str, Any] = {}
    for pack_id, entry in sorted(packs.items()):
        if not isinstance(pack_id, str) or not isinstance(entry, dict):
            raise PackError("invalid_next_lock_projection")
        projected_packs[pack_id] = {
            key: value for key, value in entry.items() if key != "receipts"
        }
    return {
        "schema_version": lock.get("schema_version"),
        "core_version": lock.get("core_version"),
        "packs": projected_packs,
    }


def _plan_response(receipt: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    return {
        "schema_version": "wiki_experience_pack_plan.v1",
        "status": "dry_run" if dry_run else "applied",
        "receipt": receipt,
        "conceptual_diff": receipt["changes"],
        "review_checklist": [
            "inspect declared capabilities, privacy and asset permissions",
            "review the conceptual diff and pinned lock entry",
            "run wiki_pack.py validate and both wiki audit boundaries",
            "open a human-gated PR from the checked-out wiki branch",
        ],
        "next_step": "review diff and open a human-gated PR",
    }


def _git_branch(root: Path) -> str | None:
    if not (root / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        raise PackError("git_branch_unavailable")
    branch = result.stdout.strip()
    return branch or None


def assert_review_branch(root: Path, requested_branch: str | None = None) -> str | None:
    if requested_branch is not None and not _BRANCH_RE.fullmatch(requested_branch):
        raise PackError("invalid_review_branch")
    current = _git_branch(root)
    if current is None:
        return requested_branch
    if current in {"main", "master"} or not current.startswith("wiki/"):
        raise PackError("protected_or_nonreview_branch")
    if requested_branch is not None and current != requested_branch:
        raise PackError("review_branch_not_checked_out")
    return current


def _dry_run_branch(root: Path, requested_branch: str | None) -> str | None:
    """Return a safe receipt label without blocking a read-only dry-run."""

    if requested_branch is not None and not _BRANCH_RE.fullmatch(requested_branch):
        raise PackError("invalid_review_branch")
    current = _git_branch(root)
    if requested_branch is not None:
        return requested_branch
    return current if current and current.startswith("wiki/") else None


def _lock_with_entry(
    lock: dict[str, Any], pack_id: str, entry: dict[str, Any] | None
) -> dict[str, Any]:
    packs = {key: value for key, value in lock["packs"].items() if key != pack_id}
    if entry is not None:
        packs[pack_id] = entry
    return {
        "schema_version": LOCK_SCHEMA_VERSION,
        "core_version": CORE_VERSION,
        "packs": dict(sorted(packs.items())),
    }


def _receipt_relative(receipt: dict[str, Any]) -> str:
    digest = str(receipt["receipt_id"]).removeprefix("sha256:")
    return (
        RECEIPT_ROOT / receipt["pack"] / f"{receipt['action']}-{digest}.json"
    ).as_posix()


@contextmanager
def _operation_guard(root: Path, *, enabled: bool = True):
    """Serialize cooperating pack mutations across agents and processes."""

    if not enabled:
        yield
        return
    if fcntl is None:
        raise PackError("pack_operation_lock_unavailable")
    state = root / STATE_ROOT
    _assert_no_symlink_chain(root, state, label="pack state")
    state.mkdir(parents=True, exist_ok=True)
    path = root / OPERATION_LOCK
    _assert_no_symlink_chain(root, path, label="pack operation lock")
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise PackError("pack_operation_lock_unavailable") from exc
    with os.fdopen(descriptor, "a+b") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _atomic_write_lock(
    root: Path,
    lock: dict[str, Any],
    *,
    expected_lock: dict[str, Any] | None = None,
) -> None:
    path = root / DEFAULT_LOCK
    _assert_no_symlink_chain(root, path, label="pack lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = _yaml_text(lock).encode("utf-8")
    fd, temporary_name = tempfile.mkstemp(prefix=".wiki-packs-lock-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        if path.is_symlink():
            raise PackError("symlink_blocked", "pack lock")
        if expected_lock is not None and load_lock(root) != expected_lock:
            raise PackError("pack_lock_changed_during_operation")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _copy_bundle(root: Path, source: PackSource) -> Path:
    state = root / STATE_ROOT
    _assert_no_symlink_chain(root, state, label="pack state")
    state.mkdir(parents=True, exist_ok=True)
    parent = root / INSTALLED_ROOT / source.pack_id
    _assert_no_symlink_chain(root, parent, label="installed pack")
    parent.mkdir(parents=True, exist_ok=True)
    final = parent / source.version
    if final.exists() or final.is_symlink():
        raise PackError("installed_bundle_already_exists", source.pack_id)
    stage = Path(tempfile.mkdtemp(prefix=f".{source.pack_id}-", dir=state))
    try:
        for record in source.files:
            src = source.path / record.path
            raw = src.read_bytes()
            if _sha256_bytes(raw) != record.sha256:
                raise PackError("pack_changed_during_install", record.path)
            target = stage / record.path
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as handle:
                handle.write(raw)
        os.replace(stage, final)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return final


def _bundle_matches_at(base: Path, entry: dict[str, Any]) -> bool:
    if not base.is_dir() or base.is_symlink():
        return False
    expected = {
        row["path"]: (row["sha256"], row["size"])
        for row in entry["files"]
        if isinstance(row, dict)
    }
    actual_paths = [
        path for path in base.rglob("*") if path.is_file() or path.is_symlink()
    ]
    if any(path.is_symlink() for path in actual_paths):
        return False
    if {path.relative_to(base).as_posix() for path in actual_paths} != set(expected):
        return False
    for relative, (digest, size) in expected.items():
        raw = (base / relative).read_bytes()
        if len(raw) != size or _sha256_bytes(raw) != digest:
            return False
    return True


def _installed_matches(root: Path, entry: dict[str, Any]) -> bool:
    base = _contained(root, entry["installed_path"], label="installed bundle")
    return _bundle_matches_at(base, entry)


def _entry_file_inventory(entry: dict[str, Any]) -> dict[str, tuple[str, int]]:
    return {
        str(row["path"]): (str(row["sha256"]), int(row["size"]))
        for row in entry.get("files") or []
        if isinstance(row, dict)
    }


def _same_inode(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _walk_open_bundle(
    directory_fd: int,
    expected: dict[str, tuple[str, int]],
    *,
    prefix: str = "",
    delete: bool = False,
) -> set[str]:
    """Verify, then optionally remove, one already-open directory tree.

    Every file is opened with ``O_NOFOLLOW`` and compared with the lock
    inventory immediately before unlink. Directory names are inode-checked
    before ``rmdir``. A pathname replacement can therefore make cleanup stop,
    but it cannot redirect cleanup into replacement content.
    """

    seen: set[str] = set()
    entries = sorted(os.scandir(directory_fd), key=lambda entry: entry.name)
    for entry in entries:
        name = entry.name
        if name in {"", ".", ".."} or "/" in name or "\\" in name:
            raise PackError("owned_bundle_cleanup_identity_mismatch", name)
        relative = f"{prefix}/{name}" if prefix else name
        metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if stat.S_ISDIR(metadata.st_mode):
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(
                os, "O_NOFOLLOW", 0
            )
            child_fd = os.open(name, flags, dir_fd=directory_fd)
            try:
                opened = os.fstat(child_fd)
                if not _same_inode(metadata, opened):
                    raise PackError(
                        "owned_bundle_cleanup_identity_mismatch", relative
                    )
                seen.update(
                    _walk_open_bundle(
                        child_fd,
                        expected,
                        prefix=relative,
                        delete=delete,
                    )
                )
                if delete:
                    current = os.stat(
                        name, dir_fd=directory_fd, follow_symlinks=False
                    )
                    if not _same_inode(opened, current):
                        raise PackError(
                            "owned_bundle_cleanup_identity_mismatch", relative
                        )
                    os.rmdir(name, dir_fd=directory_fd)
            finally:
                os.close(child_fd)
            continue
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise PackError("owned_bundle_cleanup_identity_mismatch", relative)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        file_fd = os.open(name, flags, dir_fd=directory_fd)
        try:
            opened = os.fstat(file_fd)
            if not _same_inode(metadata, opened) or opened.st_nlink != 1:
                raise PackError("owned_bundle_cleanup_identity_mismatch", relative)
            with os.fdopen(os.dup(file_fd), "rb") as handle:
                raw = handle.read()
            record = expected.get(relative)
            if (
                record is None
                or len(raw) != record[1]
                or _sha256_bytes(raw) != record[0]
            ):
                raise PackError("owned_bundle_cleanup_identity_mismatch", relative)
            seen.add(relative)
            if delete:
                current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                if not _same_inode(opened, current):
                    raise PackError(
                        "owned_bundle_cleanup_identity_mismatch", relative
                    )
                os.unlink(name, dir_fd=directory_fd)
        finally:
            os.close(file_fd)
    return seen


def _secure_delete_quarantined_bundle(
    quarantine: Path,
    entry: dict[str, Any],
) -> None:
    expected = _entry_file_inventory(entry)
    if os.name == "nt":  # pragma: no cover - Windows rename locks block swaps
        if not _bundle_matches_at(quarantine, entry):
            raise PackError("owned_bundle_cleanup_identity_mismatch")
        shutil.rmtree(quarantine)
        return
    parent_fd = os.open(
        quarantine.parent,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    bundle_fd: int | None = None
    try:
        initial = os.stat(
            quarantine.name, dir_fd=parent_fd, follow_symlinks=False
        )
        bundle_fd = os.open(
            quarantine.name,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_fd,
        )
        opened = os.fstat(bundle_fd)
        if not stat.S_ISDIR(opened.st_mode) or not _same_inode(initial, opened):
            raise PackError("owned_bundle_cleanup_identity_mismatch")
        if _walk_open_bundle(bundle_fd, expected) != set(expected):
            raise PackError("owned_bundle_cleanup_identity_mismatch")
        if _walk_open_bundle(bundle_fd, expected, delete=True) != set(expected):
            raise PackError("owned_bundle_cleanup_identity_mismatch")
        current = os.stat(
            quarantine.name, dir_fd=parent_fd, follow_symlinks=False
        )
        if not _same_inode(opened, current):
            raise PackError("owned_bundle_cleanup_identity_mismatch")
        os.rmdir(quarantine.name, dir_fd=parent_fd)
    finally:
        if bundle_fd is not None:
            os.close(bundle_fd)
        os.close(parent_fd)


def _quarantine_and_delete_owned_bundle(
    root: Path,
    entry: dict[str, Any],
) -> None:
    original = _contained(root, entry["installed_path"], label="installed bundle")
    if not _bundle_matches_at(original, entry):
        raise PackError("installed_bundle_drift", str(entry.get("installed_path")))
    quarantine_root = root / STATE_ROOT / "pack-delete-quarantine"
    _assert_no_symlink_chain(root, quarantine_root, label="pack delete quarantine")
    quarantine_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    container = Path(
        tempfile.mkdtemp(prefix=".owned-bundle-", dir=quarantine_root)
    )
    os.chmod(container, 0o700)
    quarantine = container / "bundle"
    try:
        # Destination is inside a freshly-created mode-0700 directory, so it
        # cannot pre-exist and rename cannot replace a caller-controlled path.
        os.rename(original, quarantine)
        if not _bundle_matches_at(quarantine, entry):
            if not original.exists() and quarantine.exists():
                os.rename(quarantine, original)
            raise PackError("owned_bundle_changed_before_quarantine")
        try:
            _secure_delete_quarantined_bundle(quarantine, entry)
            if original.exists() or original.is_symlink():
                raise PackError(
                    "owned_bundle_path_reoccupied",
                    str(entry.get("installed_path") or "installed bundle"),
                )
        except Exception:
            # A pre-delete failure can be rolled back byte-for-byte. If a
            # hostile writer has occupied the original name, preserve both
            # trees and fail without deleting the replacement.
            if (
                quarantine.exists()
                and _bundle_matches_at(quarantine, entry)
                and not original.exists()
            ):
                os.rename(quarantine, original)
            raise
    finally:
        try:
            container.rmdir()
        except OSError:
            pass


_RECEIPT_ID_RE = re.compile(r"sha256:[0-9a-f]{64}")
_DIGEST_RE = re.compile(r"[0-9a-f]{64}")
_RECEIPT_FILENAME_RE = re.compile(
    r"(install|upgrade|disable|remove)-([0-9a-f]{64})\.json"
)
_RECEIPT_IDENTITY_FIELDS = {
    "schema_version",
    "action",
    "pack",
    "version",
    "previous_lock_sha256",
    "next_lock_projection",
    "next_lock_sha256",
    "review_branch",
    "mutation_scope",
    "data_preservation",
    "privacy_gate",
    "changes",
}

_LOCK_PROJECTION_ENTRY_FIELDS = {
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
}


def _receipt_projection_valid(payload: dict[str, Any]) -> bool:
    projection = payload.get("next_lock_projection")
    if (
        not isinstance(projection, dict)
        or set(projection) != {"schema_version", "core_version", "packs"}
        or projection.get("schema_version") != LOCK_SCHEMA_VERSION
        or projection.get("core_version") != CORE_VERSION
        or not isinstance(projection.get("packs"), dict)
        or payload.get("next_lock_sha256") != _sha256_json(projection)
    ):
        return False
    packs = projection["packs"]
    for projected_pack_id, entry in packs.items():
        if (
            not isinstance(projected_pack_id, str)
            or not _ID_RE.fullmatch(projected_pack_id)
            or not isinstance(entry, dict)
            or set(entry) != _LOCK_PROJECTION_ENTRY_FIELDS
        ):
            return False
    target = packs.get(payload.get("pack"))
    if payload.get("action") == "remove":
        return target is None
    if not isinstance(target, dict) or target.get("version") != payload.get("version"):
        return False
    if payload.get("action") == "disable" and target.get("status") != "disabled":
        return False
    return True


def _receipt_matches(
    root: Path,
    pack_id: str,
    receipt_id: str,
    *,
    expected_entry: dict[str, Any] | None = None,
) -> bool:
    if not _RECEIPT_ID_RE.fullmatch(receipt_id):
        return False
    digest = receipt_id.removeprefix("sha256:")
    directory = root / RECEIPT_ROOT / pack_id
    try:
        _assert_no_symlink_chain(root, directory, label="pack receipt directory")
    except PackError:
        return False
    if not directory.is_dir() or directory.is_symlink():
        return False
    candidates = sorted(directory.glob(f"*-{digest}.json"))
    if len(candidates) != 1 or candidates[0].is_symlink():
        return False
    try:
        payload = json.loads(candidates[0].read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict) or set(payload) != {
        "receipt_id",
        *_RECEIPT_IDENTITY_FIELDS,
    }:
        return False
    if (
        payload.get("receipt_id") != receipt_id
        or payload.get("schema_version") != RECEIPT_SCHEMA_VERSION
        or payload.get("pack") != pack_id
        or payload.get("action") not in {"install", "upgrade", "disable", "remove"}
        or not _DIGEST_RE.fullmatch(str(payload.get("previous_lock_sha256") or ""))
        or not _DIGEST_RE.fullmatch(str(payload.get("next_lock_sha256") or ""))
    ):
        return False
    if candidates[0].name != f"{payload['action']}-{digest}.json":
        return False
    identity = {field: payload[field] for field in _RECEIPT_IDENTITY_FIELDS}
    if (
        receipt_id != f"sha256:{_sha256_json(identity)}"
        or not _receipt_projection_valid(payload)
    ):
        return False
    if expected_entry is not None:
        projected_entry = payload["next_lock_projection"]["packs"].get(pack_id)
        expected_projection = {
            key: value for key, value in expected_entry.items() if key != "receipts"
        }
        if projected_entry != expected_projection:
            return False
    return True


def _receipt_inventory_errors(root: Path) -> list[dict[str, str]]:
    directory = root / RECEIPT_ROOT
    if not directory.exists() and not directory.is_symlink():
        return []
    try:
        _assert_no_symlink_chain(root, directory, label="pack receipt directory")
    except PackError:
        return [{"code": "installed_receipt_invalid", "pack": "state"}]
    if not directory.is_dir() or directory.is_symlink():
        return [{"code": "installed_receipt_invalid", "pack": "state"}]
    errors: list[dict[str, str]] = []
    for pack_directory in sorted(directory.iterdir(), key=lambda path: path.name):
        pack_id = pack_directory.name
        if (
            not _ID_RE.fullmatch(pack_id)
            or not pack_directory.is_dir()
            or pack_directory.is_symlink()
        ):
            errors.append({"code": "installed_receipt_invalid", "pack": "state"})
            continue
        for path in sorted(pack_directory.iterdir(), key=lambda item: item.name):
            match = _RECEIPT_FILENAME_RE.fullmatch(path.name)
            if (
                match is None
                or not path.is_file()
                or path.is_symlink()
                or not _receipt_matches(root, pack_id, f"sha256:{match.group(2)}")
            ):
                errors.append({"code": "installed_receipt_invalid", "pack": pack_id})
    return errors


def _installed_entry_errors(
    root: Path,
    pack_id: str,
    entry: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    if not _installed_matches(root, entry):
        return ["installed_bundle_drift"]
    if _sha256_json(entry["files"]) != entry.get("tree_sha256"):
        errors.append("installed_tree_lock_mismatch")
    base = _contained(root, entry["installed_path"], label="installed bundle")
    inventory = {
        str(row.get("path") or ""): row
        for row in entry.get("files") or []
        if isinstance(row, dict)
    }
    manifest_record = inventory.get("pack.yaml")
    try:
        manifest_raw = (base / "pack.yaml").read_bytes()
    except OSError:
        errors.append("installed_manifest_unreadable")
        manifest_raw = b""
    if (
        not isinstance(manifest_record, dict)
        or _sha256_bytes(manifest_raw) != entry.get("manifest_sha256")
        or len(manifest_raw) != manifest_record.get("size")
        or _sha256_bytes(manifest_raw) != manifest_record.get("sha256")
    ):
        errors.append("installed_manifest_hash_mismatch")
    try:
        manifest = yaml.safe_load(manifest_raw.decode("utf-8"))
    except (UnicodeError, yaml.YAMLError):
        manifest = None
    if not isinstance(manifest, dict):
        errors.append("installed_manifest_invalid")
    else:
        if manifest.get("id") != pack_id or manifest.get("version") != entry.get(
            "version"
        ):
            errors.append("installed_manifest_identity_mismatch")
        if any(
            manifest.get(field) != entry.get(field)
            for field in ("capabilities", "slots", "dependencies", "conflicts")
        ):
            errors.append("installed_manifest_lock_mismatch")
        try:
            validate_manifest(root, base, manifest)
        except PackError:
            errors.append("installed_manifest_contract_invalid")
    receipt_ids = entry.get("receipts") or []
    if any(
        not _receipt_matches(
            root,
            pack_id,
            str(receipt_id),
            expected_entry=entry if index == len(receipt_ids) - 1 else None,
        )
        for index, receipt_id in enumerate(receipt_ids)
    ):
        errors.append("installed_receipt_invalid")
    if not entry.get("receipts"):
        errors.append("installed_receipt_missing")
    return list(dict.fromkeys(errors))


def _installed_bundle_inventory(root: Path) -> tuple[set[str], list[str]]:
    base = root / INSTALLED_ROOT
    if not base.exists():
        return set(), []
    try:
        _assert_no_symlink_chain(root, base, label="installed packs")
    except PackError:
        return set(), ["installed_state_symlink"]
    if not base.is_dir() or base.is_symlink():
        return set(), ["installed_state_invalid"]
    bundles: set[str] = set()
    errors: list[str] = []
    for pack_dir in sorted(base.iterdir()):
        if pack_dir.is_symlink() or not pack_dir.is_dir():
            errors.append("installed_state_invalid")
            continue
        for version_dir in sorted(pack_dir.iterdir()):
            if version_dir.is_symlink() or not version_dir.is_dir():
                errors.append("installed_state_invalid")
                continue
            bundles.add(version_dir.relative_to(root).as_posix())
    return bundles, list(dict.fromkeys(errors))


def _write_receipt(root: Path, receipt: dict[str, Any]) -> Path:
    relative = _receipt_relative(receipt)
    path = _contained(root, relative, label="pack receipt")
    _assert_no_symlink_chain(root, path, label="pack receipt")
    raw = (
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise PackError("receipt_already_exists") from exc
    return path


def _install_plan(
    root: Path,
    source: PackSource,
    *,
    action: str,
    branch: str | None,
    previous_entry: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    lock = load_lock(root)
    if action == "install" and source.pack_id in lock["packs"]:
        raise PackError("pack_already_installed", source.pack_id)
    _assert_composable(
        source, lock, replacing=source.pack_id if action == "upgrade" else None
    )
    prior_receipts = list(previous_entry.get("receipts", [])) if previous_entry else []
    target_status = (
        str(previous_entry.get("status", "active")) if previous_entry else "active"
    )
    changes = [
        {
            "action": "create",
            "path": (INSTALLED_ROOT / source.pack_id / source.version).as_posix(),
        },
        {
            "action": "replace" if (root / DEFAULT_LOCK).exists() else "create",
            "path": DEFAULT_LOCK.as_posix(),
        },
        {"action": "create", "path": (RECEIPT_ROOT / source.pack_id).as_posix()},
    ]
    if action == "upgrade" and previous_entry is not None:
        changes.extend(
            [
                {
                    "action": "validate_declarative_migration",
                    "path": (
                        Path(source.manifest["migrations"]["upgrades"])
                        / f"{previous_entry['version']}-to-{source.version}.yaml"
                    ).as_posix(),
                },
                {
                    "action": "delete_owned_bundle",
                    "path": str(previous_entry["installed_path"]),
                },
            ]
        )
    provisional_entry = _entry_for(
        source, receipts=prior_receipts, status=target_status
    )
    provisional_lock = _lock_with_entry(lock, source.pack_id, provisional_entry)
    provisional_receipt = _receipt(
        action=action,
        pack_id=source.pack_id,
        version=source.version,
        previous_lock=lock,
        next_lock=provisional_lock,
        changes=changes,
        branch=branch,
    )
    entry = _entry_for(
        source,
        receipts=[*prior_receipts, provisional_receipt["receipt_id"]],
        status=target_status,
    )
    next_lock = _lock_with_entry(lock, source.pack_id, entry)
    receipt = _receipt(
        action=action,
        pack_id=source.pack_id,
        version=source.version,
        previous_lock=lock,
        next_lock=next_lock,
        changes=changes,
        branch=branch,
    )
    if receipt["receipt_id"] != provisional_receipt["receipt_id"]:
        raise PackError("receipt_identity_not_stable")
    return lock, next_lock, receipt


def _install_pack_unlocked(
    root: Path,
    pack_id: str,
    *,
    version: str | None = None,
    registry_path: Path | None = None,
    dry_run: bool = False,
    branch: str | None = None,
    enforce_git_gate: bool = True,
) -> dict[str, Any]:
    source = resolve_pack(root, pack_id, version=version, registry_path=registry_path)
    reviewed_branch = (
        _dry_run_branch(root, branch)
        if dry_run and enforce_git_gate
        else assert_review_branch(root, branch)
        if enforce_git_gate
        else branch
    )
    previous, next_lock, receipt = _install_plan(
        root, source, action="install", branch=reviewed_branch
    )
    if dry_run:
        return _plan_response(receipt, dry_run=True)
    bundle: Path | None = None
    receipt_path: Path | None = None
    try:
        bundle = _copy_bundle(root, source)
        receipt_path = _write_receipt(root, receipt)
        _atomic_write_lock(root, next_lock, expected_lock=previous)
    except Exception:
        if receipt_path is not None:
            receipt_path.unlink(missing_ok=True)
        if (
            bundle is not None
            and bundle.exists()
            and _installed_matches(root, _entry_for(source, receipts=[]))
        ):
            _quarantine_and_delete_owned_bundle(
                root, _entry_for(source, receipts=[])
            )
        raise
    return _plan_response(receipt, dry_run=False)


def install_pack(
    root: Path,
    pack_id: str,
    *,
    version: str | None = None,
    registry_path: Path | None = None,
    dry_run: bool = False,
    branch: str | None = None,
    enforce_git_gate: bool = True,
) -> dict[str, Any]:
    # Reject an invalid source before the operation guard creates even its
    # repository-local lock directory. Re-resolve inside the guarded function
    # so a concurrent registry/source change still fails before mutation.
    resolve_pack(root, pack_id, version=version, registry_path=registry_path)
    with _operation_guard(root, enabled=not dry_run):
        return _install_pack_unlocked(
            root,
            pack_id,
            version=version,
            registry_path=registry_path,
            dry_run=dry_run,
            branch=branch,
            enforce_git_gate=enforce_git_gate,
        )


def _upgrade_migration(source: PackSource, from_version: str) -> None:
    filename = f"{from_version}-to-{source.version}.yaml"
    upgrades = source.path / source.manifest["migrations"]["upgrades"]
    path = upgrades / filename
    if not path.is_file() or path.is_symlink():
        raise PackError("upgrade_migration_missing")
    data = _load_migration(path, label="upgrade migration")
    if (
        data.get("pack") != source.pack_id
        or data.get("from_version") != from_version
        or data.get("to_version") != source.version
    ):
        raise PackError("upgrade_migration_version_mismatch")


def _upgrade_pack_unlocked(
    root: Path,
    pack_id: str,
    *,
    version: str | None = None,
    registry_path: Path | None = None,
    dry_run: bool = False,
    branch: str | None = None,
    enforce_git_gate: bool = True,
) -> dict[str, Any]:
    lock = load_lock(root)
    current = lock["packs"].get(pack_id)
    if not isinstance(current, dict):
        raise PackError("pack_not_installed", pack_id)
    source = resolve_pack(root, pack_id, version=version, registry_path=registry_path)
    if _semver(source.version, label="target version") <= _semver(
        current["version"], label="current version"
    ):
        raise PackError("upgrade_requires_newer_version")
    _upgrade_migration(source, current["version"])
    reviewed_branch = (
        _dry_run_branch(root, branch)
        if dry_run and enforce_git_gate
        else assert_review_branch(root, branch)
        if enforce_git_gate
        else branch
    )
    previous, next_lock, receipt = _install_plan(
        root,
        source,
        action="upgrade",
        branch=reviewed_branch,
        previous_entry=current,
    )
    if dry_run:
        return _plan_response(receipt, dry_run=True)
    if not _installed_matches(root, current):
        raise PackError("installed_bundle_drift", pack_id)
    bundle: Path | None = None
    receipt_path: Path | None = None
    try:
        bundle = _copy_bundle(root, source)
        receipt_path = _write_receipt(root, receipt)
        _atomic_write_lock(root, next_lock, expected_lock=previous)
    except Exception:
        if receipt_path is not None:
            receipt_path.unlink(missing_ok=True)
        if (
            bundle is not None
            and bundle.exists()
            and _installed_matches(root, _entry_for(source, receipts=[]))
        ):
            _quarantine_and_delete_owned_bundle(
                root, _entry_for(source, receipts=[])
            )
        raise
    try:
        _quarantine_and_delete_owned_bundle(root, current)
    except Exception as exc:
        if _installed_matches(root, current):
            if load_lock(root) == next_lock:
                _atomic_write_lock(root, previous, expected_lock=next_lock)
            if receipt_path is not None:
                receipt_path.unlink(missing_ok=True)
            if (
                bundle is not None
                and bundle.exists()
                and _installed_matches(root, _entry_for(source, receipts=[]))
            ):
                _quarantine_and_delete_owned_bundle(
                    root, _entry_for(source, receipts=[])
                )
            raise
        raise PackError(
            "owned_bundle_cleanup_recovery_required",
            str(current.get("installed_path") or pack_id),
        ) from exc
    return _plan_response(receipt, dry_run=False)


def upgrade_pack(
    root: Path,
    pack_id: str,
    *,
    version: str | None = None,
    registry_path: Path | None = None,
    dry_run: bool = False,
    branch: str | None = None,
    enforce_git_gate: bool = True,
) -> dict[str, Any]:
    # Same two-pass rule as install: the first pass is zero-write UX, while the
    # guarded pass below is the authoritative race-safe validation.
    resolve_pack(root, pack_id, version=version, registry_path=registry_path)
    with _operation_guard(root, enabled=not dry_run):
        return _upgrade_pack_unlocked(
            root,
            pack_id,
            version=version,
            registry_path=registry_path,
            dry_run=dry_run,
            branch=branch,
            enforce_git_gate=enforce_git_gate,
        )


def _state_change_plan(
    root: Path,
    pack_id: str,
    *,
    action: str,
    branch: str | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    lock = load_lock(root)
    entry = lock["packs"].get(pack_id)
    if not isinstance(entry, dict):
        raise PackError("pack_not_installed", pack_id)
    if action in {"disable", "remove"}:
        for dependent_id, dependent in _active_entries(lock, excluding=pack_id).items():
            if any(
                dependency["id"] == pack_id for dependency in dependent["dependencies"]
            ):
                raise PackError("dependent_pack_active", dependent_id)
    changes: list[dict[str, str]] = [
        {"action": "replace", "path": DEFAULT_LOCK.as_posix()}
    ]
    if action == "disable":
        if entry["status"] == "disabled":
            raise PackError("pack_already_disabled", pack_id)
        next_entry = {**entry, "status": "disabled"}
        next_lock = _lock_with_entry(lock, pack_id, next_entry)
    elif action == "remove":
        next_lock = _lock_with_entry(lock, pack_id, None)
        changes.append(
            {"action": "delete_owned_bundle", "path": entry["installed_path"]}
        )
    else:
        raise PackError("unsupported_pack_action")
    receipt = _receipt(
        action=action,
        pack_id=pack_id,
        version=entry["version"],
        previous_lock=lock,
        next_lock=next_lock,
        changes=[
            *changes,
            {"action": "create", "path": (RECEIPT_ROOT / pack_id).as_posix()},
        ],
        branch=branch,
    )
    if action == "disable":
        next_entry = {
            **next_lock["packs"][pack_id],
            "receipts": [*entry["receipts"], receipt["receipt_id"]],
        }
        next_lock = _lock_with_entry(lock, pack_id, next_entry)
        receipt = _receipt(
            action=action,
            pack_id=pack_id,
            version=entry["version"],
            previous_lock=lock,
            next_lock=next_lock,
            changes=[
                *changes,
                {"action": "create", "path": (RECEIPT_ROOT / pack_id).as_posix()},
            ],
            branch=branch,
        )
    return lock, next_lock, receipt, entry


def _disable_pack_unlocked(
    root: Path,
    pack_id: str,
    *,
    dry_run: bool = False,
    branch: str | None = None,
    enforce_git_gate: bool = True,
) -> dict[str, Any]:
    reviewed_branch = (
        _dry_run_branch(root, branch)
        if dry_run and enforce_git_gate
        else assert_review_branch(root, branch)
        if enforce_git_gate
        else branch
    )
    previous, next_lock, receipt, _entry = _state_change_plan(
        root, pack_id, action="disable", branch=reviewed_branch
    )
    if dry_run:
        return _plan_response(receipt, dry_run=True)
    receipt_path = _write_receipt(root, receipt)
    try:
        _atomic_write_lock(root, next_lock, expected_lock=previous)
    except Exception:
        receipt_path.unlink(missing_ok=True)
        raise
    return _plan_response(receipt, dry_run=False)


def disable_pack(
    root: Path,
    pack_id: str,
    *,
    dry_run: bool = False,
    branch: str | None = None,
    enforce_git_gate: bool = True,
) -> dict[str, Any]:
    with _operation_guard(root, enabled=not dry_run):
        return _disable_pack_unlocked(
            root,
            pack_id,
            dry_run=dry_run,
            branch=branch,
            enforce_git_gate=enforce_git_gate,
        )


def _remove_pack_unlocked(
    root: Path,
    pack_id: str,
    *,
    dry_run: bool = False,
    branch: str | None = None,
    enforce_git_gate: bool = True,
) -> dict[str, Any]:
    reviewed_branch = (
        _dry_run_branch(root, branch)
        if dry_run and enforce_git_gate
        else assert_review_branch(root, branch)
        if enforce_git_gate
        else branch
    )
    previous, next_lock, receipt, entry = _state_change_plan(
        root, pack_id, action="remove", branch=reviewed_branch
    )
    if not _installed_matches(root, entry):
        raise PackError("installed_bundle_drift", pack_id)
    if dry_run:
        return _plan_response(receipt, dry_run=True)
    receipt_path = _write_receipt(root, receipt)
    try:
        _atomic_write_lock(root, next_lock, expected_lock=previous)
    except Exception:
        receipt_path.unlink(missing_ok=True)
        raise
    try:
        _quarantine_and_delete_owned_bundle(root, entry)
    except Exception as exc:
        if _installed_matches(root, entry):
            if load_lock(root) == next_lock:
                _atomic_write_lock(root, previous, expected_lock=next_lock)
            receipt_path.unlink(missing_ok=True)
            raise
        raise PackError(
            "owned_bundle_cleanup_recovery_required",
            str(entry.get("installed_path") or pack_id),
        ) from exc
    return _plan_response(receipt, dry_run=False)


def remove_pack(
    root: Path,
    pack_id: str,
    *,
    dry_run: bool = False,
    branch: str | None = None,
    enforce_git_gate: bool = True,
) -> dict[str, Any]:
    with _operation_guard(root, enabled=not dry_run):
        return _remove_pack_unlocked(
            root,
            pack_id,
            dry_run=dry_run,
            branch=branch,
            enforce_git_gate=enforce_git_gate,
        )


def validate_installation(root: Path, pack_id: str | None = None) -> dict[str, Any]:
    lock = load_lock(root)
    selected = [pack_id] if pack_id is not None else sorted(lock["packs"])
    errors: list[dict[str, str]] = []
    packs: list[dict[str, Any]] = []
    for current_id in selected:
        entry = lock["packs"].get(current_id)
        if not isinstance(entry, dict):
            errors.append({"code": "pack_not_installed", "pack": current_id})
            continue
        for code in _installed_entry_errors(root, current_id, entry):
            errors.append({"code": code, "pack": current_id})
        packs.append(
            {"id": current_id, "version": entry["version"], "status": entry["status"]}
        )
    if pack_id is None:
        errors.extend(_receipt_inventory_errors(root))
        actual_bundles, inventory_errors = _installed_bundle_inventory(root)
        expected_bundles = {
            str(entry["installed_path"])
            for entry in lock["packs"].values()
            if isinstance(entry, dict)
        }
        for code in inventory_errors:
            errors.append({"code": code, "pack": "state"})
        for orphan in sorted(actual_bundles - expected_bundles):
            orphan_parts = Path(orphan).parts
            orphan_pack = orphan_parts[-2] if len(orphan_parts) >= 2 else "state"
            errors.append({"code": "orphan_installed_bundle", "pack": orphan_pack})
    for current_id, entry in _active_entries(lock).items():
        for dependency in entry["dependencies"]:
            installed = _active_entries(lock).get(dependency["id"])
            if not installed or not version_satisfies(
                installed["version"], dependency["version"]
            ):
                errors.append({"code": "dependency_not_satisfied", "pack": current_id})
    # Re-run pairwise composition from lock data without resolving mutable registry sources.
    active = _active_entries(lock)
    ids = sorted(active)
    for index, left_id in enumerate(ids):
        left = active[left_id]
        for right_id in ids[index + 1 :]:
            right = active[right_id]
            if right_id in left["conflicts"] or left_id in right["conflicts"]:
                errors.append({"code": "pack_conflict", "pack": left_id})
            for capability in (
                "page_types",
                "blocks",
                "views",
                "commands",
                "operations",
                "temporal_profiles",
            ):
                if set(left["capabilities"][capability]) & set(
                    right["capabilities"][capability]
                ):
                    errors.append({"code": "capability_conflict", "pack": left_id})
            for kind in _SLOT_KEYS:
                left_slots = {row["slot"]: row["mode"] for row in left["slots"][kind]}
                for row in right["slots"][kind]:
                    if row["slot"] in left_slots and (
                        row["mode"] == "exclusive"
                        or left_slots[row["slot"]] == "exclusive"
                    ):
                        errors.append(
                            {"code": "exclusive_slot_conflict", "pack": left_id}
                        )
    unique_errors = [
        dict(row)
        for row in {
            (str(row["code"]), str(row["pack"])): row for row in errors
        }.values()
    ]
    composition: dict[str, Any] | None = None
    if not unique_errors:
        try:
            composition = compose_active_packs(root)
        except PackError as exc:
            unique_errors = [{"code": exc.code, "pack": exc.detail or "state"}]
    return {
        "schema_version": "wiki_experience_pack_validation.v1",
        "status": "valid" if not unique_errors else "invalid",
        "packs": packs,
        "errors": unique_errors,
        "composition": composition,
    }
