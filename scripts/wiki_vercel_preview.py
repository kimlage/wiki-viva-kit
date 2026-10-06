#!/usr/bin/env python3
"""Prepare a synthetic-only Vercel prebuilt preview; never deploy or change ACLs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from scripts._common import ROOT
except ModuleNotFoundError:
    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))

from wiki_core.web.vercel_preview import write_vercel_preview


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", required=True, help="Use only the committed public walking_skeleton fixture.")
    parser.add_argument("--out", required=True, help="New immutable output directory inside this repository.")
    args = parser.parse_args()
    try:
        result = write_vercel_preview(ROOT, Path(args.out))
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"output: {result['output'].relative_to(ROOT).as_posix()}")
    print(f"source_head: {result['source_head']}")
    print(f"snapshot_id: {result['snapshot_id']}")
    print(f"payload_count: {result['payload_count']}")
    print("Deployment and Vercel Authentication are separate operator actions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
