#!/usr/bin/env python3
"""Report whether ingestion events have become integrated wiki memory."""

from __future__ import annotations

import argparse
import json
import sys

try:  # importing _common bootstraps sys.path so wiki_core resolves
    from scripts._common import ROOT  # package/spec-loader import
except ModuleNotFoundError:
    from _common import ROOT  # direct run: scripts/ on sys.path

from wiki_core.closure import build_ingestion_closure_report, render_markdown
from wiki_core.config import load_config


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
        help="fail when unclosed events or source closure gaps exceed allowed budgets",
    )
    parser.add_argument(
        "--allow-ingested-source-gaps",
        type=int,
        default=0,
        help="maximum ingested sources without closed event allowed under --check",
    )
    args = parser.parse_args(argv)

    config = load_config(ROOT)
    report = build_ingestion_closure_report(ROOT, config)
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
        unclosed = int(report["summary"]["events_without_consolidated_into"])
        source_gaps = int(report["summary"]["ingested_sources_without_closed_event"])
        if unclosed:
            print(
                f"wiki_ingestion_closure_report: events_without_consolidated_into={unclosed}",
                file=sys.stderr,
            )
            return 1
        if source_gaps > args.allow_ingested_source_gaps:
            print(
                "wiki_ingestion_closure_report: "
                f"ingested_sources_without_closed_event={source_gaps} "
                f"> allow_ingested_source_gaps={args.allow_ingested_source_gaps}",
                file=sys.stderr,
            )
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
