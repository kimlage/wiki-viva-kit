#!/usr/bin/env python3
"""End-to-end ingestion orchestrator for the living wiki.

Chains manifest -> text/chunks -> index -> pre-scan (secrets block; PII is
informative, welcome on a private page) -> input-stage-aware LLM context package
(emits the -request.json that the auditor gate watches) -> score-event. Replaces
the manual step-by-step run (each module had its own CLI). The LLM pass stays
delegated to the agent running the repo.

Examples:
  python3 scripts/wiki_ingest.py --source data/raw/example.pdf --context system
  python3 scripts/wiki_ingest.py --source X.md --context system --dry-run

Returns exit 2 for secrets or an incomplete retry that would replace a complete
capture. In either case the rejected attempt writes no artifacts.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wiki_core.config import load_config
from wiki_core.ingest import run
from wiki_core.llm.context_pass import DEFAULT_CONTEXT_MAX_BYTES, DEFAULT_REQUEST_MAX_BYTES


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--source", required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--dry-run", action="store_true", help="compute without writing artifacts")
    parser.add_argument("--no-score", action="store_true", help="do not record a score-event")
    parser.add_argument("--actor")
    parser.add_argument("--approved-revision", help="Current approved policy SHA supplied by the trusted local caller.")
    parser.add_argument("--policy-context", help="Explicit approved context ID; no fallback on refusal.")
    parser.add_argument("--context-max-bytes", type=int, default=DEFAULT_CONTEXT_MAX_BYTES)
    parser.add_argument("--request-max-bytes", type=int, default=DEFAULT_REQUEST_MAX_BYTES)
    business_root = parser.add_mutually_exclusive_group()
    business_root.add_argument("--root-entity-ref", help="Explicit authorized business-root page; this does not grant access.")
    business_root.add_argument("--omit-root-entity", action="store_true", help="Explicitly omit the business root with missing coverage; mandatory lineage rules still apply.")
    parser.add_argument("--stream", help="source recipe stream id (advances its cursor post-commit)")
    args = parser.parse_args()

    root = args.root.resolve()
    config = load_config(root)
    source = args.source
    if not Path(source).is_absolute() and not urlsplit(source).scheme:
        source = str(root / source)
    result = run(
        source,
        args.context,
        root,
        config,
        write=not args.dry_run,
        record_score=not args.no_score,
        actor=args.actor,
        stream_id=args.stream,
        approved_revision=args.approved_revision, policy_context=args.policy_context,
        context_max_bytes=args.context_max_bytes, request_max_bytes=args.request_max_bytes,
        root_entity_ref=args.root_entity_ref, omit_root_entity=args.omit_root_entity,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    if result.secret_findings:
        print(
            f"BLOCKED: {len(result.secret_findings)} secret(s) in the source; "
            "do not consolidate without removing.",
            file=sys.stderr,
        )
        return 2
    if result.blocked:
        print("BLOCKED: request preparation requires the reported context/budget action." if result.blockers else
              "BLOCKED: extraction retry was not accepted; the complete capture was retained.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
