#!/usr/bin/env python3
"""Preview importing an OKF bundle into a Wiki Viva memory tree."""

from __future__ import annotations

import argparse
import json

try:
    from scripts._common import ROOT
except ModuleNotFoundError:
    from _common import ROOT

from wiki_core.config import load_config
from wiki_core.okf import import_preview_to_dict, preview_okf_import


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, help="bundle root directory")
    parser.add_argument("--context", help="target context for imported concepts")
    parser.add_argument("--memory-root", help="target memory root; defaults to config paths.memory_root")
    parser.add_argument("--dry-run", action="store_true", help="required; print the import preview without writing memory")
    args = parser.parse_args()

    if not args.dry_run:
        parser.error("OKF import currently supports --dry-run only; write through a reviewed ingestion proposal")

    config = load_config(ROOT)
    preview = preview_okf_import(
        bundle_root=ROOT / args.bundle,
        context=args.context or config.default_context,
        memory_root=args.memory_root or str(config.paths["memory_root"]),
        default_visibility=config.default_visibility,
    )
    print(json.dumps(import_preview_to_dict(preview), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
