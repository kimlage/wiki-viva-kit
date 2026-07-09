#!/usr/bin/env python3
"""Validate and summarize the public Wiki Viva downstream consumer inventory."""

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

from wiki_core.upgrade import load_mapping, validate_consumer_inventory

DEFAULT_INVENTORY = (
    ROOT / "docs/references/upgrades/wiki-viva-v8/consumer-inventory.yaml"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 when the inventory contract is invalid",
    )
    args = parser.parse_args(argv)

    try:
        inventory = load_mapping(args.inventory)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {"status": "invalid", "errors": [str(exc)]},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1 if args.check else 0
    errors = validate_consumer_inventory(inventory)
    consumers = (
        inventory.get("consumers")
        if isinstance(inventory.get("consumers"), list)
        else []
    )
    waves: dict[str, int] = {}
    for consumer in consumers:
        if not isinstance(consumer, dict):
            continue
        wave = str(consumer.get("upgrade_wave") or "unknown")
        waves[wave] = waves.get(wave, 0) + 1
    result = {
        "schema_version": inventory.get("schema_version"),
        "verified_on": inventory.get("verified_on"),
        "status": "valid" if not errors else "invalid",
        "consumer_count": len(consumers),
        "waves": dict(sorted(waves.items())),
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if args.check and errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
