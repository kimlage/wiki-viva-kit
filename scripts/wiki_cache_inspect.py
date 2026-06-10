#!/usr/bin/env python3
"""Inspect wiki LLM cache and derived extraction coverage."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wiki_core.config import load_config
from wiki_core.llm import cache_summary
from wiki_core.paths import WikiPaths
from wiki_core.source_manifest import build_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--source")
    parser.add_argument("--context", default="sistema")
    args = parser.parse_args()

    paths = WikiPaths(ROOT, load_config(ROOT))
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
