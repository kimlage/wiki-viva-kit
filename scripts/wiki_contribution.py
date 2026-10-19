#!/usr/bin/env python3
"""Prepare, publish or reconcile a reviewed action body with any local agent."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from _common import ROOT
from wiki_core.config import load_config
from wiki_core.web.git_workflows import run_git_workflow


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("operation", choices=("prepare", "publish", "integrate", "reconcile"))
    p.add_argument("--root", type=Path, default=ROOT)
    p.add_argument("--request", type=Path, required=True)
    p.add_argument("--review", type=Path)
    p.add_argument("--pr", type=int)
    p.add_argument("--apply", action="store_true", help="Execute; otherwise validate a dry run.")
    args = p.parse_args()
    try:
        for file in (args.request, args.review):
            if file and file.stat().st_size > 1_000_000:
                p.error("input file exceeds limit")
        payload = {"request": json.loads(args.request.read_text()), "pr": args.pr}
        if args.review:
            payload["review"] = json.loads(args.review.read_text())
        root = args.root.resolve()
        result = run_git_workflow(root, load_config(root), args.operation + "_contribution",
                                  payload, dry_run=not args.apply)
    except (OSError, ValueError):
        result = {"ok": False, "status": "refused", "error": "unreadable_input_or_configuration",
                  "canonical_body_adopted": False}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
