#!/usr/bin/env python3
"""Report Wiki Viva v6.3 quality and cost telemetry.

The report is deterministic and has no LLM client. Cost is measured for control
and comparison only; v6.3 intentionally does not enforce a hard budget.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wiki_core.config import load_config
from wiki_core.quality import build_quality_report, render_markdown


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="output format (default: markdown)",
    )
    parser.add_argument("--output", help="write report to this repo-relative path")
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when quality metrics exceed their configured thresholds",
    )
    parser.add_argument(
        "--max-bad-repetition",
        type=int,
        default=None,
        help=(
            "maximum same-context/same-type repetition blocks allowed under --check "
            "(default: audit.quality_max_bad_repetition or 0)"
        ),
    )
    parser.add_argument(
        "--max-low-density",
        type=int,
        default=None,
        help=(
            "maximum low-information-density pages allowed under --check "
            "(default: audit.quality_max_low_density or 0)"
        ),
    )
    args = parser.parse_args(argv)

    config = load_config(ROOT)
    report = build_quality_report(ROOT, config)
    if args.format == "json":
        output = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    else:
        output = render_markdown(report)

    if args.output:
        out = ROOT / args.output
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(output, encoding="utf-8")
        print(f"wrote {out.relative_to(ROOT).as_posix()}")
    else:
        print(output, end="" if output.endswith("\n") else "\n")

    if args.check:
        bad = int(report["summary"]["bad_repetition_blocks"])
        low_density = int(report["summary"]["low_information_density_pages"])
        missing_exemption_reason = int(
            report["summary"].get("quality_exemption_missing_reason", 0)
        )
        try:
            max_bad_repetition = int(
                args.max_bad_repetition
                if args.max_bad_repetition is not None
                else config.audit.get("quality_max_bad_repetition", 0)
            )
            max_low_density = int(
                args.max_low_density
                if args.max_low_density is not None
                else config.audit.get("quality_max_low_density", 0)
            )
        except (TypeError, ValueError):
            print(
                "wiki_quality_report: invalid quality threshold in args/config",
                file=sys.stderr,
            )
            return 2
        if bad > max_bad_repetition:
            print(
                f"wiki_quality_report: bad_repetition_blocks={bad} "
                f"> max_bad_repetition={max_bad_repetition}",
                file=sys.stderr,
            )
            return 1
        if low_density > max_low_density:
            print(
                f"wiki_quality_report: low_information_density_pages={low_density} "
                f"> max_low_density={max_low_density}",
                file=sys.stderr,
            )
            return 1
        if missing_exemption_reason:
            print(
                "wiki_quality_report: "
                f"quality_exemption_missing_reason={missing_exemption_reason}",
                file=sys.stderr,
            )
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
