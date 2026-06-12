#!/usr/bin/env python3
"""Build and validate the Wiki Viva page graph."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wiki_core.config import WikiConfig, load_config
from wiki_core.graph import (
    build_page_graph,
    compute_impact,
    graph_to_dict,
    min_outbound_violations,
    orphan_pages,
    unreachable_pages,
)
from wiki_core.paths import WikiPaths


def run_git(args: list[str]) -> str:
    try:
        return subprocess.check_output(
            ["git", *args],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.CalledProcessError:
        return ""


def resolve_base(base: str | None) -> str | None:
    candidates = [base] if base else []
    head_base = run_git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"])
    candidates.extend([head_base, "origin/main", "main"])
    for candidate in candidates:
        if candidate and run_git(["rev-parse", "--verify", "--quiet", candidate]):
            return candidate
    return None


def changed_paths(base: str | None) -> set[str]:
    resolved = resolve_base(base)
    changed: set[str] = set()
    if resolved:
        changed.update(run_git(["diff", "--name-only", f"{resolved}...HEAD"]).splitlines())
    changed.update(run_git(["diff", "--name-only"]).splitlines())
    changed.update(run_git(["diff", "--cached", "--name-only"]).splitlines())
    return {p for p in changed if p}


def graph_path(config: WikiConfig) -> Path:
    return WikiPaths(ROOT, config).derived_root / "page-graph" / "page-graph.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write data/derived/wiki/page-graph/page-graph.json")
    parser.add_argument("--check", action="store_true", help="return non-zero for graph errors")
    parser.add_argument("--impact", action="store_true", help="print impacted memory pages for the current diff")
    parser.add_argument("--base", help="base ref for --impact (default: upstream/origin/main/main)")
    args = parser.parse_args()

    config = load_config(ROOT)
    graph = build_page_graph(ROOT, config)

    if args.write:
        out = graph_path(config)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(graph_to_dict(graph), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {out.relative_to(ROOT).as_posix()}")

    errors: list[str] = []
    warnings: list[str] = []
    audit_config = config.audit
    root_page = str(audit_config.get("reachability_root") or config.paths["memory_root"].rstrip("/") + "/index.md")
    for rel in orphan_pages(graph, set(audit_config.get("orphan_exempt_types") or [])):
        errors.append(f"{rel}: orphan memory page")
    for rel in unreachable_pages(graph, root_page):
        errors.append(f"{rel}: unreachable from {root_page}")
    try:
        minimum = int(str(audit_config.get("min_outbound_links", 0) or 0))
    except ValueError:
        minimum = 0
        errors.append("config: audit.min_outbound_links invalid (integer expected)")
    if minimum > 0:
        for rel in min_outbound_violations(graph, minimum=minimum):
            warnings.append(f"{rel}: fewer than {minimum} outbound graph links")

    if args.impact:
        result = compute_impact(
            graph,
            changed_paths(args.base),
            exempt_types=set(audit_config.get("impact_exempt_types") or []),
        )
        print(json.dumps({
            "changed_pages": list(result.changed_pages),
            "affected_pages": list(result.affected_pages),
            "references": {k: list(v) for k, v in result.references.items()},
        }, indent=2, sort_keys=True))

    for warning in warnings:
        print(f"WARN: {warning}")
    for error in errors:
        print(f"ERROR: {error}")
    print(f"wiki_page_graph: {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if args.check and errors else 0


if __name__ == "__main__":
    sys.exit(main())
