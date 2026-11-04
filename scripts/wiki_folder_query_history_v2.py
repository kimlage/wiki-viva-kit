#!/usr/bin/env python3
"""Experimental explicit query replay; reports a candidate for review only."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wiki_core.context_selection import strict_json_loads
from wiki_core.folder_policy_v2 import load_folder_policy_v2
from wiki_core.folder_query_history_v2 import assess_folder_query_history_v2
from wiki_core.safe_cli import SafeArgumentParser, report_failure


def main():
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument('--repo', default='.')
    parser.add_argument('--approved-revision', required=True)
    parser.add_argument('--integrated-revision', required=True)
    parser.add_argument('--packet', required=True)
    parser.add_argument('--result', required=True)
    parser.add_argument('--query-id', help='explicit query identity when the envelope contains multiple queries')
    args = parser.parse_args()
    try:
        policy = load_folder_policy_v2(args.repo, args.approved_revision)
        packet = strict_json_loads(Path(args.packet).read_text(encoding='utf-8'))
        result = strict_json_loads(Path(args.result).read_text(encoding='utf-8'))
        outcome = assess_folder_query_history_v2(args.repo, policy, packet=packet, result=result,
                                                 integrated_revision=args.integrated_revision, query_id=args.query_id)
    except (ValueError, OSError) as exc:
        report_failure(exc)
        return 1
    print(json.dumps(outcome, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
