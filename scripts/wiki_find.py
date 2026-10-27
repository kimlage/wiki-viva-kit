#!/usr/bin/env python3
"""Search local indexed content with provenance, without ingesting or calling a model."""
from __future__ import annotations

import argparse
import json

try:
    from scripts._common import ROOT
except ModuleNotFoundError:
    from _common import ROOT

from wiki_core.config import load_config
from wiki_core.find import find


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--context", help="Filter by observed local metadata before limiting hits")
    parser.add_argument("--source", help="Exact indexed source_id, including page:<page_id>")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args(argv)
    result = find(ROOT, load_config(ROOT), args.query, context=args.context,
                  source_id=args.source, limit=args.limit)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] in {"ok", "no_matches"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
