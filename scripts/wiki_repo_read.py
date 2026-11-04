#!/usr/bin/env python3
"""Read one explicit independent Git repository at a specific revision.

Verifies the Git root and configured origin identity locally; no network access,
remote authentication, permission grant, or writing to the wiki is performed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wiki_core.repo_read import RepoReadError, read_independent_repo


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # Argument values can themselves contain credentials.
        self.exit(2, json.dumps({'status': 'error', 'reason': 'invalid_arguments'}) + '\n')


def main() -> int:
    parser = _Parser(description=__doc__)
    parser.add_argument('--repo', required=True, help='explicit Git working-tree root')
    parser.add_argument('--identity', required=True, help='expected origin identity: host/path without .git')
    parser.add_argument('--revision', required=True, help='local commit or reference to resolve')
    parser.add_argument('--path', required=True, help='exact tracked regular-file path')
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--section')
    selection.add_argument('--field')
    args = parser.parse_args()
    try:
        result = read_independent_repo(Path(args.repo), args.identity, args.revision, args.path,
                                       section=args.section, field=args.field)
    except (RepoReadError, OSError, ValueError):
        # Never echo remote, inputs, subprocess output or selected content on failure.
        exc = sys.exc_info()[1]
        code = str(exc) if isinstance(exc, RepoReadError) else 'repository_read_failed'
        print(json.dumps({'status': 'error', 'reason': code}), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
