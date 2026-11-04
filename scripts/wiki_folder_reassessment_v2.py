#!/usr/bin/env python3
"""Join selected v2 consumer declarations with explicit consumption reports."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wiki_core.context_selection import strict_json_loads
from wiki_core.folder_policy_v2 import load_folder_policy_v2
from wiki_core.folder_reassessment_v2 import reassess_folder_source_v2
from wiki_core.safe_cli import SafeArgumentParser, report_failure


def main():
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument('--repo', default='.')
    parser.add_argument('--approved-revision', required=True)
    parser.add_argument('--folder', required=True)
    parser.add_argument('--source', required=True)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--scope')
    selection.add_argument('--candidate', action='append')
    parser.add_argument('--reports', help='JSON array of explicit packet/result reports')
    parser.add_argument('--max-files', type=int, default=256)
    parser.add_argument('--max-bytes', type=int, default=1000000)
    parser.add_argument('--independent-root', help='explicit local Git root; requires other independent options')
    parser.add_argument('--independent-identity', help='expected credential-free configured origin identity')
    parser.add_argument('--independent-revision', help='selected current immutable commit SHA')
    parser.add_argument('--independent-path', help='exact repository-relative source path')
    args = parser.parse_args()
    try:
        reports = []
        if args.reports:
            with Path(args.reports).open('rb') as stream:
                raw = stream.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ValueError('reports input exceeds byte limit')
            reports = strict_json_loads(raw.decode('utf-8'))
        policy = load_folder_policy_v2(args.repo, args.approved_revision)
        independent = (args.independent_root, args.independent_identity, args.independent_revision, args.independent_path)
        if any(independent) and not all(independent):
            raise ValueError('complete independent repository selection required')
        selected = dict(zip(('root', 'identity', 'revision', 'path'), independent)) if all(independent) else None
        output = reassess_folder_source_v2(args.repo, policy, folder=args.folder, source=args.source,
                    scope=args.scope, candidates=args.candidate, reports=reports,
                    max_files=args.max_files, max_bytes=args.max_bytes, independent_repo=selected)
    except (ValueError, OSError) as exc:
        report_failure(exc)
        return 1
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
