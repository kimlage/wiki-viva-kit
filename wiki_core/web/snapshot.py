"""Publish, read and recover snapshot artifacts atomically.

Model construction lives in snapshot_projection; existing public imports remain valid.
"""
from __future__ import annotations
import contextlib
import ctypes
import errno
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from wiki_core.config import WikiConfig, load_config
from wiki_core.output_safety import OUTPUT_OWNER_FILENAME, OUTPUT_OWNER_SCHEMA_VERSION, contained_output_path, output_is_owned, read_output_owner, validate_managed_output_target, write_output_owner
from wiki_core.web.schemas import WEB_SNAPSHOT_SCHEMA_VERSION

from wiki_core.web.snapshot_projection import (
    _payload_integrity,
    _bundle_hash_for_artifacts,
    _freshness_state,
    _graph_overlay_metrics,
    _pages_payload,
    _snapshot_warnings_payload,
    _source_lifecycle_payload,
    _summary,
    build_snapshot,
    prepare_snapshot_artifacts,
    snapshot_contract_errors,
)

try:  # POSIX live publication; flat snapshots remain portable.
    import fcntl
except ImportError:
    fcntl = None

SNAPSHOT_REVISION_RETENTION = 3


SNAPSHOT_REVISION_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


SNAPSHOT_REVISION_STORE_SUFFIX = ".wiki-revisions"


SNAPSHOT_PUBLICATION_THREAD_LOCK = threading.Lock()


SNAPSHOT_READ_RETRY_BASE_S = 0.002


SNAPSHOT_READ_RETRY_MAX_S = 0.05


SNAPSHOT_HEALTH_VALIDATION_CACHE_TTL_S = 1.0


SNAPSHOT_HEALTH_VALIDATION_CACHE_MAX_ENTRIES = 32


SNAPSHOT_HEALTH_VALIDATION_BUDGET_MS = 100.0


SNAPSHOT_CLEANUP_RECEIPT_SCHEMA_VERSION = "wiki_snapshot_cleanup_receipt.v2"


SNAPSHOT_CLEANUP_RECEIPTS_DIRNAME = "cleanup-receipts"


SNAPSHOT_CLEANUP_RECEIPT_ID_RE = re.compile(r"^[0-9a-f]{32}$")


SNAPSHOT_CLEANUP_INTENT_FILENAME = ".wiki-viva-cleanup-intent.json"


SNAPSHOT_HEALTH_VALIDATION_CACHE_LOCK = threading.Lock()


SNAPSHOT_HEALTH_VALIDATION_CACHE: dict[
    tuple[str, str, str, str],
    tuple[float, tuple[tuple[object, ...], ...], str, str | None, int],
] = {}


class SnapshotWriteResult(dict[str, Path]):
    """Backward-compatible file map plus truthful activation/cleanup receipt."""

    def __init__(
        self,
        files: dict[str, Path],
        *,
        snapshot_id: str,
        active_revision: str,
        cleanup_warnings: tuple[str, ...] = (),
        recovery_paths: tuple[Path, ...] = (),
    ) -> None:
        super().__init__(files)
        self.committed = True
        self.snapshot_id = snapshot_id
        self.active_revision = active_revision
        self.cleanup_warnings = cleanup_warnings
        self.recovery_paths = recovery_paths


class SnapshotPublicationBlockedError(RuntimeError):
    """A pre-commit pathname race blocked publication without clobbering it."""

    def __init__(self, blocker_reason: str) -> None:
        super().__init__(f"snapshot publication blocked: {blocker_reason}")
        self.committed = False
        self.blocker_reason = blocker_reason


class SnapshotCleanupBlockedError(ValueError):
    """Cleanup stopped without deleting an untrusted entry."""

    def __init__(self, message: str, *, recovery_path: Path) -> None:
        super().__init__(message)
        self.recovery_path = recovery_path


class SnapshotDescriptorDeletionBlockedError(ValueError):
    """A descriptor-pinned delete stopped after observing replacement state."""

    def __init__(self, message: str, *, recovery_paths: tuple[Path, ...]) -> None:
        super().__init__(message)
        self.recovery_paths = recovery_paths


class _SnapshotDescriptorTreeRace(ValueError):
    """Internal signal that a pinned tree no longer matches its inventory."""


class SnapshotCleanupResult(list[Path]):
    def __init__(
        self,
        removed: list[Path],
        *,
        cleanup_warnings: tuple[str, ...] = (),
        recovery_paths: tuple[Path, ...] = (),
    ) -> None:
        super().__init__(removed)
        self.cleanup_warnings = cleanup_warnings
        self.recovery_paths = recovery_paths


def _write_snapshot_artifacts(
    target_dir: Path, artifacts: dict[str, dict[str, Any]]
) -> dict[str, Path]:
    written: dict[str, Path] = {}
    for name, payload in artifacts.items():
        rel = Path(name)
        if rel.is_absolute() or not rel.parts or ".." in rel.parts:
            raise ValueError(f"unsafe snapshot artifact path: {name!r}")
        target = target_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                payload,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        written[name] = target
    return written


