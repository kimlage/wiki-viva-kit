#!/usr/bin/env python3
"""Preview a mechanical v1→folder-v2 control proposal without disclosure.

Reads all v1 manifests and candidate instructions; an actually authorized
global coordinator is required. Aggregate output is not process isolation.
No write by default. An explicitly requested file is unapproved and inactive.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wiki_core.folder_migration_v2 import FolderMigrationError, FolderMigrationUncertain, prepare_folder_controls, write_folder_controls


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.exit(2, json.dumps({'status': 'error', 'reason': 'invalid_arguments'}) + '\n')


def main() -> int:
    parser = _Parser(description=__doc__)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--approved-revision', required=True, help='exact approved v1 SHA at origin/main')
    parser.add_argument('--candidate-revision', required=True, help='exact descendant SHA with candidate AGENTS')
    parser.add_argument('--write-proposal', action='store_true', help='create unapproved controls only if comparison succeeds')
    args = parser.parse_args()
    try:
        report, proposal = prepare_folder_controls(Path(args.repo), args.approved_revision, args.candidate_revision)
        if args.write_proposal and report['status'] == 'ready_for_review':
            report = write_folder_controls(Path(args.repo), args.approved_revision, args.candidate_revision)
            report['written'] = True
        print(json.dumps(report, sort_keys=True))
        return 0 if report['status'] == 'ready_for_review' else 2
    except (FolderMigrationError, OSError, ValueError) as exc:
        reason = str(exc) if isinstance(exc, FolderMigrationError) else 'migration_unavailable'
        result = {'status': 'uncertain' if isinstance(exc, FolderMigrationUncertain) else 'error', 'reason': reason}
        if isinstance(exc, FolderMigrationUncertain):
            result['written'] = True
        print(json.dumps(result, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
