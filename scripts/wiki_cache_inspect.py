#!/usr/bin/env python3
"""Inspect wiki LLM cache and derived extraction coverage."""

from __future__ import annotations

import argparse
import json

try:  # importing _common bootstraps sys.path so wiki_core resolves
    from scripts._common import ROOT  # package/spec-loader import
except ModuleNotFoundError:
    from _common import ROOT  # direct run: scripts/ on sys.path

from wiki_core.config import load_config
from wiki_core.llm import cache_summary
from wiki_core.paths import WikiPaths
from wiki_core.source_manifest import build_manifest


def main() -> int:
    config = load_config(ROOT)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--source")
    parser.add_argument("--context", default=config.default_context)
    args = parser.parse_args()

    paths = WikiPaths(ROOT, config)
    paths.ensure()
    summary = cache_summary(paths.llm_cache)
    summary["manifests"] = len(list(paths.source_manifests.glob("*.json")))
    summary["text_sources"] = len(list(paths.source_text.glob("*.json")))
    summary["chunk_sources"] = len(list(paths.chunks.glob("*.json")))
    summary["context_plans"] = len(list(paths.extraction_events.glob("*llm-context-plan.json")))
    if args.source:
        manifest = build_manifest(args.source, args.context)
        source_id = str(manifest["source_id"])
        summary["source"] = {
            "source_id": source_id,
            "manifest_exists": (paths.source_manifests / f"{source_id}.json").exists(),
            "text_exists": (paths.source_text / f"{source_id}.json").exists(),
            "chunks_exist": (paths.chunks / f"{source_id}.json").exists(),
            "llm_plan_exists": (paths.extraction_events / f"{source_id}-llm-context-plan.json").exists(),
        }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
