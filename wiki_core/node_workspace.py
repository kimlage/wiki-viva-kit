from __future__ import annotations

import contextlib
import fcntl
import hashlib
import hmac
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from wiki_core.git_safety import (
    GitSafetyError,
    require_safe_local_config,
    resolved_git_executable,
    sanitized_git_argv,
    sanitized_git_environment,
)
from wiki_core.process_safety import (
    ProcessSafetyError,
    run_bounded_process,
    start_process_group,
    terminate_process_group,
)


LEGACY_MANIFEST_SCHEMA_VERSION = "wiki_viva_node_workspace.v1"
POLICY_SCHEMA_VERSION = "wiki_viva_node_workspace_policy.v2"
MANIFEST_SCHEMA_VERSION = POLICY_SCHEMA_VERSION
AUTHORITY_SCHEMA_VERSION = "wiki_viva_node_workspace_authority.v1"
RECEIPT_SCHEMA_VERSION = "wiki_viva_node_workspace_receipt.v2"
WORKSPACE_RELATIVE = Path("apps/wiki-cockpit")
MANIFEST_RELATIVE = WORKSPACE_RELATIVE / "node-workspace.lock.json"
PACKAGE_RELATIVE = WORKSPACE_RELATIVE / "package.json"
PACKAGE_LOCK_RELATIVE = WORKSPACE_RELATIVE / "package-lock.json"
NODE_MODULES_RELATIVE = WORKSPACE_RELATIVE / "node_modules"
INSTALL_TIMEOUT_SECONDS = 180
COMMAND_TIMEOUT_SECONDS = 1200
MAX_TREE_FILES = 50_000
MAX_TREE_BYTES = 1024 * 1024 * 1024
MAX_COMMAND_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_NODE_EXECUTABLE_BYTES = 256 * 1024 * 1024
ALLOWED_SCRIPTS = (
    "build",
    "check:architecture",
    "check:assets",
    "check:bundle",
    "check:release-matrix",
    "test",
    "test:e2e:operator",
    "test:e2e:release",
    "test:gates",
    "test:visual",
    "test:visual:update",
)
ALLOWED_INVOCATIONS: Mapping[str, tuple[tuple[str, ...], ...]] = {
    script: ((),) for script in ALLOWED_SCRIPTS
}
ALLOWED_INVOCATIONS = {
    **ALLOWED_INVOCATIONS,
    "test": ((), ("--reporter=tap",)),
}
ALLOWED_COCKPIT_ENV_KEYS = frozenset(
    {
        "WIKI_COCKPIT_EXPECT_ACTIVE_PACKS",
        "WIKI_COCKPIT_EXPECT_ADAPTER_HASH",
        "WIKI_COCKPIT_EXPECT_CAPABILITIES",
        "WIKI_COCKPIT_EXPECT_COMPOSITION_SHA256",
        "WIKI_COCKPIT_EXPECT_CONSUMER_HEAD",
        "WIKI_COCKPIT_EXPECT_EXPERIENCE_PACK_COMPOSITION_VERSION",
        "WIKI_COCKPIT_EXPECT_PUBLIC_RELEASE_SHA",
        "WIKI_COCKPIT_EXPECT_REPO_ID",
        "WIKI_COCKPIT_EXPECT_RUNTIME_VERSION",
        "WIKI_COCKPIT_EXPECT_SERVER_VERSION",
        "WIKI_COCKPIT_EXPECT_SNAPSHOT_HASH",
        "WIKI_COCKPIT_EXPECT_SNAPSHOT_REVISION",
        "WIKI_COCKPIT_EXPECT_SNAPSHOT_VERSION",
        "WIKI_COCKPIT_EXPECT_TEMPORAL_EVENT_VERSION",
        "WIKI_COCKPIT_EXPECT_TEMPORAL_GRAPH_VERSION",
        "WIKI_COCKPIT_MIN_PAGES",
        "WIKI_COCKPIT_REAL_BASE_URL",
        "WIKI_COCKPIT_SNAPSHOT_URL",
    }
)
_SECRET_ENV_KEY_RE = re.compile(
    r"(?:^|_)(?:API_?KEY|AUTH|COOKIE|CREDENTIAL|PASS(?:WORD)?|SECRET|SESSION|SIGNATURE|TOKEN)(?:_|$)",
    re.IGNORECASE,
)
_SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class NodeWorkspaceError(ValueError):
    def __init__(self, code: str, message: str, *, next_action: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.next_action = next_action


@dataclass(frozen=True)
class CommandResult:
    output: bytes
    receipt: dict[str, Any]


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    output: bytes


@dataclass(frozen=True)
class CertifiedExecutionContext:
    policy: Mapping[str, Any]
    authority: Mapping[str, Any]
    authority_sha256: str
    node: Mapping[str, Any]
    npm: Mapping[str, Any]
    environment: Mapping[str, str]


@dataclass(frozen=True)
class ProcessSpec:
    argv: tuple[str, ...]
    cwd: Path
    environment: Mapping[str, str]


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _bounded_regular_bytes(path: Path, *, label: str, limit: int) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except (OSError, ValueError) as exc:
        raise NodeWorkspaceError(
            "node_workspace_input_missing",
            f"{label} is not one regular file",
            next_action="restore the certified Node workspace inputs",
        ) from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise NodeWorkspaceError(
                "node_workspace_input_missing",
                f"{label} is not one regular file",
                next_action="restore the certified Node workspace inputs",
            )
        if before.st_nlink != 1:
            raise NodeWorkspaceError(
                "node_workspace_unsafe_hardlink",
                f"{label} is not one uniquely linked regular file",
                next_action="restore the certified Node workspace inputs",
            )
        if before.st_size > limit:
            raise NodeWorkspaceError(
                "node_workspace_input_oversized",
                f"{label} exceeds its bounded contract",
                next_action="reduce and recertify the Node workspace input",
            )
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            raw = handle.read(limit + 1)
        after = os.fstat(descriptor)
        if len(raw) > limit:
            raise NodeWorkspaceError(
                "node_workspace_input_oversized",
                f"{label} exceeds its bounded contract",
                next_action="reduce and recertify the Node workspace input",
            )
        if (
            before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_mode != after.st_mode
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
            or before.st_nlink != after.st_nlink
            or after.st_nlink != 1
            or len(raw) != after.st_size
        ):
            raise NodeWorkspaceError(
                "node_workspace_input_changed",
                f"{label} changed while it was being verified",
                next_action="stop concurrent mutation and restore the certified input",
            )
        return raw
    finally:
        os.close(descriptor)


def _bounded_regular_sha256(path: Path, *, label: str, limit: int) -> tuple[str, int]:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except (OSError, ValueError) as exc:
        raise NodeWorkspaceError(
            "node_workspace_runtime_invalid",
            f"{label} is not safely readable",
            next_action="restore the exact certified Node/npm toolchain",
        ) from exc
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_size <= 0
            or metadata.st_size > limit
        ):
            raise NodeWorkspaceError(
                "node_workspace_runtime_invalid",
                f"{label} exceeds its regular-file authority",
                next_action="restore the exact certified Node/npm toolchain",
            )
        digest = hashlib.sha256()
        total = 0
        before = metadata
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise NodeWorkspaceError(
                        "node_workspace_runtime_invalid",
                        f"{label} exceeds its bounded authority",
                        next_action="restore the exact certified Node/npm toolchain",
                    )
                digest.update(chunk)
        after = os.fstat(descriptor)
        if (
            before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_mode != after.st_mode
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
            or before.st_nlink != after.st_nlink
            or after.st_nlink != 1
            or total != after.st_size
        ):
            raise NodeWorkspaceError(
                "node_workspace_runtime_invalid",
                f"{label} changed while its runtime authority was being verified",
                next_action="restore the exact certified Node/npm toolchain",
            )
        return digest.hexdigest(), total
    finally:
        os.close(descriptor)


def _platform_identity() -> dict[str, str]:
    system = platform.system().strip().lower()
    machine = platform.machine().strip().lower()
    if (
        re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,31}", system) is None
        or re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,31}", machine) is None
    ):
        raise NodeWorkspaceError(
            "node_workspace_platform_invalid",
            "the active Node platform identity is not canonical",
            next_action="use a supported release-certification platform",
        )
    return {"platform_system": system, "platform_machine": machine}


