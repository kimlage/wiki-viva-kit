#!/usr/bin/env python3
"""Detects toolkit DRIFT between the current branch and another (e.g., opensource).

The toolkit (wiki_core/ + scripts/wiki_*.py + tests/) is shared between main
(personal project) and the open-source branch, but the sync is 100% manual — nothing
guarantees that a fix on one branch reaches the other. This command compares the
TOOLKIT files (not the personal content) between the current branch and a
reference branch and lists those that diverge, so the drift becomes visible (and, in
the future, a CI gate). It changes nothing; it only compares via `git`.

We compare only the portable CODE; memory pages, config and targets are
specific to each repo and are expected to differ.

Examples:
  python3 scripts/wiki_toolkit_drift.py                       # vs opensource/wiki-viva-kit
  python3 scripts/wiki_toolkit_drift.py --ref main
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


def _git(args: list[str]) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True)


def _toolkit_files(ref: str) -> set[str]:
    out = _git(["ls-tree", "-r", "--name-only", ref])
    return {
        line
        for line in out.splitlines()
        if line and any(line.startswith(p) for p in TOOLKIT_PREFIXES)
    }


def drift(ref: str) -> dict[str, list[str]]:
    head_files = _toolkit_files("HEAD")
    ref_files = _toolkit_files(ref)
    only_head = sorted(head_files - ref_files)
    only_ref = sorted(ref_files - head_files)
    differing: list[str] = []
    for path in sorted(head_files & ref_files):
        head_blob = _git(["rev-parse", f"HEAD:{path}"]).strip()
        ref_blob = _git(["rev-parse", f"{ref}:{path}"]).strip()
        if head_blob != ref_blob:
            differing.append(path)
    ignored = _ignored()
    return {
        "only_in_head": [p for p in only_head if p not in ignored],
        "only_in_ref": [p for p in only_ref if p not in ignored],
        "content_differs": differing,
        "ignored_per_repo": sorted(set(only_head + only_ref) & ignored),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--ref", default=DEFAULT_REF, help=f"reference branch (default {DEFAULT_REF})")
    parser.add_argument("--check", action="store_true", help="exit 1 if there is any drift")
    args = parser.parse_args(argv)

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

    print(json.dumps({"ref": args.ref, "drift_total": total, **report}, ensure_ascii=False, indent=2))
    if total:
        print(
            f"DRIFT: {total} toolkit file(s) diverge from {args.ref}. "
            "Backport the fixes to keep the kit unified.",
            file=sys.stderr,
        )
    if args.check and total:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
