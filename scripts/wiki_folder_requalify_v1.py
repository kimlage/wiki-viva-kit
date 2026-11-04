#!/usr/bin/env python3
"""Propose a read-only requalification of one explicit historical v1 requirement."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wiki_core.context_selection import strict_json_loads
from wiki_core.folder_policy_v2 import load_folder_policy_v2
from wiki_core.folder_requalification_v2 import requalify_explicit_v1_requirement
from wiki_core.safe_cli import SafeArgumentParser, report_failure


def main():
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument('--repo', default='.')
    parser.add_argument('--approved-revision', required=True)
    parser.add_argument('--folder', required=True)
    parser.add_argument('--index', required=True)
    parser.add_argument('--consumer', required=True)
    parser.add_argument('--requirement-index', required=True, type=int)
    parser.add_argument('--packet', required=True)
    parser.add_argument('--result', required=True)
    parser.add_argument('--proposal-head', required=True)
    args = parser.parse_args()
    try:
        policy = load_folder_policy_v2(args.repo, args.approved_revision)
        packet = strict_json_loads(Path(args.packet).read_text(encoding='utf-8'))
        result = strict_json_loads(Path(args.result).read_text(encoding='utf-8'))
        outcome = requalify_explicit_v1_requirement(args.repo, policy, folder=args.folder, index_path=args.index,
                         consumer=args.consumer, requirement_index=args.requirement_index, packet=packet,
                         result=result, proposal_head=args.proposal_head)
    except (ValueError, OSError) as exc:
        report_failure(exc)
        return 1
    print(json.dumps(outcome, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
