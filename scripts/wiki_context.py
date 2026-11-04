#!/usr/bin/env python3
"""Enter a folder context or explicitly select legacy v1 coordination."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wiki_core.context_selection import strict_json_loads
from wiki_core.safe_cli import SafeArgumentParser, report_failure


def _mode_and_args(argv):
    parser = SafeArgumentParser(add_help=False)
    parser.add_argument('--mode', choices=('folder', 'v1'), default='folder')
    return parser.parse_known_args(argv)


def _read_json(path):
    with Path(path).open('rb') as stream:
        raw = stream.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError('request exceeds byte limit')
    return strict_json_loads(raw.decode('utf-8'))


def _folder_main(argv):
    from wiki_core.folder_policy_v2 import load_folder_policy_v2
    from wiki_core.folder_packet_v2 import build_folder_packet_v2
    from wiki_core.folder_declarations_v2 import preauthorize_index, authorized_instruction_chain, authorized_index
    from wiki_core.folder_context import inspect_folder
    from wiki_core.folder_coordination_v2 import _output_authorized
    from wiki_core.context_policy import ContextPolicy, safe_path
    from wiki_core.repository_reader import RepositoryReader

    parser = SafeArgumentParser(description='Enter a folder context without granting access.',
                                epilog='Use --mode v1 explicitly for the legacy flow.')
    parser.add_argument('--repo', default='.')
    parser.add_argument('--approved-revision', required=True)
    sub = parser.add_subparsers(dest='command', required=True)
    resolve = sub.add_parser('resolve'); resolve.add_argument('folder'); resolve.add_argument('--index', required=True)
    resolve.add_argument('--max-instruction-bytes', type=int, default=32768)
    pack = sub.add_parser('pack'); pack.add_argument('folder'); pack.add_argument('--index', required=True)
    pack.add_argument('--index-section'); pack.add_argument('--start-folder')
    pack.add_argument('--content-revision', required=True); pack.add_argument('--request', required=True)
    attach = sub.add_parser('attach-queries', help='attach queries to an existing ingestion packet')
    attach.add_argument('folder'); attach.add_argument('--index', required=True)
    attach.add_argument('--source-request', required=True); attach.add_argument('--queries', required=True)
    search = sub.add_parser('search', help='bounded literal search in an authorized folder or explicit source')
    search.add_argument('folder'); search.add_argument('--index', required=True); search.add_argument('--literal', required=True)
    selected = search.add_mutually_exclusive_group(required=True)
    selected.add_argument('--scope'); selected.add_argument('--raw-capture')
    selected.add_argument('--source-repository', nargs=4, metavar=('ROOT', 'IDENTITY', 'REVISION', 'PATH'))
    search.add_argument('--source-ref', help='approved source page naming the selected independent repository')
    search.add_argument('--max-files', type=int, default=256); search.add_argument('--max-bytes', type=int, default=1000000)
    search.add_argument('--max-hits', type=int, default=100)
    args = parser.parse_args(argv)
    try:
        if args.command == 'search':
            from wiki_core.folder_ingestion_v2 import host_binding_from_environment
            from wiki_core.folder_coordination_v2 import _bound_policy
            from wiki_core.folder_search_v2 import search_folder
            host = host_binding_from_environment()
            _bound_policy(args.repo, host, args.folder, args.approved_revision)
            if bool(args.source_repository) != bool(args.source_ref):
                raise ValueError('repository source reference required only with a repository selection')
            repository = ({'source_ref':args.source_ref, 'root':args.source_repository[0],
                           'identity':args.source_repository[1], 'revision':args.source_repository[2],
                           'path':args.source_repository[3]} if args.source_repository else None)
            capture = _read_json(args.raw_capture) if args.raw_capture else None
            output = search_folder(args.repo, host, approved_revision=args.approved_revision, folder=args.folder,
                index_path=args.index, query=args.literal, scope=args.scope, raw_capture=capture,
                repository=repository, max_files=args.max_files, max_bytes=args.max_bytes, max_hits=args.max_hits)
            print(json.dumps(output, ensure_ascii=False, sort_keys=True))
            return 0
        policy = load_folder_policy_v2(args.repo, args.approved_revision)
        if args.command == 'resolve':
            preauthorize_index(policy, args.folder, args.index)
            reader = RepositoryReader(args.repo, policy.policy_revision)
            chain = authorized_instruction_chain(policy, reader, args.folder, max_bytes=args.max_instruction_bytes)
            authorized_index(policy, args.folder, args.index, chain)
            output = inspect_folder(args.repo, policy.policy_revision, args.folder,
                                    index_path=args.index, max_instruction_bytes=args.max_instruction_bytes)
            output['policy_revision'] = policy.policy_revision
            output['enforcement_claim'] = 'none'
        elif args.command == 'attach-queries':
            source_request = _read_json(args.source_request)
            queries = _read_json(args.queries)
            base_packet = source_request.get('block_context_package') if isinstance(source_request, dict) else None
            if (not isinstance(base_packet, dict) or base_packet.get('context_folder') != args.folder
                    or base_packet.get('index_path') != args.index
                    or base_packet.get('ingestion_binding') is None):
                raise ValueError('matching ingestion packet required')
            _output_authorized(policy, args.folder, base_packet['output'])
            from wiki_core.folder_query_packet_v2 import build_folder_query_packet_v2
            output = build_folder_query_packet_v2(args.repo, policy, base_packet=base_packet, queries=queries)
        else:
            request = _read_json(args.request)
            required = {'max_bytes', 'task_id', 'goal', 'output', 'integrator'}
            if not isinstance(request, dict) or not required <= set(request) or set(request) - (required | {'evidence', 'queries'}):
                raise ValueError('invalid folder task request')
            if args.start_folder is None:
                _output_authorized(policy, args.folder, request['output'])
            else:
                # The builder qualifies the auxiliary lineage next. Check the
                # ancestor context's owner and limits before opening it.
                target = safe_path(request['output']); context = policy.folder_ids[args.folder]
                if (ContextPolicy.owner_of(policy, target) != context or not policy.permits(context, 'read', target)
                        or not policy.permits(context, 'write', target)):
                    raise ValueError('output unavailable')
            output = build_folder_packet_v2(args.repo, policy, args.folder, request['max_bytes'],
                        content_revision=args.content_revision, index_path=args.index,
                        index_section=args.index_section, start_folder=args.start_folder,
                        task_id=request['task_id'], goal=request['goal'], output=request['output'],
                        integrator=request['integrator'], evidence=request.get('evidence', []))
            queries = request.get('queries', [])
            if not isinstance(queries, list):
                raise ValueError('invalid folder query selection')
            if queries:
                from wiki_core.folder_query_packet_v2 import build_folder_query_packet_v2
                output = build_folder_query_packet_v2(args.repo, policy, base_packet=output, queries=queries)
        policy.fresh()
    except (ValueError, KeyError, TypeError, OSError) as exc:
        if args.command == 'search':
            from wiki_core.folder_search_v2 import FolderSearchError
            if isinstance(exc, FolderSearchError):
                print(json.dumps({'status':'blocked', 'reason':exc.code}), file=sys.stderr)
                return 1
        report_failure(exc)
        return 1
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


def _v1_main(argv):
    from wiki_core.context_policy import load_policy, PolicyError
    from wiki_core.context_packet import build_packet

    parser = argparse.ArgumentParser(description='Explicit legacy v1 context and packet.')
    parser.add_argument('--repo', default='.')
    parser.add_argument('--approved-revision', required=True)
    parser.add_argument('--manifest', default='context.yaml')
    sub = parser.add_subparsers(dest='command', required=True)
    resolve = sub.add_parser('resolve'); resolve.add_argument('context')
    pack = sub.add_parser('pack'); pack.add_argument('context'); pack.add_argument('--content-revision', required=True); pack.add_argument('--request', required=True)
    args = parser.parse_args(argv)
    try:
        policy = load_policy(args.repo, args.approved_revision, args.manifest)
        if args.command == 'resolve':
            output = {'policy_revision': policy.policy_revision, 'context': args.context, 'effective': policy.effective[args.context], 'lineage': [c['id'] for c in policy.lineage(args.context)], 'enforcement_claim': 'none'}
        else:
            request = strict_json_loads(Path(args.request).read_text(encoding='utf-8'))
            output = build_packet(args.repo, policy, args.context, args.content_revision, request['evidence'], request['max_bytes'], query_fingerprint=request.get('query_fingerprint'), omissions=request.get('omissions', []), task_id=request['task_id'], goal=request['goal'], output=request['output'], integrator=request['integrator'], queries=request.get('queries', []))
        if args.command == 'pack':
            sys.stdout.write(json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
        else:
            print(json.dumps(output, ensure_ascii=False, indent=2))
    except (PolicyError, KeyError, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr); return 1
    return 0


def main(argv=None):
    args, rest = _mode_and_args(sys.argv[1:] if argv is None else argv)
    return _v1_main(rest) if args.mode == 'v1' else _folder_main(rest)


if __name__ == '__main__': raise SystemExit(main())
