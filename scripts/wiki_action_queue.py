#!/usr/bin/env python3
"""Render or validate the action queue directly from canonical action pages."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from wiki_core.action_queue import read_queue  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--base', default='origin/main')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    try:
        base = None
        if args.check:
            result = subprocess.run(['git', 'merge-base', 'HEAD', args.base], cwd=ROOT,
                                    capture_output=True, text=True, check=False)
            if result.returncode or not result.stdout.strip():
                raise ValueError('merge base unavailable')
            base = result.stdout.strip()
        rows, errors = read_queue(ROOT, base=base)
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        print(f'ERROR: queue source unavailable ({type(exc).__name__})', file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f'ERROR: {error}', file=sys.stderr)
        return 1
    if args.check:
        print(f'action queue valid: {len(rows)} active action(s)')
    elif args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for row in rows:
            print(f"{row['state']}\t{row['page_id']}\t{row['path']}\t{row['next_action']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
