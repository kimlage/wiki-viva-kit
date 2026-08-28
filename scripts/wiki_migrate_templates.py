#!/usr/bin/env python3
"""Assisted migration to the source-entity + template contracts.

Deterministic, additive-only, dry-run-first, PR-gated. It NEVER overwrites a
value the owner wrote and NEVER invents data — unknown values become explicit
``TODO`` placeholders for a human to complete.

Two concerns:

* ``--sources`` (default): add ``platform`` / ``source_locator`` / ``owner`` +
  a ``sync`` block to ``source`` pages, and scaffold a ``recipe:`` block on
  ``source_config`` pages that have none.
* ``--pinned``: REPORT (never write) pages whose ``page_type`` has pinned
  template fields the page is missing. The cockpit's template inspector already
  offers to fill these interactively; this is a read-only audit.

Usage:
    python3 scripts/wiki_migrate_templates.py            # dry-run source plan
    python3 scripts/wiki_migrate_templates.py --pinned   # + template gaps
    python3 scripts/wiki_migrate_templates.py --apply     # write source changes
"""

from __future__ import annotations

import argparse
import sys

try:  # importing _common bootstraps sys.path so wiki_core resolves
    from scripts._common import ROOT
except ModuleNotFoundError:
    from _common import ROOT

from wiki_core.config import load_config
from wiki_core.frontmatter import parse_frontmatter_flat
from wiki_core.source_migration import apply_change, plan_source_migration
from wiki_core.templates_registry import load_template_registry, resolve_template_spec


def _report_source_plan(changes: list, apply: bool) -> None:
    if not changes:
        print("sources: already at contract — nothing to migrate.")
        return
    verb = "APPLIED" if apply else "would add"
    print(f"sources: {len(changes)} page(s) to migrate ({'apply' if apply else 'dry-run'}):\n")
    for change in changes:
        print(f"  {change.rel}  [{change.page_type}]")
        for key, value in change.add_frontmatter.items():
            print(f"    {verb}: {key}: {value!r}")
        if change.append_recipe:
            print(f"    {verb}: recipe scaffold ({change.append_recipe.count(chr(10))} lines)")
        for note in change.notes:
            print(f"    note: {note}")
        print()


def _report_pinned_gaps(root, config) -> int:
    registry = load_template_registry(root, config)
    memory_root = root / str(config.paths.get("memory_root") or "memories")
    if not memory_root.exists():
        return 0
    gaps = 0
    lines: list[str] = []
    for path in sorted(memory_root.rglob("*.md")):
        values = parse_frontmatter_flat(path)
        page_type = str(values.get("page_type") or "")
        if not page_type or page_type not in registry.raw_types:
            continue
        spec = resolve_template_spec(registry, page_type)
        missing = [f for f in spec.pinned_fields if not str(values.get(f) or "").strip()]
        if missing:
            gaps += 1
            rel = path.relative_to(root).as_posix()
            lines.append(f"  {rel}  [{page_type}]  missing: {', '.join(missing)}")
    print(f"\ntemplates: {gaps} page(s) missing pinned fields (report-only):")
    for line in lines:
        print(line)
    return gaps


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="write source changes (default: dry-run)")
    parser.add_argument(
        "--operational-recipes",
        action="store_true",
        help="derive selected streams, targets, cadence and operator auth pointers from existing source metadata",
    )
    parser.add_argument("--no-sources", action="store_true", help="skip the source migration")
    parser.add_argument("--pinned", action="store_true", help="also report template pinned-field gaps")
    args = parser.parse_args()

    config = load_config(ROOT)

    if not args.no_sources:
        changes = plan_source_migration(
            ROOT, config, operational_recipes=args.operational_recipes
        )
        if args.apply:
            for change in changes:
                apply_change(ROOT, change)
        _report_source_plan(changes, args.apply)

    if args.pinned:
        _report_pinned_gaps(ROOT, config)

    if not args.apply:
        print("\n(dry-run — re-run with --apply to write, then review the PR)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
