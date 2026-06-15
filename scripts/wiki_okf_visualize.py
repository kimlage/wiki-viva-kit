#!/usr/bin/env python3
"""Generate a self-contained HTML viewer for an OKF bundle."""

from __future__ import annotations

import argparse
import json

try:
    from scripts._common import ROOT
except ModuleNotFoundError:
    from _common import ROOT

from wiki_core.okf import generate_okf_visualization


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, help="bundle root directory")
    parser.add_argument("--out", help="output HTML path; defaults to <bundle>/viz.html")
    parser.add_argument("--name", help="display name for the viewer")
    args = parser.parse_args()

    bundle = ROOT / args.bundle
    output = ROOT / args.out if args.out else bundle / "viz.html"
    result = generate_okf_visualization(bundle, output, name=args.name)
    print(json.dumps(result.__dict__, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
