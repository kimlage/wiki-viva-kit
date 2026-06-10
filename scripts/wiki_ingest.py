#!/usr/bin/env python3
"""End-to-end ingestion orchestrator for the living wiki.

Chains manifest -> text/chunks -> index -> pre-scan (secrets block; PII is
informative, welcome on a private page) -> LLM context package (emits the
-request.json that the auditor gate watches) -> score-event. Replaces the manual
step-by-step run (each module had its own CLI). The LLM pass stays delegated to
the agent running the repo.

Examples:
  python3 scripts/wiki_ingest.py --source data/raw/example.pdf --context system
  python3 scripts/wiki_ingest.py --source X.md --context system --dry-run

Returns exit 2 if the pre-triage finds a SECRET in the source (block at origin).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wiki_core.config import load_config
from wiki_core.ingest import run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--dry-run", action="store_true", help="compute without writing artifacts")
    parser.add_argument("--no-score", action="store_true", help="do not record a score-event")
    parser.add_argument("--actor")
    args = parser.parse_args()

    config = load_config(ROOT)
    result = run(
        args.source,
        args.context,
        ROOT,
        config,
        write=not args.dry_run,
        record_score=not args.no_score,
        actor=args.actor,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    if result.secret_findings:
        print(
            f"BLOCKED: {len(result.secret_findings)} secret(s) in the source; "
            "do not consolidate without removing.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
