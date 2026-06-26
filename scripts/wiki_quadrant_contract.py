#!/usr/bin/env python3
"""Print the canonical Wilber/AQAL quadrant contract used by the kit."""

from __future__ import annotations

import argparse
import json

try:
    from scripts._common import ROOT  # package/spec-loader import
except ModuleNotFoundError:
    from _common import ROOT  # direct run

from wiki_core.config import load_config
from wiki_core.quadrants import quadrant_contract


def _render_markdown(contract: dict[str, object]) -> str:
    quadrants = contract["quadrants"]
    assert isinstance(quadrants, dict)
    lines = [
        "# Wilber/AQAL Quadrant Contract",
        "",
        f"- Schema: `{contract['schema_version']}`",
        f"- Model: {contract['model']}",
        "- Axes: `interior/exterior` x `individual/collective`",
        "",
        "| Quadrant | Semantic key | AQAL position | Perspective | Operational test |",
        "| --- | --- | --- | --- | --- |",
    ]
    for quadrant_id, quadrant in quadrants.items():
        assert isinstance(quadrant, dict)
        operational_test = str(quadrant["operational_test"]).replace("|", "\\|")
        lines.append(
            "| "
            + " | ".join(
                [
                    str(quadrant_id),
                    str(quadrant["semantic_key"]),
                    str(quadrant["aqal_position"]),
                    str(quadrant["perspective_id"]),
                    operational_test,
                ]
            )
            + " |"
        )
    lines.extend(["", "## Boundary Rule", "", str(contract["boundary_rule"]), ""])
    anti_patterns = contract["anti_patterns"]
    assert isinstance(anti_patterns, list)
    lines.extend(["## Anti-patterns", ""])
    lines.extend(f"- {item}" for item in anti_patterns)
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    args = parser.parse_args()

    config = load_config(ROOT)
    contract = quadrant_contract(config.language)
    if args.format == "markdown":
        print(_render_markdown(contract))
    else:
        print(json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