def resolved_node_authority() -> dict[str, Any]:
    executable = shutil.which("node")
    if executable is None:
        raise NodeWorkspaceError(
            "node_unavailable",
            "Node.js is unavailable in the active certified toolchain",
            next_action="install the exact Node/npm toolchain certified by the release",
        )
    try:
        resolved = Path(executable).resolve(strict=True)
        runtime_root = resolved.parent.parent.resolve(strict=True)
        resolved.relative_to(runtime_root)
    except (OSError, ValueError) as exc:
        raise NodeWorkspaceError(
            "node_authority_invalid",
            "the active Node.js executable cannot be resolved safely",
            next_action="install the exact Node/npm toolchain certified by the release",
        ) from exc
    executable_sha256, executable_bytes = _bounded_regular_sha256(
        resolved, label="Node.js executable", limit=MAX_NODE_EXECUTABLE_BYTES
    )
    runtime_tree = tree_summary(runtime_root)
    result = _run_bounded(
        [str(resolved), "--version"],
        cwd=resolved.parent,
        env={"PATH": str(resolved.parent), "LANG": "C"},
        timeout=30,
        output_limit=1024,
        timeout_error=(
            "node_authority_invalid",
            "the active Node.js version probe timed out",
            "install the exact Node/npm toolchain certified by the release",
        ),
        output_error=(
            "node_authority_invalid",
            "the active Node.js version probe returned oversized output",
            "install the exact Node/npm toolchain certified by the release",
        ),
    )
    try:
        version = result.output.decode("ascii", "strict").strip().removeprefix("v")
    except UnicodeDecodeError as exc:
        raise NodeWorkspaceError(
            "node_authority_invalid",
            "the active Node.js version is not canonical",
            next_action="install the exact Node/npm toolchain certified by the release",
        ) from exc
    if result.returncode != 0 or _SEMVER_RE.fullmatch(version) is None:
        raise NodeWorkspaceError(
            "node_authority_invalid",
            "the active Node.js version is not canonical",
            next_action="install the exact Node/npm toolchain certified by the release",
        )
    return {
        "name": "node-resolved",
        "version": version,
        **_platform_identity(),
        "executable_sha256": executable_sha256,
        "executable_bytes": executable_bytes,
        "runtime_tree_sha256": runtime_tree["tree_sha256"],
        "runtime_entry_count": runtime_tree["entry_count"],
        "runtime_total_bytes": runtime_tree["total_bytes"],
        "executable": str(resolved),
        "runtime_root": str(runtime_root),
    }


def node_toolchain_identity() -> dict[str, str]:
    return _node_identity_from_authority(resolved_node_authority())


def _node_identity_from_authority(authority: Mapping[str, Any]) -> dict[str, str]:
    return {
        "name": "node-resolved",
        "version": (
            f"{authority['version']}+{authority['platform_system']}."
            f"{authority['platform_machine']}.runtime.{authority['runtime_tree_sha256']}"
        ),
    }


def _node_manifest_authority(authority: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in authority.items()
        if key not in {"executable", "runtime_root"}
    }


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    terminate_process_group(process)


def _run_bounded(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout: int,
    output_limit: int,
    timeout_error: tuple[str, str, str],
    output_error: tuple[str, str, str],
) -> ProcessResult:
    try:
        result = run_bounded_process(
            argv,
            cwd=cwd,
            env=env,
            timeout=timeout,
            output_limit=output_limit,
            popen_factory=subprocess.Popen,
        )
    except OSError as exc:
        raise NodeWorkspaceError(
            "node_workspace_process_unavailable",
            "a certified Node workspace process could not be started",
            next_action="restore the exact release toolchain and retry",
        ) from exc
    except ProcessSafetyError as exc:
        if exc.reason == "output_limit":
            code, message, next_action = output_error
            raise NodeWorkspaceError(code, message, next_action=next_action)
        if exc.reason == "timeout":
            code, message, next_action = timeout_error
            raise NodeWorkspaceError(code, message, next_action=next_action)
        raise NodeWorkspaceError(
            "node_workspace_process_unavailable",
            "a certified Node workspace process could not be terminated and verified",
            next_action="discard the command result and restore the exact release toolchain",
        ) from exc
    return ProcessResult(returncode=result.returncode, output=result.output)


def _safe_symlink(root: Path, path: Path) -> str:
    target = os.readlink(path)
    if not target or "\x00" in target or Path(target).is_absolute():
        raise NodeWorkspaceError(
            "node_workspace_unsafe_symlink",
            "the Node workspace contains an unsafe symbolic link",
            next_action="reinstall the certified dependency tree without escaping links",
        )
    try:
        (path.parent / target).resolve(strict=True).relative_to(
            root.resolve(strict=True)
        )
    except (OSError, ValueError) as exc:
        raise NodeWorkspaceError(
            "node_workspace_unsafe_symlink",
            "the Node workspace contains an escaping or broken symbolic link",
            next_action="reinstall the certified dependency tree without escaping links",
        ) from exc
    return target


def _read_tree_file(
    path: Path, *, remaining: int, expected: os.stat_result
) -> tuple[bytes, os.stat_result]:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise NodeWorkspaceError(
            "node_workspace_tree_changed",
            "the Node dependency tree changed while it was being verified",
            next_action="stop concurrent mutation and rematerialize the workspace",
        ) from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise NodeWorkspaceError(
                "node_workspace_unsafe_hardlink",
                "the Node dependency tree contains an aliased or unsafe regular file",
                next_action="reinstall the certified dependency tree without hard links",
            )
        if before.st_size > remaining:
            raise NodeWorkspaceError(
                "node_workspace_tree_oversized",
                "the Node dependency tree exceeds its bounded authority",
                next_action="reduce and recertify the dependency closure",
            )
        if (
            expected.st_dev != before.st_dev
            or expected.st_ino != before.st_ino
            or expected.st_mode != before.st_mode
            or expected.st_size != before.st_size
            or expected.st_nlink != before.st_nlink
            or expected.st_mtime_ns != before.st_mtime_ns
            or expected.st_ctime_ns != before.st_ctime_ns
        ):
            raise NodeWorkspaceError(
                "node_workspace_tree_changed",
                "the Node dependency tree changed while it was being verified",
                next_action="stop concurrent mutation and rematerialize the workspace",
            )
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            raw = handle.read(remaining + 1)
        if len(raw) > remaining:
            raise NodeWorkspaceError(
                "node_workspace_tree_oversized",
                "the Node dependency tree exceeds its bounded authority",
                next_action="reduce and recertify the dependency closure",
            )
        after = os.fstat(descriptor)
        if (
            before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_mode != after.st_mode
            or before.st_size != after.st_size
            or before.st_nlink != after.st_nlink
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
            or len(raw) != after.st_size
        ):
            raise NodeWorkspaceError(
                "node_workspace_tree_changed",
                "the Node dependency tree changed while it was being verified",
                next_action="stop concurrent mutation and rematerialize the workspace",
            )
        return raw, after
    finally:
        os.close(descriptor)


def _walk_error(_error: OSError) -> None:
    raise NodeWorkspaceError(
        "node_workspace_tree_unreadable",
        "the Node dependency tree could not be traversed completely",
        next_action="repair workspace permissions and rematerialize dependencies",
    )


