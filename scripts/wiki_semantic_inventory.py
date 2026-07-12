#!/usr/bin/env python3
"""Check authored event/relation semantics against snapshot read models."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

try:  # package/spec-loader import
    from scripts._common import ROOT
except ModuleNotFoundError:  # direct execution from scripts/
    from _common import ROOT

from wiki_core.config import load_config
from wiki_core.semantic_inventory import (
    SEMANTIC_INVENTORY_SCHEMA_VERSION,
    SemanticInventoryError,
    build_semantic_inventory,
    load_snapshot_payloads,
    render_markdown,
)


def _operational_failure(code: str) -> dict[str, object]:
    return {
        "schema_version": SEMANTIC_INVENTORY_SCHEMA_VERSION,
        "status": "error",
        "summary": {"error_count": 1},
        "operational_error": {"code": code},
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="return non-zero when semantic parity does not hold",
    )
    parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
        help="sanitized output format",
    )
    parser.add_argument(
        "--snapshot-dir",
        help="optional existing snapshot directory; omitted builds read models in memory",
    )
    args = parser.parse_args(argv)

    try:
        config = load_config(ROOT)
        payloads = (
            load_snapshot_payloads(Path(args.snapshot_dir))
            if args.snapshot_dir
            else None
        )
        report = build_semantic_inventory(ROOT, config, payloads)
    except SemanticInventoryError as exc:
        report = _operational_failure(exc.code)
        print(
            json.dumps(report, indent=2, sort_keys=True)
            if args.format == "json"
            else (
                "# Wiki semantic inventory\n\n"
                "- Status: **ERROR**\n"
                f"- Operational code: `{exc.code}`\n"
            ),
            end="\n" if args.format == "json" else "",
        )
        return 2

    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render_markdown(report), end="")
    if args.check and report.get("status") != "pass":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
