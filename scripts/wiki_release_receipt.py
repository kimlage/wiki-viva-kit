#!/usr/bin/env python3
"""Generate or verify an exact-subject Wiki Viva release receipt."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

try:
    from scripts._common import ROOT
except ModuleNotFoundError:
    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))

from wiki_core.release_receipt import (  # noqa: E402
    ReleaseReceiptError,
    build_release_receipt,
    load_json_object,
    validate_release_receipt,
)

DEFAULT_RECEIPT = Path("data/derived/wiki/release-receipt.json")


def _repo_path(root: Path, raw: str | Path) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else root / path


def _write_json(root: Path, relative: Path, payload: object) -> Path:
    serialized = f"{json.dumps(payload, indent=2, sort_keys=True)}\n".encode()
    if os.name == "nt" or not all(
        hasattr(os, name) for name in ("O_DIRECTORY", "O_NOFOLLOW")
    ):
        raise ReleaseReceiptError(
            "receipt output creation requires POSIX no-follow directory handles"
        )
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    opened = [root_fd]
    parent_fd = root_fd
    temporary_name = f".{relative.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    try:
        for part in relative.parts[:-1]:
            try:
                child_fd = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=parent_fd,
                )
            except FileNotFoundError:
                os.mkdir(part, mode=0o700, dir_fd=parent_fd)
                child_fd = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=parent_fd,
                )
            opened.append(child_fd)
            parent_fd = child_fd
        descriptor = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent_fd,
        )
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(
                temporary_name,
                relative.name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise ReleaseReceiptError(
                "receipt output already exists or could not be created without replacement"
            ) from exc
        os.unlink(temporary_name, dir_fd=parent_fd)
        os.fsync(parent_fd)
    finally:
        try:
            os.unlink(temporary_name, dir_fd=parent_fd)
        except OSError:
            pass
        for descriptor in reversed(opened):
            os.close(descriptor)
    return root / relative


def _assert_ignored_output(root: Path, path: Path) -> Path:
    root = root.resolve()
    lexical = Path(os.path.abspath(path))
    if path != lexical:
        raise ReleaseReceiptError(
            "receipt output must be a normalized path without dot-segment traversal"
        )
    try:
        relative_path = lexical.relative_to(root)
    except ValueError as exc:
        raise ReleaseReceiptError(
            "receipt output must stay inside the repository"
        ) from exc
    if (
        len(relative_path.parts) < 3
        or relative_path.parts[:2] != ("data", "derived")
        or relative_path.parts[2] not in {"wiki", "release"}
    ):
        raise ReleaseReceiptError(
            "receipt output must stay under an owned data/derived release root"
        )
    current = root
    for part in relative_path.parts[:-1]:
        current /= part
        if current.is_symlink():
            raise ReleaseReceiptError("receipt output must not traverse a symlink")
    relative = relative_path.as_posix()
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--no-index", "--", relative],
        cwd=root,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise ReleaseReceiptError(
            "receipt output must be gitignored so writing it cannot change the attested subject"
        )
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", relative],
        cwd=root,
        check=False,
        capture_output=True,
    )
    if tracked.returncode == 0:
        raise ReleaseReceiptError(
            "receipt output must be untracked; a tracked file cannot be replaced"
        )
    return relative_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        default=str(ROOT),
        help="Wiki repository root (default: this checkout).",
    )
    parser.add_argument(
        "--evidence", help="JSON evidence manifest used when generating a receipt."
    )
    parser.add_argument(
        "--out", default=str(DEFAULT_RECEIPT), help="Generated receipt path."
    )
    parser.add_argument("--receipt", help="Receipt to verify (defaults to --out).")
    parser.add_argument(
        "--base-sha",
        help=(
            "Exact ancestor base commit; required for browser_closure. Without it "
            "v1 emits blocked local_evidence only."
        ),
    )
    parser.add_argument(
        "--promote-e5",
        action="store_true",
        help=(
            "Request E5. v1 is browser-evidence-only and always exits 2 until an external "
            "signed authority is implemented."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify an existing receipt against the current repository.",
    )
    parser.add_argument(
        "--require-e5",
        action="store_true",
        help="With --check, reject browser-only receipts as E5 proof.",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    out = _repo_path(root, args.out)
    try:
        if args.check:
            if args.evidence or args.promote_e5:
                parser.error(
                    "--check cannot be combined with --evidence or --promote-e5"
                )
            receipt_path = _repo_path(root, args.receipt or args.out)
            receipt = load_json_object(receipt_path, label="release receipt")
            errors = validate_release_receipt(
                receipt, root=root, require_e5=args.require_e5
            )
            if args.base_sha:
                from wiki_core.release_receipt import collect_git_subject

                expected = collect_git_subject(root, base_sha=args.base_sha)["base_sha"]
                if receipt.get("subject", {}).get("base_sha") != expected:
                    errors.append("receipt base_sha does not match --base-sha")
            if errors:
                for error in errors:
                    print(f"release receipt error: {error}", file=sys.stderr)
                return 1
            print(
                f"release receipt valid: {receipt['release_id']} {receipt['evidence_scope']} "
                f"{receipt['subject']['source_sha']}"
            )
            return 0

        if not args.evidence:
            parser.error("--evidence is required when generating a receipt")
        evidence_path = _repo_path(root, args.evidence)
        evidence = load_json_object(evidence_path, label="release evidence")
        receipt = build_release_receipt(
            root,
            evidence,
            base_sha=args.base_sha,
            promote_e5=args.promote_e5,
        )
        out_relative = _assert_ignored_output(root, out)
        prewrite_errors = validate_release_receipt(receipt, root=root)
        if prewrite_errors:
            raise ReleaseReceiptError(
                "generated receipt failed semantic validation: "
                + "; ".join(prewrite_errors)
            )
        out = _write_json(root, out_relative, receipt)
        readback = load_json_object(out, label="written release receipt")
        readback_errors = validate_release_receipt(readback, root=root)
        if readback_errors:
            raise ReleaseReceiptError(
                "written receipt failed readback validation: "
                + "; ".join(readback_errors)
            )
        print(
            f"release receipt written: {out} "
            f"({receipt['overall_status']}, scope={receipt['evidence_scope']})"
        )
        if args.promote_e5 and receipt["evidence_scope"] != "e5_release":
            print(
                "E5 promotion blocked: " + ", ".join(receipt["reason_codes"]),
                file=sys.stderr,
            )
            return 2
        return 0
    except ReleaseReceiptError as exc:
        print(f"release receipt error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