def _snapshot_tree_inventory(target_dir: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Inventory one snapshot tree without following or reading symlinks."""

    if target_dir.is_symlink():
        raise ValueError(f"snapshot directory is a symlink: {target_dir}")
    try:
        root_mode = target_dir.stat(follow_symlinks=False).st_mode
    except FileNotFoundError:
        raise
    if not stat.S_ISDIR(root_mode):
        raise ValueError(f"snapshot path is not a directory: {target_dir}")

    files: list[str] = []
    directories: list[str] = []

    def visit(directory: Path, relative_parent: Path) -> None:
        with os.scandir(directory) as entries:
            for entry in entries:
                relative = relative_parent / entry.name
                relative_name = relative.as_posix()
                entry_stat = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(entry_stat.st_mode):
                    raise ValueError(
                        f"snapshot directory contains symlink: {relative_name}"
                    )
                if stat.S_ISDIR(entry_stat.st_mode):
                    directories.append(relative_name)
                    visit(directory / entry.name, relative)
                elif stat.S_ISREG(entry_stat.st_mode):
                    files.append(relative_name)
                else:
                    raise ValueError(
                        "snapshot directory contains a non-regular entry: "
                        f"{relative_name}"
                    )

    visit(target_dir, Path())
    return tuple(sorted(files)), tuple(sorted(directories))


def _snapshot_tree_fingerprint(target_dir: Path) -> tuple[tuple[object, ...], ...]:
    """Return a metadata fingerprint after a strict no-follow inventory scan."""

    files, directories = _snapshot_tree_inventory(target_dir)
    fingerprint: list[tuple[object, ...]] = []
    for name in ("", *directories, *files):
        path = target_dir if not name else target_dir / name
        entry_stat = path.stat(follow_symlinks=False)
        if stat.S_ISLNK(entry_stat.st_mode):
            raise ValueError(f"snapshot fingerprint encountered symlink: {name}")
        fingerprint.append(
            (
                name,
                stat.S_IFMT(entry_stat.st_mode),
                entry_stat.st_dev,
                entry_stat.st_ino,
                entry_stat.st_size,
                entry_stat.st_mtime_ns,
                entry_stat.st_ctime_ns,
            )
        )
    return tuple(fingerprint)


def _declared_snapshot_files(manifest: dict[str, Any]) -> tuple[str, ...]:
    raw_declared = manifest.get("files")
    if not isinstance(raw_declared, list):
        raise ValueError("snapshot manifest files must be a list")
    declared: list[str] = []
    for value in raw_declared:
        if not isinstance(value, str):
            raise ValueError("snapshot manifest file names must be strings")
        relative = Path(value)
        if (
            relative.is_absolute()
            or not relative.parts
            or value != relative.as_posix()
            or any(part in {"", ".", ".."} for part in relative.parts)
            or value == OUTPUT_OWNER_FILENAME
        ):
            raise ValueError(f"unsafe snapshot artifact path: {value!r}")
        declared.append(value)
    if len(set(declared)) != len(declared):
        raise ValueError("snapshot manifest contains duplicate file names")
    if "manifest.json" not in declared:
        raise ValueError("snapshot manifest must declare manifest.json")
    return tuple(declared)


def _read_snapshot_file_bytes(target_dir: Path, name: str) -> bytes:
    """Read one regular in-tree file through a no-follow component chain."""

    relative = Path(name)
    if os.name != "posix":  # pragma: no cover - Windows flat-build fallback.
        path = target_dir / relative
        before = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or path.is_symlink():
            raise ValueError(f"snapshot artifact is unsafe: {name}")
        data = path.read_bytes()
        if path.read_bytes() != data:
            raise ValueError(f"snapshot artifact bytes changed while reading: {name}")
        after = path.stat(follow_symlinks=False)
        if (before.st_dev, before.st_ino, before.st_size) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
        ):
            raise ValueError(f"snapshot artifact changed while reading: {name}")
        return data

    directory_fd = os.open(target_dir, _directory_open_flags())
    file_fd: int | None = None
    try:
        for part in relative.parts[:-1]:
            next_fd = os.open(part, _directory_open_flags(), dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        file_fd = os.open(relative.name, flags, dir_fd=directory_fd)
        before = os.fstat(file_fd)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"snapshot artifact is not a regular file: {name}")
        with os.fdopen(file_fd, "rb", closefd=False) as handle:
            data = handle.read()
            handle.seek(0)
            if handle.read() != data:
                raise ValueError(
                    f"snapshot artifact bytes changed while reading: {name}"
                )
        after = os.fstat(file_fd)
        if (before.st_dev, before.st_ino, before.st_size) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
        ):
            raise ValueError(f"snapshot artifact changed while reading: {name}")
        return data
    finally:
        if file_fd is not None:
            os.close(file_fd)
        os.close(directory_fd)


def _strict_snapshot_directory_payloads(
    target_dir: Path,
    *,
    role: str,
) -> dict[str, dict[str, Any]]:
    """Load exactly the declared regular-file inventory of one snapshot."""

    before_files, before_directories = _snapshot_tree_inventory(target_dir)
    if "manifest.json" not in before_files:
        raise ValueError(f"snapshot {role} directory has no manifest.json")
    manifest_bytes = _read_snapshot_file_bytes(target_dir, "manifest.json")
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("snapshot manifest must be a JSON object")
    declared = _declared_snapshot_files(manifest)
    actual_payload_files = tuple(
        name for name in before_files if name != OUTPUT_OWNER_FILENAME
    )
    expected_directories = {
        parent.as_posix()
        for name in declared
        for parent in Path(name).parents
        if parent != Path(".")
    }
    if (
        tuple(sorted(declared)) != actual_payload_files
        or tuple(sorted(expected_directories)) != before_directories
    ):
        raise ValueError(
            f"snapshot {role} directory differs from manifest: "
            f"declared={len(declared)} actual={len(actual_payload_files)}"
        )
    artifact_bytes = {"manifest.json": manifest_bytes}
    artifact_bytes.update(
        {
            name: _read_snapshot_file_bytes(target_dir, name)
            for name in declared
            if name != "manifest.json"
        }
    )
    loaded = {
        name: json.loads(artifact_bytes[name].decode("utf-8"))
        for name in declared
    }
    after_inventory = _snapshot_tree_inventory(target_dir)
    if after_inventory != (before_files, before_directories):
        raise ValueError(f"snapshot {role} inventory changed while reading")
    errors = snapshot_contract_errors(loaded)
    if errors:
        raise ValueError(
            f"invalid {role} snapshot contract: " + "; ".join(errors)
        )
    return loaded


def _validate_snapshot_directory(target_dir: Path) -> dict[str, dict[str, Any]]:
    return _strict_snapshot_directory_payloads(target_dir, role="staging")


def _is_legacy_snapshot_directory(target_dir: Path, *, expected_repo_id: str) -> bool:
    """Recognize a complete pre-marker snapshot for one safe migration.

    A directory with any undeclared file is not considered legacy-managed.  It
    therefore cannot smuggle arbitrary user files through the ownership gate.
    """

    try:
        before_files, before_directories = _snapshot_tree_inventory(target_dir)
        manifest = json.loads(
            _read_snapshot_file_bytes(target_dir, "manifest.json").decode("utf-8")
        )
        if not isinstance(manifest, dict):
            return False
        declared = _declared_snapshot_files(manifest)
        actual = tuple(
            name for name in before_files if name != OUTPUT_OWNER_FILENAME
        )
        expected_directories = tuple(
            sorted(
                {
                    parent.as_posix()
                    for name in declared
                    for parent in Path(name).parents
                    if parent != Path(".")
                }
            )
        )
        if manifest.get("schema_version") != WEB_SNAPSHOT_SCHEMA_VERSION:
            return False
        if str((manifest.get("repo") or {}).get("repo_id") or "") != expected_repo_id:
            return False
        if tuple(sorted(declared)) != actual or expected_directories != before_directories:
            return False
        loaded = {
            name: json.loads(
                _read_snapshot_file_bytes(target_dir, name).decode("utf-8")
            )
            for name in declared
        }
        if _snapshot_tree_inventory(target_dir) != (
            before_files,
            before_directories,
        ):
            return False
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False
    errors = snapshot_contract_errors(loaded)
    # v8 snapshots generated immediately before RT-34 are structurally and
    # cryptographically complete but do not yet carry per-page content hashes.
    # Recognize exactly that legacy shape so the local operator can adopt its
    # own default cache once; every other contract error remains unowned.
    return bool(errors) and all(
        error.startswith("invalid page content hash: ") for error in errors
    )


def _revision_store_path(out_dir: Path) -> Path:
    return out_dir.parent / f".{out_dir.name}{SNAPSHOT_REVISION_STORE_SUFFIX}"


def _revision_store_kind(output_kind: str) -> str:
    return f"{output_kind}_revision_store"


def _cleanup_receipts_kind(output_kind: str) -> str:
    return f"{output_kind}_cleanup_receipts"


def _cleanup_receipts_path(store: Path) -> Path:
    return store / SNAPSHOT_CLEANUP_RECEIPTS_DIRNAME


def _revision_hash(artifacts: dict[str, dict[str, Any]]) -> str:
    bundle_hash = str((artifacts.get("manifest.json") or {}).get("bundle_hash") or "")
    if not SNAPSHOT_REVISION_HASH_RE.fullmatch(bundle_hash):
        raise ValueError("snapshot bundle_hash is not a canonical sha256 revision")
    return bundle_hash


def _prepare_revision_store(
    root: Path,
    out_dir: Path,
    *,
    output_kind: str,
    repo_id: str,
) -> Path:
    store = validate_managed_output_target(
        root,
        _revision_store_path(out_dir),
        kind=_revision_store_kind(output_kind),
        repo_id=repo_id,
    )
    store.mkdir(parents=True, exist_ok=True)
    write_output_owner(
        store,
        kind=_revision_store_kind(output_kind),
        repo_id=repo_id,
    )
    leases = store / "leases"
    if leases.is_symlink() or (leases.exists() and not leases.is_dir()):
        raise ValueError(f"snapshot leases directory is unsafe: {leases}")
    leases.mkdir(exist_ok=True)
    receipts = validate_managed_output_target(
        root,
        _cleanup_receipts_path(store),
        kind=_cleanup_receipts_kind(output_kind),
        repo_id=repo_id,
    )
    receipts.mkdir(exist_ok=True)
    write_output_owner(
        receipts,
        kind=_cleanup_receipts_kind(output_kind),
        repo_id=repo_id,
    )
    _fsync_file(store / OUTPUT_OWNER_FILENAME)
    _fsync_file(receipts / OUTPUT_OWNER_FILENAME)
    _fsync_directory(leases)
    _fsync_directory(receipts)
    _fsync_directory(store)
    _fsync_directory(store.parent)
    return store


def _managed_revision_pointer_target(
    root: Path,
    out_dir: Path,
    store: Path,
    *,
    output_kind: str,
    repo_id: str,
) -> Path:
    """Resolve only a publisher-owned, repository-contained active pointer.

    This is intentionally narrower than accepting an arbitrary output symlink.
    The link must be relative, point directly into the expected sibling store,
    name one canonical sha256 revision and resolve to a matching owned bundle.
    User-provided target or ancestor symlinks therefore remain rejected.
    """

    relative = _validate_revision_pointer_store(
        root,
        out_dir,
        store,
        output_kind=output_kind,
        repo_id=repo_id,
    )
    target = out_dir.parent / relative
    try:
        if target.parent.resolve(strict=True) != store.resolve(strict=True):
            raise ValueError(f"generated output cannot be a symlink: {out_dir}")
        target_resolved = target.resolve(strict=True)
        target_resolved.relative_to(root.resolve(strict=True))
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError(f"generated output cannot be a symlink: {out_dir}") from exc
    if target.is_symlink() or not target.is_dir():
        raise ValueError(f"generated output cannot be a symlink: {out_dir}")
    _validate_owned_snapshot_revision(
        target,
        requested_revision=relative.name,
        output_kind=output_kind,
        repo_id=repo_id,
    )
    return target_resolved


def _validate_revision_pointer_store(
    root: Path,
    out_dir: Path,
    store: Path,
    *,
    output_kind: str,
    repo_id: str,
) -> Path:
    """Validate pointer shape and its owned store without opening a revision.

    Publication uses this narrow pre-lock check so another serialized publisher
    may retire the previously active revision without racing validation. The
    full revision is validated only after acquiring the publication lease.
    """

    if not out_dir.is_symlink():
        raise ValueError(f"generated output is not a revision pointer: {out_dir}")
    contained_output_path(root, out_dir.parent / f".{out_dir.name}.pointer-probe")
    relative = Path(os.readlink(out_dir))
    if (
        relative.is_absolute()
        or relative.parts != (store.name, relative.name)
        or not SNAPSHOT_REVISION_HASH_RE.fullmatch(relative.name)
    ):
        raise ValueError(f"generated output cannot be a symlink: {out_dir}")
    try:
        contained_output_path(root, store)
    except ValueError as exc:
        raise ValueError(f"generated output cannot be a symlink: {out_dir}") from exc
    if not output_is_owned(
        store,
        kind=_revision_store_kind(output_kind),
        repo_id=repo_id,
    ):
        raise ValueError(f"snapshot revision store is not owned by this repo: {store}")
    return relative


def _atomic_exchange_paths(first: Path, second: Path) -> None:
    """Atomically exchange two existing directory entries on Darwin/Linux.

    Python does not expose either syscall. There is deliberately no two-rename
    fallback: on an unsupported platform the one-time legacy-directory
    migration fails closed and leaves both entries untouched.
    """

    if sys.platform != "darwin" and not sys.platform.startswith("linux"):
        raise OSError(
            errno.ENOTSUP,
            "atomic snapshot migration is supported only on Darwin and Linux; "
            "the existing directory was not changed",
        )

    libc = ctypes.CDLL(None, use_errno=True)
    encoded_first = os.fsencode(first)
    encoded_second = os.fsencode(second)
    if sys.platform == "darwin":
        rename_swap = 0x00000002
        renamex_np = libc.renamex_np
        renamex_np.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        renamex_np.restype = ctypes.c_int
        result = renamex_np(encoded_first, encoded_second, rename_swap)
    elif sys.platform.startswith("linux"):
        at_fdcwd = -100
        rename_exchange = 0x00000002
        try:
            renameat2 = libc.renameat2
        except AttributeError as exc:  # pragma: no cover - old libc only.
            raise OSError(
                errno.ENOTSUP,
                "atomic snapshot migration requires renameat2(RENAME_EXCHANGE)",
            ) from exc
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        result = renameat2(
            at_fdcwd,
            encoded_first,
            at_fdcwd,
            encoded_second,
            rename_exchange,
        )
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(
            error_number,
            os.strerror(error_number),
            f"{first} <-> {second}",
        )


def _atomic_install_directory_noreplace(source: Path, target: Path) -> None:
    """Atomically install one directory only when the target entry is absent."""

    libc = ctypes.CDLL(None, use_errno=True)
    encoded_source = os.fsencode(source)
    encoded_target = os.fsencode(target)
    if sys.platform == "darwin":
        rename_excl = 0x00000004
        renamex_np = libc.renamex_np
        renamex_np.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        renamex_np.restype = ctypes.c_int
        result = renamex_np(encoded_source, encoded_target, rename_excl)
    elif sys.platform.startswith("linux"):
        at_fdcwd = -100
        rename_noreplace = 0x00000001
        try:
            renameat2 = libc.renameat2
        except AttributeError as exc:  # pragma: no cover - old libc only.
            raise OSError(
                errno.ENOTSUP,
                "content-addressed install requires renameat2(RENAME_NOREPLACE)",
            ) from exc
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        result = renameat2(
            at_fdcwd,
            encoded_source,
            at_fdcwd,
            encoded_target,
            rename_noreplace,
        )
    else:  # pragma: no cover - live publisher rejects other platforms first.
        raise OSError(
            errno.ENOTSUP,
            "content-addressed directory install is supported only on Darwin/Linux",
        )
    if result != 0:
        error_number = ctypes.get_errno()
        if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
            raise FileExistsError(
                error_number,
                os.strerror(error_number),
                str(target),
            )
        raise OSError(
            error_number,
            os.strerror(error_number),
            f"{source} -> {target}",
        )


def _path_entry_identity(path: Path) -> tuple[int, int, int, str | None]:
    """Capture one stable directory-entry identity without following symlinks."""

    before = path.stat(follow_symlinks=False)
    link_target = os.readlink(path) if stat.S_ISLNK(before.st_mode) else None
    after = path.stat(follow_symlinks=False)
    before_identity = (
        before.st_dev,
        before.st_ino,
        stat.S_IFMT(before.st_mode),
        link_target,
    )
    after_identity = (
        after.st_dev,
        after.st_ino,
        stat.S_IFMT(after.st_mode),
        os.readlink(path) if stat.S_ISLNK(after.st_mode) else None,
    )
    if before_identity != after_identity:
        raise SnapshotPublicationBlockedError("active pathname changed during identity capture")
    return before_identity


def _stat_identity(entry_stat: os.stat_result) -> tuple[int, int, int]:
    return (
        entry_stat.st_dev,
        entry_stat.st_ino,
        stat.S_IFMT(entry_stat.st_mode),
    )


def _descriptor_entry_identity(
    directory_fd: int,
    name: str,
) -> tuple[int, int, int]:
    return _stat_identity(
        os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    )


def _descriptor_tree_children(
    inventory: dict[str, tuple[int, int, int]],
) -> dict[str, set[str]]:
    children: dict[str, set[str]] = {}
    for relative_name in inventory:
        if not relative_name:
            continue
        relative = Path(relative_name)
        parent = relative.parent.as_posix()
        if parent == ".":
            parent = ""
        children.setdefault(parent, set()).add(relative.name)
    return children


def _clear_snapshot_tree_by_descriptor(
    directory_fd: int,
    *,
    relative_directory: str,
    inventory: dict[str, tuple[int, int, int]],
    children: dict[str, set[str]],
) -> None:
    """Delete only the exact no-follow inventory below one pinned directory."""

    expected_names = children.get(relative_directory, set())
    observed_names = set(os.listdir(directory_fd))
    if observed_names != expected_names:
        raise _SnapshotDescriptorTreeRace(
            "snapshot prune inventory changed inside pinned quarantine: "
            f"expected={sorted(expected_names)!r} observed={sorted(observed_names)!r}"
        )
    for name in sorted(observed_names):
        relative_name = f"{relative_directory}/{name}" if relative_directory else name
        expected_identity = inventory.get(relative_name)
        if expected_identity is None:
            raise _SnapshotDescriptorTreeRace(
                f"snapshot prune encountered undeclared entry: {relative_name}"
            )
        try:
            observed_identity = _descriptor_entry_identity(directory_fd, name)
        except OSError as exc:
            raise _SnapshotDescriptorTreeRace(
                f"snapshot prune entry changed before open: {relative_name}"
            ) from exc
        if observed_identity != expected_identity:
            raise _SnapshotDescriptorTreeRace(
                f"snapshot prune entry identity changed: {relative_name}"
            )
        expected_type = expected_identity[2]
        if expected_type == stat.S_IFDIR:
            try:
                child_fd = os.open(
                    name,
                    _directory_open_flags(),
                    dir_fd=directory_fd,
                )
            except OSError as exc:
                raise _SnapshotDescriptorTreeRace(
                    f"snapshot prune directory changed before pin: {relative_name}"
                ) from exc
            try:
                pinned_identity = _stat_identity(os.fstat(child_fd))
                if pinned_identity != expected_identity:
                    raise _SnapshotDescriptorTreeRace(
                        f"snapshot prune directory pin mismatch: {relative_name}"
                    )
                _clear_snapshot_tree_by_descriptor(
                    child_fd,
                    relative_directory=relative_name,
                    inventory=inventory,
                    children=children,
                )
                if (
                    _descriptor_entry_identity(directory_fd, name)
                    != pinned_identity
                ):
                    raise _SnapshotDescriptorTreeRace(
                        f"snapshot prune directory changed before rmdir: {relative_name}"
                    )
                os.rmdir(name, dir_fd=directory_fd)
                os.fsync(directory_fd)
            finally:
                os.close(child_fd)
            continue
        if expected_type != stat.S_IFREG:
            raise _SnapshotDescriptorTreeRace(
                f"snapshot prune refuses non-regular entry: {relative_name}"
            )
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            file_fd = os.open(name, flags, dir_fd=directory_fd)
        except OSError as exc:
            raise _SnapshotDescriptorTreeRace(
                f"snapshot prune file changed before pin: {relative_name}"
            ) from exc
        try:
            pinned_identity = _stat_identity(os.fstat(file_fd))
            if pinned_identity != expected_identity:
                raise _SnapshotDescriptorTreeRace(
                    f"snapshot prune file pin mismatch: {relative_name}"
                )
            if _descriptor_entry_identity(directory_fd, name) != pinned_identity:
                raise _SnapshotDescriptorTreeRace(
                    f"snapshot prune file changed before unlink: {relative_name}"
                )
            os.unlink(name, dir_fd=directory_fd)
            os.fsync(directory_fd)
        finally:
            os.close(file_fd)


def _descriptor_identity_recovery_paths(
    parent_fd: int,
    parent: Path,
    *,
    expected_identity: tuple[int, int, int],
    quarantine: Path,
) -> tuple[Path, ...]:
    recovery: list[Path] = []
    if os.path.lexists(quarantine):
        recovery.append(quarantine)
    with contextlib.suppress(OSError):
        for name in os.listdir(parent_fd):
            candidate = parent / name
            try:
                identity = _descriptor_entry_identity(parent_fd, name)
            except OSError:
                continue
            if identity == expected_identity and candidate not in recovery:
                recovery.append(candidate)
    return tuple(recovery)


def _delete_snapshot_tree_descriptor_pinned(
    store: Path,
    quarantine: Path,
    *,
    expected_identity: tuple[int, int, int, str | None],
    fingerprint: tuple[tuple[object, ...], ...],
) -> None:
    """Delete one validated quarantine through pinned, no-follow descriptors.

    POSIX has no inode-conditional ``rmdir``. The parent entry is therefore
    rechecked against the pinned root immediately before the final dirfd-relative
    rmdir; a non-cooperating writer still has an unavoidable compare-to-rmdir
    micro-window, which publication health reports explicitly.
    """

    expected_root = expected_identity[:3]
    inventory = {
        str(row[0]): (int(row[2]), int(row[3]), int(row[1]))
        for row in fingerprint
    }
    if inventory.get("") != expected_root:
        raise ValueError("snapshot prune fingerprint root identity mismatch")
    children = _descriptor_tree_children(inventory)
    parent_fd = os.open(store, _directory_open_flags())
    root_fd: int | None = None
    try:
        try:
            try:
                root_fd = os.open(
                    quarantine.name,
                    _directory_open_flags(),
                    dir_fd=parent_fd,
                )
            except OSError as exc:
                raise _SnapshotDescriptorTreeRace(
                    "snapshot prune quarantine root changed before descriptor open"
                ) from exc
            pinned_root = _stat_identity(os.fstat(root_fd))
            if pinned_root != expected_root:
                raise _SnapshotDescriptorTreeRace(
                    "snapshot prune quarantine root changed before descriptor pin"
                )
            _clear_snapshot_tree_by_descriptor(
                root_fd,
                relative_directory="",
                inventory=inventory,
                children=children,
            )
            os.fsync(root_fd)
            if (
                _descriptor_entry_identity(parent_fd, quarantine.name)
                != pinned_root
            ):
                raise _SnapshotDescriptorTreeRace(
                    "snapshot prune quarantine root changed before final rmdir"
                )
            os.rmdir(quarantine.name, dir_fd=parent_fd)
            os.fsync(parent_fd)
        except (FileNotFoundError, NotADirectoryError) as exc:
            raise _SnapshotDescriptorTreeRace(
                "snapshot prune quarantine root disappeared or changed type"
            ) from exc
        except _SnapshotDescriptorTreeRace as exc:
            recovery_paths = _descriptor_identity_recovery_paths(
                parent_fd,
                store,
                expected_identity=expected_root,
                quarantine=quarantine,
            )
            raise SnapshotDescriptorDeletionBlockedError(
                str(exc),
                recovery_paths=recovery_paths,
            ) from exc
    finally:
        if root_fd is not None:
            os.close(root_fd)
        os.close(parent_fd)


def _restore_exchanged_path_or_raise(
    active_path: Path,
    candidate_path: Path,
    *,
    expected_candidate_identity: tuple[int, int, int, str | None],
) -> None:
    """Roll back an exchange only while the active entry is still our candidate."""

    try:
        observed_candidate = _path_entry_identity(active_path)
    except (FileNotFoundError, SnapshotPublicationBlockedError) as exc:
        raise RuntimeError(
            "snapshot activation race could not be rolled back safely; "
            f"displaced entry remains at {candidate_path}"
        ) from exc
    if observed_candidate != expected_candidate_identity:
        raise RuntimeError(
            "snapshot activation race changed the candidate before rollback; "
            f"displaced entry remains at {candidate_path}"
        )
    _atomic_exchange_paths(active_path, candidate_path)
    _fsync_directory_set(active_path.parent, candidate_path.parent)


def _activate_snapshot_pointer_cas(
    pointer: Path,
    out_dir: Path,
    *,
    expected_active_identity: tuple[int, int, int, str | None] | None,
) -> bool:
    """Install ``pointer`` without clobbering an absent or changed pathname.

    Returns ``True`` when an existing entry was exchanged into ``pointer`` and
    ``False`` when the candidate was installed into an absent pathname.
    """

    candidate_identity = _path_entry_identity(pointer)
    if expected_active_identity is None:
        try:
            _atomic_install_directory_noreplace(pointer, out_dir)
        except FileExistsError as exc:
            raise SnapshotPublicationBlockedError(
                "active pathname appeared after preflight; external entry preserved"
            ) from exc
        return False

    try:
        _atomic_exchange_paths(out_dir, pointer)
    except FileNotFoundError as exc:
        raise SnapshotPublicationBlockedError(
            "active pathname disappeared after preflight; no activation committed"
        ) from exc

    try:
        displaced_identity = _path_entry_identity(pointer)
    except (FileNotFoundError, SnapshotPublicationBlockedError) as exc:
        _restore_exchanged_path_or_raise(
            out_dir,
            pointer,
            expected_candidate_identity=candidate_identity,
        )
        raise SnapshotPublicationBlockedError(
            "active pathname changed during commit; displaced entry restored"
        ) from exc
    if displaced_identity != expected_active_identity:
        _restore_exchanged_path_or_raise(
            out_dir,
            pointer,
            expected_candidate_identity=candidate_identity,
        )
        raise SnapshotPublicationBlockedError(
            "active pathname changed after preflight; external entry restored"
        )
    return True


def _directory_open_flags() -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return flags


def _open_lock_at(directory_fd: int, name: str) -> Any:
    """Open one regular lock leaf relative to an already pinned directory."""

    if not name or Path(name).name != name or "\x00" in name:
        raise ValueError(f"unsafe snapshot lock name: {name!r}")
    descriptor: int | None = None
    last_missing: FileNotFoundError | None = None
    for _ in range(8):
        try:
            flags = os.O_RDWR | os.O_CREAT
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(name, flags, 0o600, dir_fd=directory_fd)
            break
        except FileNotFoundError as exc:
            # Darwin may transiently report ENOENT when several processes race
            # the first O_CREAT for the same dirfd-relative lock. The pinned
            # no-follow directory/name invariants remain unchanged on retry.
            last_missing = exc
            time.sleep(0.001)
    if descriptor is None:
        assert last_missing is not None
        raise last_missing
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise ValueError(f"snapshot lock is not a regular file: {name}")
    return os.fdopen(descriptor, "a+b")


def _open_revision_lock(store: Path, revision: str) -> Any:
    """Pin parent -> store -> leases with openat/O_NOFOLLOW before lock open."""

    parent_fd = os.open(store.parent, _directory_open_flags())
    store_fd: int | None = None
    leases_fd: int | None = None
    try:
        store_fd = os.open(
            store.name,
            _directory_open_flags(),
            dir_fd=parent_fd,
        )
        leases_fd = os.open(
            "leases",
            _directory_open_flags(),
            dir_fd=store_fd,
        )
        return _open_lock_at(leases_fd, f"{revision}.lock")
    finally:
        if leases_fd is not None:
            os.close(leases_fd)
        if store_fd is not None:
            os.close(store_fd)
        os.close(parent_fd)


def _open_contained_directory_fd(root: Path, directory: Path) -> int:
    """Walk a repository-relative directory one no-follow component at a time."""

    root_resolved = root.resolve(strict=True)
    directory_resolved = directory.resolve(strict=True)
    relative = directory_resolved.relative_to(root_resolved)
    current_fd = os.open(root_resolved, _directory_open_flags())
    try:
        for part in relative.parts:
            next_fd = os.open(part, _directory_open_flags(), dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory_set(*directories: Path) -> None:
    """Attempt every distinct directory fsync before surfacing any failure."""

    failures: list[tuple[Path, OSError]] = []
    for directory in dict.fromkeys(directories):
        try:
            _fsync_directory(directory)
        except OSError as exc:
            failures.append((directory, exc))
    if failures:
        detail = ", ".join(str(directory) for directory, _exc in failures)
        raise OSError(errno.EIO, f"snapshot directory fsync failed: {detail}") from (
            failures[0][1]
        )


def _fsync_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"snapshot durable file is unsafe: {path}")
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _fsync_snapshot_tree(root: Path) -> None:
    """Flush every snapshot file, then directories from leaves to root."""

    files = sorted(path for path in root.rglob("*") if path.is_file())
    for path in files:
        if path.is_symlink():
            raise ValueError(f"snapshot staging contains a symlink: {path}")
        with path.open("rb") as handle:
            os.fsync(handle.fileno())
    directories = sorted(
        (path for path in root.rglob("*") if path.is_dir() and not path.is_symlink()),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for directory in [*directories, root]:
        _fsync_directory(directory)


@contextlib.contextmanager
def _revision_lease(store: Path, revision: str, *, exclusive: bool) -> Iterator[bool]:
    """Hold a cross-process advisory lease for one immutable revision."""

    if fcntl is None:  # pragma: no cover - Windows live publication is unsupported.
        yield False
        return
    if not SNAPSHOT_REVISION_HASH_RE.fullmatch(revision):
        raise ValueError(f"snapshot lease revision must be a sha256: {revision!r}")
    leases = store / "leases"
    if leases.is_symlink() or not leases.is_dir():
        raise ValueError(f"snapshot leases directory is unsafe: {leases}")
    try:
        handle = _open_revision_lock(store, revision)
    except FileNotFoundError:
        # A reader may have resolved a revision immediately before serialized
        # cleanup retired it. Let the active-reader loop resolve the pointer
        # again; every other lock error remains a hard unsafe-path failure.
        raise
    except OSError as exc:
        raise ValueError(
            f"snapshot lease lock is unsafe: {leases / f'{revision}.lock'}: {exc}"
        ) from exc
    acquired = False
    try:
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        if exclusive:
            operation |= fcntl.LOCK_NB
        try:
            fcntl.flock(handle.fileno(), operation)
            acquired = True
        except BlockingIOError:
            acquired = False
        yield acquired
    finally:
        if acquired:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


@contextlib.contextmanager
def _publication_lease(root: Path, out_dir: Path) -> Iterator[None]:
    """Serialize store bootstrap, activation and pruning across processes."""

    if fcntl is None:  # pragma: no cover - rejected before store creation.
        raise OSError(errno.ENOTSUP, "cross-process publication leases unavailable")
    lock_name = f".{out_dir.name}.publication.lock"
    lock_path = out_dir.parent / lock_name
    contained_output_path(root, lock_path)
    if lock_path.is_symlink() or (lock_path.exists() and not lock_path.is_file()):
        raise ValueError(f"snapshot publication lock is unsafe: {lock_path}")
    with SNAPSHOT_PUBLICATION_THREAD_LOCK:
        parent_fd: int | None = None
        try:
            parent_fd = _open_contained_directory_fd(root, out_dir.parent)
            handle = _open_lock_at(parent_fd, lock_name)
        except OSError as exc:
            raise ValueError(f"snapshot publication lock is unsafe: {lock_path}") from exc
        finally:
            if parent_fd is not None:
                os.close(parent_fd)
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()


def _load_snapshot_directory(revision_dir: Path) -> dict[str, dict[str, Any]]:
    return _strict_snapshot_directory_payloads(revision_dir, role="active")


def _validate_owned_snapshot_revision(
    revision_dir: Path,
    *,
    requested_revision: str,
    output_kind: str,
    repo_id: str,
    require_directory_name: bool = True,
) -> dict[str, dict[str, Any]]:
    """Prove requested hash == directory == manifest == recomputed bundle."""

    if not SNAPSHOT_REVISION_HASH_RE.fullmatch(requested_revision):
        raise ValueError(f"snapshot revision must be a sha256: {requested_revision!r}")
    if (
        (require_directory_name and revision_dir.name != requested_revision)
        or revision_dir.is_symlink()
        or not revision_dir.is_dir()
    ):
        raise ValueError(
            f"snapshot revision directory does not match request: {revision_dir}"
        )
    try:
        owner = json.loads(
            _read_snapshot_file_bytes(
                revision_dir,
                OUTPUT_OWNER_FILENAME,
            ).decode("utf-8")
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            "snapshot revision is not owned by this repo "
            f"(missing or unsafe marker): {revision_dir}"
        ) from exc
    expected_owner = {
        "schema_version": OUTPUT_OWNER_SCHEMA_VERSION,
        "kind": output_kind,
        "repo_id": repo_id,
    }
    if owner != expected_owner:
        raise ValueError(f"snapshot revision is not owned by this repo: {revision_dir}")
    payloads = _load_snapshot_directory(revision_dir)
    manifest_repo_id = str(
        ((payloads.get("manifest.json") or {}).get("repo") or {}).get("repo_id")
        or ""
    )
    if manifest_repo_id != repo_id:
        raise ValueError(
            "snapshot revision manifest belongs to a different repository: "
            f"expected={repo_id!r} observed={manifest_repo_id!r}"
        )
    manifest_revision = str(
        (payloads.get("manifest.json") or {}).get("bundle_hash") or ""
    )
    recomputed_revision = _bundle_hash_for_artifacts(payloads)
    identities = [requested_revision, manifest_revision, recomputed_revision]
    if require_directory_name:
        identities.append(revision_dir.name)
    if len(set(identities)) != 1:
        raise ValueError(
            "snapshot revision identity mismatch: "
            f"requested={requested_revision} directory={revision_dir.name} "
            f"manifest={manifest_revision} recomputed={recomputed_revision}"
        )
    return payloads


def load_active_snapshot_artifacts(
    out_dir: Path,
    *,
    max_attempts: int = 8,
    output_kind: str = "web_snapshot",
    expected_repo_id: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Load one pinned active revision without accepting absence or a mix.

    The pointer is resolved once. All payloads then come from that immutable
    directory while a cross-process shared lease prevents pruning. A deletion
    race immediately before lease acquisition retries from the active pointer;
    corruption of a stable revision remains a hard error.

    A regular directory is accepted only for one-release compatibility during
    migration. Its manifest is confirmed after the read and a concurrent
    exchange is retried rather than returned as a mixed bundle.
    """

    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    def wait_before_retry(attempt: int) -> None:
        if attempt + 1 >= max_attempts:
            return
        time.sleep(
            min(
                SNAPSHOT_READ_RETRY_BASE_S * (2**attempt),
                SNAPSHOT_READ_RETRY_MAX_S,
            )
        )

    last_transient: OSError | None = None
    for attempt in range(max_attempts):
        if out_dir.is_symlink():
            raw_target = os.readlink(out_dir)
            relative = Path(raw_target)
            expected_store_name = _revision_store_path(out_dir).name
            if (
                relative.is_absolute()
                or len(relative.parts) != 2
                or relative.parts[0] != expected_store_name
                or not SNAPSHOT_REVISION_HASH_RE.fullmatch(relative.name)
            ):
                raise ValueError(f"unrecognized snapshot revision pointer: {out_dir}")
            store = out_dir.parent / relative.parts[0]
            if store.is_symlink() or not store.is_dir():
                raise ValueError(f"unrecognized snapshot revision store: {store}")
            store_owner = read_output_owner(store)
            if (
                store_owner is None
                or store_owner.get("kind") != _revision_store_kind(output_kind)
                or (
                    expected_repo_id is not None
                    and store_owner.get("repo_id") != expected_repo_id
                )
            ):
                raise ValueError(f"unowned snapshot revision store: {store}")
            revision_dir = out_dir.parent / relative
            try:
                with _revision_lease(store, relative.name, exclusive=False) as acquired:
                    if not acquired:
                        raise OSError(
                            errno.ENOTSUP,
                            "cross-process snapshot leases are unavailable",
                        )
                    if not revision_dir.is_dir() or revision_dir.is_symlink():
                        raise FileNotFoundError(revision_dir)
                    payloads = _validate_owned_snapshot_revision(
                        revision_dir,
                        requested_revision=relative.name,
                        output_kind=output_kind,
                        repo_id=str(store_owner.get("repo_id") or ""),
                    )
                    manifest = payloads["manifest.json"]
                    repo_id = str((manifest.get("repo") or {}).get("repo_id") or "")
                    if repo_id != store_owner.get("repo_id"):
                        raise ValueError(
                            "snapshot revision ownership differs from its manifest"
                        )
                    return payloads
            except FileNotFoundError as exc:
                last_transient = exc
                wait_before_retry(attempt)
                continue
        elif out_dir.is_dir():
            try:
                before = (out_dir / "manifest.json").read_bytes()
                payloads = _load_snapshot_directory(out_dir)
                after = (out_dir / "manifest.json").read_bytes()
            except FileNotFoundError as exc:
                last_transient = exc
                wait_before_retry(attempt)
                continue
            except ValueError:
                # A one-time atomic directory-to-pointer exchange may occur
                # after the first manifest read. Retry that transition, but do
                # not mask corruption of a stable flat directory.
                if out_dir.is_symlink():
                    wait_before_retry(attempt)
                    continue
                try:
                    after = (out_dir / "manifest.json").read_bytes()
                except FileNotFoundError as exc:
                    last_transient = exc
                    wait_before_retry(attempt)
                    continue
                if before != after:
                    wait_before_retry(attempt)
                    continue
                raise
            if before == after:
                repo_id = str(
                    ((payloads["manifest.json"].get("repo") or {}).get("repo_id"))
                    or ""
                )
                if expected_repo_id is not None and repo_id != expected_repo_id:
                    raise ValueError(
                        f"snapshot repo mismatch: expected {expected_repo_id!r}, "
                        f"observed {repo_id!r}"
                    )
                if not output_is_owned(
                    out_dir,
                    kind=output_kind,
                    repo_id=repo_id,
                ):
                    raise ValueError(
                        "flat snapshot directory is unowned; only an exact owned "
                        "build or the strict writer-side legacy migration is supported"
                    )
                return payloads
        else:
            last_transient = FileNotFoundError(out_dir)
            wait_before_retry(attempt)
    raise RuntimeError(
        f"active snapshot changed during {max_attempts} read attempts: {out_dir}"
    ) from last_transient


def _install_snapshot_revision(
    store: Path,
    artifacts: dict[str, dict[str, Any]],
    *,
    output_kind: str,
    repo_id: str,
) -> tuple[Path, bool]:
    revision = _revision_hash(artifacts)
    recomputed = _bundle_hash_for_artifacts(artifacts)
    if recomputed != revision:
        raise ValueError(
            f"requested snapshot revision differs from artifacts: {revision} != {recomputed}"
    )
    target = store / revision
    if os.path.lexists(target):
        _validate_owned_snapshot_revision(
            target,
            requested_revision=revision,
            output_kind=output_kind,
            repo_id=repo_id,
        )
        return target, False
    staging_dir = Path(tempfile.mkdtemp(prefix=".stage-", dir=store))
    try:
        write_output_owner(
            staging_dir,
            kind=f"{output_kind}_staging",
            repo_id=repo_id,
        )
        _write_snapshot_artifacts(staging_dir, artifacts)
        _validate_snapshot_directory(staging_dir)
        _fsync_snapshot_tree(staging_dir)
        # The final immutable revision owns the normal output kind; persist the
        # ownership change before publishing its directory entry.
        write_output_owner(staging_dir, kind=output_kind, repo_id=repo_id)
        _fsync_snapshot_tree(staging_dir)
        try:
            _atomic_install_directory_noreplace(staging_dir, target)
        except FileExistsError:
            # Concurrent publishers may install the same content-addressed
            # revision. Reuse it only after validating the exact owned bundle.
            _validate_owned_snapshot_revision(
                target,
                requested_revision=revision,
                output_kind=output_kind,
                repo_id=repo_id,
            )
            return target, False
        _fsync_directory(store)
        return target, True
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir)


