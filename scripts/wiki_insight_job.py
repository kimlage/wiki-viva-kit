#!/usr/bin/env python3
"""Minimal insight job: closes the Information -> Insight loop.

Gathers already-existing signals (score events + indexed chunks + memory
pages) about a THEME, assembles a context packet and emits an insight PROPOSAL
for human gating. Does NOT call a model and does NOT write canonical memory: the
synthesis is delegated to the agent running the repo; promotion to memory goes through a PR.

The artifacts (packet + proposal) go to data/derived/wiki/insight-jobs/
(gitignored). The agent reads the packet, synthesizes and opens the insight page via PR.

Examples:
  python3 scripts/wiki_insight_job.py --theme "gate de honestidade" --context sistema
  python3 scripts/wiki_insight_job.py --theme "conciliacao" --context financeiro --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wiki_core.config import load_config
from wiki_core.insight import run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--theme", required=True, help="theme/subject of the insight")
    parser.add_argument("--context", default="sistema")
    parser.add_argument("--limit", type=int, default=10, help="maximum chunks gathered")
    parser.add_argument("--dry-run", action="store_true", help="compute without writing artifacts")
    args = parser.parse_args()

    config = load_config(ROOT)
    result = run(
        args.theme,
        args.context,
        ROOT,
        config,
        write=not args.dry_run,
        limit=args.limit,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
