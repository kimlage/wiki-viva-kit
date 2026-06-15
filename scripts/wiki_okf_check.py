#!/usr/bin/env python3
"""Check an Open Knowledge Format bundle for OKF v0.1 conformance."""

from __future__ import annotations

import argparse
import json

try:
    from scripts._common import ROOT
except ModuleNotFoundError:
    from _common import ROOT

from wiki_core.okf import check_okf_bundle


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, help="bundle root directory")
    parser.add_argument("--check", action="store_true", help="return non-zero when conformance errors exist")
    args = parser.parse_args()

    result = check_okf_bundle(ROOT / args.bundle)
    print(json.dumps(result.__dict__, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if args.check and result.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
