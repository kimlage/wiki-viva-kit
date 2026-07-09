#!/usr/bin/env python3
"""Generate the local web cockpit JSON snapshot."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from scripts._common import ROOT
except ModuleNotFoundError:
    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))

from wiki_core.config import load_config
from wiki_core.paths import WikiPaths
from wiki_core.web.snapshot import write_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="", help="Output directory for snapshot JSON files.")
    parser.add_argument("--clean", action="store_true", help="Remove existing *.json files first.")
    parser.add_argument("--mode", default="static", choices=["static", "local_operator", "github_connected"])
    parser.add_argument(
        "--content-sidecars",
        action="store_true",
        help="Also write content/{page}.json sidecars so the static reader can show full pages.",
    )
    parser.add_argument(
        "--check-contract",
        action="store_true",
        help="Build in memory and fail unless the v8 atomic envelope and integrity contract are complete.",
    )
    args = parser.parse_args()

    config = load_config(ROOT)
    if args.out:
        raw_out = Path(args.out)
        out_dir = raw_out if raw_out.is_absolute() else ROOT / raw_out
    else:
        out_dir = WikiPaths(ROOT, config).derived_root / "web-snapshot"
    if args.check_contract:
        from wiki_core.web.snapshot import build_snapshot, snapshot_contract_errors

        payloads = build_snapshot(ROOT, config, mode=args.mode, content_sidecars=args.content_sidecars)
        manifest = payloads["manifest.json"]
        missing = [name for name in manifest["files"] if name != "manifest.json" and name not in manifest["integrity"]]
        errors = snapshot_contract_errors(payloads)
        if missing or errors or not manifest.get("snapshot_id") or not manifest.get("bundle_hash"):
            print(f"snapshot contract invalid: missing={missing}; errors={errors}", file=sys.stderr)
            return 1
        print(f"snapshot contract ok: {manifest['snapshot_id']} ({len(manifest['integrity'])} payloads)")
        return 0
    written = write_snapshot(
        ROOT, out_dir, config, clean=args.clean, mode=args.mode, content_sidecars=args.content_sidecars
    )
    for name in sorted(written):
        print(f"{name}: {written[name].relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