def tree_summary(root: Path) -> dict[str, Any]:
    if root.is_symlink():
        raise NodeWorkspaceError(
            "node_workspace_tree_root_unsafe",
            "the Node dependency tree root is a symbolic link",
            next_action="remove the unsafe root and materialize the certified dependency tree",
        )
    if not root.is_dir():
        raise NodeWorkspaceError(
            "node_workspace_tree_missing",
            "the expected Node dependency tree is unavailable",
            next_action="materialize the certified lockfile-exact workspace",
        )
    entries: list[dict[str, Any]] = []
    total_bytes = 0
    resolved_root = root.resolve(strict=True)
    for current, raw_dirs, raw_files in os.walk(
        root, topdown=True, followlinks=False, onerror=_walk_error
    ):
        current_path = Path(current)
        raw_dirs.sort()
        raw_files.sort()
        retained_dirs: list[str] = []
        for name in raw_dirs:
            candidate = current_path / name
            relative = candidate.relative_to(root).as_posix()
            metadata = candidate.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                if metadata.st_nlink != 1:
                    raise NodeWorkspaceError(
                        "node_workspace_unsafe_hardlink",
                        "the Node dependency tree contains an aliased symbolic link",
                        next_action="reinstall the certified dependency tree without hard links",
                    )
                entries.append(
                    {
                        "path": relative,
                        "mode": "120000",
                        "target": _safe_symlink(resolved_root, candidate),
                    }
                )
                if len(entries) > MAX_TREE_FILES:
                    raise NodeWorkspaceError(
                        "node_workspace_tree_oversized",
                        "the Node dependency tree exceeds its bounded authority",
                        next_action="reduce and recertify the dependency closure",
                    )
            elif stat.S_ISDIR(metadata.st_mode):
                retained_dirs.append(name)
            else:
                raise NodeWorkspaceError(
                    "node_workspace_unsafe_entry",
                    "the Node workspace contains a non-regular tree entry",
                    next_action="reinstall the certified dependency tree",
                )
        raw_dirs[:] = retained_dirs
        for name in raw_files:
            candidate = current_path / name
            relative = candidate.relative_to(root).as_posix()
            metadata = candidate.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                if metadata.st_nlink != 1:
                    raise NodeWorkspaceError(
                        "node_workspace_unsafe_hardlink",
                        "the Node dependency tree contains an aliased symbolic link",
                        next_action="reinstall the certified dependency tree without hard links",
                    )
                entries.append(
                    {
                        "path": relative,
                        "mode": "120000",
                        "target": _safe_symlink(resolved_root, candidate),
                    }
                )
                if len(entries) > MAX_TREE_FILES:
                    raise NodeWorkspaceError(
                        "node_workspace_tree_oversized",
                        "the Node dependency tree exceeds its bounded authority",
                        next_action="reduce and recertify the dependency closure",
                    )
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise NodeWorkspaceError(
                    "node_workspace_unsafe_entry",
                    "the Node workspace contains a non-regular tree entry",
                    next_action="reinstall the certified dependency tree",
                )
            if metadata.st_nlink != 1:
                raise NodeWorkspaceError(
                    "node_workspace_unsafe_hardlink",
                    "the Node dependency tree contains an aliased or unsafe regular file",
                    next_action="reinstall the certified dependency tree without hard links",
                )
            raw, metadata = _read_tree_file(
                candidate,
                remaining=MAX_TREE_BYTES - total_bytes,
                expected=metadata,
            )
            total_bytes += len(raw)
            entries.append(
                {
                    "path": relative,
                    "mode": "100755" if metadata.st_mode & 0o111 else "100644",
                    "bytes": len(raw),
                    "sha256": _sha256(raw),
                }
            )
            if len(entries) > MAX_TREE_FILES or total_bytes > MAX_TREE_BYTES:
                raise NodeWorkspaceError(
                    "node_workspace_tree_oversized",
                    "the Node dependency tree exceeds its bounded authority",
                    next_action="reduce and recertify the dependency closure",
                )
    entries.sort(key=lambda item: item["path"])
    return {
        "tree_sha256": _sha256(_canonical_bytes(entries)),
        "entry_count": len(entries),
        "total_bytes": total_bytes,
    }


def resolved_npm_authority() -> dict[str, Any]:
    executable = shutil.which("npm")
    if executable is None:
        raise NodeWorkspaceError(
            "npm_unavailable",
            "npm is unavailable in the active certified toolchain",
            next_action="install the exact Node/npm toolchain certified by the release",
        )
    try:
        launcher = Path(executable)
        launcher_dir = launcher.parent.resolve(strict=True)
        entrypoint = launcher.resolve(strict=True)
        npm_root = entrypoint.parent.parent.resolve(strict=True)
        entrypoint.relative_to(npm_root)
    except (OSError, ValueError) as exc:
        raise NodeWorkspaceError(
            "npm_authority_invalid",
            "the active npm entrypoint cannot be resolved safely",
            next_action="install the exact Node/npm toolchain certified by the release",
        ) from exc
    package_raw = _bounded_regular_bytes(
        npm_root / "package.json", label="npm package", limit=1024 * 1024
    )
    try:
        package = json.loads(package_raw)
    except (UnicodeDecodeError, ValueError, TypeError) as exc:
        raise NodeWorkspaceError(
            "npm_authority_invalid",
            "the active npm package metadata is invalid",
            next_action="install the exact Node/npm toolchain certified by the release",
        ) from exc
    version = package.get("version") if isinstance(package, Mapping) else None
    name = package.get("name") if isinstance(package, Mapping) else None
    if (
        name != "npm"
        or not isinstance(version, str)
        or _SEMVER_RE.fullmatch(version) is None
    ):
        raise NodeWorkspaceError(
            "npm_authority_invalid",
            "the active npm package identity is not canonical",
            next_action="install the exact Node/npm toolchain certified by the release",
        )
    summary = tree_summary(npm_root)
    entrypoint_raw = _bounded_regular_bytes(
        entrypoint, label="npm entrypoint", limit=1024 * 1024
    )
    return {
        "name": "npm-resolved",
        "version": version,
        **_platform_identity(),
        "entrypoint_sha256": _sha256(entrypoint_raw),
        **summary,
        "executable": str(entrypoint),
        "launcher_dir": str(launcher_dir),
    }


def npm_toolchain_identity() -> dict[str, str]:
    authority = resolved_npm_authority()
    return _npm_identity_from_authority(authority)


def _npm_identity_from_authority(authority: Mapping[str, Any]) -> dict[str, str]:
    return {
        "name": "npm-resolved",
        "version": (
            f"{authority['version']}+{authority['platform_system']}."
            f"{authority['platform_machine']}.tree.{authority['tree_sha256']}"
        ),
    }


def _npm_manifest_authority(authority: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in authority.items()
        if key not in {"executable", "launcher_dir"}
    }


def _without_digest(payload: Mapping[str, Any], key: str) -> dict[str, Any]:
    unsigned = dict(payload)
    unsigned.pop(key, None)
    return unsigned


def _install_argv() -> list[str]:
    return [
        "npm",
        "--prefix",
        WORKSPACE_RELATIVE.as_posix(),
        "ci",
        "--ignore-scripts",
        "--no-audit",
        "--no-fund",
        "--prefer-offline",
        "--registry=https://registry.npmjs.org/",
    ]


def _expected_invocations() -> dict[str, list[list[str]]]:
    return {
        name: [list(arguments) for arguments in ALLOWED_INVOCATIONS[name]]
        for name in ALLOWED_SCRIPTS
    }


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _is_source_sha(value: Any) -> bool:
    return (
        isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40,64}", value) is not None
    )


def _is_platform_value(value: Any) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,31}", value) is not None
    )


def _is_bounded_int(value: Any, *, minimum: int, maximum: int) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and minimum <= value <= maximum
    )


def _valid_tree_summary(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == {"tree_sha256", "entry_count", "total_bytes"}
        and _is_sha256(value.get("tree_sha256"))
        and _is_bounded_int(value.get("entry_count"), minimum=1, maximum=MAX_TREE_FILES)
        and _is_bounded_int(value.get("total_bytes"), minimum=1, maximum=MAX_TREE_BYTES)
    )


def validate_workspace_boundary(repo_root: Path) -> None:
    if repo_root.is_symlink() or not repo_root.is_dir():
        raise NodeWorkspaceError(
            "node_workspace_root_unsafe",
            "the repository root is not one regular directory boundary",
            next_action="use the exact non-symlink Git worktree root",
        )
    resolved_root = repo_root.resolve(strict=True)
    for relative in (Path("apps"), WORKSPACE_RELATIVE):
        candidate = repo_root / relative
        try:
            metadata = candidate.lstat()
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(resolved_root)
        except (OSError, ValueError) as exc:
            raise NodeWorkspaceError(
                "node_workspace_root_unsafe",
                "the Node workspace boundary is missing or escapes the repository",
                next_action="restore the exact portable C1 workspace directories",
            ) from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise NodeWorkspaceError(
                "node_workspace_root_unsafe",
                "the Node workspace boundary contains a symbolic or special directory",
                next_action="restore the exact portable C1 workspace directories",
            )


def _load_package_inputs(
    repo_root: Path,
) -> tuple[bytes, bytes, Mapping[str, Any], Mapping[str, Any]]:
    package_raw = _bounded_regular_bytes(
        repo_root / PACKAGE_RELATIVE, label="cockpit package", limit=1024 * 1024
    )
    lock_raw = _bounded_regular_bytes(
        repo_root / PACKAGE_LOCK_RELATIVE,
        label="cockpit package lock",
        limit=16 * 1024 * 1024,
    )
    try:
        package = json.loads(package_raw)
        lock = json.loads(lock_raw)
    except (UnicodeDecodeError, ValueError, TypeError) as exc:
        raise NodeWorkspaceError(
            "node_workspace_input_invalid",
            "the cockpit package or lockfile is invalid",
            next_action="repair and recertify the portable Node workspace policy",
        ) from exc
    if not isinstance(package, Mapping) or not isinstance(lock, Mapping):
        raise NodeWorkspaceError(
            "node_workspace_input_invalid",
            "the cockpit package or lockfile is not a JSON object",
            next_action="repair and recertify the portable Node workspace policy",
        )
    return package_raw, lock_raw, package, lock


