#!/usr/bin/env python3
"""Compose a narrow v2 instruction/index packet; no execution or ACL claim."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wiki_core.safe_cli import SafeArgumentParser, report_failure
from wiki_core.context_policy import PolicyError
from wiki_core.folder_policy_v2 import load_folder_policy_v2
from wiki_core.folder_packet_v2 import build_folder_packet_v2
from wiki_core.context_selection import strict_json_loads


def main():
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument('--repo', default='.')
    parser.add_argument('--approved-revision', required=True)
    parser.add_argument('--content-revision', required=True)
    parser.add_argument('--index', required=True, help='explicit authorized context index path')
    parser.add_argument('--index-section', help='optional authorized index section')
    parser.add_argument('--start-folder', help='optional qualified auxiliary starting folder within the selected context')
    parser.add_argument('--max-bytes', type=int, required=True)
    parser.add_argument('--task-id', required=True)
    parser.add_argument('--goal', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--integrator', required=True)
    parser.add_argument('--evidence', help='JSON array of exact source selectors')
    parser.add_argument('--queries', help='JSON array of bounded v2 queries at the approved revision')
    parser.add_argument('folder')
    args = parser.parse_args()
    try:
        policy = load_folder_policy_v2(args.repo, args.approved_revision)
        evidence = strict_json_loads(Path(args.evidence).read_text(encoding='utf-8')) if args.evidence else []
        packet = build_folder_packet_v2(args.repo, policy, args.folder, args.max_bytes,
                                        content_revision=args.content_revision,
                                        index_path=args.index, index_section=args.index_section,
                                        start_folder=args.start_folder,
                                        task_id=args.task_id, goal=args.goal, output=args.output, integrator=args.integrator,
                                        evidence=evidence)
        if args.queries:
            from wiki_core.folder_query_packet_v2 import build_folder_query_packet_v2
            queries = strict_json_loads(Path(args.queries).read_text(encoding='utf-8'))
            packet = build_folder_query_packet_v2(args.repo, policy, base_packet=packet, queries=queries)
    except (ValueError, OSError) as exc:
        report_failure(exc)
        return 1
    print(json.dumps(packet, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
