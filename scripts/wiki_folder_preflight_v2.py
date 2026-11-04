#!/usr/bin/env python3
"""Review an exact v2 proposal without approving, publishing or merging it."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wiki_core.safe_cli import SafeArgumentParser, report_failure
from wiki_core.context_selection import strict_json_loads
from wiki_core.folder_integration_v2 import preflight_folder_v2
from wiki_core.folder_policy_v2 import load_folder_policy_v2


def read_json(path):
    with Path(path).open('rb') as stream:
        raw = stream.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError('request exceeds byte limit')
    return strict_json_loads(raw.decode('utf-8'))


def main():
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument('--repo', default='.')
    parser.add_argument('--approved-revision', required=True)
    parser.add_argument('--base', required=True)
    parser.add_argument('--head', required=True)
    parser.add_argument('--branch', required=True)
    parser.add_argument('--packet', required=True)
    parser.add_argument('--result', required=True)
    parser.add_argument('--query-requalifications', help='explicit prior query reports for reviewable replacement')
    args = parser.parse_args()
    try:
        policy = load_folder_policy_v2(args.repo, args.approved_revision)
        packet = read_json(args.packet)
        result = read_json(args.result)
        if isinstance(packet, dict) and packet.get('schema_version') == 'wiki.folder-query-task-context/v2':
            from wiki_core.folder_query_packet_v2 import preflight_folder_query_v2
            requalifications = None
            if args.query_requalifications:
                requalifications = read_json(args.query_requalifications)
            outcome = preflight_folder_query_v2(args.repo, policy, base=args.base, head=args.head,
                                                branch=args.branch, packet=packet, result=result,
                                                query_requalifications=requalifications)
        else:
            if args.query_requalifications:
                raise ValueError('query requalification requires a query packet')
            outcome = preflight_folder_v2(args.repo, policy, base=args.base, head=args.head,
                                          branch=args.branch, packet=packet, result=result)
    except (ValueError, OSError) as exc:
        report_failure(exc)
        return 1
    print(json.dumps(outcome, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
