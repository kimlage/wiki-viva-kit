#!/usr/bin/env python3
"""Manage the portable Node policy and an external certified authority."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import uuid
from pathlib import Path

sys.dont_write_bytecode = True

try:
    from scripts._common import ROOT
except ModuleNotFoundError:
    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))

from wiki_core.node_workspace import (  # noqa: E402
    MANIFEST_RELATIVE,
    POLICY_SCHEMA_VERSION,
    NodeWorkspaceError,
    build_policy,
    capture_authority,
    materialize,
    run_script,
    serialize_policy,
    validate_workspace_boundary,
    verify_workspace,
)


AUTHORITY_ENV = "WIKI_VIVA_NODE_WORKSPACE_AUTHORITY"
AUTHORITY_SHA_ENV = "WIKI_VIVA_NODE_WORKSPACE_AUTHORITY_SHA256"
SOURCE_SHA_ENV = "WIKI_VIVA_NODE_WORKSPACE_SOURCE_SHA"


def _canonical_line(payload: object) -> bytes:
    return (
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        + b"\n"
    )


def _write_policy(root: Path, raw: bytes) -> None:
    validate_workspace_boundary(root)
    target = root / MANIFEST_RELATIVE
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        metadata = target.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise NodeWorkspaceError(
                "node_workspace_policy_target_unsafe",
                "the Node workspace policy target is unsafe",
                next_action="restore one regular policy target and retry",
            )
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
        os.replace(temporary, target)
        directory = os.open(
            target.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _authority_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--authority", type=Path)
    parser.add_argument("--trusted-authority-sha256")
    parser.add_argument("--source-sha")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    subcommands = parser.add_subparsers(dest="command", required=True)
    snapshot = subcommands.add_parser("snapshot")
    snapshot.add_argument("--check", action="store_true")
    capture = subcommands.add_parser("capture-authority")
    capture.add_argument("--out", type=Path, required=True)
    capture.add_argument("--source-sha")
    check = subcommands.add_parser("check")
    _authority_options(check)
    materialize_parser = subcommands.add_parser("materialize")
    _authority_options(materialize_parser)
    run = subcommands.add_parser("run")
    _authority_options(run)
    run.add_argument("script")
    run.add_argument("arguments", nargs=argparse.REMAINDER)
    return parser


def _failure(exc: NodeWorkspaceError) -> dict[str, str]:
    return {
        "schema_version": "wiki_viva_node_workspace_failure.v2",
        "status": "invalid",
        "error_code": exc.code,
        "lane": os.environ.get("WIKI_UPGRADE_LANE", "standalone"),
        "surface": os.environ.get("WIKI_UPGRADE_GATE_ID", "node_workspace"),
        "contract": POLICY_SCHEMA_VERSION,
        "message": exc.message,
        "next_action": exc.next_action,
    }


def _coalesce_string(explicit: str | None, env_name: str) -> str | None:
    carried = os.environ.get(env_name)
    if explicit is not None and carried is not None and explicit != carried:
        raise NodeWorkspaceError(
            "node_workspace_authority_binding_conflict",
            "the CLI and environment carry conflicting Node workspace authority bindings",
            next_action="provide one identical capsule-bound value through one channel",
        )
    return explicit if explicit is not None else carried


def _coalesce_path(explicit: Path | None, env_name: str) -> Path | None:
    carried = os.environ.get(env_name)
    if explicit is not None and carried is not None:
        left = Path(os.path.abspath(explicit))
        right = Path(os.path.abspath(carried))
        if left != right:
            raise NodeWorkspaceError(
                "node_workspace_authority_binding_conflict",
                "the CLI and environment carry conflicting Node workspace authority paths",
                next_action="provide one identical external authority path through one channel",
            )
    selected = (
        explicit if explicit is not None else (Path(carried) if carried else None)
    )
    return Path(os.path.abspath(selected)) if selected is not None else None


def _bindings(args: argparse.Namespace) -> tuple[Path | None, str | None, str | None]:
    return (
        _coalesce_path(args.authority, AUTHORITY_ENV),
        _coalesce_string(args.trusted_authority_sha256, AUTHORITY_SHA_ENV),
        _coalesce_string(args.source_sha, SOURCE_SHA_ENV),
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        root = Path(os.path.abspath(args.root))
        if args.command == "snapshot":
            policy = build_policy(root)
            raw = serialize_policy(policy)
            target = root / MANIFEST_RELATIVE
            if args.check:
                if (
                    target.is_symlink()
                    or not target.is_file()
                    or target.read_bytes() != raw
                ):
                    raise NodeWorkspaceError(
                        "node_workspace_policy_stale",
                        "the tracked portable Node workspace policy is not current",
                        next_action="regenerate the policy before certifying a new release",
                    )
                output: object = {
                    "schema_version": policy["schema_version"],
                    "status": "verified",
                    "policy_sha256": policy["policy_sha256"],
                    "package_json_sha256": policy["package_json_sha256"],
                    "package_lock_sha256": policy["package_lock_sha256"],
                }
            else:
                _write_policy(root, raw)
                output = {
                    "schema_version": policy["schema_version"],
                    "status": "generated",
                    "policy": MANIFEST_RELATIVE.as_posix(),
                    "policy_sha256": policy["policy_sha256"],
                }
        elif args.command == "capture-authority":
            source_sha = _coalesce_string(args.source_sha, SOURCE_SHA_ENV)
            output = capture_authority(
                root,
                Path(os.path.abspath(args.out)),
                source_sha=source_sha,
            )
        elif args.command == "check":
            authority, trusted_sha, source_sha = _bindings(args)
            output = verify_workspace(
                root, authority, trusted_sha, source_sha=source_sha
            )
        elif args.command == "materialize":
            authority, trusted_sha, source_sha = _bindings(args)
            output = materialize(root, authority, trusted_sha, source_sha=source_sha)
        else:
            authority, trusted_sha, source_sha = _bindings(args)
            arguments = list(args.arguments)
            if arguments[:1] == ["--"]:
                arguments = arguments[1:]
            result = run_script(
                root,
                args.script,
                arguments,
                authority,
                trusted_sha,
                source_sha=source_sha,
            )
            sys.stdout.buffer.write(result.output)
            if result.output and not result.output.endswith(b"\n"):
                sys.stdout.buffer.write(b"\n")
            sys.stdout.buffer.write(_canonical_line(result.receipt))
            return int(result.receipt["exit_code"])
    except (OSError, NodeWorkspaceError) as exc:
        if not isinstance(exc, NodeWorkspaceError):
            exc = NodeWorkspaceError(
                "node_workspace_io_error",
                "the certified Node workspace could not be accessed safely",
                next_action="restore the exact portable workspace and retry",
            )
        sys.stderr.buffer.write(_canonical_line(_failure(exc)))
        return 2
    sys.stdout.buffer.write(_canonical_line(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
