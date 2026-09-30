#!/usr/bin/env python3
"""Explicit, repeat-safe C3 adoption of an already installed pack version.

Uses the existing bounded upgrade operation. It never installs a missing pack,
activates a disabled pack or executes a user-content migration language.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wiki_core.experience_packs import (  # noqa: E402
    PackError,
    load_lock,
    resolve_pack,
    upgrade_pack,
    validate_installation,
)


def adopt_pack(
    root: Path, pack: str, version: str, *, dry_run: bool = False,
    branch: str | None = None,
) -> dict[str, Any]:
    source = resolve_pack(root, pack, version=version)
    entry = load_lock(root)["packs"].get(pack)
    if not isinstance(entry, dict):
        raise PackError("pack_not_installed", pack)
    if entry["version"] == source.version:
        if (entry["manifest_sha256"] != source.manifest_sha256
                or entry["tree_sha256"] != source.tree_sha256):
            raise PackError("installed_source_pin_mismatch", pack)
        validation = validate_installation(root)
        if validation["errors"]:
            raise PackError("installed_pack_validation_failed", pack)
        return {
            "schema_version": "wiki_experience_pack_adoption.v1",
            "status": "unchanged", "pack": pack, "version": version,
            "installed_status": entry["status"], "conceptual_diff": [],
        }
    # The normal upgrade enforces version ordering, the declarative migration,
    # reviewed Git branch, owned-bundle hashes, lock and receipt boundaries.
    return upgrade_pack(root, pack, version=version, dry_run=dry_run, branch=branch)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack")
    parser.add_argument("--version", required=True)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--branch")
    args = parser.parse_args(argv)
    try:
        result = adopt_pack(args.root.resolve(), args.pack, args.version,
                            dry_run=args.dry_run, branch=args.branch)
    except PackError as exc:
        result = {"schema_version": "wiki_experience_pack_error.v1",
                  "status": "blocked", "error": {"code": exc.code, "detail": exc.detail}}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
