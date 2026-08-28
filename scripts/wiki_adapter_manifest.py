#!/usr/bin/env python3
"""Build or verify the tracked downstream adapter identity manifest."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import uuid
from pathlib import Path

try:
    from scripts._common import ROOT
except ModuleNotFoundError:
    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))

from wiki_core.adapter_manifest import (  # noqa: E402
    AdapterManifestError,
    DEFAULT_ADAPTER_MANIFEST,
    build_adapter_manifest,
    load_and_verify_adapter_manifest,
    serialize_adapter_manifest,
)


def _write_manifest(root: Path, payload: dict[str, object]) -> Path:
    if os.name == "nt" or not hasattr(os, "O_NOFOLLOW"):
        raise AdapterManifestError(
            "unsupported_platform", "POSIX no-follow writes required"
        )
    target = root / DEFAULT_ADAPTER_MANIFEST
    if target.exists() or target.is_symlink():
        state = target.lstat()
        if stat.S_ISLNK(state.st_mode):
            raise AdapterManifestError("symlink", DEFAULT_ADAPTER_MANIFEST)
        if not stat.S_ISREG(state.st_mode) or state.st_nlink != 1:
            raise AdapterManifestError("unsafe_manifest_target")
    temporary = (
        root / f".{DEFAULT_ADAPTER_MANIFEST}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    )
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(serialize_adapter_manifest(payload))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        parent = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return target


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    subcommands = parser.add_subparsers(dest="command", required=True)
    build = subcommands.add_parser("build", help="compile wiki.adapter-manifest.json")
    build.add_argument(
        "--file",
        action="append",
        dest="files",
        required=True,
        help="tracked repository-relative adapter file; repeat explicitly",
    )
    subcommands.add_parser(
        "check",
        help="require a tracked clean manifest and rehash every tracked clean file",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        root = args.root.resolve(strict=True)
        if args.command == "build":
            payload = build_adapter_manifest(root, args.files, require_tracked=True)
            target = _write_manifest(root, payload)
            output = {
                "schema_version": payload["schema_version"],
                "status": "built_unverified_until_committed",
                "manifest": target.relative_to(root).as_posix(),
                "adapter_sha256": payload["adapter_sha256"],
                "file_count": len(payload["files"]),
            }
        else:
            evidence = load_and_verify_adapter_manifest(root, require_tracked=True)
            output = {**evidence, "status": "verified"}
    except (OSError, AdapterManifestError) as exc:
        code = exc.code if isinstance(exc, AdapterManifestError) else "io_error"
        print(
            json.dumps(
                {
                    "schema_version": "wiki_downstream_adapter_manifest_check.v1",
                    "status": "invalid",
                    "code": code,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(output, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