def _prune_snapshot_revisions(
    store: Path,
    *,
    active_revision: str,
    output_kind: str,
    repo_id: str,
    retention: int = SNAPSHOT_REVISION_RETENTION,
) -> tuple[list[Path], list[str], list[Path]]:
    """Prune old inactive revisions without racing pinned cross-process readers."""

    if retention < 2:
        raise ValueError("snapshot revision retention must keep at least two revisions")
    discovered = sorted(
        (
            path
            for path in store.iterdir()
            if path.is_dir()
            and not path.is_symlink()
            and SNAPSHOT_REVISION_HASH_RE.fullmatch(path.name)
        ),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
        reverse=True,
    )
    warnings: list[str] = []
    revisions: list[Path] = []
    for path in discovered:
        try:
            _validate_owned_snapshot_revision(
                path,
                requested_revision=path.name,
                output_kind=output_kind,
                repo_id=repo_id,
            )
            revisions.append(path)
        except (OSError, ValueError):
            warnings.append(f"invalid_or_unowned_revision_preserved:{path.name}")

    # Retention ranks only exact owned+valid revisions. Ambiguous directories
    # are preserved for review but can never consume a backup slot and thereby
    # cause an older valid revision to be deleted indirectly.
    inactive = [path for path in revisions if path.name != active_revision]
    keep = {active_revision, *(path.name for path in inactive[: retention - 1])}
    removed: list[Path] = []
    recovery_paths: list[Path] = []
    for path in inactive[retention - 1 :]:
        if path.name in keep:
            continue
        deleted = False
        quarantine: Path | None = None
        delete_started = False
        try:
            with _revision_lease(store, path.name, exclusive=True) as acquired:
                if not acquired:
                    warnings.append(f"revision_leased_preserved:{path.name}")
                    continue
                # Pin the directory entry before validation. A non-cooperating
                # writer may still replace the pathname while the advisory
                # lease is held; the post-rename inode check catches that race.
                expected_identity = _path_entry_identity(path)
                _validate_owned_snapshot_revision(
                    path,
                    requested_revision=path.name,
                    output_kind=output_kind,
                    repo_id=repo_id,
                )
                quarantine = store / (
                    f".prune-{path.name}-{secrets.token_hex(16)}"
                )
                _atomic_install_directory_noreplace(path, quarantine)
                _fsync_directory(store)
                if _path_entry_identity(quarantine) != expected_identity:
                    raise ValueError(
                        "snapshot revision pathname changed before quarantine"
                    )
                _validate_owned_snapshot_revision(
                    quarantine,
                    requested_revision=path.name,
                    output_kind=output_kind,
                    repo_id=repo_id,
                    require_directory_name=False,
                )
                if _path_entry_identity(quarantine) != expected_identity:
                    raise ValueError(
                        "snapshot revision quarantine identity changed during validation"
                    )
                fingerprint = _snapshot_tree_fingerprint(quarantine)
                if _path_entry_identity(quarantine) != expected_identity:
                    raise ValueError(
                        "snapshot revision quarantine changed during fingerprint"
                    )
                delete_started = True
                _delete_snapshot_tree_descriptor_pinned(
                    store,
                    quarantine,
                    expected_identity=expected_identity,
                    fingerprint=fingerprint,
                )
                quarantine = None
                deleted = True
                removed.append(path)
        except SnapshotDescriptorDeletionBlockedError as exc:
            recovery_paths.extend(exc.recovery_paths)
            warnings.append(
                f"revision_prune_descriptor_race_preserved:{path.name}"
            )
            warnings.append(f"invalid_or_unowned_revision_preserved:{path.name}")
        except (OSError, SnapshotPublicationBlockedError, ValueError):
            if quarantine is not None and os.path.lexists(quarantine):
                if delete_started:
                    warnings.append(
                        f"revision_prune_quarantine_pending:{quarantine.name}"
                    )
                else:
                    try:
                        _atomic_install_directory_noreplace(quarantine, path)
                    except FileExistsError:
                        warnings.append(
                            "revision_prune_race_quarantine_preserved:"
                            f"{quarantine.name}"
                        )
                    except OSError:
                        warnings.append(
                            "revision_prune_quarantine_restore_failed:"
                            f"{quarantine.name}"
                        )
                    else:
                        quarantine = None
                        try:
                            _fsync_directory(store)
                        except OSError:
                            warnings.append(
                                "revision_prune_restore_directory_fsync_failed:"
                                f"{path.name}"
                            )
            code = (
                "revision_deleted_directory_fsync_failed"
                if deleted
                else "invalid_or_unowned_revision_preserved"
            )
            warnings.append(f"{code}:{path.name}")
    return removed, warnings, recovery_paths


