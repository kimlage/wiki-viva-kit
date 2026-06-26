#!/usr/bin/env python3
"""Compile the integral input stage from root entity, sources and configs."""

from __future__ import annotations

import argparse
import json
import sys

try:
    from scripts._common import ROOT  # package/spec-loader import
except ModuleNotFoundError:
    from _common import ROOT  # direct run

from wiki_core.config import load_config
from wiki_core.input_stage import (
    compile_input_stage,
    existing_generated_at,
    render_input_stage_markdown,
    write_input_stage,
)
from wiki_core.paths import WikiPaths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the input-stage page and catalog")
    parser.add_argument("--check", action="store_true", help="fail if generated files differ")
    parser.add_argument("--format", choices=["json", "markdown"], default="markdown")
    parser.add_argument(
        "--ready",
        action="store_true",
        help="print staged or ready_for_ingest input rows as JSON",
    )
    args = parser.parse_args()

    config = load_config(ROOT)
    paths = WikiPaths(ROOT, config)

    if args.write:
        catalog = write_input_stage(ROOT, config)
        print(paths.input_stage_page.relative_to(ROOT).as_posix())
        print(paths.input_stage_catalog.relative_to(ROOT).as_posix())
        return 0

    generated_at = existing_generated_at(paths)
    catalog = compile_input_stage(ROOT, config, generated_at=generated_at)
    markdown = render_input_stage_markdown(catalog, config)

    if args.check:
        errors: list[str] = []
        if not paths.input_stage_page.exists():
            errors.append(f"missing input-stage page: {paths.input_stage_page.relative_to(ROOT).as_posix()}")
        elif paths.input_stage_page.read_text(encoding="utf-8") != markdown:
            errors.append(f"stale input-stage page: {paths.input_stage_page.relative_to(ROOT).as_posix()}")

        expected_json = json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if paths.input_stage_catalog.exists() and paths.input_stage_catalog.read_text(encoding="utf-8") != expected_json:
            errors.append(f"stale input-stage catalog: {paths.input_stage_catalog.relative_to(ROOT).as_posix()}")

        if errors:
            for error in errors:
                print(f"ERROR: {error}", file=sys.stderr)
            return 1
        print("input stage deterministic content equal to a recompile at HEAD.")
        return 0

    if args.ready:
        print(json.dumps(catalog.get("ready_inputs", []), ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.format == "json":
        print(json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
