#!/usr/bin/env python3
"""Observe integration readiness and branch/worktree hygiene without writes."""
import argparse
import json
from pathlib import Path

from _common import ROOT
from wiki_core.integration_check import inspect


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--pr', type=int)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    if args.pr is not None and args.pr < 1:
        parser.error('--pr must be positive')
    result = inspect(args.root, args.pr)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif not result['ok']:
        print(result['status'])
    else:
        for item in result['proposals']:
            print(f"PR {item['number']}: {item['status']}" + (f" ({item['responsible_thread']})" if item.get('responsible_thread') else ''))
            if item.get('action_reconciliation'):
                print('  action reconciliation: ' + json.dumps(item['action_reconciliation'], ensure_ascii=False))
            if item.get('pending'):
                print('  pending: ' + ', '.join(item['pending']))
            if item.get('required_at_integration'):
                print('  required at integration: ' + ', '.join(item['required_at_integration']))
        for item in result['hygiene']:
            print(f"{item['status']}: {item.get('action_id') or item.get('branch') or item.get('path')}" + (f" PR {item['pr']}" if item.get('pr') else ''))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
