#!/usr/bin/env python3
"""Compile the operational pass across sources, actions and contexts."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wiki_core.config import load_config
from wiki_core.operational_pass import (
    build_operational_pass_page,
    build_operational_pass_report,
    read_markdown_page,
    report_to_dict,
)
from wiki_core.paths import WikiPaths


def _recorded_date(path: Path, fallback: str) -> str:
    if not path.exists():
        return fallback
    page = read_markdown_page(path, ROOT, "system")
    return page.updated_at or fallback


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the configured operational-pass page")
    parser.add_argument("--check", action="store_true", help="fail if the generated page is out of date")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", help="write to a repo-relative path instead of the configured page")
    parser.add_argument("--date", default=dt.date.today().isoformat())
    parser.add_argument("--context", action="append", default=[], help="restrict to one context; repeatable")
    args = parser.parse_args()

    config = load_config(ROOT)
    paths = WikiPaths(ROOT, config)
    target_path = Path(args.output) if args.output else None
    target = ROOT / target_path if target_path is not None else paths.operational_pass_page
    contexts = tuple(args.context)

    if args.format == "json":
        as_of = dt.date.fromisoformat(args.date)
        report = build_operational_pass_report(
            ROOT,
            config,
            as_of=as_of,
            contexts=contexts,
            exclude_path=target_path,
        )
        payload = json.dumps(report_to_dict(report), ensure_ascii=False, indent=2)
        if args.write or args.output:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(payload + "\n", encoding="utf-8")
            print(paths.rel(target))
            return 0
        print(payload)
        return 0

    if args.check:
        if not target.exists():
            print(f"{paths.rel(target)}: missing (run wiki_operational_pass.py --write)", file=sys.stderr)
            return 1
        expected = build_operational_pass_page(
            ROOT,
            config,
            updated_at=_recorded_date(target, args.date),
            contexts=contexts,
            target_path=target_path,
        )
        actual = target.read_text(encoding="utf-8")
        if expected != actual:
            print(f"{paths.rel(target)}: operational pass out of date; run wiki_operational_pass.py --write", file=sys.stderr)
            return 1
        print(f"{paths.rel(target)}: operational pass up to date.")
        return 0

    page = build_operational_pass_page(
        ROOT,
        config,
        updated_at=args.date,
        contexts=contexts,
        target_path=target_path,
    )
    if args.write or args.output:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(page, encoding="utf-8")
        print(paths.rel(target))
        return 0
    print(page)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
