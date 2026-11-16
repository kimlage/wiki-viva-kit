#!/usr/bin/env python3
"""Observe integration readiness and branch/worktree hygiene without writes."""
import argparse
import json
from pathlib import Path

from _common import ROOT
from wiki_core.integration_check import inspect, load_owner_activity


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--pr', type=int)
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--owner-activity', type=Path,
                        help='host-exported JSON {owner reference: "active"|"ended"} for worktree owners')
    args = parser.parse_args()
    if args.pr is not None and args.pr < 1:
        parser.error('--pr must be positive')
    activity = None
    if args.owner_activity is not None:
        try:
            activity = load_owner_activity(args.owner_activity)
        except ValueError as exc:
            parser.error(f'--owner-activity: {exc}')
    result = (inspect(args.root, args.pr) if activity is None
              else inspect(args.root, args.pr, owner_activity=activity))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif not result['ok']:
        print(result['status'])
    else:
        for item in result['proposals']:
            print(f"PR {item['number']}: {item['status']}" + (f" ({item['responsible_thread']})" if item.get('responsible_thread') else ''))
            if item.get('ci_failed_checks'):
                print('  failed checks: ' + ', '.join(item['ci_failed_checks']))
            if item.get('action_reconciliation'):
                print('  action reconciliation: ' + json.dumps(item['action_reconciliation'], ensure_ascii=False))
                if (isinstance(item['action_reconciliation'], list) and any(
                    isinstance(entry, dict) and entry.get('event') == 'new_proposal_missing_action_association'
                    for entry in item['action_reconciliation']
                )):
                    print('  WARNING: no action association observed on the default branch; verify the PR head and reconcile before closure.')
            if item.get('pending'):
                print('  pending: ' + ', '.join(item['pending']))
            if item.get('required_at_integration'):
                print('  required at integration: ' + ', '.join(item['required_at_integration']))
        for item in result['hygiene']:
            print(f"{item['status']}: {item.get('action_id') or item.get('branch') or item.get('path')}"
                  + (f" PR {item['pr']}" if item.get('pr') else '')
                  + (f" at {item['path']}" if item.get('branch') and 'worktree' in str(item['status']) else '')
                  + (f" owner {item['owner']}" if item.get('owner') else '')
                  + (f" ({item['owner_activity']})" if item.get('owner_activity') else ''))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
