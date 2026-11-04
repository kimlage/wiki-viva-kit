#!/usr/bin/env python3
"""Join selected v2 consumer declarations with explicit consumption reports."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wiki_core.context_selection import strict_json_loads
from wiki_core.safe_cli import SafeArgumentParser, report_failure


def read_json(path):
    with Path(path).open('rb') as stream:
        raw = stream.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError('input exceeds byte limit')
    return strict_json_loads(raw.decode('utf-8'))


def main():
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument('--repo', default='.')
    parser.add_argument('--approved-revision', required=True)
    parser.add_argument('--folder', required=True)
    parser.add_argument('--source')
    parser.add_argument('--query-changed', action='append', help='changed wiki path for bounded query-consumer reassessment')
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--scope')
    selection.add_argument('--candidate', action='append')
    parser.add_argument('--reports', help='JSON array of explicit packet/result reports')
    parser.add_argument('--source-request', help='recorded contextual ingestion request when required by the selected source')
    parser.add_argument('--max-files', type=int, default=256)
    parser.add_argument('--max-bytes', type=int, default=1000000)
    parser.add_argument('--independent-root', help='explicit local Git root; requires other independent options')
    parser.add_argument('--independent-identity', help='expected credential-free configured origin identity')
    parser.add_argument('--independent-revision', help='explicitly selected immutable commit SHA')
    parser.add_argument('--independent-path', help='exact repository-relative source path')
    args = parser.parse_args()
    try:
        from wiki_core.folder_ingestion_v2 import host_binding_from_environment
        binding = host_binding_from_environment()
        reports = read_json(args.reports) if args.reports else []
        independent = (args.independent_root, args.independent_identity, args.independent_revision, args.independent_path)
        if any(independent) and not all(independent):
            raise ValueError('complete independent repository selection required')
        selected = dict(zip(('root', 'identity', 'revision', 'path'), independent)) if all(independent) else None
        if args.query_changed:
            if args.source or selected is not None or args.source_request:
                raise ValueError('select either query changes or an exact source')
            from wiki_core.folder_query_consumers_v2 import reassess_query_consumers
            output = reassess_query_consumers(args.repo, binding, folder=args.folder,
                        approved_revision=args.approved_revision, changed_paths=args.query_changed,
                        scope=args.scope, candidates=args.candidate, reports=reports,
                        max_files=args.max_files, max_bytes=args.max_bytes)
        else:
            if not args.source:
                raise ValueError('source or query change required')
            from wiki_core.folder_reassessment_host_v2 import prepare_folder_reassessment
            request = {'folder': args.folder, 'approved_revision': args.approved_revision,
                       'source': args.source, 'reports': reports,
                       'max_files': args.max_files, 'max_bytes': args.max_bytes}
            if args.scope is not None:
                request['scope'] = args.scope
            else:
                request['candidates'] = args.candidate
            if selected is not None:
                request['independent_repo'] = selected
            if args.source_request:
                request['source_request'] = read_json(args.source_request)
            output = prepare_folder_reassessment(args.repo, binding, request)['reassessment']
    except (ValueError, OSError) as exc:
        report_failure(exc)
        return 1
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