def promote_snapshot_artifacts(
    root: Path,
    out_dir: Path,
    artifacts: dict[str, dict[str, Any]],
    *,
    output_kind: str = "web_snapshot",
    force_unowned_output: bool = False,
) -> dict[str, Path]:
    """Promote one flat build artifact with rollback.

    This compatibility path is for committed demo fixtures and portable deploy
    bundles that are activated by their build/hosting layer. Live filesystem
    readers must use :func:`promote_snapshot_revisioned` instead.
    """

    errors = snapshot_contract_errors(artifacts)
    if errors:
        raise ValueError("invalid snapshot contract: " + "; ".join(errors))
    repo_id = str(
        ((artifacts.get("manifest.json") or {}).get("repo") or {}).get("repo_id")
        or "unknown"
    )
    out_dir = validate_managed_output_target(
        root,
        out_dir,
        kind=output_kind,
        repo_id=repo_id,
        force_unowned=force_unowned_output,
        recognize_legacy=lambda target: _is_legacy_snapshot_directory(
            target, expected_repo_id=repo_id
        ),
    )
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(
        tempfile.mkdtemp(prefix=f".{out_dir.name}.stage-", dir=out_dir.parent)
    )
    backup_dir = staging_dir.with_name(f"{staging_dir.name}.previous")
    old_moved = False
    try:
        _write_snapshot_artifacts(staging_dir, artifacts)
        write_output_owner(staging_dir, kind=output_kind, repo_id=repo_id)
        _validate_snapshot_directory(staging_dir)
        if out_dir.exists():
            os.replace(out_dir, backup_dir)
            old_moved = True
        try:
            os.replace(staging_dir, out_dir)
        except BaseException as promote_error:
            if old_moved and backup_dir.exists():
                if out_dir.exists():
                    shutil.rmtree(out_dir)
                try:
                    os.replace(backup_dir, out_dir)
                    old_moved = False
                except BaseException as rollback_error:
                    raise RuntimeError(
                        f"snapshot promotion and rollback failed; previous snapshot remains at {backup_dir}"
                    ) from rollback_error
            raise promote_error
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
            old_moved = False
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        # Never delete a backup after an unsuccessful rollback. Its unique
        # sibling path is the final recovery surface reported by the exception.
        if backup_dir.exists() and not old_moved:
            shutil.rmtree(backup_dir)
    return {
        name: out_dir / name
        for name in (artifacts.get("manifest.json") or {}).get("files") or []
    }


def _archive_exchanged_snapshot_directory(
    previous_dir: Path,
    store: Path,
    *,
    output_kind: str,
    repo_id: str,
) -> None:
    """Archive a valid exchanged snapshot; preserve any unrecognized tree."""

    entries = [
        path
        for path in previous_dir.iterdir()
        if path.name != OUTPUT_OWNER_FILENAME
    ]
    if not entries:
        shutil.rmtree(previous_dir)
        _fsync_directory(previous_dir.parent)
        return
    payloads = _load_snapshot_directory(previous_dir)
    manifest = payloads["manifest.json"]
    revision = str(manifest.get("bundle_hash") or "")
    manifest_repo_id = str((manifest.get("repo") or {}).get("repo_id") or "")
    if (
        not SNAPSHOT_REVISION_HASH_RE.fullmatch(revision)
        or manifest_repo_id != repo_id
        or _bundle_hash_for_artifacts(payloads) != revision
    ):
        raise ValueError("previous snapshot recovery does not match this repository")
    write_output_owner(previous_dir, kind=output_kind, repo_id=repo_id)
    _fsync_file(previous_dir / OUTPUT_OWNER_FILENAME)
    _fsync_directory(previous_dir)
    archived = store / revision
    if os.path.lexists(archived):
        _validate_owned_snapshot_revision(
            archived,
            requested_revision=revision,
            output_kind=output_kind,
            repo_id=repo_id,
        )
        shutil.rmtree(previous_dir)
        _fsync_directory_set(previous_dir.parent, store)
        return
    try:
        _atomic_install_directory_noreplace(previous_dir, archived)
    except FileExistsError:
        # A concurrent or adversarial target is never replaced. Only an exact
        # owned revision permits the exchanged duplicate to be discarded.
        _validate_owned_snapshot_revision(
            archived,
            requested_revision=revision,
            output_kind=output_kind,
            repo_id=repo_id,
        )
        shutil.rmtree(previous_dir)
    _fsync_directory_set(previous_dir.parent, store)


def _activation_cleanup_path(activation_dir: Path) -> Path:
    if ".cleanup-" in activation_dir.name:
        return activation_dir
    if ".activate-" not in activation_dir.name:
        raise ValueError(
            f"unrecognized snapshot activation container: {activation_dir}"
        )
    return activation_dir.with_name(
        activation_dir.name.replace(".activate-", ".cleanup-", 1)
    )


