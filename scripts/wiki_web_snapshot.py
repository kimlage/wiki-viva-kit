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
from wiki_core.web.snapshot import validate_snapshot_output_location, write_snapshot


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="", help="Output directory for snapshot JSON files.")
    parser.add_argument(
        "--clean",
        action="store_true",
        help=(
            "Compatibility flag. A complete validated immutable revision is always "
            "activated; stale active artifacts are never retained."
        ),
    )
    parser.add_argument(
        "--force-unowned-output",
        action="store_true",
        help=(
            "Explicitly adopt a non-empty unmarked output directory inside the repo. "
            "Review its contents first; external paths remain forbidden."
        ),
    )
    parser.add_argument("--mode", default="static", choices=["static", "local_operator", "github_connected"])
    parser.add_argument(
        "--content-sidecars",
        action="store_true",
        help="Also write content/{page}.json sidecars so the static reader can show full pages.",
    )
    parser.add_argument(
        "--flat-build",
        action="store_true",
        help=(
            "Write a flat offline/static build artifact. Never mutate this target "
            "while it is being served; the host must activate the build atomically."
        ),
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
    # Reject escaped or unrecognized symlink targets before walking/building the
    # repository. Output trust errors must not be masked by unrelated content
    # diagnostics from an expensive snapshot build.
    validate_snapshot_output_location(ROOT, out_dir, repo_id=config.repo_id)
    written = write_snapshot(
        ROOT,
        out_dir,
        config,
        clean=args.clean,
        mode=args.mode,
        content_sidecars=args.content_sidecars,
        force_unowned_output=args.force_unowned_output,
        publication="flat_build" if args.flat_build else "auto",
    )
    for name in sorted(written):
        print(f"{name}: {_display_path(written[name])}")
    if hasattr(written, "active_revision"):
        print(
            "activation: committed "
            f"snapshot={written.snapshot_id} revision={written.active_revision}"
        )
        for warning in written.cleanup_warnings:
            print(f"cleanup warning: {warning}", file=sys.stderr)
        for recovery in written.recovery_paths:
            print(f"recovery: {_display_path(recovery)}", file=sys.stderr)
    else:
        print("activation: flat build (host/offline atomic activation required)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
