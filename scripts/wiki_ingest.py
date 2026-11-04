#!/usr/bin/env python3
"""End-to-end ingestion orchestrator for the living wiki.

Chains manifest -> text/chunks -> index -> pre-scan (secrets block; PII is
informative, welcome on a private page) -> input-stage-aware LLM context package
(emits the -request.json that the auditor gate watches) -> score-event. Replaces
the manual step-by-step run (each module had its own CLI). The LLM pass stays
delegated to the agent running the repo.

Approved-context example (replace placeholders with authorized values):
  python3 scripts/wiki_ingest.py --mode v1 --source SOURCE --context SOURCE_CONTEXT \\
    --approved-revision APPROVED_SHA --policy-context CONTEXT_ID

Folder mode (trusted local coordinator; host binding configured separately):
  python3 scripts/wiki_ingest.py --source SOURCE --context SOURCE_CONTEXT \\
    --approved-revision APPROVED_SHA --folder-context FOLDER \\
    --folder-index INDEX --folder-output OUTPUT --dry-run

Working-tree compatibility example (does not establish approved policy or source freshness):
  python3 scripts/wiki_ingest.py --mode working-tree --source X.md --context system --dry-run

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
from wiki_core.ingestion_cli_mode import validate_mode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--mode', choices=('folder', 'v1', 'working-tree'), default='folder',
                        help='Folder is the default; legacy authority or working-tree compatibility must be explicit.')
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--source", required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--dry-run", action="store_true", help="compute without writing artifacts")
    parser.add_argument("--no-score", action="store_true", help="do not record a score-event")
    parser.add_argument("--actor")
    parser.add_argument("--approved-revision", help="Current approved policy SHA supplied by the trusted local caller.")
    parser.add_argument("--policy-context", help="Explicit approved context ID; no fallback on refusal.")
    parser.add_argument("--folder-context", help="Opt-in exact folder for a trusted local coordinator; never a grant.")
    parser.add_argument("--folder-index", help="Explicit authorized folder index.")
    parser.add_argument("--folder-output", help="Concrete authorized proposal output path.")
    parser.add_argument("--folder-source-ref", help="Approved source page explicitly associated with staged RAW.")
    parser.add_argument("--folder-repo", nargs=4, action="append", metavar=("ROOT", "IDENTITY", "REVISION", "PATH"), help="Explicit host-authorized local Git selection; repeat for each path; no network access.")
    parser.add_argument("--folder-queries", help="Explicit JSON array of authorized folder queries to include in the request.")
    parser.add_argument("--context-max-bytes", type=int, default=DEFAULT_CONTEXT_MAX_BYTES)
    parser.add_argument("--request-max-bytes", type=int, default=DEFAULT_REQUEST_MAX_BYTES)
    business_root = parser.add_mutually_exclusive_group()
    business_root.add_argument("--root-entity-ref", help="Explicit authorized business-root page; this does not grant access.")
    business_root.add_argument("--omit-root-entity", action="store_true", help="Explicitly omit the business root with missing coverage; mandatory lineage rules still apply.")
    parser.add_argument("--stream", help="source recipe stream id (advances its cursor post-commit)")
    args = parser.parse_args()
    validate_mode(parser, args)

    root = args.root.resolve()
    selection = None
    folder_queries = None
    if args.mode == 'folder':
        from wiki_core.folder_ingestion_v2 import selection_from_host_environment, load_folder_queries
        try:
            selection = selection_from_host_environment(args.folder_context, args.folder_index, args.folder_output, args.folder_source_ref,
                independent_repo=tuple(args.folder_repo[0]) if args.folder_repo else None,
                additional_repos=tuple(tuple(row) for row in args.folder_repo[1:]) if args.folder_repo else ())
            if args.folder_queries is not None:
                folder_queries = load_folder_queries(args.folder_queries)
        except (ValueError, OSError):
            parser.error("invalid folder selection")
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
        folder_selection=selection,
        folder_queries=folder_queries,
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
