#!/usr/bin/env python3
"""Validate v8 migration evidence and compile deterministic JSON/Markdown reports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

try:
    from scripts._common import ROOT
except ModuleNotFoundError:
    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))

from wiki_core.upgrade import (
    compile_migration_report,
    load_mapping,
    migration_evidence_template,
    render_migration_report_markdown,
    validate_upgrade_package,
)

PACKAGE = ROOT / "docs/references/upgrades/wiki-viva-v8/upgrade-package.yaml"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=PACKAGE)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--evidence", type=Path)
    group.add_argument(
        "--template",
        action="store_true",
        help="print a deterministic evidence template",
    )
    parser.add_argument(
        "--public-export",
        action="store_true",
        help="enforce public redaction/PII boundary",
    )
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    parser.add_argument(
        "--check", action="store_true", help="exit 1 unless the report is complete"
    )
    args = parser.parse_args(argv)

    try:
        package = load_mapping(args.package)
        package_errors = validate_upgrade_package(package)
        if package_errors:
            raise ValueError("; ".join(package_errors))
        if args.template:
            print(
                yaml.safe_dump(
                    migration_evidence_template(package),
                    sort_keys=False,
                    allow_unicode=True,
                ),
                end="",
            )
            return 0
        evidence = load_mapping(args.evidence)
        report = compile_migration_report(
            evidence, package, public_export=args.public_export
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": "wiki_viva_migration_report.v1",
                    "status": "invalid",
                    "errors": [str(exc)],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    json_output = (
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    markdown_output = render_migration_report_markdown(report)
    if args.json_out:
        _write(args.json_out, json_output)
    if args.markdown_out:
        _write(args.markdown_out, markdown_output)
    if not args.json_out and not args.markdown_out:
        print(json_output, end="")
    return 1 if args.check and report["status"] != "complete" else 0


if __name__ == "__main__":
    raise SystemExit(main())
