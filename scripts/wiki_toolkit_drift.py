#!/usr/bin/env python3
"""Detects toolkit DRIFT between the current branch and another source.

The toolkit (wiki_core/ + scripts/wiki_*.py + tests/) is shared between main
(personal project) and the open-source branch, but the sync is 100% manual — nothing
guarantees that a fix on one branch reaches the other. This command compares the
TOOLKIT files (not the personal content) between the current branch and a
reference branch or checkout path and lists those that diverge, so the drift
becomes visible (and, in the future, a CI gate). It changes nothing.

We compare only the portable CODE; memory pages, config and targets are
specific to each repo and are expected to differ.

Examples:
  python3 scripts/wiki_toolkit_drift.py                       # vs opensource/wiki-viva-kit
  python3 scripts/wiki_toolkit_drift.py --ref main
  python3 scripts/wiki_toolkit_drift.py --ref-path ../wiki-viva-kit
  python3 scripts/wiki_toolkit_drift.py --check               # exit 1 if there is drift
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_REF = "opensource/wiki-viva-kit"

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--ref", default=DEFAULT_REF, help=f"reference branch (default {DEFAULT_REF})")
    parser.add_argument(
        "--ref-path",
        type=Path,
        help="reference checkout path; compares current working tree files against that checkout",
    )
    parser.add_argument("--check", action="store_true", help="exit 1 if there is any drift")
    args = parser.parse_args(argv)

    ref_label = args.ref
    if args.ref_path:
        ref_label = str(args.ref_path)
        try:
            report = drift_against_path(args.ref_path)
        except FileNotFoundError:
            print(
                f"WARNING: could not compare with checkout path {str(args.ref_path)!r}. "
                "Adjust --ref-path.",
                file=sys.stderr,
            )
            return 3 if args.check else 0
    else:
        try:
            report = drift(args.ref)
        except subprocess.CalledProcessError:
            print(
                f"WARNING: could not compare with {args.ref!r} (missing branch?). "
                "Run `git fetch` or adjust --ref.",
                file=sys.stderr,
            )
            return 3 if args.check else 0  # distinct code: missing ref must not pass a --check gate

    total = sum(len(v) for k, v in report.items() if k != "ignored_per_repo")
    import json

    print(json.dumps({"ref": ref_label, "drift_total": total, **report}, ensure_ascii=False, indent=2))
    if total:
        print(
            f"DRIFT: {total} toolkit file(s) diverge from {ref_label}. "
            "Backport the fixes to keep the kit unified.",
            file=sys.stderr,
        )
    if args.check and total:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