def build_policy(repo_root: Path) -> dict[str, Any]:
    validate_workspace_boundary(repo_root)
    package_raw, lock_raw, package, lock = _load_package_inputs(repo_root)
    package_manager = package.get("packageManager")
    scripts = package.get("scripts")
    if (
        not isinstance(package_manager, str)
        or re.fullmatch(r"npm@[0-9]+\.[0-9]+\.[0-9]+", package_manager) is None
        or not isinstance(scripts, Mapping)
        or any(name not in scripts for name in ALLOWED_SCRIPTS)
        or lock.get("lockfileVersion") != 3
    ):
        raise NodeWorkspaceError(
            "node_workspace_input_invalid",
            "the cockpit package does not pin the portable npm/scripts contract",
            next_action="pin packageManager, scripts and lockfile v3 before certification",
        )
    policy: dict[str, Any] = {
        "schema_version": POLICY_SCHEMA_VERSION,
        "workspace": WORKSPACE_RELATIVE.as_posix(),
        "package_json_sha256": _sha256(package_raw),
        "package_lock_sha256": _sha256(lock_raw),
        "package_manager": package_manager,
        "allowed_scripts": list(ALLOWED_SCRIPTS),
        "allowed_invocations": _expected_invocations(),
        "install": {
            "argv": _install_argv(),
            "timeout_seconds": INSTALL_TIMEOUT_SECONDS,
        },
        "command_timeout_seconds": COMMAND_TIMEOUT_SECONDS,
    }
    policy["policy_sha256"] = _sha256(_canonical_bytes(policy))
    return policy


def validate_policy(policy: Any) -> dict[str, Any]:
    if (
        isinstance(policy, Mapping)
        and policy.get("schema_version") == LEGACY_MANIFEST_SCHEMA_VERSION
    ):
        raise NodeWorkspaceError(
            "node_workspace_legacy_manifest_rejected",
            "the platform-bound Node workspace manifest v1 cannot authorize a new run",
            next_action="migrate the tracked manifest to portable policy v2 and recertify",
        )
    expected = {
        "schema_version",
        "workspace",
        "package_json_sha256",
        "package_lock_sha256",
        "package_manager",
        "allowed_scripts",
        "allowed_invocations",
        "install",
        "command_timeout_seconds",
        "policy_sha256",
    }
    if not isinstance(policy, Mapping) or set(policy) != expected:
        raise NodeWorkspaceError(
            "node_workspace_policy_invalid",
            "the portable Node workspace policy shape is invalid",
            next_action="regenerate and recertify the portable Node workspace policy",
        )
    normalized = dict(policy)
    install = normalized.get("install")
    if (
        normalized.get("schema_version") != POLICY_SCHEMA_VERSION
        or normalized.get("workspace") != WORKSPACE_RELATIVE.as_posix()
        or not _is_sha256(normalized.get("package_json_sha256"))
        or not _is_sha256(normalized.get("package_lock_sha256"))
        or not isinstance(normalized.get("package_manager"), str)
        or re.fullmatch(
            r"npm@[0-9]+\.[0-9]+\.[0-9]+", str(normalized.get("package_manager"))
        )
        is None
        or normalized.get("allowed_scripts") != list(ALLOWED_SCRIPTS)
        or normalized.get("allowed_invocations") != _expected_invocations()
        or not isinstance(install, Mapping)
        or set(install) != {"argv", "timeout_seconds"}
        or install.get("argv") != _install_argv()
        or install.get("timeout_seconds") != INSTALL_TIMEOUT_SECONDS
        or normalized.get("command_timeout_seconds") != COMMAND_TIMEOUT_SECONDS
        or not _is_sha256(normalized.get("policy_sha256"))
        or normalized.get("policy_sha256")
        != _sha256(_canonical_bytes(_without_digest(normalized, "policy_sha256")))
    ):
        raise NodeWorkspaceError(
            "node_workspace_policy_invalid",
            "the portable Node workspace policy is stale or incomplete",
            next_action="regenerate and recertify the portable Node workspace policy",
        )
    return normalized


def serialize_policy(policy: Mapping[str, Any]) -> bytes:
    return _canonical_bytes(validate_policy(policy)) + b"\n"


def load_policy(repo_root: Path) -> dict[str, Any]:
    validate_workspace_boundary(repo_root)
    raw = _bounded_regular_bytes(
        repo_root / MANIFEST_RELATIVE,
        label="Node workspace policy",
        limit=1024 * 1024,
    )
    try:
        return validate_policy(json.loads(raw))
    except (UnicodeDecodeError, ValueError, TypeError) as exc:
        if isinstance(exc, NodeWorkspaceError):
            raise
        raise NodeWorkspaceError(
            "node_workspace_policy_invalid",
            "the portable Node workspace policy is not valid UTF-8 JSON",
            next_action="regenerate and recertify the portable Node workspace policy",
        ) from exc


def _valid_node_authority(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value)
        == {
            "name",
            "version",
            "platform_system",
            "platform_machine",
            "executable_sha256",
            "executable_bytes",
            "runtime_tree_sha256",
            "runtime_entry_count",
            "runtime_total_bytes",
        }
        and value.get("name") == "node-resolved"
        and isinstance(value.get("version"), str)
        and _SEMVER_RE.fullmatch(str(value.get("version"))) is not None
        and _is_platform_value(value.get("platform_system"))
        and _is_platform_value(value.get("platform_machine"))
        and _is_sha256(value.get("executable_sha256"))
        and _is_bounded_int(
            value.get("executable_bytes"), minimum=1, maximum=MAX_NODE_EXECUTABLE_BYTES
        )
        and _is_sha256(value.get("runtime_tree_sha256"))
        and _is_bounded_int(
            value.get("runtime_entry_count"), minimum=1, maximum=MAX_TREE_FILES
        )
        and _is_bounded_int(
            value.get("runtime_total_bytes"), minimum=1, maximum=MAX_TREE_BYTES
        )
    )


def _valid_npm_authority(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value)
        == {
            "name",
            "version",
            "entrypoint_sha256",
            "platform_system",
            "platform_machine",
            "tree_sha256",
            "entry_count",
            "total_bytes",
        }
        and value.get("name") == "npm-resolved"
        and isinstance(value.get("version"), str)
        and _SEMVER_RE.fullmatch(str(value.get("version"))) is not None
        and _is_platform_value(value.get("platform_system"))
        and _is_platform_value(value.get("platform_machine"))
        and _is_sha256(value.get("entrypoint_sha256"))
        and _is_sha256(value.get("tree_sha256"))
        and _is_bounded_int(value.get("entry_count"), minimum=1, maximum=MAX_TREE_FILES)
        and _is_bounded_int(value.get("total_bytes"), minimum=1, maximum=MAX_TREE_BYTES)
    )


def validate_authority(authority: Any) -> dict[str, Any]:
    expected = {
        "schema_version",
        "policy_sha256",
        "source_sha",
        "platform",
        "node",
        "npm",
        "node_modules",
    }
    if not isinstance(authority, Mapping) or set(authority) != expected:
        raise NodeWorkspaceError(
            "node_workspace_authority_invalid",
            "the external Node workspace authority shape is invalid",
            next_action="capture a new path-free authority from the exact source",
        )
    normalized = dict(authority)
    source_sha = normalized.get("source_sha")
    platform_value = normalized.get("platform")
    node = normalized.get("node")
    npm = normalized.get("npm")
    if (
        normalized.get("schema_version") != AUTHORITY_SCHEMA_VERSION
        or not _is_sha256(normalized.get("policy_sha256"))
        or (source_sha is not None and not _is_source_sha(source_sha))
        or not isinstance(platform_value, Mapping)
        or set(platform_value) != {"system", "machine"}
        or not _is_platform_value(platform_value.get("system"))
        or not _is_platform_value(platform_value.get("machine"))
        or not _valid_node_authority(node)
        or not _valid_npm_authority(npm)
        or not _valid_tree_summary(normalized.get("node_modules"))
        or node.get("platform_system") != platform_value.get("system")
        or node.get("platform_machine") != platform_value.get("machine")
        or npm.get("platform_system") != platform_value.get("system")
        or npm.get("platform_machine") != platform_value.get("machine")
    ):
        raise NodeWorkspaceError(
            "node_workspace_authority_invalid",
            "the external Node workspace authority is stale or incomplete",
            next_action="capture a new path-free authority from the exact source",
        )
    return normalized


def serialize_authority(authority: Mapping[str, Any]) -> bytes:
    return _canonical_bytes(validate_authority(authority)) + b"\n"


def authority_identity_sha256(authority: Mapping[str, Any]) -> str:
    return _sha256(_canonical_bytes(validate_authority(authority)))


