#!/usr/bin/env python3
"""Export the configured living-wiki memory tree as an OKF v0.1 bundle."""

from __future__ import annotations

import argparse
import json

try:
    from scripts._common import ROOT
except ModuleNotFoundError:
    from _common import ROOT

from wiki_core.config import load_config
from wiki_core.okf import export_okf_bundle


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", help="repo-relative source root; defaults to config paths.memory_root")
    parser.add_argument("--out", required=True, help="output bundle directory")
    parser.add_argument("--clean", action="store_true", help="delete the output directory before exporting")
    args = parser.parse_args()

    config = load_config(ROOT)
    result = export_okf_bundle(
        root=ROOT,
        source_root=args.source_root or str(config.paths["memory_root"]),
        bundle_root=ROOT / args.out,
        clean=args.clean,
    )
    print(json.dumps(result.__dict__, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
