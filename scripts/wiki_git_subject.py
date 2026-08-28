#!/usr/bin/env python3
"""Print a stable, path-safe Git subject for cross-runtime release gates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from scripts._git_subject import GitSubjectError, collect_git_subject
except ModuleNotFoundError:
    from _git_subject import GitSubjectError, collect_git_subject


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Exact Git repository root")
    parser.add_argument("--base-sha", help="Optional exact base commit")
    args = parser.parse_args(argv)
    try:
        subject = collect_git_subject(
            Path(args.root), base_sha=args.base_sha
        )
    except GitSubjectError as exc:
        print(f"git subject error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(subject, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