def _activation_name_for_cleanup(cleanup_dir: Path) -> str:
    if ".cleanup-" not in cleanup_dir.name:
        raise ValueError(f"unrecognized snapshot cleanup path: {cleanup_dir}")
    return cleanup_dir.name.replace(".cleanup-", ".activate-", 1)


def _cleanup_receipt_path(
    store: Path,
    cleanup_dir: Path,
    *,
    output_kind: str,
    repo_id: str,
) -> Path:
    basis = "\0".join((repo_id, output_kind, cleanup_dir.name)).encode("utf-8")
    return _cleanup_receipts_path(store) / f"{hashlib.sha256(basis).hexdigest()}.json"


def _cleanup_receipt_binding(
    *,
    receipt_id: str,
    activation_name: str,
    cleanup_name: str,
    cleanup_dev: str,
    cleanup_ino: str,
    cleanup_type: str,
    output_kind: str,
    repo_id: str,
) -> str:
    basis = "\0".join(
        (
            SNAPSHOT_CLEANUP_RECEIPT_SCHEMA_VERSION,
            receipt_id,
            activation_name,
            cleanup_name,
            cleanup_dev,
            cleanup_ino,
            cleanup_type,
            output_kind,
            repo_id,
        )
    ).encode("utf-8")
    return hashlib.sha256(basis).hexdigest()


def _expected_cleanup_receipt_static(
    cleanup_dir: Path,
    *,
    cleanup_identity: tuple[int, int, int, str | None],
    output_kind: str,
    repo_id: str,
) -> dict[str, str]:
    return {
        "schema_version": SNAPSHOT_CLEANUP_RECEIPT_SCHEMA_VERSION,
        "kind": f"{output_kind}_activation_cleanup",
        "repo_id": repo_id,
        "activation_name": _activation_name_for_cleanup(cleanup_dir),
        "cleanup_name": cleanup_dir.name,
        "cleanup_dev": str(cleanup_identity[0]),
        "cleanup_ino": str(cleanup_identity[1]),
        "cleanup_type": str(cleanup_identity[2]),
    }


def _cleanup_bound_payload(
    cleanup_dir: Path,
    *,
    receipt_id: str,
    cleanup_identity: tuple[int, int, int, str | None],
    output_kind: str,
    repo_id: str,
) -> dict[str, str]:
    if not SNAPSHOT_CLEANUP_RECEIPT_ID_RE.fullmatch(receipt_id):
        raise ValueError("snapshot cleanup identity is not high entropy")
    if cleanup_identity[2] != stat.S_IFDIR or cleanup_identity[3] is not None:
        raise ValueError("snapshot cleanup identity is not a real directory")
    payload = _expected_cleanup_receipt_static(
        cleanup_dir,
        cleanup_identity=cleanup_identity,
        output_kind=output_kind,
        repo_id=repo_id,
    )
    payload["receipt_id"] = receipt_id
    payload["binding_sha256"] = _cleanup_receipt_binding(
        receipt_id=receipt_id,
        activation_name=payload["activation_name"],
        cleanup_name=payload["cleanup_name"],
        cleanup_dev=payload["cleanup_dev"],
        cleanup_ino=payload["cleanup_ino"],
        cleanup_type=payload["cleanup_type"],
        output_kind=output_kind,
        repo_id=repo_id,
    )
    return payload


def _read_cleanup_intent(
    container: Path,
    cleanup_dir: Path,
    *,
    output_kind: str,
    repo_id: str,
) -> dict[str, str] | None:
    try:
        payload = json.loads(
            _read_snapshot_file_bytes(
                container,
                SNAPSHOT_CLEANUP_INTENT_FILENAME,
            ).decode("utf-8")
        )
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    normalized = {str(key): str(value) for key, value in payload.items()}
    receipt_id = normalized.get("receipt_id", "")
    try:
        cleanup_identity = _path_entry_identity(container)
        expected = _cleanup_bound_payload(
            cleanup_dir,
            receipt_id=receipt_id,
            cleanup_identity=cleanup_identity,
            output_kind=output_kind,
            repo_id=repo_id,
        )
    except (FileNotFoundError, SnapshotPublicationBlockedError, ValueError):
        return None
    return normalized if normalized == expected else None


def _ensure_cleanup_intent(
    container: Path,
    cleanup_dir: Path,
    *,
    output_kind: str,
    repo_id: str,
) -> dict[str, str]:
    intent = container / SNAPSHOT_CLEANUP_INTENT_FILENAME
    if os.path.lexists(intent):
        payload = _read_cleanup_intent(
            container,
            cleanup_dir,
            output_kind=output_kind,
            repo_id=repo_id,
        )
        if payload is None:
            raise ValueError(f"snapshot cleanup intent is unsafe: {intent}")
        return payload

    cleanup_identity = _path_entry_identity(container)
    payload = _cleanup_bound_payload(
        cleanup_dir,
        receipt_id=secrets.token_hex(16),
        cleanup_identity=cleanup_identity,
        output_kind=output_kind,
        repo_id=repo_id,
    )
    descriptor, temporary_name = tempfile.mkstemp(prefix=".intent-", dir=container)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(
                (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
            )
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, intent, follow_symlinks=False)
        except FileExistsError:
            observed = _read_cleanup_intent(
                container,
                cleanup_dir,
                output_kind=output_kind,
                repo_id=repo_id,
            )
            if observed is None:
                raise ValueError(f"snapshot cleanup intent is unsafe: {intent}")
            payload = observed
        _fsync_file(intent)
        _fsync_directory(container)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        _fsync_directory(container)
    return payload


def _validate_cleanup_receipts_store(
    store: Path,
    *,
    output_kind: str,
    repo_id: str,
) -> Path:
    receipts = _cleanup_receipts_path(store)
    if receipts.is_symlink() or not receipts.is_dir():
        raise ValueError(f"snapshot cleanup receipts directory is unsafe: {receipts}")
    try:
        owner = json.loads(
            _read_snapshot_file_bytes(receipts, OUTPUT_OWNER_FILENAME).decode("utf-8")
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"snapshot cleanup receipts are unowned: {receipts}") from exc
    if owner != {
        "schema_version": OUTPUT_OWNER_SCHEMA_VERSION,
        "kind": _cleanup_receipts_kind(output_kind),
        "repo_id": repo_id,
    }:
        raise ValueError(f"snapshot cleanup receipts are unowned: {receipts}")
    return receipts


def _read_cleanup_receipt(
    store: Path,
    cleanup_dir: Path,
    *,
    output_kind: str,
    repo_id: str,
    require_directory_match: bool = True,
) -> dict[str, str] | None:
    try:
        receipts = _validate_cleanup_receipts_store(
            store,
            output_kind=output_kind,
            repo_id=repo_id,
        )
        receipt = _cleanup_receipt_path(
            store,
            cleanup_dir,
            output_kind=output_kind,
            repo_id=repo_id,
        )
        payload = json.loads(
            _read_snapshot_file_bytes(receipts, receipt.name).decode("utf-8")
        )
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    normalized = {str(key): str(value) for key, value in payload.items()}
    receipt_id = normalized.get("receipt_id", "")
    if not SNAPSHOT_CLEANUP_RECEIPT_ID_RE.fullmatch(receipt_id):
        return None
    try:
        bound_identity = (
            int(normalized["cleanup_dev"]),
            int(normalized["cleanup_ino"]),
            int(normalized["cleanup_type"]),
            None,
        )
        expected = _cleanup_bound_payload(
            cleanup_dir,
            receipt_id=receipt_id,
            cleanup_identity=bound_identity,
            output_kind=output_kind,
            repo_id=repo_id,
        )
    except (KeyError, TypeError, ValueError):
        return None
    if normalized != expected:
        return None
    if require_directory_match:
        try:
            observed_identity = _path_entry_identity(cleanup_dir)
        except (FileNotFoundError, SnapshotPublicationBlockedError):
            return None
        if observed_identity[:3] != bound_identity[:3]:
            return None
    return normalized


def _ensure_cleanup_receipt(
    store: Path,
    cleanup_dir: Path,
    *,
    output_kind: str,
    repo_id: str,
    receipt_id: str | None = None,
) -> Path:
    receipts = _validate_cleanup_receipts_store(
        store,
        output_kind=output_kind,
        repo_id=repo_id,
    )
    receipt = _cleanup_receipt_path(
        store,
        cleanup_dir,
        output_kind=output_kind,
        repo_id=repo_id,
    )
    if os.path.lexists(receipt):
        observed = _read_cleanup_receipt(
            store,
            cleanup_dir,
            output_kind=output_kind,
            repo_id=repo_id,
        )
        if observed is None or (
            receipt_id is not None and observed["receipt_id"] != receipt_id
        ):
            raise ValueError(f"snapshot cleanup receipt is unsafe: {receipt}")
        return receipt

    receipt_id = receipt_id or secrets.token_hex(16)
    cleanup_identity = _path_entry_identity(cleanup_dir)
    payload = _cleanup_bound_payload(
        cleanup_dir,
        receipt_id=receipt_id,
        cleanup_identity=cleanup_identity,
        output_kind=output_kind,
        repo_id=repo_id,
    )
    descriptor, temporary_name = tempfile.mkstemp(prefix=".receipt-", dir=receipts)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(
                (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
            )
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, receipt, follow_symlinks=False)
        except FileExistsError:
            if _read_cleanup_receipt(
                store,
                cleanup_dir,
                output_kind=output_kind,
                repo_id=repo_id,
            ) is None:
                raise ValueError(f"snapshot cleanup receipt is unsafe: {receipt}")
        _fsync_file(receipt)
        _fsync_directory(receipts)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        _fsync_directory(receipts)
    return receipt


def _remove_cleanup_receipt(
    store: Path,
    cleanup_dir: Path,
    *,
    output_kind: str,
    repo_id: str,
) -> None:
    receipt = _cleanup_receipt_path(
        store,
        cleanup_dir,
        output_kind=output_kind,
        repo_id=repo_id,
    )
    if _read_cleanup_receipt(
        store,
        cleanup_dir,
        output_kind=output_kind,
        repo_id=repo_id,
        require_directory_match=False,
    ) is None:
        raise ValueError(f"snapshot cleanup receipt is missing or invalid: {receipt}")
    receipt.unlink()
    _fsync_directory(receipt.parent)


