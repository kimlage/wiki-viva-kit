from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

from .models import PerformanceContractError, sha256_file, sha256_value

NODE_MODULES_ENV = "WIKI_PERFORMANCE_NODE_MODULES"


def _git(root: Path, *args: str) -> str:
    process = subprocess.run(
        ["git", *args], cwd=root, check=False, capture_output=True, text=True
    )
    if process.returncode:
        raise PerformanceContractError(
            f"git {' '.join(args)} failed: {process.stderr.strip()}"
        )
    return process.stdout


def source_subject(root: Path) -> dict[str, Any]:
    """Bind committed and dirty bytes without pretending a dirty HEAD is immutable."""

    head = _git(root, "rev-parse", "HEAD").strip()
    branch_process = subprocess.run(
        ["git", "symbolic-ref", "--short", "-q", "HEAD"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if branch_process.returncode not in {0, 1}:
        raise PerformanceContractError(
            f"git symbolic-ref failed: {branch_process.stderr.strip()}"
        )
    branch = branch_process.stdout.strip() or None
    raw_paths = _git(
        root,
        "ls-files",
        "-z",
        "--cached",
        "--others",
        "--exclude-standard",
    ).encode("utf-8", "surrogateescape").split(b"\0")
    entries: list[dict[str, Any]] = []
    for raw in sorted(item for item in raw_paths if item):
        relative = os.fsdecode(raw)
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise PerformanceContractError(f"unsupported source subject entry: {relative}")
        stat = path.stat()
        entries.append(
            {
                "path": relative,
                "mode": stat.st_mode & 0o777,
                "bytes": stat.st_size,
                "sha256": sha256_file(path),
            }
        )
    status = _git(root, "status", "--porcelain=v1", "--untracked-files=all").splitlines()
    payload = {
        "schema_version": "wiki_performance_source_subject.v1",
        "head_sha": head,
        "branch": branch,
        "clean": not status,
        "status": status,
        "entry_count": len(entries),
        "entries_sha256": sha256_value(entries),
        "portable_tree_sha256": None,
        "portable_tree_reason": "dirty_worktree_performance_subject_not_a_release_capsule",
    }
    payload["subject_sha256"] = sha256_value(payload)
    return payload


def node_modules_root(root: Path) -> Path:
    configured = os.environ.get(NODE_MODULES_ENV)
    candidate = Path(configured).expanduser().resolve() if configured else root / "apps/wiki-cockpit/node_modules"
    if not candidate.is_dir():
        raise PerformanceContractError(
            f"Node dependencies unavailable; set {NODE_MODULES_ENV} to a public, pre-existing node_modules tree"
        )
    source_lock = root / "apps/wiki-cockpit/package-lock.json"
    authority_lock = candidate.parent / "package-lock.json"
    if not authority_lock.is_file() or sha256_file(authority_lock) != sha256_file(source_lock):
        raise PerformanceContractError("Node dependency authority package-lock diverges from the source")
    return candidate


def toolchain_identity(root: Path) -> dict[str, Any]:
    def command_version(command: list[str], *, cwd: Path = root) -> str | None:
        try:
            process = subprocess.run(
                command,
                cwd=cwd,
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if process.returncode:
            return None
        return (process.stdout or process.stderr).strip().splitlines()[0]

    app_root = root / "apps/wiki-cockpit"
    dependencies = node_modules_root(root)
    chromium_executable = command_version(
        [
            "node",
            "--input-type=module",
            "-e",
            (
                f"import {{ chromium }} from {json.dumps((dependencies / '@playwright/test/index.mjs').as_uri())}; "
                "console.log(chromium.executablePath())"
            ),
        ],
        cwd=app_root,
    )
    chromium_path = Path(chromium_executable) if chromium_executable else None
    chromium_version = (
        command_version([str(chromium_path), "--version"])
        if chromium_path is not None and chromium_path.is_file()
        else None
    )
    payload = {
        "schema_version": "wiki_performance_toolchain.v1",
        "python_executable": str(Path(sys.executable).resolve()),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "node_version": command_version(["node", "--version"]),
        "npm_version": command_version(["npm", "--version"]),
        "git_version": command_version(["git", "--version"]),
        "playwright_version": command_version(
            [str(dependencies / ".bin/playwright"), "--version"]
        ),
        "node_dependencies_path": str(dependencies),
        "node_dependencies_source_lock_sha256": sha256_file(app_root / "package-lock.json"),
        "node_dependencies_authority_lock_sha256": sha256_file(dependencies.parent / "package-lock.json"),
        "node_dependencies_internal_lock_sha256": (
            sha256_file(dependencies / ".package-lock.json")
            if (dependencies / ".package-lock.json").is_file()
            else None
        ),
        "chromium_executable": str(chromium_path.resolve()) if chromium_path is not None and chromium_path.exists() else None,
        "chromium_version": chromium_version,
    }
    payload["toolchain_sha256"] = sha256_value(payload)
    return payload
