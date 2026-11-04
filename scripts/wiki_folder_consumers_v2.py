#!/usr/bin/env python3
"""Inventory canonical requirements in explicitly authorized v2 owner paths."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wiki_core.folder_consumers_v2 import inventory_folder_consumers_v2
from wiki_core.folder_policy_v2 import load_folder_policy_v2
from wiki_core.safe_cli import SafeArgumentParser, report_failure


def main():
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument('--repo', default='.')
    parser.add_argument('--approved-revision', required=True)
    parser.add_argument('--folder', required=True)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--scope')
    selection.add_argument('--candidate', action='append')
    parser.add_argument('--max-files', type=int, default=256)
    parser.add_argument('--max-bytes', type=int, default=1000000)
    args = parser.parse_args()
    try:
        policy = load_folder_policy_v2(args.repo, args.approved_revision)
        result = inventory_folder_consumers_v2(args.repo, policy, folder=args.folder,
                    scope=args.scope, candidates=args.candidate, max_files=args.max_files, max_bytes=args.max_bytes)
    except (ValueError, OSError) as exc:
        report_failure(exc)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
