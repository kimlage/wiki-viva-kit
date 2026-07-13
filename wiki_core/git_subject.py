"""Standard-library-only Git subject and exact worktree fingerprint helpers.

This module belongs to the portable core, but intentionally imports no other
``wiki_core`` module. The cockpit's Node-only CI job loads this file directly
before it creates browser evidence, so that path does not silently depend on
PyYAML or the rest of the Python runtime.

The fingerprint binds the staged patch, the unstaged patch, every untracked
path and its bytes, and the clean commit identity of initialized submodules.
Only hashes and counts leave this module; private paths and file contents do
not become release metadata.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any


FINGERPRINT_VERSION = "wiki_git_worktree_fingerprint.v1"
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")


class GitSubjectError(RuntimeError):
    """Raised when an exact, stable repository subject cannot be collected."""


def _git_bytes(
    root: Path, *args: str, check: bool = True
) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        raise GitSubjectError(f"git {' '.join(args)} could not start") from exc
    if check and result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise GitSubjectError(
            f"git {' '.join(args)} failed{': ' + detail if detail else ''}"
        )
    return result


def _canonical_commit(root: Path, revision: str) -> tuple[str, str]:
    commit = (
        _git_bytes(root, "rev-parse", "--verify", f"{revision}^{{commit}}")
        .stdout.decode("ascii", errors="strict")
        .strip()
        .lower()
    )
    tree = (
        _git_bytes(root, "rev-parse", "--verify", f"{commit}^{{tree}}")
        .stdout.decode("ascii", errors="strict")
        .strip()
        .lower()
    )
    if not SHA1_RE.fullmatch(commit) or not SHA1_RE.fullmatch(tree):
        raise GitSubjectError("git returned a non-canonical commit/tree hash")
    return commit, tree


def _frame(digest: Any, label: bytes, value: bytes) -> None:
    digest.update(len(label).to_bytes(4, "big"))
    digest.update(label)
    digest.update(len(value).to_bytes(8, "big"))
    digest.update(value)


def _untracked_digest(root: Path, raw_paths: bytes) -> tuple[str, int]:
    paths = [value for value in raw_paths.split(b"\0") if value]
    paths.sort()
    digest = hashlib.sha256()
    digest.update(b"wiki_git_untracked.v1\0")
    root_bytes = os.fsencode(root)
    for relative in paths:
        if relative.startswith(b"/") or b"\0" in relative:
            raise GitSubjectError("git returned an unsafe untracked path")
        absolute = os.path.join(root_bytes, relative)
        try:
            metadata = os.lstat(absolute)
        except OSError as exc:
            raise GitSubjectError(
                "an untracked path changed while its fingerprint was collected"
            ) from exc
        _frame(digest, b"path", relative)
        _frame(digest, b"mode", f"{stat.S_IMODE(metadata.st_mode):06o}".encode())
        if stat.S_ISLNK(metadata.st_mode):
            _frame(digest, b"type", b"symlink")
            _frame(digest, b"target", os.readlink(absolute))
        elif stat.S_ISREG(metadata.st_mode):
            _frame(digest, b"type", b"regular")
            content = hashlib.sha256()
            try:
                flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                descriptor = os.open(absolute, flags)
                with os.fdopen(descriptor, "rb", buffering=0) as handle:
                    before = os.fstat(handle.fileno())
                    if (
                        before.st_dev,
                        before.st_ino,
                        stat.S_IFMT(before.st_mode),
                    ) != (
                        metadata.st_dev,
                        metadata.st_ino,
                        stat.S_IFMT(metadata.st_mode),
                    ):
                        raise GitSubjectError(
                            "an untracked file was replaced while its fingerprint was collected"
                        )
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        content.update(chunk)
                    after = os.fstat(handle.fileno())
            except GitSubjectError:
                raise
            except OSError as exc:
                raise GitSubjectError(
                    "an untracked file could not be read for fingerprinting"
                ) from exc
            if (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ):
                raise GitSubjectError(
                    "an untracked file changed while its fingerprint was collected"
                )
            _frame(digest, b"bytes_sha256", content.digest())
            _frame(digest, b"bytes", str(after.st_size).encode())
        else:
            raise GitSubjectError(
                "special untracked filesystem entries cannot be fingerprinted safely"
            )
    return digest.hexdigest(), len(paths)


def _submodule_state(root: Path) -> bytes:
    status = _git_bytes(root, "submodule", "status", "--recursive").stdout
    if not status:
        return b""
    for line in status.splitlines():
        if not line.startswith(b" "):
            raise GitSubjectError(
                "uninitialized, conflicted or commit-mismatched submodule blocks exact fingerprinting"
            )
    cleanliness = _git_bytes(
        root,
        "submodule",
        "foreach",
        "--recursive",
        "--quiet",
        'test -z "$(git status --porcelain=v1 --untracked-files=all)"',
        check=False,
    )
    if cleanliness.returncode != 0:
        raise GitSubjectError("a dirty submodule blocks exact worktree fingerprinting")
    return status


def _assert_no_hidden_index_entries(root: Path) -> None:
    """Reject tracked entries hidden by assume-unchanged/sparse flags.

    ``git status`` and ``git diff`` intentionally trust those index flags, so a
    modified worktree file could otherwise produce ``dirty=false``. ``-v``
    lowercases assume-unchanged tags and uses ``S`` for skip-worktree (including
    sparse-index directory entries). Paths are never included in diagnostics.
    """

    raw = _git_bytes(root, "ls-files", "-v", "-z").stdout
    for record in (item for item in raw.split(b"\0") if item):
        if len(record) < 3 or record[1:2] != b" ":
            raise GitSubjectError("git returned malformed tracked-index metadata")
        tag = record[:1]
        if tag == b"S" or tag in b"abcdefghijklmnopqrstuvwxyz":
            raise GitSubjectError(
                "assume-unchanged, skip-worktree or sparse index flags block exact fingerprinting"
            )


def _collect_once(root: Path, *, base_sha: str | None) -> dict[str, Any]:
    source_sha, tree_hash = _canonical_commit(root, "HEAD")
    _assert_no_hidden_index_entries(root)
    status_z = _git_bytes(
        root, "status", "--porcelain=v1", "-z", "--untracked-files=all"
    ).stdout
    status_lines = _git_bytes(
        root, "status", "--porcelain=v1", "--untracked-files=all"
    ).stdout.splitlines()
    staged = _git_bytes(
        root,
        "diff",
        "--binary",
        "--full-index",
        "--no-ext-diff",
        "--no-textconv",
        "--cached",
        "HEAD",
        "--",
    ).stdout
    unstaged = _git_bytes(
        root,
        "diff",
        "--binary",
        "--full-index",
        "--no-ext-diff",
        "--no-textconv",
        "--",
    ).stdout
    untracked_paths = _git_bytes(
        root, "ls-files", "--others", "--exclude-standard", "-z"
    ).stdout
    untracked_hash, untracked_count = _untracked_digest(root, untracked_paths)
    submodules = _submodule_state(root)

    digest = hashlib.sha256()
    digest.update(f"{FINGERPRINT_VERSION}\0".encode())
    _frame(digest, b"source_sha", source_sha.encode())
    _frame(digest, b"status", status_z)
    _frame(digest, b"staged", staged)
    _frame(digest, b"unstaged", unstaged)
    _frame(digest, b"untracked_sha256", untracked_hash.encode())
    _frame(digest, b"submodules", submodules)

    subject: dict[str, Any] = {
        "source_sha": source_sha,
        "tree_hash": tree_hash,
        "dirty": bool(status_lines),
        "dirty_entry_count": len(status_lines),
        "worktree_fingerprint_version": FINGERPRINT_VERSION,
        "worktree_fingerprint": digest.hexdigest(),
        "staged_patch_sha256": hashlib.sha256(staged).hexdigest(),
        "unstaged_patch_sha256": hashlib.sha256(unstaged).hexdigest(),
        "untracked_state_sha256": untracked_hash,
        "untracked_entry_count": untracked_count,
        "submodule_state_sha256": hashlib.sha256(submodules).hexdigest(),
        "base_sha": None,
        "base_tree_hash": None,
        "base_is_ancestor": None,
    }
    if base_sha:
        resolved_base, base_tree = _canonical_commit(root, base_sha)
        ancestor = _git_bytes(
            root,
            "merge-base",
            "--is-ancestor",
            resolved_base,
            source_sha,
            check=False,
        )
        if ancestor.returncode not in {0, 1}:
            raise GitSubjectError("git merge-base --is-ancestor failed")
        subject.update(
            {
                "base_sha": resolved_base,
                "base_tree_hash": base_tree,
                "base_is_ancestor": ancestor.returncode == 0,
            }
        )
    return subject


def collect_git_subject(
    root: Path, *, base_sha: str | None = None, stability_attempts: int = 3
) -> dict[str, Any]:
    """Return one stable exact subject or fail closed on concurrent mutation."""

    root = root.resolve()
    top = Path(
        _git_bytes(root, "rev-parse", "--show-toplevel")
        .stdout.decode("utf-8", errors="strict")
        .strip()
    ).resolve()
    if top != root:
        raise GitSubjectError("--root must be the exact Git repository root")
    for _attempt in range(max(1, stability_attempts)):
        before = _collect_once(root, base_sha=base_sha)
        after = _collect_once(root, base_sha=base_sha)
        if before == after:
            return after
    raise GitSubjectError(
        "repository changed while the exact worktree fingerprint was collected"
    )


__all__ = [
    "FINGERPRINT_VERSION",
    "GitSubjectError",
    "collect_git_subject",
]