def _cleanup_receipt_identity(payload: dict[str, str]) -> tuple[int, int, int]:
    try:
        identity = (
            int(payload["cleanup_dev"]),
            int(payload["cleanup_ino"]),
            int(payload["cleanup_type"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("snapshot cleanup receipt identity is invalid") from exc
    if identity[2] != stat.S_IFDIR:
        raise ValueError("snapshot cleanup receipt is not bound to a directory")
    return identity


def _open_cleanup_directory_pinned(
    cleanup_dir: Path,
    receipt_payload: dict[str, str],
) -> tuple[int, int, tuple[int, int, int]]:
    expected_identity = _cleanup_receipt_identity(receipt_payload)
    parent_fd = os.open(cleanup_dir.parent, _directory_open_flags())
    cleanup_fd: int | None = None
    try:
        cleanup_fd = os.open(
            cleanup_dir.name,
            _directory_open_flags(),
            dir_fd=parent_fd,
        )
        pinned_identity = _stat_identity(os.fstat(cleanup_fd))
        parent_identity = _descriptor_entry_identity(parent_fd, cleanup_dir.name)
        if not (
            pinned_identity == parent_identity == expected_identity
        ):
            raise SnapshotCleanupBlockedError(
                "snapshot cleanup inode differs from its durable receipt",
                recovery_path=cleanup_dir,
            )
        return parent_fd, cleanup_fd, pinned_identity
    except BaseException:
        if cleanup_fd is not None:
            os.close(cleanup_fd)
        os.close(parent_fd)
        raise


def _require_pinned_cleanup_parent_entry(
    parent_fd: int,
    cleanup_fd: int,
    cleanup_dir: Path,
    *,
    expected_identity: tuple[int, int, int],
) -> None:
    try:
        parent_identity = _descriptor_entry_identity(parent_fd, cleanup_dir.name)
    except OSError as exc:
        raise SnapshotCleanupBlockedError(
            "snapshot cleanup pathname changed while its inode was pinned",
            recovery_path=cleanup_dir,
        ) from exc
    if not (
        parent_identity == _stat_identity(os.fstat(cleanup_fd)) == expected_identity
    ):
        raise SnapshotCleanupBlockedError(
            "snapshot cleanup pathname no longer names the receipted inode",
            recovery_path=cleanup_dir,
        )


def _unlink_regular_entry_at(directory_fd: int, name: str) -> None:
    entry_stat = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    if not stat.S_ISREG(entry_stat.st_mode):
        raise ValueError(f"snapshot cleanup entry is not regular: {name}")
    os.unlink(name, dir_fd=directory_fd)
    os.fsync(directory_fd)


def _remove_receipted_cleanup_directory_pinned(
    cleanup_dir: Path,
    receipt_payload: dict[str, str],
    *,
    remove_owner_marker: bool,
    remove_intent: bool,
) -> None:
    """Remove only the cleanup inode cryptographically bound by the receipt."""

    parent_fd, cleanup_fd, expected_identity = _open_cleanup_directory_pinned(
        cleanup_dir,
        receipt_payload,
    )
    try:
        expected_entries: set[str] = set()
        if remove_owner_marker:
            expected_entries.add(OUTPUT_OWNER_FILENAME)
        if remove_intent:
            expected_entries.add(SNAPSHOT_CLEANUP_INTENT_FILENAME)
        observed_entries = set(os.listdir(cleanup_fd))
        if observed_entries != expected_entries:
            raise SnapshotCleanupBlockedError(
                "snapshot cleanup inventory changed after receipt creation",
                recovery_path=cleanup_dir,
            )
        _require_pinned_cleanup_parent_entry(
            parent_fd,
            cleanup_fd,
            cleanup_dir,
            expected_identity=expected_identity,
        )
        if remove_intent:
            _unlink_regular_entry_at(
                cleanup_fd,
                SNAPSHOT_CLEANUP_INTENT_FILENAME,
            )
        _require_pinned_cleanup_parent_entry(
            parent_fd,
            cleanup_fd,
            cleanup_dir,
            expected_identity=expected_identity,
        )
        if remove_owner_marker:
            _unlink_regular_entry_at(cleanup_fd, OUTPUT_OWNER_FILENAME)
        if os.listdir(cleanup_fd):
            raise SnapshotCleanupBlockedError(
                "snapshot cleanup gained entries before final rmdir",
                recovery_path=cleanup_dir,
            )
        os.fsync(cleanup_fd)
        _require_pinned_cleanup_parent_entry(
            parent_fd,
            cleanup_fd,
            cleanup_dir,
            expected_identity=expected_identity,
        )
        # POSIX exposes no inode-conditional rmdir. This dirfd-relative call is
        # immediately preceded by the identity comparison above, leaving only
        # the unavoidable final compare-to-rmdir micro-window.
        os.rmdir(cleanup_dir.name, dir_fd=parent_fd)
        os.fsync(parent_fd)
    finally:
        os.close(cleanup_fd)
        os.close(parent_fd)


def _restore_unattested_cleanup_container(
    cleanup_dir: Path,
    activation_dir: Path,
    *,
    observed_cleanup_identity: tuple[int, int, int, str | None],
) -> None:
    """Restore an untrusted raced entry without replacing either pathname."""

    try:
        current_identity = _path_entry_identity(cleanup_dir)
    except (FileNotFoundError, SnapshotPublicationBlockedError) as exc:
        raise SnapshotCleanupBlockedError(
            "unattested snapshot cleanup changed again and remains preserved at "
            f"{cleanup_dir}",
            recovery_path=cleanup_dir,
        ) from exc
    if current_identity != observed_cleanup_identity:
        raise SnapshotCleanupBlockedError(
            "unattested snapshot cleanup identity changed again and remains "
            f"preserved at {cleanup_dir}",
            recovery_path=cleanup_dir,
        )
    try:
        _atomic_install_directory_noreplace(cleanup_dir, activation_dir)
    except FileExistsError as exc:
        raise SnapshotCleanupBlockedError(
            "unattested snapshot cleanup could not return to an occupied "
            f"activation pathname and remains preserved at {cleanup_dir}",
            recovery_path=cleanup_dir,
        ) from exc
    except OSError as exc:
        raise SnapshotCleanupBlockedError(
            f"unattested snapshot cleanup remains preserved at {cleanup_dir}",
            recovery_path=cleanup_dir,
        ) from exc
    try:
        _fsync_directory(cleanup_dir.parent)
    except OSError as exc:
        raise SnapshotCleanupBlockedError(
            "unattested snapshot cleanup was restored but its parent fsync failed: "
            f"{activation_dir}",
            recovery_path=activation_dir,
        ) from exc
    raise SnapshotCleanupBlockedError(
        "unattested snapshot cleanup was restored without clobbering to "
        f"{activation_dir}",
        recovery_path=activation_dir,
    )


def _remove_owned_activation_container(
    activation_dir: Path,
    store: Path,
    *,
    output_kind: str,
    repo_id: str,
) -> None:
    cleanup_dir = _activation_cleanup_path(activation_dir)
    if not output_is_owned(
        activation_dir,
        kind=f"{output_kind}_activation",
        repo_id=repo_id,
    ):
        raise ValueError(f"snapshot activation container is not owned: {activation_dir}")
    marker = activation_dir / OUTPUT_OWNER_FILENAME
    intent = activation_dir / SNAPSHOT_CLEANUP_INTENT_FILENAME
    entries = set(activation_dir.iterdir())
    if marker not in entries or not entries <= {marker, intent}:
        raise ValueError(
            f"snapshot activation container is not empty: {activation_dir}"
        )

    intent_payload = (
        _read_cleanup_intent(
            activation_dir,
            cleanup_dir,
            output_kind=output_kind,
            repo_id=repo_id,
        )
        if intent in entries
        else None
    )
    if intent in entries and intent_payload is None:
        raise ValueError(f"snapshot cleanup intent is unsafe: {intent}")

    if cleanup_dir != activation_dir:
        if intent_payload is None:
            intent_payload = _ensure_cleanup_intent(
                activation_dir,
                cleanup_dir,
                output_kind=output_kind,
                repo_id=repo_id,
            )
        try:
            activation_identity = _path_entry_identity(activation_dir)
        except (FileNotFoundError, SnapshotPublicationBlockedError) as exc:
            raise ValueError(
                f"snapshot activation changed before cleanup rename: {activation_dir}"
            ) from exc
        try:
            _atomic_install_directory_noreplace(activation_dir, cleanup_dir)
        except FileExistsError as exc:
            raise ValueError(
                f"snapshot cleanup tombstone already exists: {cleanup_dir}"
            ) from exc
        _fsync_directory(cleanup_dir.parent)
        marker = cleanup_dir / OUTPUT_OWNER_FILENAME
        intent = cleanup_dir / SNAPSHOT_CLEANUP_INTENT_FILENAME
        try:
            cleanup_identity = _path_entry_identity(cleanup_dir)
        except (FileNotFoundError, SnapshotPublicationBlockedError) as exc:
            raise ValueError(
                f"snapshot cleanup changed after rename: {cleanup_dir}"
            ) from exc
        reopened_intent = _read_cleanup_intent(
            cleanup_dir,
            cleanup_dir,
            output_kind=output_kind,
            repo_id=repo_id,
        )
        if (
            cleanup_identity != activation_identity
            or not output_is_owned(
                cleanup_dir,
                kind=f"{output_kind}_activation",
                repo_id=repo_id,
            )
            or set(cleanup_dir.iterdir()) != {marker, intent}
            or reopened_intent != intent_payload
        ):
            _restore_unattested_cleanup_container(
                cleanup_dir,
                activation_dir,
                observed_cleanup_identity=cleanup_identity,
            )
        intent_payload = reopened_intent
    else:
        receipt_payload = _read_cleanup_receipt(
            store,
            cleanup_dir,
            output_kind=output_kind,
            repo_id=repo_id,
        )
        if intent_payload is None and receipt_payload is None:
            raise ValueError(
                f"unreceipted snapshot cleanup tombstone is ambiguous: {cleanup_dir}"
            )

    if intent_payload is not None:
        _ensure_cleanup_receipt(
            store,
            cleanup_dir,
            output_kind=output_kind,
            repo_id=repo_id,
            receipt_id=intent_payload["receipt_id"],
        )
    receipt_payload = _read_cleanup_receipt(
        store,
        cleanup_dir,
        output_kind=output_kind,
        repo_id=repo_id,
    )
    if receipt_payload is None:
        raise SnapshotCleanupBlockedError(
            "snapshot cleanup inode does not match its receipt before removal",
            recovery_path=cleanup_dir,
        )
    _remove_receipted_cleanup_directory_pinned(
        cleanup_dir,
        receipt_payload,
        remove_owner_marker=True,
        remove_intent=intent_payload is not None,
    )
    _remove_cleanup_receipt(
        store,
        cleanup_dir,
        output_kind=output_kind,
        repo_id=repo_id,
    )


def _reconcile_snapshot_leftovers(
    root: Path,
    out_dir: Path,
    store: Path,
    *,
    output_kind: str,
    repo_id: str,
) -> tuple[list[str], list[Path]]:
    """Recover publisher-owned crash leftovers; preserve everything ambiguous."""

    warnings: list[str] = []
    recovery_paths: list[Path] = []
    for activation_dir in sorted(
        out_dir.parent.glob(f".{out_dir.name}.activate-*")
    ):
        if activation_dir.is_symlink() or not activation_dir.is_dir():
            warnings.append(f"unowned_activation_leftover_preserved:{activation_dir.name}")
            continue
        try:
            contained_output_path(root, activation_dir)
        except ValueError:
            warnings.append(f"escaped_activation_leftover_preserved:{activation_dir.name}")
            continue
        if not output_is_owned(
            activation_dir,
            kind=f"{output_kind}_activation",
            repo_id=repo_id,
        ):
            warnings.append(f"unowned_activation_leftover_preserved:{activation_dir.name}")
            continue
        entries = [
            path
            for path in activation_dir.iterdir()
            if path.name != OUTPUT_OWNER_FILENAME
        ]
        cleanup_dir = _activation_cleanup_path(activation_dir)
        intent = activation_dir / SNAPSHOT_CLEANUP_INTENT_FILENAME
        recoverable_cleanup = not entries or (
            set(entries) == {intent}
            and _read_cleanup_intent(
                activation_dir,
                cleanup_dir,
                output_kind=output_kind,
                repo_id=repo_id,
            )
            is not None
        )
        if recoverable_cleanup:
            try:
                _remove_owned_activation_container(
                    activation_dir,
                    store,
                    output_kind=output_kind,
                    repo_id=repo_id,
                )
            except (OSError, ValueError) as cleanup_error:
                explicit_recovery = getattr(cleanup_error, "recovery_path", None)
                candidate = (
                    Path(explicit_recovery)
                    if explicit_recovery is not None
                    and os.path.lexists(explicit_recovery)
                    else activation_dir
                )
                if not os.path.lexists(candidate):
                    candidate = cleanup_dir
                warnings.append(f"activation_cleanup_pending:{candidate.name}")
                if os.path.lexists(candidate):
                    recovery_paths.append(candidate)
            continue
        previous = activation_dir / "active"
        if entries != [previous] or previous.is_symlink() or not previous.is_dir():
            warnings.append(f"ambiguous_activation_leftover_preserved:{activation_dir.name}")
            recovery_paths.append(activation_dir)
            continue
        try:
            _archive_exchanged_snapshot_directory(
                previous,
                store,
                output_kind=output_kind,
                repo_id=repo_id,
            )
            _remove_owned_activation_container(
                activation_dir,
                store,
                output_kind=output_kind,
                repo_id=repo_id,
            )
        except (OSError, ValueError) as cleanup_error:
            warnings.append(f"activation_recovery_pending:{activation_dir.name}")
            explicit_recovery = getattr(cleanup_error, "recovery_path", None)
            candidate = (
                Path(explicit_recovery)
                if explicit_recovery is not None
                and os.path.lexists(explicit_recovery)
                else previous
            )
            if not os.path.lexists(candidate):
                candidate = _activation_cleanup_path(activation_dir)
            if not os.path.lexists(candidate):
                candidate = activation_dir
            if os.path.lexists(candidate):
                recovery_paths.append(candidate)

    for cleanup_dir in sorted(out_dir.parent.glob(f".{out_dir.name}.cleanup-*")):
        if cleanup_dir.is_symlink() or not cleanup_dir.is_dir():
            warnings.append(f"unsafe_cleanup_tombstone_preserved:{cleanup_dir.name}")
            continue
        receipt_payload = _read_cleanup_receipt(
            store,
            cleanup_dir,
            output_kind=output_kind,
            repo_id=repo_id,
        )
        if receipt_payload is None:
            entries = set(cleanup_dir.iterdir())
            marker = cleanup_dir / OUTPUT_OWNER_FILENAME
            intent = cleanup_dir / SNAPSHOT_CLEANUP_INTENT_FILENAME
            intent_payload = (
                _read_cleanup_intent(
                    cleanup_dir,
                    cleanup_dir,
                    output_kind=output_kind,
                    repo_id=repo_id,
                )
                if intent in entries
                else None
            )
            if (
                entries == {marker, intent}
                and intent_payload is not None
                and output_is_owned(
                    cleanup_dir,
                    kind=f"{output_kind}_activation",
                    repo_id=repo_id,
                )
            ):
                try:
                    _remove_owned_activation_container(
                        cleanup_dir,
                        store,
                        output_kind=output_kind,
                        repo_id=repo_id,
                    )
                except (OSError, ValueError):
                    warnings.append(
                        f"owned_cleanup_tombstone_pending:{cleanup_dir.name}"
                    )
                    recovery_paths.append(cleanup_dir)
                continue
            warnings.append(
                f"unreceipted_cleanup_tombstone_preserved:{cleanup_dir.name}"
            )
            recovery_paths.append(cleanup_dir)
            continue
        entries = set(cleanup_dir.iterdir())
        if not entries:
            try:
                _remove_receipted_cleanup_directory_pinned(
                    cleanup_dir,
                    receipt_payload,
                    remove_owner_marker=False,
                    remove_intent=False,
                )
                _remove_cleanup_receipt(
                    store,
                    cleanup_dir,
                    output_kind=output_kind,
                    repo_id=repo_id,
                )
            except (OSError, ValueError) as cleanup_error:
                warnings.append(f"empty_cleanup_tombstone_pending:{cleanup_dir.name}")
                receipt = _cleanup_receipt_path(
                    store,
                    cleanup_dir,
                    output_kind=output_kind,
                    repo_id=repo_id,
                )
                explicit_recovery = getattr(cleanup_error, "recovery_path", None)
                candidate = (
                    Path(explicit_recovery)
                    if explicit_recovery is not None
                    and os.path.lexists(explicit_recovery)
                    else (cleanup_dir if cleanup_dir.exists() else receipt)
                )
                if os.path.lexists(candidate):
                    recovery_paths.append(candidate)
            continue
        marker = cleanup_dir / OUTPUT_OWNER_FILENAME
        intent = cleanup_dir / SNAPSHOT_CLEANUP_INTENT_FILENAME
        intent_payload = (
            _read_cleanup_intent(
                cleanup_dir,
                cleanup_dir,
                output_kind=output_kind,
                repo_id=repo_id,
            )
            if intent in entries
            else None
        )
        receipt_matches_intent = intent_payload is None or (
            intent_payload["receipt_id"] == receipt_payload["receipt_id"]
        )
        if (
            entries in ({marker}, {marker, intent})
            and receipt_matches_intent
            and (intent not in entries or intent_payload is not None)
            and output_is_owned(
                cleanup_dir,
                kind=f"{output_kind}_activation",
                repo_id=repo_id,
            )
        ):
            try:
                _remove_owned_activation_container(
                    cleanup_dir,
                    store,
                    output_kind=output_kind,
                    repo_id=repo_id,
                )
            except (OSError, ValueError):
                warnings.append(f"owned_cleanup_tombstone_pending:{cleanup_dir.name}")
                recovery_paths.append(cleanup_dir)
            continue
        warnings.append(f"ambiguous_cleanup_tombstone_preserved:{cleanup_dir.name}")
        recovery_paths.append(cleanup_dir)

    receipts = _validate_cleanup_receipts_store(
        store,
        output_kind=output_kind,
        repo_id=repo_id,
    )
    for receipt in sorted(receipts.glob("*.json")):
        if receipt.name == OUTPUT_OWNER_FILENAME:
            continue
        try:
            raw_payload = json.loads(
                _read_snapshot_file_bytes(receipts, receipt.name).decode("utf-8")
            )
            cleanup_name = str(raw_payload.get("cleanup_name") or "")
            if (
                Path(cleanup_name).name != cleanup_name
                or not cleanup_name.startswith(f".{out_dir.name}.cleanup-")
            ):
                raise ValueError("cleanup receipt names an unsafe path")
            cleanup_dir = out_dir.parent / cleanup_name
            expected_receipt = _cleanup_receipt_path(
                store,
                cleanup_dir,
                output_kind=output_kind,
                repo_id=repo_id,
            )
            payload = _read_cleanup_receipt(
                store,
                cleanup_dir,
                output_kind=output_kind,
                repo_id=repo_id,
                require_directory_match=False,
            )
        except (OSError, AttributeError, ValueError, json.JSONDecodeError):
            payload = None
            expected_receipt = receipt
            cleanup_dir = out_dir.parent
        if payload is None or receipt != expected_receipt:
            warnings.append(f"invalid_cleanup_receipt_preserved:{receipt.name}")
            recovery_paths.append(receipt)
            continue
        if os.path.lexists(cleanup_dir) and _read_cleanup_receipt(
            store,
            cleanup_dir,
            output_kind=output_kind,
            repo_id=repo_id,
        ) is None:
            warnings.append(
                f"cleanup_receipt_inode_mismatch_preserved:{cleanup_dir.name}"
            )
            recovery_paths.extend((cleanup_dir, receipt))
            continue
        activation_dir = out_dir.parent / payload["activation_name"]
        if not os.path.lexists(cleanup_dir) and not os.path.lexists(activation_dir):
            try:
                receipt.unlink()
                _fsync_directory(receipts)
            except OSError:
                warnings.append(f"orphan_cleanup_receipt_pending:{receipt.name}")
                recovery_paths.append(receipt)

    for staging_dir in sorted(store.glob(".stage-*")):
        if staging_dir.is_symlink() or not staging_dir.is_dir():
            warnings.append(f"unowned_staging_leftover_preserved:{staging_dir.name}")
            continue
        if not output_is_owned(
            staging_dir,
            kind=f"{output_kind}_staging",
            repo_id=repo_id,
        ):
            warnings.append(f"unowned_staging_leftover_preserved:{staging_dir.name}")
            continue
        try:
            shutil.rmtree(staging_dir)
            _fsync_directory(store)
        except OSError:
            warnings.append(f"owned_staging_cleanup_failed:{staging_dir.name}")
            recovery_paths.append(staging_dir)
    return warnings, recovery_paths


def promote_snapshot_revisioned(
    root: Path,
    out_dir: Path,
    artifacts: dict[str, dict[str, Any]],
    *,
    output_kind: str = "web_snapshot",
    force_unowned_output: bool = False,
    retention: int = SNAPSHOT_REVISION_RETENTION,
) -> SnapshotWriteResult:
    """Activate one immutable snapshot revision through an atomic pointer.

    New bundles are built and validated below a managed sibling revision store.
    The compatibility path ``out_dir/<artifact>`` is an internal relative
    symlink to the active immutable revision and is switched with one atomic
    directory-entry operation. Existing directory layouts are migrated with an
    atomic name exchange on Darwin/Linux; unsupported platforms fail closed.
    """

    if fcntl is None or not (
        sys.platform == "darwin" or sys.platform.startswith("linux")
    ):
        raise OSError(
            errno.ENOTSUP,
            "live snapshot revision publication is supported only on Darwin "
            "and Linux; use the flat build artifact path for offline deployment",
        )
    if retention < 2:
        raise ValueError("snapshot revision retention must keep at least two revisions")
    errors = snapshot_contract_errors(artifacts)
    if errors:
        raise ValueError("invalid snapshot contract: " + "; ".join(errors))
    repo_id = str(
        ((artifacts.get("manifest.json") or {}).get("repo") or {}).get("repo_id")
        or "unknown"
    )
    raw_out = Path(out_dir)
    store_path = _revision_store_path(raw_out)
    previous_pointer: Path | None = None
    expected_active_identity: tuple[int, int, int, str | None] | None = None
    if raw_out.is_symlink():
        # Validate pointer shape/store before creating or modifying any sibling
        # path. The active revision itself is read only under the publication
        # lease, so another publisher cannot prune it during validation.
        _validate_revision_pointer_store(
            root,
            raw_out,
            store_path,
            output_kind=output_kind,
            repo_id=repo_id,
        )
        out_dir = raw_out
    else:
        out_dir = validate_managed_output_target(
            root,
            raw_out,
            kind=output_kind,
            repo_id=repo_id,
            force_unowned=force_unowned_output,
            recognize_legacy=lambda target: _is_legacy_snapshot_directory(
                target, expected_repo_id=repo_id
            ),
        )
        store_path = _revision_store_path(out_dir)
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    publication_lease = contextlib.ExitStack()
    publication_lease.enter_context(_publication_lease(root, out_dir))
    try:
        # State may have advanced while this publisher waited for the
        # cross-process lock. Revalidate the actual active path under the lock;
        # this also handles two first publishers racing an initially absent path.
        if out_dir.is_symlink():
            previous_pointer = _managed_revision_pointer_target(
                root,
                out_dir,
                store_path,
                output_kind=output_kind,
                repo_id=repo_id,
            )
            expected_active_identity = _path_entry_identity(out_dir)
        else:
            previous_pointer = None
            out_dir = validate_managed_output_target(
                root,
                out_dir,
                kind=output_kind,
                repo_id=repo_id,
                force_unowned=force_unowned_output,
                recognize_legacy=lambda target: _is_legacy_snapshot_directory(
                    target, expected_repo_id=repo_id
                ),
            )
            store_path = _revision_store_path(out_dir)
            expected_active_identity = (
                _path_entry_identity(out_dir)
                if os.path.lexists(out_dir)
                else None
            )
        store = _prepare_revision_store(
            root,
            out_dir,
            output_kind=output_kind,
            repo_id=repo_id,
        )
        cleanup_warnings, recovery_paths = _reconcile_snapshot_leftovers(
            root,
            out_dir,
            store,
            output_kind=output_kind,
            repo_id=repo_id,
        )
        revision_dir, _created_revision = _install_snapshot_revision(
            store,
            artifacts,
            output_kind=output_kind,
            repo_id=repo_id,
        )
        revision = revision_dir.name
        activation_dir = Path(
            tempfile.mkdtemp(prefix=f".{out_dir.name}.activate-", dir=out_dir.parent)
        )
        write_output_owner(
            activation_dir,
            kind=f"{output_kind}_activation",
            repo_id=repo_id,
        )
        pointer = activation_dir / "active"
        pointer.symlink_to(Path(store.name) / revision, target_is_directory=True)
        _fsync_snapshot_tree(activation_dir)
    except BaseException:
        publication_lease.close()
        raise
    activation_succeeded = False
    recovery_path: Path | None = None
    try:
        exchanged_existing = _activate_snapshot_pointer_cas(
            pointer,
            out_dir,
            expected_active_identity=expected_active_identity,
        )
        activation_succeeded = True
        if exchanged_existing and previous_pointer is None:
            # One-time migration of the exact flat directory pinned at
            # preflight. A changed pathname is exchanged back by the CAS helper.
            recovery_path = pointer

        # rename(2) and exchange mutate both directory entries. Persist the
        # source activation directory and destination parent immediately after
        # the commit point, before attempting archive/prune cleanup.
        try:
            _fsync_directory(activation_dir)
        except OSError:
            cleanup_warnings.append("activation_source_directory_fsync_failed")
        try:
            _fsync_directory(out_dir.parent)
        except OSError:
            cleanup_warnings.append("active_pointer_parent_fsync_failed")

        if recovery_path is not None:
            try:
                _archive_exchanged_snapshot_directory(
                    pointer,
                    store,
                    output_kind=output_kind,
                    repo_id=repo_id,
                )
                recovery_path = None
            except (OSError, ValueError):
                cleanup_warnings.append(
                    f"previous_snapshot_recovery_pending:{activation_dir.name}"
                )
                recovery_path = pointer if pointer.exists() else activation_dir
                recovery_paths.append(recovery_path)
        try:
            _removed, prune_warnings, prune_recovery = _prune_snapshot_revisions(
                store,
                active_revision=revision,
                output_kind=output_kind,
                repo_id=repo_id,
                retention=retention,
            )
            cleanup_warnings.extend(prune_warnings)
            recovery_paths.extend(prune_recovery)
        except (OSError, ValueError):
            cleanup_warnings.append("revision_prune_failed_after_commit")
    except BaseException:
        if not activation_succeeded:
            # The one-step activation did not commit. A revision created by
            # this serialized publisher cannot be referenced, so remove only
            # that exact owned+validated directory and leave the old path alone.
            if _created_revision and revision_dir.exists():
                with contextlib.suppress(OSError, ValueError):
                    _validate_owned_snapshot_revision(
                        revision_dir,
                        requested_revision=revision,
                        output_kind=output_kind,
                        repo_id=repo_id,
                    )
                    shutil.rmtree(revision_dir)
                    _fsync_directory(store)
        raise
    finally:
        if pointer.is_symlink():
            try:
                pointer.unlink()
            except OSError:
                if activation_succeeded:
                    cleanup_warnings.append(
                        f"activation_pointer_cleanup_failed:{activation_dir.name}"
                    )
                    recovery_paths.append(pointer)
        # After a successful exchange the previous directory is either archived
        # or intentionally retained at ``recovery_path``. Never recursively
        # delete that recovery surface from a finally block.
        if activation_dir.exists() and recovery_path is None:
            try:
                _remove_owned_activation_container(
                    activation_dir,
                    store,
                    output_kind=output_kind,
                    repo_id=repo_id,
                )
            except (OSError, ValueError) as cleanup_error:
                if activation_succeeded:
                    cleanup_path = _activation_cleanup_path(activation_dir)
                    cleanup_warnings.append(
                        f"activation_container_cleanup_failed:{activation_dir.name}"
                    )
                    explicit_recovery = getattr(
                        cleanup_error,
                        "recovery_path",
                        None,
                    )
                    candidate = (
                        Path(explicit_recovery)
                        if explicit_recovery is not None
                        and os.path.lexists(explicit_recovery)
                        else (
                            activation_dir
                            if activation_dir.exists()
                            else cleanup_path
                        )
                    )
                    if not os.path.lexists(candidate):
                        candidate = _cleanup_receipt_path(
                            store,
                            cleanup_path,
                            output_kind=output_kind,
                            repo_id=repo_id,
                        )
                    if os.path.lexists(candidate):
                        recovery_paths.append(candidate)
        try:
            publication_lease.close()
        except (OSError, ValueError):
            if activation_succeeded:
                cleanup_warnings.append("publication_lock_release_failed_after_commit")
    files = {
        name: out_dir / name
        for name in (artifacts.get("manifest.json") or {}).get("files") or []
    }
    snapshot_id = str((artifacts.get("manifest.json") or {}).get("snapshot_id") or "")
    unique_recovery = tuple(dict.fromkeys(recovery_paths))
    return SnapshotWriteResult(
        files,
        snapshot_id=snapshot_id,
        active_revision=revision,
        cleanup_warnings=tuple(dict.fromkeys(cleanup_warnings)),
        recovery_paths=unique_recovery,
    )


def prune_snapshot_revisions(
    root: Path,
    out_dir: Path,
    *,
    output_kind: str = "web_snapshot",
    repo_id: str,
    retention: int = SNAPSHOT_REVISION_RETENTION,
) -> SnapshotCleanupResult:
    """Prune inactive revisions while preserving active and leased bundles."""

    store = _revision_store_path(out_dir)
    _validate_revision_pointer_store(
        root,
        out_dir,
        store,
        output_kind=output_kind,
        repo_id=repo_id,
    )
    with _publication_lease(root, out_dir):
        active = _managed_revision_pointer_target(
            root,
            out_dir,
            store,
            output_kind=output_kind,
            repo_id=repo_id,
        )
        cleanup_warnings, recovery_paths = _reconcile_snapshot_leftovers(
            root,
            out_dir,
            store,
            output_kind=output_kind,
            repo_id=repo_id,
        )
        removed, prune_warnings, prune_recovery = _prune_snapshot_revisions(
            store,
            active_revision=active.name,
            output_kind=output_kind,
            repo_id=repo_id,
            retention=retention,
        )
        cleanup_warnings.extend(prune_warnings)
        recovery_paths.extend(prune_recovery)
    return SnapshotCleanupResult(
        removed,
        cleanup_warnings=tuple(dict.fromkeys(cleanup_warnings)),
        recovery_paths=tuple(dict.fromkeys(recovery_paths)),
    )


def validate_snapshot_output_location(
    root: Path,
    out_dir: Path,
    *,
    repo_id: str,
    output_kind: str = "web_snapshot",
) -> Path:
    """Preflight snapshot containment before the expensive snapshot build."""

    if out_dir.is_symlink():
        _validate_revision_pointer_store(
            root,
            out_dir,
            _revision_store_path(out_dir),
            output_kind=output_kind,
            repo_id=repo_id,
        )
        return out_dir
    return contained_output_path(root, out_dir)


def _snapshot_health_identity(
    root: Path,
    out_dir: Path,
    store: Path,
    *,
    output_kind: str,
    repo_id: str,
    max_attempts: int = 8,
) -> tuple[str, str | None, int, bool, float]:
    """Read a lease-pinned identity, caching only unchanged tree metadata."""

    started = time.perf_counter()
    last_transient: OSError | None = None
    for attempt in range(max_attempts):
        relative = _validate_revision_pointer_store(
            root,
            out_dir,
            store,
            output_kind=output_kind,
            repo_id=repo_id,
        )
        target = out_dir.parent / relative
        try:
            with _revision_lease(store, relative.name, exclusive=False) as acquired:
                if not acquired:
                    raise OSError(
                        errno.ENOTSUP,
                        "cross-process snapshot leases are unavailable",
                    )
                if not target.is_dir() or target.is_symlink():
                    raise FileNotFoundError(target)
                fingerprint = _snapshot_tree_fingerprint(target)
                cache_key = (
                    str(out_dir.parent.resolve(strict=True) / out_dir.name),
                    output_kind,
                    repo_id,
                    relative.name,
                )
                now = time.monotonic()
                with SNAPSHOT_HEALTH_VALIDATION_CACHE_LOCK:
                    cached = SNAPSHOT_HEALTH_VALIDATION_CACHE.get(cache_key)
                if (
                    cached is not None
                    and cached[0] >= now
                    and cached[1] == fingerprint
                ):
                    return (
                        cached[2],
                        cached[3],
                        cached[4],
                        True,
                        (time.perf_counter() - started) * 1000,
                    )

                payloads = _validate_owned_snapshot_revision(
                    target,
                    requested_revision=relative.name,
                    output_kind=output_kind,
                    repo_id=repo_id,
                )
                manifest = payloads["manifest.json"]
                snapshot_id = str(manifest.get("snapshot_id") or "") or None
                cache_value = (
                    now + SNAPSHOT_HEALTH_VALIDATION_CACHE_TTL_S,
                    fingerprint,
                    relative.name,
                    snapshot_id,
                    len(payloads),
                )
                with SNAPSHOT_HEALTH_VALIDATION_CACHE_LOCK:
                    if (
                        len(SNAPSHOT_HEALTH_VALIDATION_CACHE)
                        >= SNAPSHOT_HEALTH_VALIDATION_CACHE_MAX_ENTRIES
                    ):
                        oldest_key = min(
                            SNAPSHOT_HEALTH_VALIDATION_CACHE,
                            key=lambda key: SNAPSHOT_HEALTH_VALIDATION_CACHE[key][0],
                        )
                        SNAPSHOT_HEALTH_VALIDATION_CACHE.pop(oldest_key, None)
                    SNAPSHOT_HEALTH_VALIDATION_CACHE[cache_key] = cache_value
                return (
                    relative.name,
                    snapshot_id,
                    len(payloads),
                    False,
                    (time.perf_counter() - started) * 1000,
                )
        except FileNotFoundError as exc:
            last_transient = exc
            if attempt + 1 < max_attempts:
                time.sleep(
                    min(
                        SNAPSHOT_READ_RETRY_BASE_S * (2**attempt),
                        SNAPSHOT_READ_RETRY_MAX_S,
                    )
                )
                continue
    raise RuntimeError(
        f"active snapshot changed during {max_attempts} health attempts: {out_dir}"
    ) from last_transient


def snapshot_publication_status(
    root: Path,
    out_dir: Path,
    *,
    repo_id: str,
    output_kind: str = "web_snapshot",
) -> dict[str, Any]:
    """Return explicit publication capability and fully validated active identity."""

    platform_supported = fcntl is not None and (
        sys.platform == "darwin" or sys.platform.startswith("linux")
    )
    primitive: str | None = None
    if sys.platform == "darwin":
        primitive = "renamex_np(RENAME_SWAP)"
    elif sys.platform.startswith("linux"):
        with contextlib.suppress(AttributeError):
            getattr(ctypes.CDLL(None), "renameat2")
            primitive = "renameat2(RENAME_EXCHANGE)"

    layout = "absent"
    active_revision: str | None = None
    active_snapshot_id: str | None = None
    pointer_state = "not_applicable"
    validation_artifact_count = 0
    validation_cache_hit = False
    validation_duration_ms = 0.0
    store = _revision_store_path(out_dir)
    if out_dir.is_symlink():
        layout = "immutable_revision_relative_pointer"
        try:
            (
                active_revision,
                active_snapshot_id,
                validation_artifact_count,
                validation_cache_hit,
                validation_duration_ms,
            ) = _snapshot_health_identity(
                root,
                out_dir,
                store,
                output_kind=output_kind,
                repo_id=repo_id,
            )
            pointer_state = "full_inventory_owner_repo_and_hash_valid"
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError):
            pointer_state = "invalid"
    elif out_dir.is_dir():
        layout = "flat_build_directory"
    elif out_dir.exists():
        layout = "unsafe_non_directory"

    activation_owned_pending = 0
    activation_unowned_preserved = 0
    for candidate in out_dir.parent.glob(f".{out_dir.name}.activate-*"):
        if candidate.is_symlink() or not candidate.is_dir():
            activation_unowned_preserved += 1
        elif output_is_owned(
            candidate,
            kind=f"{output_kind}_activation",
            repo_id=repo_id,
        ):
            activation_owned_pending += 1
        else:
            activation_unowned_preserved += 1
    cleanup_empty_pending = 0
    cleanup_owned_pending = 0
    cleanup_ambiguous_preserved = 0
    for candidate in out_dir.parent.glob(f".{out_dir.name}.cleanup-*"):
        if candidate.is_symlink() or not candidate.is_dir():
            cleanup_ambiguous_preserved += 1
            continue
        receipt_payload = _read_cleanup_receipt(
            store,
            candidate,
            output_kind=output_kind,
            repo_id=repo_id,
        )
        if receipt_payload is None:
            entries = set(candidate.iterdir())
            marker = candidate / OUTPUT_OWNER_FILENAME
            intent = candidate / SNAPSHOT_CLEANUP_INTENT_FILENAME
            intent_payload = (
                _read_cleanup_intent(
                    candidate,
                    candidate,
                    output_kind=output_kind,
                    repo_id=repo_id,
                )
                if intent in entries
                else None
            )
            if (
                entries == {marker, intent}
                and intent_payload is not None
                and output_is_owned(
                    candidate,
                    kind=f"{output_kind}_activation",
                    repo_id=repo_id,
                )
            ):
                cleanup_owned_pending += 1
            else:
                cleanup_ambiguous_preserved += 1
            continue
        entries = set(candidate.iterdir())
        if not entries:
            cleanup_empty_pending += 1
        else:
            marker = candidate / OUTPUT_OWNER_FILENAME
            intent = candidate / SNAPSHOT_CLEANUP_INTENT_FILENAME
            intent_payload = (
                _read_cleanup_intent(
                    candidate,
                    candidate,
                    output_kind=output_kind,
                    repo_id=repo_id,
                )
                if intent in entries
                else None
            )
            if (
                entries in ({marker}, {marker, intent})
                and (intent not in entries or intent_payload is not None)
                and (
                    intent_payload is None
                    or intent_payload["receipt_id"] == receipt_payload["receipt_id"]
                )
                and output_is_owned(
                    candidate,
                    kind=f"{output_kind}_activation",
                    repo_id=repo_id,
                )
            ):
                cleanup_owned_pending += 1
            else:
                cleanup_ambiguous_preserved += 1
    cleanup_orphan_receipts_pending = 0
    cleanup_invalid_receipts_preserved = 0
    receipts = _cleanup_receipts_path(store)
    if receipts.is_dir() and not receipts.is_symlink():
        for receipt in receipts.glob("*.json"):
            if receipt.name == OUTPUT_OWNER_FILENAME:
                continue
            try:
                raw_payload = json.loads(
                    _read_snapshot_file_bytes(receipts, receipt.name).decode("utf-8")
                )
                cleanup_name = str(raw_payload.get("cleanup_name") or "")
                if (
                    Path(cleanup_name).name != cleanup_name
                    or not cleanup_name.startswith(f".{out_dir.name}.cleanup-")
                ):
                    raise ValueError("unsafe cleanup name")
                cleanup_dir = out_dir.parent / cleanup_name
                payload = _read_cleanup_receipt(
                    store,
                    cleanup_dir,
                    output_kind=output_kind,
                    repo_id=repo_id,
                    require_directory_match=False,
                )
            except (OSError, AttributeError, ValueError, json.JSONDecodeError):
                payload = None
                cleanup_dir = out_dir.parent
            if payload is None:
                cleanup_invalid_receipts_preserved += 1
                continue
            if os.path.lexists(cleanup_dir) and _read_cleanup_receipt(
                store,
                cleanup_dir,
                output_kind=output_kind,
                repo_id=repo_id,
            ) is None:
                cleanup_invalid_receipts_preserved += 1
                continue
            activation_dir = out_dir.parent / payload["activation_name"]
            if not os.path.lexists(cleanup_dir) and not os.path.lexists(
                activation_dir
            ):
                cleanup_orphan_receipts_pending += 1
    owned_recovery = (
        activation_owned_pending
        + cleanup_empty_pending
        + cleanup_owned_pending
        + cleanup_orphan_receipts_pending
    )
    unowned_recovery = (
        activation_unowned_preserved
        + cleanup_ambiguous_preserved
        + cleanup_invalid_receipts_preserved
    )
    leases_state = "absent"
    if store.is_dir() and not store.is_symlink():
        leases = store / "leases"
        leases_state = (
            "safe_directory"
            if leases.is_dir() and not leases.is_symlink()
            else "unsafe"
        )
    return {
        "version": "wiki_filesystem_snapshot_publication.v1",
        "publication_supported": platform_supported,
        "platform": sys.platform,
        "layout": layout,
        "pointer_state": pointer_state,
        "active_revision": active_revision,
        "active_snapshot_id": active_snapshot_id,
        "reader_contract": "filesystem_consumer_resolves_pointer_once_and_validates_envelope",
        "validation": {
            "mode": "lease_pinned_full_inventory_owner_repo_and_sha256",
            "cache_ttl_seconds": SNAPSHOT_HEALTH_VALIDATION_CACHE_TTL_S,
            "budget_ms": SNAPSHOT_HEALTH_VALIDATION_BUDGET_MS,
            "cache_hit": validation_cache_hit,
            "metadata_fingerprint_checked_on_cache_hit": True,
            "artifact_count": validation_artifact_count,
            "duration_ms": round(validation_duration_ms, 3),
            "within_budget": (
                validation_duration_ms <= SNAPSHOT_HEALTH_VALIDATION_BUDGET_MS
            ),
        },
        "retention": SNAPSHOT_REVISION_RETENTION,
        "leases_state": leases_state,
        "recovery": {
            "owned_pending": owned_recovery,
            "unowned_preserved": unowned_recovery,
            "activation_owned_pending": activation_owned_pending,
            "activation_unowned_preserved": activation_unowned_preserved,
            "cleanup_empty_pending": cleanup_empty_pending,
            "cleanup_owned_pending": cleanup_owned_pending,
            "cleanup_ambiguous_preserved": cleanup_ambiguous_preserved,
            "cleanup_orphan_receipts_pending": cleanup_orphan_receipts_pending,
            "cleanup_invalid_receipts_preserved": (
                cleanup_invalid_receipts_preserved
            ),
        },
        "legacy_directory_migration": {
            "supported": platform_supported and primitive is not None,
            "primitive": primitive,
            "filesystem_support": "probed_on_first_exchange",
        },
        "durability": {
            "live_files_fsynced_before_activation": platform_supported,
            "revision_store_and_staging_directories_fsynced_before_commit": (
                platform_supported
            ),
            "activation_source_and_destination_parent_fsync_attempted_after_commit": (
                platform_supported
            ),
            "archive_source_and_destination_directories_fsync_attempted": (
                platform_supported
            ),
            "post_commit_fsync_failures_return_cleanup_warnings": True,
            "flat_build_host_activation_required": True,
        },
        "deletion_safety": {
            "prune_recursive_delete": "descriptor_pinned_no_follow",
            "cleanup_receipt_binding": "directory_dev_ino_type",
            "posix_final_compare_to_rmdir_window": (
                "unavoidable_without_inode_conditional_rmdir"
            ),
        },
        "flat_build_supported": True,
    }


def write_snapshot(
    root: Path,
    out_dir: Path,
    config: WikiConfig | None = None,
    *,
    clean: bool = False,
    mode: str = "static",
    content_sidecars: bool = False,
    force_unowned_output: bool = False,
    publication: str = "auto",
) -> dict[str, Path] | SnapshotWriteResult:
    config = config or load_config(root)
    payloads = build_snapshot(
        root, config, mode=mode, content_sidecars=content_sidecars
    )
    artifacts = prepare_snapshot_artifacts(
        root, config, payloads, content_sidecars=content_sidecars
    )
    errors = snapshot_contract_errors(artifacts)
    if errors:
        raise ValueError("invalid snapshot contract: " + "; ".join(errors))
    # ``clean`` remains a CLI/API compatibility argument. A complete immutable
    # revision is activated as one unit, so stale per-file artifacts cannot
    # survive in the active view.
    _ = clean
    if publication not in {"auto", "live", "flat_build"}:
        raise ValueError("publication must be auto, live or flat_build")
    live_supported = fcntl is not None and (
        sys.platform == "darwin" or sys.platform.startswith("linux")
    )
    use_flat_build = publication == "flat_build" or (
        publication == "auto" and mode == "static" and not live_supported
    )
    if use_flat_build:
        return promote_snapshot_artifacts(
            root,
            out_dir,
            artifacts,
            force_unowned_output=force_unowned_output,
        )
    return promote_snapshot_revisioned(
        root,
        out_dir,
        artifacts,
        force_unowned_output=force_unowned_output,
    )
