#!/usr/bin/env python3
"""End-to-end ingestion orchestrator for the living wiki.

Chains manifest -> text/chunks -> index -> pre-scan (secrets block; PII is
informative, welcome on a private page) -> input-stage-aware LLM context package
(emits the -request.json that the auditor gate watches) -> score-event. Replaces
the manual step-by-step run (each module had its own CLI). The LLM pass stays
delegated to the agent running the repo.

Approved-context example (replace placeholders with authorized values):
  python3 scripts/wiki_ingest.py --source SOURCE --context SOURCE_CONTEXT \\
    --approved-revision APPROVED_SHA --policy-context CONTEXT_ID

Working-tree compatibility example (does not establish approved policy or source freshness):
  python3 scripts/wiki_ingest.py --source X.md --context system --dry-run

Approved mode requires both flags and refuses invalid or missing authority without
falling back to compatibility. See docs/references/guides/bounded-ingestion.md.

Returns exit 2 for secrets, context or budget blockers, or an incomplete retry
that would replace a complete capture. A rejected attempt writes no artifacts.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

CODE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_ROOT))
from scripts._common import ROOT

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
    parser.add_argument("--approved-revision", help="Retired v1 option; use the folder source-stage.")
    parser.add_argument("--policy-context", help="Retired v1 option; use the folder source-stage.")
    parser.add_argument("--folder", help="Local context folder relative to the wiki root; defaults to nested cwd.")
    parser.add_argument("--index", help="Selected context index relative to the wiki root; required for the root.")
    parser.add_argument("--repo", nargs=4, action="append", metavar=("ROOT", "IDENTITY", "REVISION", "PATH"),
                        help="Explicit independent Git file; repeat for each selection; no network access.")
    parser.add_argument("--context-max-bytes", type=int, default=DEFAULT_CONTEXT_MAX_BYTES)
    parser.add_argument("--request-max-bytes", type=int, default=DEFAULT_REQUEST_MAX_BYTES)
    business_root = parser.add_mutually_exclusive_group()
    business_root.add_argument("--root-entity-ref", help="Explicit authorized business-root page; this does not grant access.")
    business_root.add_argument("--omit-root-entity", action="store_true", help="Explicitly omit the business root with missing coverage; mandatory lineage rules still apply.")
    parser.add_argument("--stream", help="source recipe stream id (advances its cursor post-commit)")
    args = parser.parse_args()

    if args.approved_revision is not None or args.policy_context is not None:
        parser.error('new approved v1 ingestion is retired; use wiki_coordination.py --source-stage with a trusted host binding')

    root = args.root.resolve()
    from wiki_core.llm.context_pass import local_entry_selection
    try:
        entry_folder, entry_index = local_entry_selection(root, args.folder, args.index, cwd=Path.cwd(),
            approved_revision=args.approved_revision, policy_context=args.policy_context)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    if args.repo is not None and entry_folder is None:
        parser.error('repository selection requires a local folder')
    if entry_folder is not None and not args.source.strip():
        parser.error('folder entry requires an explicit source')
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
        entry_folder=entry_folder, entry_index=entry_index, repo_selections=args.repo,
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
