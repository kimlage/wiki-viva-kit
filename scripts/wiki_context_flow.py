#!/usr/bin/env python3
"""Folder preflight by default; legacy v1 flow requires explicit selection."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from wiki_core.context_selection import strict_json_loads
from wiki_core.safe_cli import SafeArgumentParser, report_failure

def _v1_main(argv):
    from wiki_core.context_policy import load_policy, PolicyError
    from wiki_core.context_impact import assess_impact, report_review, ImpactError
    from wiki_core.context_integration import preflight, IntegrationError
    from wiki_core.context_requirements import assess_approved_impact, requirements_from_result, revalidate_approved_queries, RequirementError
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo',default='.')
    p.add_argument('--approved-revision',required=True)
    p.add_argument('--manifest',default='context.yaml')
    sub=p.add_subparsers(dest='command',required=True)
    impact=sub.add_parser('impact'); source=impact.add_mutually_exclusive_group(required=True); source.add_argument('--graph'); source.add_argument('--consumer',action='append'); impact.add_argument('--before',required=True); impact.add_argument('--after',required=True); impact.add_argument('--context',required=True); impact.add_argument('--limit',type=int,default=100); impact.add_argument('--offset',type=int,default=0); impact.add_argument('--selection'); impact.add_argument('--trace',default='[]')
    requirements=sub.add_parser('requirements'); requirements.add_argument('--packet',required=True); requirements.add_argument('--result',required=True); requirements.add_argument('--output',required=True); requirements.add_argument('--proposal-head',required=True); requirements.add_argument('--temporal',required=True,choices=['current','historical']); requirements.add_argument('--max-age-days',type=int,required=True)
    revalidate=sub.add_parser('revalidate'); revalidate.add_argument('--consumer',required=True); revalidate.add_argument('--context',required=True)
    review=sub.add_parser('review'); review.add_argument('--candidate',required=True); review.add_argument('--disposition',required=True,choices=['updated','still_valid','superseded','blocked']); review.add_argument('--reason',required=True); review.add_argument('--evidence-revision',required=True)
    check=sub.add_parser('preflight'); check.add_argument('--context',required=True); check.add_argument('--base',required=True); check.add_argument('--head',required=True); check.add_argument('--branch',required=True); check.add_argument('--packet',required=True); check.add_argument('--result',required=True)
    args=p.parse_args(argv)
    try:
        policy=load_policy(args.repo,args.approved_revision,args.manifest)
        if args.command=='impact':
            options={'before':args.before,'after':args.after,'destination_context':args.context,'max_fanout':args.limit,'offset':args.offset,'expected_selection':args.selection,'trace':json.loads(args.trace)}
            out=(assess_impact(args.repo,policy,strict_json_loads(Path(args.graph).read_text(encoding='utf-8')),**options) if args.graph else assess_approved_impact(args.repo,policy,consumers=args.consumer,**options))
        elif args.command=='revalidate':
            out=revalidate_approved_queries(args.repo,policy,consumer=args.consumer,context_id=args.context)
        elif args.command=='requirements':
            out=requirements_from_result(args.repo,policy,packet=strict_json_loads(Path(args.packet).read_text(encoding='utf-8')),result=strict_json_loads(Path(args.result).read_text(encoding='utf-8')),output_path=args.output,proposal_head=args.proposal_head,temporal=args.temporal,max_age_days=args.max_age_days)
        elif args.command=='review':
            out=report_review(args.repo,policy,strict_json_loads(Path(args.candidate).read_text(encoding='utf-8')),disposition=args.disposition,reason=args.reason,evidence_revision=args.evidence_revision)
        else:
            out=preflight(args.repo,policy,context_id=args.context,base=args.base,head=args.head,branch=args.branch,packet=strict_json_loads(Path(args.packet).read_text(encoding='utf-8')),result=strict_json_loads(Path(args.result).read_text(encoding='utf-8')))
        print(json.dumps(out,ensure_ascii=False,sort_keys=True,indent=2))
    except (PolicyError,ImpactError,IntegrationError,RequirementError,ValueError,KeyError,OSError) as exc:
        print(str(exc),file=sys.stderr); return 1
    return 0


def _folder_main(argv):
    from wiki_core.folder_policy_v2 import load_folder_policy_v2
    from wiki_core.folder_integration_v2 import preflight_folder_v2

    parser = SafeArgumentParser(description='Check an exact folder proposal without approving it.',
                                epilog='Use --mode v1 explicitly for the legacy flow.')
    parser.add_argument('--repo', default='.')
    parser.add_argument('--approved-revision', required=True)
    sub = parser.add_subparsers(dest='command', required=True)
    check = sub.add_parser('preflight')
    check.add_argument('--folder', required=True); check.add_argument('--index', required=True)
    check.add_argument('--base', required=True); check.add_argument('--head', required=True)
    check.add_argument('--branch', required=True); check.add_argument('--packet', required=True); check.add_argument('--result', required=True)
    check.add_argument('--source-request', help='explicit contextual ingestion request for host-bound capture verification')
    check.add_argument('--requalify-source', action='store_true', help='explicitly requalify the selected source in an existing claim')
    args = parser.parse_args(argv)
    try:
        policy = load_folder_policy_v2(args.repo, args.approved_revision)
        def read_json(path):
            with Path(path).open('rb') as stream:
                raw = stream.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ValueError('request exceeds byte limit')
            return strict_json_loads(raw.decode('utf-8'))
        packet = read_json(args.packet)
        result = read_json(args.result)
        if not isinstance(packet, dict):
            raise ValueError('folder packet unavailable')
        if packet.get('schema_version') == 'wiki.folder-query-task-context/v2':
            base_packet = packet.get('base_packet')
        elif packet.get('schema_version') == 'wiki.folder-task-context/v2':
            base_packet = packet
        else:
            raise ValueError('v2 packet required; v1 packets need explicit migration')
        if (not isinstance(base_packet, dict) or base_packet.get('context_folder') != args.folder
                or base_packet.get('index_path') != args.index):
            raise ValueError('folder or index differs from packet')
        if packet.get('schema_version') == 'wiki.folder-query-task-context/v2':
            from wiki_core.folder_query_packet_v2 import preflight_folder_query_v2
            binding = None
            source_request = None
            if args.source_request:
                from wiki_core.folder_ingestion_v2 import selection_from_host_environment
                source_request = read_json(args.source_request)
                binding = selection_from_host_environment(args.folder, args.index, base_packet['output']).host
            output = preflight_folder_query_v2(args.repo, policy, base=args.base, head=args.head,
                                                branch=args.branch, packet=packet, result=result,
                                                binding=binding, source_request=source_request,
                                                requalify_source=args.requalify_source)
        elif args.source_request:
            from wiki_core.folder_coordination_v2 import prepare_folder_preflight
            from wiki_core.folder_ingestion_v2 import selection_from_host_environment
            source_request = read_json(args.source_request)
            selection = selection_from_host_environment(args.folder, args.index, base_packet['output'])
            output = prepare_folder_preflight(args.repo, selection.host, {'folder':args.folder,
                     'approved_revision':args.approved_revision, 'base':args.base, 'head':args.head,
                     'branch':args.branch, 'packet':packet, 'result':result,
                     'source_request':source_request, 'requalify_source':args.requalify_source})['preflight']
        else:
            output = preflight_folder_v2(args.repo, policy, base=args.base, head=args.head,
                                          branch=args.branch, packet=packet, result=result, requalify_source=args.requalify_source)
        policy.fresh()
    except (ValueError, KeyError, TypeError, OSError) as exc:
        report_failure(exc)
        return 1
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


def main(argv=None):
    parser = SafeArgumentParser(add_help=False)
    parser.add_argument('--mode', choices=('folder', 'v1'), default='folder')
    args, rest = parser.parse_known_args(sys.argv[1:] if argv is None else argv)
    return _v1_main(rest) if args.mode == 'v1' else _folder_main(rest)


if __name__=='__main__': raise SystemExit(main())
