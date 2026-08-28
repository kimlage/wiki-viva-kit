#!/usr/bin/env python3
"""Prepare portable web cockpit deploy inputs for one implementation."""

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
from wiki_core.web.deploy_bundle import write_deploy_bundle


def _display(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="", help="Output directory for config, snapshot and deployment proof.")
    parser.add_argument("--snapshot-base", default="/snapshot", help="Runtime snapshot base path or URL.")
    parser.add_argument("--api-base", default="", help="Runtime operator API base URL. Leave empty for static/read-only deploys.")
    parser.add_argument("--repo-label", default="", help="Display label for the deployed cockpit.")
    parser.add_argument("--mode", default="static", choices=["static", "local_operator", "github_connected", "controlled_operator"])
    parser.add_argument("--data-boundary", default="synthetic_or_public", help="Declared data boundary for this deploy proof.")
    parser.add_argument("--target", default="static", help="Deployment target label, such as vercel_static or cloud_run_operator.")
    parser.add_argument("--clean", action="store_true", help="Remove existing snapshot *.json files first.")
    parser.add_argument(
        "--force-unowned-output",
        action="store_true",
        help=(
            "Explicitly adopt a non-empty unmarked output directory inside the repo. "
            "Review its contents first; external paths remain forbidden."
        ),
    )
    args = parser.parse_args()

    config = load_config(ROOT)
    if args.out:
        raw_out = Path(args.out)
        out_dir = raw_out if raw_out.is_absolute() else ROOT / raw_out
    else:
        out_dir = WikiPaths(ROOT, config).derived_root / "web-cockpit-deploy"
    try:
        written = write_deploy_bundle(
            ROOT,
            out_dir,
            config,
            snapshot_base=args.snapshot_base,
            api_base=args.api_base,
            repo_label=args.repo_label,
            runtime_mode=args.mode,
            data_boundary=args.data_boundary,
            target=args.target,
            clean=args.clean,
            force_unowned_output=args.force_unowned_output,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    for name in sorted(written):
        print(f"{name}: {_display(written[name])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
