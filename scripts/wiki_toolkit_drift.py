#!/usr/bin/env python3
"""Detect portable toolkit DRIFT between the current consumer and a source.

For branch-to-branch diagnostics, the legacy ``--ref`` mode compares the
historical toolkit prefixes. For a downstream release gate, ``--ref-path`` is
package-aware: it loads the reference checkout's upgrade package and compares
only ``portable_import`` paths against the exact pinned ``release.source_sha``.
Consumer-owned tests, workflows, configuration and private memory therefore do
not create false drift, while every portable payload byte remains enforced.

Release mode compares only the package-declared portable payload; memory pages,
consumer tests, workflows, config and targets are expected to differ.

Examples:
  python3 scripts/wiki_toolkit_drift.py                       # vs opensource/wiki-viva-kit
  python3 scripts/wiki_toolkit_drift.py --ref main
  python3 scripts/wiki_toolkit_drift.py --ref-path ../wiki-viva-kit
  python3 scripts/wiki_toolkit_drift.py --check               # exit 1 if there is drift
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

try:
    from scripts._common import ROOT
except ModuleNotFoundError:
    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))

from wiki_core.upgrade import (
    compare_portable_files,
    upgrade_package_sha256,
    validate_upgrade_package,
)

DEFAULT_REF = "opensource/wiki-viva-kit"
PACKAGE_REL = Path("docs/references/upgrades/wiki-viva-v8/upgrade-package.yaml")
SOURCE_SHA_RE = re.compile(r"[0-9a-f]{40,64}")

# Per-repo allowlist (one path per line; # comments). Files listed here are
# expected to exist on only one branch (e.g. personal one-shot scripts) and are
# reported separately instead of counting as drift — keeps --check usable as a
# CI gate. Content differences of SHARED files are never ignorable.
IGNORE_FILE = ROOT / ".toolkit-drift-ignore"


def _ignored() -> set[str]:
    if not IGNORE_FILE.exists():
        return set()
    out: set[str] = set()
    for line in IGNORE_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.add(line)
    return out

# Portable TOOLKIT prefixes (shared code). Personal content,
# config, targets and the meta-wiki are left out — they diverge by design.
TOOLKIT_PREFIXES = ("wiki_core/", "scripts/wiki_", "tests/", ".github/workflows/")
SKIP_DISK_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


def _git(args: list[str]) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True)


def _toolkit_files(ref: str) -> set[str]:
    out = _git(["ls-tree", "-r", "--name-only", ref])
    return {
        line
        for line in out.splitlines()
        if line and any(line.startswith(p) for p in TOOLKIT_PREFIXES)
    }


def _iter_toolkit_files_on_disk(root: Path) -> set[str]:
    files: set[str] = set()
    for prefix in TOOLKIT_PREFIXES:
        if prefix.endswith("/"):
            base = root / prefix.rstrip("/")
            if not base.exists():
                continue
            candidates = base.rglob("*")
        else:
            prefix_path = Path(prefix)
            base = root / prefix_path.parent
            if not base.exists():
                continue
            candidates = base.glob(f"{prefix_path.name}*")
        for path in candidates:
            if not path.is_file():
                continue
            if path.suffix in {".pyc", ".pyo"}:
                continue
            rel_parts = path.relative_to(root).parts
            if any(part in SKIP_DISK_PARTS for part in rel_parts):
                continue
            rel = path.relative_to(root).as_posix()
            if any(rel.startswith(p) for p in TOOLKIT_PREFIXES):
                files.add(rel)
    return files


def _same_file(left: Path, right: Path) -> bool:
    try:
        return left.read_bytes() == right.read_bytes()
    except OSError:
        return False


def drift(ref: str) -> dict[str, list[str]]:
    head_files = _toolkit_files("HEAD")
    ref_files = _toolkit_files(ref)
    only_head = sorted(head_files - ref_files)
    only_ref = sorted(ref_files - head_files)
    # ONE `git diff --name-only` covers every shared file (the old loop spawned
    # 2 rev-parse subprocesses per file). Prefixes become pathspecs: trailing-slash
    # dirs match recursively as-is; bare prefixes (scripts/wiki_) need a '*'.
    pathspecs = [p if p.endswith("/") else f"{p}*" for p in TOOLKIT_PREFIXES]
    changed = {
        line
        for line in _git(["diff", "--name-only", ref, "HEAD", "--", *pathspecs]).splitlines()
        if line
    }
    differing = sorted((head_files & ref_files) & changed)
    ignored = _ignored()
    return {
        "only_in_head": [p for p in only_head if p not in ignored],
        "only_in_ref": [p for p in only_ref if p not in ignored],
        "content_differs": differing,
        "ignored_per_repo": sorted(set(only_head + only_ref) & ignored),
    }


def drift_against_path(ref_path: Path) -> dict[str, list[str]]:
    ref_root = ref_path.resolve()
    if not ref_root.exists() or not ref_root.is_dir():
        raise FileNotFoundError(ref_root)
    head_files = _iter_toolkit_files_on_disk(ROOT)
    ref_files = _iter_toolkit_files_on_disk(ref_root)
    only_head = sorted(head_files - ref_files)
    only_ref = sorted(ref_files - head_files)
    shared = head_files & ref_files
    differing = sorted(
        rel for rel in shared if not _same_file(ROOT / rel, ref_root / rel)
    )
    ignored = _ignored()
    return {
        "only_in_head": [p for p in only_head if p not in ignored],
        "only_in_ref": [p for p in only_ref if p not in ignored],
        "content_differs": [p for p in differing if p not in ignored],
        "ignored_per_repo": sorted(set(only_head + only_ref + differing) & ignored),
    }


def portable_drift_against_path(
    ref_path: Path,
    *,
    package_path: Path | None = None,
    require_committed_package: bool = True,
) -> dict[str, object]:
    """Compare this consumer with one package-pinned public payload.

    The package is authoritative and must live in the reference checkout unless
    the caller supplies an explicit path. There is deliberately no fallback to
    the legacy prefix list: a missing/invalid package or unavailable source SHA
    is an authority failure, not an empty drift report.
    """

    ref_root = ref_path.resolve()
    if not ref_root.exists() or not ref_root.is_dir():
        raise FileNotFoundError(ref_root)
    raw_canonical_package = ref_root / PACKAGE_REL
    raw_authority_path = package_path or raw_canonical_package
    git_env = {**os.environ, "GIT_NO_REPLACE_OBJECTS": "1"}

    package_commit = ""
    package_source = "working_tree"
    if require_committed_package:
        if raw_authority_path.absolute() != raw_canonical_package.absolute():
            raise ValueError(
                "release checks require the canonical upgrade package from --ref-path"
            )
        try:
            top_level = Path(
                subprocess.check_output(
                    ["git", "rev-parse", "--show-toplevel"],
                    cwd=ref_root,
                    text=True,
                    stderr=subprocess.DEVNULL,
                    env=git_env,
                ).strip()
            ).resolve()
            if top_level != ref_root:
                raise ValueError("--ref-path must be the reference Git worktree root")
            replace_refs = subprocess.check_output(
                ["git", "replace", "-l"],
                cwd=ref_root,
                text=True,
                stderr=subprocess.DEVNULL,
                env=git_env,
            ).splitlines()
            if replace_refs:
                raise ValueError(
                    "reference Git worktree contains object replacement refs"
                )
            package_commit = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=ref_root,
                text=True,
                stderr=subprocess.DEVNULL,
                env=git_env,
            ).strip()
            committed_package = subprocess.check_output(
                ["git", "show", f"{package_commit}:{PACKAGE_REL.as_posix()}"],
                cwd=ref_root,
                stderr=subprocess.DEVNULL,
                env=git_env,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise ValueError(
                "canonical upgrade package is unavailable at reference HEAD"
            ) from exc
        package_diff = subprocess.run(
            [
                "git",
                "diff",
                "--quiet",
                "--no-ext-diff",
                package_commit,
                "--",
                PACKAGE_REL.as_posix(),
            ],
            cwd=ref_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=git_env,
            check=False,
        )
        if package_diff.returncode != 0:
            raise ValueError(
                "canonical upgrade package differs from the committed reference HEAD"
            )
        package_bytes = committed_package
        package_label = PACKAGE_REL.as_posix()
        package_source = "committed_head"
    else:
        if raw_authority_path.is_symlink():
            raise ValueError("upgrade package authority cannot be a symlink")
        authority_path = raw_authority_path.resolve()
        if not authority_path.exists() or not authority_path.is_file():
            raise FileNotFoundError(authority_path)
        package_bytes = authority_path.read_bytes()
        try:
            package_label = authority_path.relative_to(ref_root).as_posix()
        except ValueError:
            package_label = "<explicit-package>"

    package_blob_sha256 = hashlib.sha256(package_bytes).hexdigest()
    try:
        package = yaml.safe_load(package_bytes.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError("upgrade package is not valid UTF-8 YAML") from exc
    if not isinstance(package, dict):
        raise ValueError("upgrade package must have a mapping root")
    errors = validate_upgrade_package(package)
    if errors:
        raise ValueError("invalid upgrade package: " + "; ".join(errors))
    package_sha256 = upgrade_package_sha256(package)
    release = package.get("release") or {}
    source_sha = str(release.get("source_sha") or "").strip().lower()
    if not SOURCE_SHA_RE.fullmatch(source_sha) or len(set(source_sha)) < 4:
        raise ValueError("release.source_sha must be one exact full hexadecimal SHA")
    try:
        source_commit = subprocess.check_output(
            ["git", "rev-parse", f"{source_sha}^{{commit}}"],
            cwd=ref_root,
            text=True,
            stderr=subprocess.DEVNULL,
            env=git_env,
        ).strip().lower()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("release.source_sha is not an available commit") from exc
    if source_commit != source_sha:
        raise ValueError("release.source_sha must identify the commit object directly")
    if package_commit:
        ancestry = subprocess.run(
            ["git", "merge-base", "--is-ancestor", source_sha, package_commit],
            cwd=ref_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=git_env,
            check=False,
        )
        if ancestry.returncode != 0:
            raise ValueError(
                "release.source_sha is not an ancestor of the package commit"
            )
    report = compare_portable_files(
        ref_root,
        ROOT,
        package,
        source_sha=source_sha,
        git_no_replace_objects=True,
    )
    # Preserve the historical CLI field names while also exposing the canonical
    # package-aware vocabulary used by the upgrade compiler.
    return {
        "only_in_head": report["only_in_consumer"],
        "only_in_ref": report["only_in_kit"],
        "content_differs": report["content_differs"],
        "ignored_per_repo": report["ignored_matches"],
        "unsafe_ignore_patterns": report["unsafe_ignore_patterns"],
        "only_in_consumer": report["only_in_consumer"],
        "only_in_kit": report["only_in_kit"],
        "source_mode": report["source_mode"],
        "source_sha": source_sha,
        "release": str(release.get("id") or ""),
        "package": package_label,
        "package_commit": package_commit,
        "package_blob_sha256": package_blob_sha256,
        "package_sha256": package_sha256,
        "package_source": package_source,
        "drift_total": report["drift_total"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    reference = parser.add_mutually_exclusive_group()
    reference.add_argument(
        "--ref",
        default=None,
        help=f"reference branch (default {DEFAULT_REF})",
    )
    reference.add_argument(
        "--ref-path",
        type=Path,
        help=(
            "reference kit checkout; compares this consumer with the exact "
            "package-pinned portable payload"
        ),
    )
    parser.add_argument(
        "--package",
        type=Path,
        help=(
            "explicit upgrade-package YAML; defaults to the canonical path "
            "inside --ref-path"
        ),
    )
    parser.add_argument("--check", action="store_true", help="exit 1 if there is any drift")
    args = parser.parse_args(argv)
    if args.package and not args.ref_path:
        parser.error("--package requires --ref-path")

    ref = args.ref or DEFAULT_REF
    ref_label = ref
    if args.ref_path:
        ref_label = "<reference-kit>"
        try:
            report = portable_drift_against_path(
                args.ref_path,
                package_path=args.package,
                require_committed_package=args.check or args.package is None,
            )
        except FileNotFoundError:
            print(
                "ERROR: package authority is missing from <reference-kit>",
                file=sys.stderr,
            )
            return 3 if args.check else 0
        except ValueError:
            print(
                "ERROR: package authority is invalid for <reference-kit>",
                file=sys.stderr,
            )
            return 3 if args.check else 0
    else:
        try:
            report = drift(ref)
        except subprocess.CalledProcessError:
            print(
                f"WARNING: could not compare with {ref!r} (missing branch?). "
                "Run `git fetch` or adjust --ref.",
                file=sys.stderr,
            )
            return 3 if args.check else 0  # distinct code: missing ref must not pass a --check gate

    total = int(report.get("drift_total", -1))
    if total < 0:
        total = sum(
            len(value)
            for key, value in report.items()
            if key != "ignored_per_repo" and isinstance(value, list)
        )
    unsafe_ignore_patterns = list(report.get("unsafe_ignore_patterns") or [])

    print(
        json.dumps(
            {"ref": ref_label, "drift_total": total, **report},
            ensure_ascii=False,
            indent=2,
        )
    )
    if unsafe_ignore_patterns:
        print(
            "DRIFT POLICY: unsafe .toolkit-drift-ignore pattern(s): "
            + ", ".join(unsafe_ignore_patterns),
            file=sys.stderr,
        )
    if total:
        print(
            f"DRIFT: {total} toolkit file(s) diverge from {ref_label}. "
            "Backport the fixes to keep the kit unified.",
            file=sys.stderr,
        )
    if args.check and (total or unsafe_ignore_patterns):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