def npm_workspace_toolchain_identity(authority: Mapping[str, Any]) -> dict[str, str]:
    normalized = validate_authority(authority)
    npm = normalized["npm"]
    platform_value = normalized["platform"]
    return {
        "name": "npm-resolved",
        "version": (
            f"{npm['version']}+{platform_value['system']}.{platform_value['machine']}."
            f"workspace.{authority_identity_sha256(normalized)}"
        ),
    }


def load_authority(authority_path: Path) -> dict[str, Any]:
    raw = _bounded_regular_bytes(
        authority_path,
        label="external Node workspace authority",
        limit=1024 * 1024,
    )
    try:
        return validate_authority(json.loads(raw))
    except (UnicodeDecodeError, ValueError, TypeError) as exc:
        if isinstance(exc, NodeWorkspaceError):
            raise
        raise NodeWorkspaceError(
            "node_workspace_authority_invalid",
            "the external Node workspace authority is not valid UTF-8 JSON",
            next_action="restore the externally anchored authority payload",
        ) from exc


# Compatibility aliases are intentionally policy-only. A v1 platform-bound
# manifest is recognized and rejected by validate_policy rather than reused.
build_manifest = build_policy
serialize_manifest = serialize_policy
validate_manifest = validate_policy
load_manifest = load_policy


def _verify_policy_inputs(repo_root: Path, policy: Mapping[str, Any]) -> None:
    if build_policy(repo_root) != policy:
        raise NodeWorkspaceError(
            "node_workspace_policy_mismatch",
            "the package or lockfile differs from the portable certified policy",
            next_action="restore the exact portable C1 projection",
        )


def _verify_policy_unchanged(
    repo_root: Path, policy: Mapping[str, Any]
) -> dict[str, Any]:
    observed = load_policy(repo_root)
    if observed != policy:
        raise NodeWorkspaceError(
            "node_workspace_policy_changed",
            "the portable Node workspace policy changed during execution",
            next_action="discard the workspace and restore the exact portable C1 projection",
        )
    _verify_policy_inputs(repo_root, policy)
    return observed


def _coerce_authority(authority: Mapping[str, Any] | Path | None) -> dict[str, Any]:
    if authority is None:
        raise NodeWorkspaceError(
            "node_workspace_authority_required",
            "an external Node workspace authority is required",
            next_action="provide the capsule-bound authority and its trusted SHA-256",
        )
    if isinstance(authority, Path):
        return load_authority(authority)
    if not isinstance(authority, Mapping):
        raise NodeWorkspaceError(
            "node_workspace_authority_invalid",
            "the external Node workspace authority input is invalid",
            next_action="provide the exact capsule-bound authority payload",
        )
    return validate_authority(authority)


def _verify_trusted_authority(
    authority: Mapping[str, Any], trusted_authority_sha256: str | None
) -> str:
    if not _is_sha256(trusted_authority_sha256):
        raise NodeWorkspaceError(
            "node_workspace_authority_sha256_required",
            "one canonical trusted authority SHA-256 is required",
            next_action="carry the authority SHA-256 out of band from Lane A",
        )
    observed = authority_identity_sha256(authority)
    if not hmac.compare_digest(observed, str(trusted_authority_sha256)):
        raise NodeWorkspaceError(
            "node_workspace_authority_sha256_mismatch",
            "the external Node workspace authority differs from its trusted SHA-256",
            next_action="restore the exact capsule-bound authority payload",
        )
    return observed


def _verify_source_binding(
    authority: Mapping[str, Any], source_sha: str | None
) -> None:
    bound_source = authority.get("source_sha")
    if source_sha is not None and not _is_source_sha(source_sha):
        raise NodeWorkspaceError(
            "node_workspace_source_invalid",
            "the expected source SHA is not canonical",
            next_action="provide the exact capsule source SHA",
        )
    if bound_source is None:
        if source_sha is not None:
            raise NodeWorkspaceError(
                "node_workspace_source_mismatch",
                "the unbound authority cannot satisfy a source-bound execution",
                next_action="capture a new authority bound to the exact source SHA",
            )
        return
    if source_sha is None:
        raise NodeWorkspaceError(
            "node_workspace_source_required",
            "the authority is source-bound but no expected source SHA was provided",
            next_action="provide the exact capsule source SHA",
        )
    if not hmac.compare_digest(str(bound_source), source_sha):
        raise NodeWorkspaceError(
            "node_workspace_source_mismatch",
            "the authority source binding differs from the expected source SHA",
            next_action="restore the authority captured for this exact source",
        )


