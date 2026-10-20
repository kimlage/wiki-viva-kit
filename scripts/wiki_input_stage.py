#!/usr/bin/env python3
"""Compile the integral input stage from root entity, sources and configs."""

from __future__ import annotations

import argparse
import datetime as dt
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
    matching_input_stage_catalog,
    matching_input_stage_cache,
    render_input_stage_markdown,
    write_input_stage,
)
from wiki_core.paths import WikiPaths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the input-stage page and catalog")
    parser.add_argument("--if-changed", action="store_true",
                        help="with --write, preserve an exactly reproducible artifact and its date")
    parser.add_argument("--check", action="store_true", help="fail if generated files differ")
    parser.add_argument("--format", choices=["json", "markdown"], default="markdown")
    parser.add_argument(
        "--ready",
        action="store_true",
        help="print staged or ready_for_ingest input rows as JSON",
    )
    args = parser.parse_args()
    if args.if_changed and not args.write:
        parser.error("--if-changed requires --write")

    config = load_config(ROOT)
    paths = WikiPaths(ROOT, config)

    if args.write:
        page_before = paths.input_stage_page.read_bytes() if paths.input_stage_page.exists() else None
        cache_before = paths.input_stage_catalog.read_bytes() if paths.input_stage_catalog.exists() else None
        catalog = write_input_stage(ROOT, config, if_changed=args.if_changed)
        print(paths.input_stage_page.relative_to(ROOT).as_posix())
        print(paths.input_stage_catalog.relative_to(ROOT).as_posix())
        md_changed = page_before != paths.input_stage_page.read_bytes()
        cache_changed = cache_before != paths.input_stage_catalog.read_bytes()
        markdown_catalog = matching_input_stage_catalog(catalog, config, paths.input_stage_page.read_bytes())
        print(json.dumps(dict(md_changed=md_changed, catalog_changed=cache_changed,
                              md_publication_date=markdown_catalog["generated_at"],
                              catalog_generation_date=catalog["generated_at"],
                              executed_at=dt.datetime.now().astimezone().isoformat()), sort_keys=True))
        return 0

    generated_at = existing_generated_at(paths)
    if args.format == "json" and not args.check and not args.ready and not paths.input_stage_page.exists():
        # Without published Markdown, an unverified cache cannot date the
        # fallback. The complete-model check below may retain a valid cache.
        generated_at = None
    catalog = compile_input_stage(ROOT, config, generated_at=generated_at)
    markdown = render_input_stage_markdown(catalog, config)

    if args.check:
        errors: list[str] = []
        if not paths.input_stage_page.exists():
            errors.append(f"missing input-stage page: {paths.input_stage_page.relative_to(ROOT).as_posix()}")
        elif matching_input_stage_catalog(catalog, config, paths.input_stage_page.read_bytes()) is None:
            errors.append(f"stale input-stage page: {paths.input_stage_page.relative_to(ROOT).as_posix()}")

        if (paths.input_stage_catalog.exists()
                and matching_input_stage_cache(catalog, paths.input_stage_catalog.read_bytes()) is None):
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
        # JSON has its own generation date. Reuse it only when the complete
        # stored model reproduces current inputs; Markdown dates only Markdown.
        if paths.input_stage_catalog.exists():
            retained = matching_input_stage_cache(catalog, paths.input_stage_catalog.read_bytes())
            if retained is not None:
                catalog = retained
        print(json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
