#!/usr/bin/env python3
"""Compile a deterministic read-only v8 upgrade preflight for one consumer."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from scripts._common import ROOT
except ModuleNotFoundError:
    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))

from wiki_core.upgrade import (
    build_preflight_report,
    consumer_from_inventory,
    load_mapping,
    validate_consumer_inventory,
    validate_upgrade_package,
)

PACKAGE = ROOT / "docs/references/upgrades/wiki-viva-v8/upgrade-package.yaml"
INVENTORY = ROOT / "docs/references/upgrades/wiki-viva-v8/consumer-inventory.yaml"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--consumer-root", type=Path, required=True)
    parser.add_argument("--consumer-id", required=True)
    parser.add_argument("--kit-root", type=Path, default=ROOT)
    parser.add_argument("--package", type=Path, default=PACKAGE)
    parser.add_argument("--inventory", type=Path, default=INVENTORY)
    parser.add_argument("--gate-evidence", type=Path)
    parser.add_argument(
        "--checked-on",
        required=True,
        help="explicit YYYY-MM-DD; keeps the report reproducible",
    )
    parser.add_argument(
        "--redact", action="store_true", help="remove local paths and drift filenames"
    )
    parser.add_argument("--out", type=Path)
    parser.add_argument(
        "--check", action="store_true", help="exit 1 unless the consumer is ready"
    )
    args = parser.parse_args(argv)

    try:
        package = load_mapping(args.package)
        inventory = load_mapping(args.inventory)
        errors = validate_upgrade_package(package) + validate_consumer_inventory(
            inventory
        )
        if errors:
            raise ValueError("; ".join(errors))
        consumer = consumer_from_inventory(inventory, args.consumer_id)
        gate_evidence = load_mapping(args.gate_evidence) if args.gate_evidence else None
        report = build_preflight_report(
            kit_root=args.kit_root.resolve(),
            consumer_root=args.consumer_root.resolve(),
            package=package,
            consumer=consumer,
            gate_evidence=gate_evidence,
            checked_on=args.checked_on,
            redact=args.redact,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": "wiki_viva_upgrade_preflight.v1",
                    "status": "invalid",
                    "errors": [str(exc)],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    output = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.out:
        _write(args.out, output)
    print(output, end="")
    return 1 if args.check and report["status"] != "ready" else 0


if __name__ == "__main__":
    raise SystemExit(main())
