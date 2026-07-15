"""Exact clean-source verification for release-bearing gate execution."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
from typing import Sequence

from wiki_core.git_safety import (
    GitSafetyError,
    require_safe_local_config,
    resolved_git_executable,
    sanitized_git_argv,
    sanitized_git_environment,
)
from wiki_core.process_safety import ProcessSafetyError, run_bounded_process


class SourceIntegrityError(ValueError):
    """The checked-out release source differs from its immutable Git subject."""


@dataclass(frozen=True)
class SourceIntegrity:
    head_sha: str
    tree_sha: str
    tracked_tree_sha256: str
    tracked_entry_count: int


_SHA_RE = re.compile(r"^[0-9a-f]{40,64}$")
_MAX_GIT_OUTPUT = 256 * 1024 * 1024
_MAX_TRACKED_FILE = 64 * 1024 * 1024


def _git(
    root: Path, arguments: Sequence[str], *, input_bytes: bytes | None = None
) -> bytes:
    executable = resolved_git_executable()
    try:
        result = run_bounded_process(
            sanitized_git_argv(arguments, executable=executable),
            cwd=root,
            env=sanitized_git_environment(executable=executable),
            timeout=120,
            output_limit=_MAX_GIT_OUTPUT,
            input_bytes=input_bytes,
        )
    except (OSError, ProcessSafetyError, GitSafetyError) as exc:
        raise SourceIntegrityError("exact Git source authority is unavailable") from exc
    if result.returncode != 0:
        raise SourceIntegrityError("exact Git source authority is unavailable")
    return result.output


def _tree_entries(raw: bytes) -> list[tuple[str, str, str]]:
    entries: list[tuple[str, str, str]] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        metadata, separator, raw_path = record.partition(b"\t")
        fields = metadata.split()
        if not separator or len(fields) != 3 or fields[1] != b"blob":
            raise SourceIntegrityError("release source contains a non-blob tree entry")
        try:
            mode = fields[0].decode("ascii", "strict")
            object_id = fields[2].decode("ascii", "strict")
            path = raw_path.decode("utf-8", "strict")
        except UnicodeDecodeError as exc:
            raise SourceIntegrityError(
                "release source paths are not canonical UTF-8"
            ) from exc
        if (
            mode not in {"100644", "100755", "120000"}
            or _SHA_RE.fullmatch(object_id) is None
            or not path
            or Path(path).is_absolute()
            or ".." in Path(path).parts
            or Path(path).as_posix() != path
        ):
            raise SourceIntegrityError("release source tree entry is unsafe")
        entries.append((mode, object_id, path))
    if entries != sorted(entries, key=lambda item: item[2]) or len(entries) != len(
        {entry[2] for entry in entries}
    ):
        raise SourceIntegrityError("release source tree is not canonical")
    return entries


def _index_entries(raw: bytes) -> list[tuple[str, str, str]]:
    entries: list[tuple[str, str, str]] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        metadata, separator, raw_path = record.partition(b"\t")
        fields = metadata.split()
        if not separator or len(fields) != 3 or fields[2] != b"0":
            raise SourceIntegrityError("release source index is not one exact stage")
        try:
            entries.append(
                (
                    fields[0].decode("ascii", "strict"),
                    fields[1].decode("ascii", "strict"),
                    raw_path.decode("utf-8", "strict"),
                )
            )
        except UnicodeDecodeError as exc:
            raise SourceIntegrityError("release source index is not canonical") from exc
    return entries


def _blob_payloads(root: Path, object_ids: Sequence[str]) -> dict[str, bytes]:
    ordered = sorted(set(object_ids))
    if not ordered:
        return {}
    raw = _git(
        root,
        ["cat-file", "--batch"],
        input_bytes="".join(f"{value}\n" for value in ordered).encode("ascii"),
    )
    payloads: dict[str, bytes] = {}
    stream = io.BytesIO(raw)
    for expected in ordered:
        header = stream.readline().decode("ascii", "strict").strip().split()
        if len(header) != 3 or header[0] != expected or header[1] != "blob":
            raise SourceIntegrityError("release source blob authority is incomplete")
        try:
            size = int(header[2])
        except ValueError as exc:
            raise SourceIntegrityError("release source blob size is invalid") from exc
        if size < 0 or size > _MAX_TRACKED_FILE:
            raise SourceIntegrityError("release source blob exceeds its size bound")
        payload = stream.read(size)
        if len(payload) != size or stream.read(1) != b"\n":
            raise SourceIntegrityError("release source blob authority is truncated")
        payloads[expected] = payload
    if stream.read(1):
        raise SourceIntegrityError("release source blob authority has trailing bytes")
    return payloads


def _regular_bytes(parent: int, name: str) -> tuple[bytes, os.stat_result]:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    descriptor = os.open(name, flags, dir_fd=parent)
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size > _MAX_TRACKED_FILE
        ):
            raise SourceIntegrityError("tracked source file is unsafe")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, _MAX_TRACKED_FILE + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_TRACKED_FILE:
                raise SourceIntegrityError("tracked source file exceeds its size bound")
            chunks.append(chunk)
        after = os.fstat(descriptor)
        identity = lambda value: (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
            value.st_nlink,
        )
        if identity(before) != identity(after):
            raise SourceIntegrityError("tracked source file changed while read")
        return b"".join(chunks), after
    finally:
        os.close(descriptor)


def _worktree_entry(root: Path, mode: str, relative: str) -> bytes:
    if os.name != "posix":
        raise SourceIntegrityError("exact source verification requires POSIX")
    parts = Path(relative).parts
    opened: list[int] = []
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(root, directory_flags)
        opened.append(descriptor)
        for part in parts[:-1]:
            descriptor = os.open(part, directory_flags, dir_fd=descriptor)
            opened.append(descriptor)
        if mode == "120000":
            before = os.stat(parts[-1], dir_fd=descriptor, follow_symlinks=False)
            if not stat.S_ISLNK(before.st_mode):
                raise SourceIntegrityError("tracked source symlink changed type")
            target = os.readlink(parts[-1], dir_fd=descriptor)
            after = os.stat(parts[-1], dir_fd=descriptor, follow_symlinks=False)
            if (
                before.st_dev,
                before.st_ino,
                before.st_mode,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
                before.st_nlink,
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_mode,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
                after.st_nlink,
            ):
                raise SourceIntegrityError("tracked source symlink changed while read")
            target_path = Path(target)
            if target_path.is_absolute():
                raise SourceIntegrityError("tracked source symlink escapes its root")
            try:
                (root / Path(relative).parent / target).resolve(
                    strict=True
                ).relative_to(root.resolve(strict=True))
            except (OSError, ValueError) as exc:
                raise SourceIntegrityError(
                    "tracked source symlink escapes its root"
                ) from exc
            return os.fsencode(target)
        raw, metadata = _regular_bytes(descriptor, parts[-1])
        executable = bool(metadata.st_mode & 0o111)
        if executable != (mode == "100755"):
            raise SourceIntegrityError(
                "tracked source executable mode differs from Git"
            )
        return raw
    except SourceIntegrityError:
        raise
    except OSError as exc:
        raise SourceIntegrityError("tracked source path is missing or unsafe") from exc
    finally:
        for descriptor in reversed(opened):
            try:
                os.close(descriptor)
            except OSError:
                pass


def verify_clean_source(root: Path, expected_head: str) -> SourceIntegrity:
    """Recompute exact Git/index/worktree identity for one clean source."""

    try:
        source = root.resolve(strict=True)
        require_safe_local_config(source)
    except (OSError, GitSafetyError) as exc:
        raise SourceIntegrityError("release source Git policy is unsafe") from exc
    if (
        not source.is_dir()
        or root.is_symlink()
        or _SHA_RE.fullmatch(expected_head) is None
    ):
        raise SourceIntegrityError("release source root or subject is invalid")
    top = (
        _git(source, ["rev-parse", "--show-toplevel"]).decode("utf-8", "strict").strip()
    )
    head = _git(source, ["rev-parse", "HEAD"]).decode("ascii", "strict").strip()
    if Path(top).resolve() != source or head != expected_head:
        raise SourceIntegrityError("release source HEAD differs from authority")
    tree_sha = (
        _git(source, ["rev-parse", f"{expected_head}^{{tree}}"])
        .decode("ascii", "strict")
        .strip()
    )
    entries = _tree_entries(_git(source, ["ls-tree", "-r", "-z", expected_head]))
    index = _index_entries(_git(source, ["ls-files", "--stage", "-z"]))
    if index != entries:
        raise SourceIntegrityError("release source index differs from exact Git tree")
    if _git(source, ["status", "--porcelain=v1", "--untracked-files=all"]):
        raise SourceIntegrityError("release source has tracked or untracked drift")
    payloads = _blob_payloads(source, [entry[1] for entry in entries])
    projection: list[dict[str, str]] = []
    for mode, object_id, relative in entries:
        working = _worktree_entry(source, mode, relative)
        if working != payloads[object_id]:
            raise SourceIntegrityError(
                "release source bytes differ from exact Git tree"
            )
        projection.append(
            {
                "mode": mode,
                "path": relative,
                "sha256": hashlib.sha256(working).hexdigest(),
            }
        )
    serialized = json.dumps(
        projection, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return SourceIntegrity(
        head_sha=head,
        tree_sha=tree_sha,
        tracked_tree_sha256=hashlib.sha256(serialized).hexdigest(),
        tracked_entry_count=len(projection),
    )