def _resolve_bound_runtime(
    policy: Mapping[str, Any], authority: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    node = resolved_node_authority()
    npm = resolved_npm_authority()
    observed_node = _node_manifest_authority(node)
    observed_npm = _npm_manifest_authority(npm)
    expected_manager = f"npm@{npm['version']}"
    if (
        authority.get("policy_sha256") != policy.get("policy_sha256")
        or policy.get("package_manager") != expected_manager
        or observed_node != authority.get("node")
        or observed_npm != authority.get("npm")
        or authority.get("platform")
        != {
            "system": node.get("platform_system"),
            "machine": node.get("platform_machine"),
        }
    ):
        raise NodeWorkspaceError(
            "node_workspace_authority_mismatch",
            "the policy, source toolchain or platform differs from certified authority",
            next_action="restore the exact release toolchain and portable C1 projection",
        )
    return node, npm


def _context(
    repo_root: Path,
    authority_input: Mapping[str, Any] | Path | None,
    trusted_authority_sha256: str | None,
    *,
    source_sha: str | None,
    verify_tree: bool,
) -> CertifiedExecutionContext:
    policy = load_policy(repo_root)
    _verify_policy_inputs(repo_root, policy)
    authority = _coerce_authority(authority_input)
    authority_sha256 = _verify_trusted_authority(authority, trusted_authority_sha256)
    _verify_source_binding(authority, source_sha)
    node, npm = _resolve_bound_runtime(policy, authority)
    if verify_tree:
        observed_tree = tree_summary(repo_root / NODE_MODULES_RELATIVE)
        if observed_tree != authority.get("node_modules"):
            raise NodeWorkspaceError(
                "node_workspace_tree_mismatch",
                "the active dependency tree differs from external certified authority",
                next_action="materialize the lockfile-exact workspace before running gates",
            )
    _verify_policy_unchanged(repo_root, policy)
    return CertifiedExecutionContext(
        policy=policy,
        authority=authority,
        authority_sha256=authority_sha256,
        node=node,
        npm=npm,
        environment=_command_environment(node=node, npm=npm),
    )


def verify_authority(
    repo_root: Path,
    authority: Mapping[str, Any] | Path | None,
    trusted_authority_sha256: str | None,
    *,
    source_sha: str | None = None,
    verify_tree: bool = True,
) -> dict[str, Any]:
    started = time.monotonic()
    context = _context(
        repo_root,
        authority,
        trusted_authority_sha256,
        source_sha=source_sha,
        verify_tree=verify_tree,
    )
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "operation": "verify-authority",
        "status": "verified",
        "tree_verified": verify_tree,
        "policy_sha256": context.policy["policy_sha256"],
        "authority_sha256": context.authority_sha256,
        "source_sha": context.authority["source_sha"],
        "package_json_sha256": context.policy["package_json_sha256"],
        "package_lock_sha256": context.policy["package_lock_sha256"],
        "npm_toolchain": npm_workspace_toolchain_identity(context.authority),
        "node_toolchain": _node_identity_from_authority(context.node),
        "node_modules": context.authority["node_modules"],
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def certified_execution_context(
    repo_root: Path,
    authority: Mapping[str, Any] | Path | None,
    trusted_authority_sha256: str | None,
    *,
    source_sha: str | None = None,
) -> CertifiedExecutionContext:
    return _context(
        repo_root,
        authority,
        trusted_authority_sha256,
        source_sha=source_sha,
        verify_tree=True,
    )


def _install_environment(
    *, node: Mapping[str, Any], npm: Mapping[str, Any]
) -> dict[str, str]:
    allowed = {
        "HOME",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "LANG",
        "LC_ALL",
        "NODE_EXTRA_CA_CERTS",
        "NO_PROXY",
        "SSL_CERT_FILE",
        "TMPDIR",
    }
    environment = {key: value for key, value in os.environ.items() if key in allowed}
    environment.update(
        {
            "NPM_CONFIG_AUDIT": "false",
            "NPM_CONFIG_FUND": "false",
            "NPM_CONFIG_IGNORE_SCRIPTS": "true",
            "NPM_CONFIG_REGISTRY": "https://registry.npmjs.org/",
            "NPM_CONFIG_USERCONFIG": os.devnull,
        }
    )
    environment["PATH"] = os.pathsep.join(
        [
            str(Path(str(node["executable"])).parent),
            str(npm["launcher_dir"]),
            "/usr/bin",
            "/bin",
        ]
    )
    return environment


def _command_environment(
    *, node: Mapping[str, Any], npm: Mapping[str, Any]
) -> dict[str, str]:
    exact = {
        "CI",
        "HOME",
        "LANG",
        "LC_ALL",
        "PLAYWRIGHT_BROWSERS_PATH",
        "TMPDIR",
        "TZ",
        "WIKI_PLAYWRIGHT_HTML_REPORT",
        "WIKI_PLAYWRIGHT_JSON_REPORT",
        "WIKI_PLAYWRIGHT_OUTPUT_DIR",
        "WIKI_UPGRADE_GATE_ARTIFACT_DIR",
        "WIKI_UPGRADE_GATE_ID",
        "WIKI_UPGRADE_LANE",
        "WIKI_UPGRADE_RUN_DIR",
        "WIKI_VIVA_KIT_ROOT",
    }
    environment = {
        key: value
        for key, value in os.environ.items()
        if (
            (key in exact or key in ALLOWED_COCKPIT_ENV_KEYS)
            and _SECRET_ENV_KEY_RE.search(key) is None
        )
    }
    environment.update(
        {
            "NPM_CONFIG_AUDIT": "false",
            "NPM_CONFIG_FUND": "false",
            "NPM_CONFIG_IGNORE_SCRIPTS": "true",
            "NPM_CONFIG_USERCONFIG": os.devnull,
        }
    )
    environment["PATH"] = os.pathsep.join(
        [
            str(Path(str(node["executable"])).parent),
            str(npm["launcher_dir"]),
            "/usr/bin",
            "/bin",
        ]
    )
    return environment


def _workspace_lock(repo_root: Path):
    key = hashlib.sha256(str(repo_root.resolve()).encode("utf-8")).hexdigest()[:24]
    path = Path(tempfile.gettempdir()) / f"wiki-viva-node-workspace-{key}.lock"
    try:
        descriptor = os.open(
            path,
            os.O_CREAT
            | os.O_RDWR
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except OSError as exc:
        raise NodeWorkspaceError(
            "node_workspace_lock_unsafe",
            "the Node workspace serialization lock is unavailable or unsafe",
            next_action="remove the unsafe temporary lock and retry the unchanged plan",
        ) from exc
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_mode & 0o077
        or (hasattr(os, "getuid") and metadata.st_uid != os.getuid())
    ):
        os.close(descriptor)
        raise NodeWorkspaceError(
            "node_workspace_lock_unsafe",
            "the Node workspace serialization lock has unsafe ownership or mode",
            next_action="remove the unsafe temporary lock and retry the unchanged plan",
        )
    return descriptor


def _install(
    repo_root: Path,
    policy: Mapping[str, Any],
    *,
    node: Mapping[str, Any],
    npm: Mapping[str, Any],
) -> ProcessResult:
    argv = list(policy["install"]["argv"])
    argv[0:1] = [str(node["executable"]), str(npm["executable"])]
    return _run_bounded(
        argv,
        cwd=repo_root,
        env=_install_environment(node=node, npm=npm),
        timeout=int(policy["install"]["timeout_seconds"]),
        output_limit=MAX_COMMAND_OUTPUT_BYTES,
        timeout_error=(
            "node_workspace_install_timeout",
            "lockfile-exact dependency materialization exceeded 180 seconds",
            "repair network/cache access and resume the unchanged plan",
        ),
        output_error=(
            "node_workspace_install_output_oversized",
            "dependency materialization exceeded its bounded output",
            "repair the npm cache or registry response and resume the unchanged plan",
        ),
    )


def _tree_or_missing(repo_root: Path) -> dict[str, Any] | None:
    try:
        return tree_summary(repo_root / NODE_MODULES_RELATIVE)
    except NodeWorkspaceError as exc:
        if exc.code != "node_workspace_tree_missing":
            raise
        return None


def _validate_materialization_target(repo_root: Path) -> Path | None:
    root = repo_root / NODE_MODULES_RELATIVE
    try:
        metadata = root.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise NodeWorkspaceError(
            "node_workspace_tree_root_unsafe",
            "the Node dependency tree root cannot be inspected safely",
            next_action="remove the unsafe root and restore the certified workspace",
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise NodeWorkspaceError(
            "node_workspace_tree_root_unsafe",
            "the Node dependency tree root is symbolic or not a directory",
            next_action="remove the unsafe root and materialize the certified dependency tree",
        )
    try:
        root.resolve(strict=True).relative_to(repo_root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise NodeWorkspaceError(
            "node_workspace_tree_root_unsafe",
            "the Node dependency tree root escapes the repository boundary",
            next_action="remove the unsafe root and restore the certified workspace",
        ) from exc
    return root


def _git_output(repo_root: Path, arguments: Sequence[str]) -> bytes:
    try:
        executable = resolved_git_executable()
        completed = run_bounded_process(
            sanitized_git_argv(arguments, executable=executable),
            cwd=repo_root,
            env=sanitized_git_environment(executable=executable),
            timeout=30,
            output_limit=16 * 1024 * 1024,
            stderr=subprocess.DEVNULL,
            popen_factory=subprocess.Popen,
        )
    except (GitSafetyError, OSError, ProcessSafetyError, ValueError) as exc:
        raise NodeWorkspaceError(
            "node_workspace_capture_git_invalid",
            "the exact Git source could not be verified safely",
            next_action="restore the clean exact worktree and retry capture",
        ) from exc
    if completed.returncode != 0:
        raise NodeWorkspaceError(
            "node_workspace_capture_git_invalid",
            "the exact Git source could not be verified safely",
            next_action="restore the clean exact worktree and retry capture",
        )
    return completed.output


def _verify_exact_git_source(repo_root: Path, source_sha: str | None) -> str:
    if source_sha is None:
        raise NodeWorkspaceError(
            "node_workspace_source_required",
            "authority capture requires one exact Git source SHA",
            next_action="provide the current clean Git HEAD SHA",
        )
    if not _is_source_sha(source_sha):
        raise NodeWorkspaceError(
            "node_workspace_source_invalid",
            "the capture source SHA is not canonical",
            next_action="provide the exact Git source SHA",
        )
    validate_workspace_boundary(repo_root)
    try:
        require_safe_local_config(repo_root)
    except GitSafetyError as exc:
        raise NodeWorkspaceError(
            "node_workspace_capture_git_invalid",
            "the exact Git source contains executable local configuration",
            next_action="remove executable repository-local Git configuration and retry",
        ) from exc
    top_level = _git_output(repo_root, ("rev-parse", "--show-toplevel")).rstrip(b"\r\n")
    try:
        observed_root = Path(os.fsdecode(top_level)).resolve(strict=True)
        expected_root = repo_root.resolve(strict=True)
    except OSError as exc:
        raise NodeWorkspaceError(
            "node_workspace_capture_git_invalid",
            "the exact Git source root cannot be resolved safely",
            next_action="retry from the exact non-symlink Git worktree root",
        ) from exc
    if observed_root != expected_root:
        raise NodeWorkspaceError(
            "node_workspace_capture_git_invalid",
            "authority capture must run at the exact Git worktree root",
            next_action="retry from the exact clean Git worktree root",
        )
    try:
        observed_head = (
            _git_output(repo_root, ("rev-parse", "--verify", "HEAD^{commit}"))
            .rstrip(b"\r\n")
            .decode("ascii", errors="strict")
        )
    except UnicodeDecodeError as exc:
        raise NodeWorkspaceError(
            "node_workspace_capture_git_invalid",
            "the exact Git HEAD identity is not canonical",
            next_action="restore the clean exact worktree and retry capture",
        ) from exc
    if not _is_source_sha(observed_head) or not hmac.compare_digest(
        observed_head, source_sha
    ):
        raise NodeWorkspaceError(
            "node_workspace_capture_source_mismatch",
            "the worktree HEAD differs from the requested capture source",
            next_action="checkout the exact source commit in a clean worktree",
        )
    status = _git_output(
        repo_root,
        (
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--ignore-submodules=none",
        ),
    )
    if status:
        raise NodeWorkspaceError(
            "node_workspace_capture_source_dirty",
            "authority capture requires a clean tracked and untracked Git source",
            next_action="commit or remove every source change before capture",
        )
    return observed_head


def _external_authority_target(repo_root: Path, output_path: Path) -> Path:
    validate_workspace_boundary(repo_root)
    if output_path.name in {"", ".", ".."} or "\x00" in output_path.name:
        raise NodeWorkspaceError(
            "node_workspace_authority_target_unsafe",
            "the authority target name is unsafe",
            next_action="choose one new regular file outside the Git subject",
        )
    try:
        root = repo_root.resolve(strict=True)
        parent = output_path.parent.resolve(strict=True)
        parent.relative_to(root)
    except ValueError:
        pass
    except OSError as exc:
        raise NodeWorkspaceError(
            "node_workspace_authority_target_unsafe",
            "the authority target parent is unavailable",
            next_action="create one safe external evidence directory",
        ) from exc
    else:
        raise NodeWorkspaceError(
            "node_workspace_authority_target_inside_subject",
            "the authority target must remain outside the Git subject",
            next_action="choose an ignored external evidence directory",
        )
    target = parent / output_path.name
    if target.exists() or target.is_symlink():
        raise NodeWorkspaceError(
            "node_workspace_authority_target_exists",
            "the immutable authority target already exists",
            next_action="choose a new first-write authority target",
        )
    return target


def _write_external_authority(repo_root: Path, output_path: Path, raw: bytes) -> Path:
    target = _external_authority_target(repo_root, output_path)
    temporary = target.parent / f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    descriptor = os.open(
        temporary,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, target, follow_symlinks=False)
        except (FileExistsError, OSError) as exc:
            raise NodeWorkspaceError(
                "node_workspace_authority_target_unsafe",
                "the immutable authority target could not be created safely",
                next_action="choose a new safe external authority target",
            ) from exc
        directory = os.open(
            target.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
    return target


def _capture_runtime(
    policy: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    node = resolved_node_authority()
    npm = resolved_npm_authority()
    if (
        policy.get("package_manager") != f"npm@{npm['version']}"
        or node.get("platform_system") != npm.get("platform_system")
        or node.get("platform_machine") != npm.get("platform_machine")
    ):
        raise NodeWorkspaceError(
            "node_workspace_capture_toolchain_mismatch",
            "the active Node/npm toolchain cannot satisfy the portable policy",
            next_action="install the packageManager-pinned npm runtime and retry",
        )
    return node, npm


def capture_authority(
    repo_root: Path,
    output_path: Path,
    *,
    source_sha: str | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    source_sha = _verify_exact_git_source(repo_root, source_sha)
    target = _external_authority_target(repo_root, output_path)
    policy = load_policy(repo_root)
    _verify_policy_inputs(repo_root, policy)
    descriptor = _workspace_lock(repo_root)
    output = b""
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        _verify_exact_git_source(repo_root, source_sha)
        _validate_materialization_target(repo_root)
        node, npm = _capture_runtime(policy)
        initial_node = _node_manifest_authority(node)
        initial_npm = _npm_manifest_authority(npm)
        install_error: NodeWorkspaceError | None = None
        try:
            result = _install(repo_root, policy, node=node, npm=npm)
            output = result.output
            if result.returncode != 0:
                install_error = NodeWorkspaceError(
                    "node_workspace_install_failed",
                    "lockfile-exact dependency materialization failed",
                    next_action="repair network/cache access and retry the unchanged source",
                )
        except NodeWorkspaceError as exc:
            install_error = exc
        tree_error: NodeWorkspaceError | None = None
        try:
            node_modules = tree_summary(repo_root / NODE_MODULES_RELATIVE)
        except NodeWorkspaceError as exc:
            tree_error = exc
            node_modules = None
        _verify_policy_unchanged(repo_root, policy)
        final_node, final_npm = _capture_runtime(policy)
        if (
            _node_manifest_authority(final_node) != initial_node
            or _npm_manifest_authority(final_npm) != initial_npm
        ):
            raise NodeWorkspaceError(
                "node_workspace_capture_toolchain_changed",
                "the Node/npm toolchain changed during authority capture",
                next_action="restore one stable toolchain and recapture",
            )
        if install_error is not None:
            raise install_error
        if tree_error is not None:
            raise tree_error
        if node_modules is None:
            raise NodeWorkspaceError(
                "node_workspace_tree_missing",
                "authority capture produced no dependency tree",
                next_action="repair npm materialization and recapture",
            )
        _verify_exact_git_source(repo_root, source_sha)
        _validate_materialization_target(repo_root)
        confirmed_tree = tree_summary(repo_root / NODE_MODULES_RELATIVE)
        if confirmed_tree != node_modules:
            raise NodeWorkspaceError(
                "node_workspace_tree_changed",
                "the Node dependency tree changed during authority capture",
                next_action="stop concurrent mutation and recapture from the clean source",
            )
        authority = validate_authority(
            {
                "schema_version": AUTHORITY_SCHEMA_VERSION,
                "policy_sha256": policy["policy_sha256"],
                "source_sha": source_sha,
                "platform": {
                    "system": final_node["platform_system"],
                    "machine": final_node["platform_machine"],
                },
                "node": _node_manifest_authority(final_node),
                "npm": _npm_manifest_authority(final_npm),
                "node_modules": node_modules,
            }
        )
        authority_sha256 = authority_identity_sha256(authority)
        _write_external_authority(repo_root, target, serialize_authority(authority))
        written = load_authority(target)
        if (
            written != authority
            or authority_identity_sha256(written) != authority_sha256
        ):
            raise NodeWorkspaceError(
                "node_workspace_authority_write_mismatch",
                "the external authority did not survive its atomic write",
                next_action="discard the target and recapture to a safe filesystem",
            )
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "operation": "capture-authority",
        "status": "captured",
        "policy_sha256": policy["policy_sha256"],
        "authority_sha256": authority_sha256,
        "source_sha": source_sha,
        "npm_toolchain": npm_workspace_toolchain_identity(authority),
        "node_toolchain": _node_identity_from_authority(final_node),
        "node_modules": authority["node_modules"],
        "install_forced": True,
        "install_output_sha256": _sha256(output),
        "install_output_bytes": len(output),
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def verify_workspace(
    repo_root: Path,
    authority: Mapping[str, Any] | Path | None = None,
    trusted_authority_sha256: str | None = None,
    *,
    source_sha: str | None = None,
) -> dict[str, Any]:
    receipt = verify_authority(
        repo_root,
        authority,
        trusted_authority_sha256,
        source_sha=source_sha,
        verify_tree=True,
    )
    receipt["operation"] = "check"
    return receipt


def materialize(
    repo_root: Path,
    authority: Mapping[str, Any] | Path | None = None,
    trusted_authority_sha256: str | None = None,
    *,
    source_sha: str | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    descriptor = _workspace_lock(repo_root)
    output = b""
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        _validate_materialization_target(repo_root)
        context = _context(
            repo_root,
            authority,
            trusted_authority_sha256,
            source_sha=source_sha,
            verify_tree=False,
        )
        expected_tree = context.authority["node_modules"]
        before = _tree_or_missing(repo_root)
        materialized = before != expected_tree
        install_error: NodeWorkspaceError | None = None
        if materialized:
            try:
                result = _install(
                    repo_root,
                    context.policy,
                    node=context.node,
                    npm=context.npm,
                )
                output = result.output
                if result.returncode != 0:
                    install_error = NodeWorkspaceError(
                        "node_workspace_install_failed",
                        "lockfile-exact dependency materialization failed",
                        next_action="repair network/cache access and resume the unchanged plan",
                    )
            except NodeWorkspaceError as exc:
                install_error = exc
        tree_error: NodeWorkspaceError | None = None
        try:
            _validate_materialization_target(repo_root)
            after = tree_summary(repo_root / NODE_MODULES_RELATIVE)
        except NodeWorkspaceError as exc:
            tree_error = exc
            after = None
        post = _context(
            repo_root,
            authority,
            trusted_authority_sha256,
            source_sha=source_sha,
            verify_tree=False,
        )
        if post.authority_sha256 != context.authority_sha256:
            raise NodeWorkspaceError(
                "node_workspace_authority_changed",
                "the external authority changed during materialization",
                next_action="discard the workspace and restore the exact authority",
            )
        if install_error is not None:
            raise install_error
        if tree_error is not None:
            raise tree_error
        if after != expected_tree:
            raise NodeWorkspaceError(
                "node_workspace_tree_mismatch",
                "materialized dependencies differ from external certified authority",
                next_action="discard the divergent workspace and recertify the dependency closure",
            )
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "operation": "materialize",
        "status": "verified",
        "materialized": materialized,
        "policy_sha256": context.policy["policy_sha256"],
        "authority_sha256": context.authority_sha256,
        "source_sha": context.authority["source_sha"],
        "package_json_sha256": context.policy["package_json_sha256"],
        "package_lock_sha256": context.policy["package_lock_sha256"],
        "npm_toolchain": npm_workspace_toolchain_identity(context.authority),
        "node_toolchain": _node_identity_from_authority(context.node),
        "node_modules": after,
        "install_output_sha256": _sha256(output),
        "install_output_bytes": len(output),
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def preview_process_spec(
    repo_root: Path,
    port: int,
    authority: Mapping[str, Any] | Path | None,
    trusted_authority_sha256: str | None,
    *,
    source_sha: str | None = None,
) -> ProcessSpec:
    if not _is_bounded_int(port, minimum=1024, maximum=65535):
        raise NodeWorkspaceError(
            "node_workspace_preview_port_invalid",
            "the preview port is outside the certified unprivileged range",
            next_action="choose one integer port between 1024 and 65535",
        )
    context = certified_execution_context(
        repo_root,
        authority,
        trusted_authority_sha256,
        source_sha=source_sha,
    )
    _package_raw, _lock_raw, package, _lock = _load_package_inputs(repo_root)
    scripts = package.get("scripts")
    if (
        not isinstance(scripts, Mapping)
        or scripts.get("preview") != "vite preview --host 127.0.0.1"
    ):
        raise NodeWorkspaceError(
            "node_workspace_preview_contract_invalid",
            "the exact-source preview script differs from certified policy",
            next_action="restore the reviewed Vite preview script and recertify",
        )
    return ProcessSpec(
        argv=(
            str(context.node["executable"]),
            str(context.npm["executable"]),
            "--prefix",
            WORKSPACE_RELATIVE.as_posix(),
            "run",
            "preview",
            "--",
            "--port",
            str(port),
            "--strictPort",
        ),
        cwd=repo_root,
        environment=context.environment,
    )


@contextlib.contextmanager
def certified_preview_process(
    repo_root: Path,
    port: int,
    authority: Mapping[str, Any] | Path | None,
    trusted_authority_sha256: str | None,
    *,
    source_sha: str | None = None,
    stdout: Any = subprocess.DEVNULL,
    stderr: Any = subprocess.STDOUT,
) -> Iterator[subprocess.Popen[bytes]]:
    descriptor = _workspace_lock(repo_root)
    process: subprocess.Popen[bytes] | None = None
    initial: CertifiedExecutionContext | None = None
    body_succeeded = False
    exited_before_teardown = False
    try:
        fcntl.flock(descriptor, fcntl.LOCK_SH)
        _validate_materialization_target(repo_root)
        initial = certified_execution_context(
            repo_root,
            authority,
            trusted_authority_sha256,
            source_sha=source_sha,
        )
        spec = preview_process_spec(
            repo_root,
            port,
            authority,
            trusted_authority_sha256,
            source_sha=source_sha,
        )
        try:
            process = start_process_group(
                spec.argv,
                cwd=spec.cwd,
                env=spec.environment,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                popen_factory=subprocess.Popen,
            )
        except OSError as exc:
            raise NodeWorkspaceError(
                "node_workspace_preview_unavailable",
                "the certified preview process could not be started",
                next_action="restore the exact preview runtime and retry",
            ) from exc
        yield process
        body_succeeded = True
    finally:
        active_error = sys.exc_info()[1]
        termination_error: BaseException | None = None
        if process is not None:
            try:
                exited_before_teardown = process.poll() is not None
            except BaseException as exc:
                termination_error = exc
            try:
                _terminate_process_group(process)
            except BaseException as exc:
                if termination_error is None:
                    termination_error = exc

        postcheck_error: BaseException | None = None
        try:
            if initial is not None:
                _validate_materialization_target(repo_root)
                final = certified_execution_context(
                    repo_root,
                    authority,
                    trusted_authority_sha256,
                    source_sha=source_sha,
                )
                if (
                    final.authority_sha256 != initial.authority_sha256
                    or final.policy != initial.policy
                    or final.node != initial.node
                    or final.npm != initial.npm
                ):
                    raise NodeWorkspaceError(
                        "node_workspace_preview_context_changed",
                        "the certified preview context changed during execution",
                        next_action="discard the preview evidence and restore the exact authority",
                    )
        except BaseException as exc:
            postcheck_error = exc

        unlock_error: BaseException | None = None
        close_error: BaseException | None = None
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        except BaseException as exc:
            unlock_error = exc
        try:
            os.close(descriptor)
        except BaseException as exc:
            close_error = exc

        if postcheck_error is not None:
            raise postcheck_error
        if active_error is None:
            if body_succeeded and exited_before_teardown:
                raise NodeWorkspaceError(
                    "node_workspace_preview_exited",
                    "the certified preview process exited before controlled teardown",
                    next_action="discard the preview evidence and restore the exact preview runtime",
                )
            if termination_error is not None:
                raise termination_error
            if unlock_error is not None:
                raise unlock_error
            if close_error is not None:
                raise close_error


def run_script(
    repo_root: Path,
    script_name: str,
    extra_args: Sequence[str],
    authority: Mapping[str, Any] | Path | None = None,
    trusted_authority_sha256: str | None = None,
    *,
    source_sha: str | None = None,
) -> CommandResult:
    normalized_args = tuple(extra_args)
    if (
        script_name not in ALLOWED_INVOCATIONS
        or normalized_args not in ALLOWED_INVOCATIONS.get(script_name, ())
        or any(
            not isinstance(value, str)
            or not value
            or "\x00" in value
            or "\n" in value
            or "\r" in value
            for value in extra_args
        )
    ):
        raise NodeWorkspaceError(
            "node_workspace_command_rejected",
            "the requested Node script or argument is outside certified policy",
            next_action="use one package-certified script and literal arguments",
        )
    materialization = materialize(
        repo_root,
        authority,
        trusted_authority_sha256,
        source_sha=source_sha,
    )
    descriptor = _workspace_lock(repo_root)
    started = time.monotonic()
    try:
        fcntl.flock(descriptor, fcntl.LOCK_SH)
        context = _context(
            repo_root,
            authority,
            trusted_authority_sha256,
            source_sha=source_sha,
            verify_tree=True,
        )
        argv = [
            str(context.node["executable"]),
            str(context.npm["executable"]),
            "--prefix",
            WORKSPACE_RELATIVE.as_posix(),
            "run",
            script_name,
        ]
        if extra_args:
            argv.extend(["--", *extra_args])
        command_error: NodeWorkspaceError | None = None
        result: ProcessResult | None = None
        try:
            result = _run_bounded(
                argv,
                cwd=repo_root,
                env=context.environment,
                timeout=int(context.policy["command_timeout_seconds"]),
                output_limit=MAX_COMMAND_OUTPUT_BYTES,
                timeout_error=(
                    "node_workspace_command_timeout",
                    "the certified Node command exceeded its bounded runtime",
                    "inspect the named gate and resume the unchanged plan",
                ),
                output_error=(
                    "node_workspace_command_output_oversized",
                    "the certified Node command exceeded its bounded output",
                    "use the quiet registered reporter and resume the unchanged plan",
                ),
            )
        except NodeWorkspaceError as exc:
            command_error = exc
        tree_error: NodeWorkspaceError | None = None
        try:
            post_tree = tree_summary(repo_root / NODE_MODULES_RELATIVE)
        except NodeWorkspaceError as exc:
            tree_error = exc
            post_tree = None
        post = _context(
            repo_root,
            authority,
            trusted_authority_sha256,
            source_sha=source_sha,
            verify_tree=False,
        )
        if post.authority_sha256 != context.authority_sha256:
            raise NodeWorkspaceError(
                "node_workspace_authority_changed",
                "the external authority changed during command execution",
                next_action="discard the workspace and restore the exact authority",
            )
        if tree_error is not None:
            raise tree_error
        if post_tree != context.authority["node_modules"]:
            raise NodeWorkspaceError(
                "node_workspace_post_command_drift",
                "a Node command changed the certified dependency closure",
                next_action="repair the named script and certify a new release",
            )
        if command_error is not None:
            raise command_error
        if result is None:
            raise NodeWorkspaceError(
                "node_workspace_command_failed",
                "the certified Node command returned no process result",
                next_action="inspect the named gate and resume the unchanged plan",
            )
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "operation": "run",
        "status": "passed" if result.returncode == 0 else "failed",
        "script": script_name,
        "arguments_sha256": _sha256(_canonical_bytes(list(extra_args))),
        "command_sha256": _sha256(_canonical_bytes(argv[1:])),
        "exit_code": result.returncode,
        "output_sha256": _sha256(result.output),
        "output_bytes": len(result.output),
        "policy_sha256": context.policy["policy_sha256"],
        "authority_sha256": context.authority_sha256,
        "source_sha": context.authority["source_sha"],
        "npm_toolchain": npm_workspace_toolchain_identity(context.authority),
        "node_toolchain": _node_identity_from_authority(context.node),
        "node_modules": post_tree,
        "materialization": materialization,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }
    return CommandResult(output=result.output, receipt=receipt)
