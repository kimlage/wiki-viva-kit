#!/usr/bin/env python3
"""Finite, read-only context impact and proposal preflight."""
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from wiki_core.context_selection import strict_json_loads
from wiki_core.context_policy import load_policy, PolicyError
from wiki_core.context_impact import assess_impact, report_review, ImpactError
from wiki_core.context_integration import preflight, preflight_composite, IntegrationError
from wiki_core.context_requirements import assess_approved_impact, requirements_from_result, revalidate_approved_queries, route_impact_to_action, RequirementError
from wiki_core.git_env import local_git_environment, local_git_executable
from wiki_core.cli_errors import SafeArgumentParser, report_context_error


def _composite_participants(path):
    """Read a bounded, operator-selected JSON document without logging it."""
    try:
        flags = os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0)
        with os.fdopen(os.open(path, flags), 'rb') as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise ValueError('input is not a regular file')
            data = handle.read(8_000_001)
        if len(data) > 8_000_000:
            raise ValueError('input too large')
        return strict_json_loads(data.decode('utf-8'))
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise PolicyError('composite participant input unavailable') from exc

def main():
    p=SafeArgumentParser(prog="wiki_context_flow.py", description=__doc__)
    p.add_argument('--repo',help='wiki Git root; defaults to the current Git root')
    p.add_argument('--approved-revision',required=True)
    p.add_argument('--manifest',choices=['wiki.config.yaml'],default='wiki.config.yaml')
    sub=p.add_subparsers(dest='command',required=True)
    impact=sub.add_parser('impact'); source=impact.add_mutually_exclusive_group(); source.add_argument('--graph'); source.add_argument('--consumer',action='append'); impact.add_argument('--before',required=True); impact.add_argument('--after',required=True); impact.add_argument('--context',required=True); impact.add_argument('--limit',type=int,default=100); impact.add_argument('--offset',type=int,default=0); impact.add_argument('--selection'); impact.add_argument('--trace',default='[]')
    for option in ('event-id', 'action-id', 'action-path', 'profile', 'expected-sha256'):
        impact.add_argument('--' + option)
    requirements=sub.add_parser('requirements'); requirements.add_argument('--packet',required=True); requirements.add_argument('--result',required=True); requirements.add_argument('--output',required=True); requirements.add_argument('--proposal-head',required=True); requirements.add_argument('--temporal',required=True,choices=['current','historical']); requirements.add_argument('--max-age-days',type=int,required=True)
    requirements.add_argument('--context', help='explicit executor context, required when selecting additional trusted contexts')
    revalidate=sub.add_parser('revalidate'); revalidate.add_argument('--consumer',required=True); revalidate.add_argument('--context',required=True)
    review=sub.add_parser('review'); review.add_argument('--candidate',required=True); review.add_argument('--disposition',required=True,choices=['updated','still_valid','superseded','blocked']); review.add_argument('--reason',required=True); review.add_argument('--evidence-revision',required=True)
    check=sub.add_parser('preflight'); check.add_argument('--context',required=True); check.add_argument('--base',required=True); check.add_argument('--head',required=True); check.add_argument('--branch',required=True); check.add_argument('--packet',required=True); check.add_argument('--result',required=True)
    check.add_argument('--owned-range', action='store_true', help='enable the host-bound self-owned v2 range contract')
    composite=sub.add_parser('preflight-composite', help='host-bound multi-owner proposal check (read-only)')
    composite.add_argument('--base',required=True); composite.add_argument('--head',required=True); composite.add_argument('--branch',required=True)
    composite.add_argument('--participants',required=True, help='operator-selected JSON array, maximum 8 MB')
    for command in (requirements, check):
        command.add_argument('--additional-reader', action='append', default=[], metavar='CONTEXT',
            help='repeat the trusted local operator selection; packet contents do not grant access')
        command.add_argument('--trusted-context', action='append', default=[], metavar='CONTEXT',
            help='additional producer context selected explicitly by the trusted local operator')
    args=p.parse_args()
    try:
        if args.repo is None:
            found=subprocess.run([local_git_executable(),'--no-lazy-fetch','-C',str(Path.cwd()),'rev-parse','--show-toplevel'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=local_git_environment())
            if found.returncode: raise PolicyError('current Git root unavailable')
            args.repo=found.stdout.decode('utf-8').strip()
            if not args.repo: raise PolicyError('current Git root unavailable')
        binding=None
        if args.command == 'preflight' and args.owned_range:
            from wiki_core.coordination_context import CoordinationBinding, _policy
            if args.trusted_context or args.additional_reader: raise PolicyError('owned range does not support extra trusted contexts')
            binding = CoordinationBinding.from_environment()
            if binding is None or binding.manifest != 'wiki.config.yaml': raise PolicyError('folder coordination host binding required')
            policy = _policy(args.repo, binding, args.context, args.approved_revision)
        elif args.command == 'impact':
            from wiki_core.coordination_context import CoordinationBinding, _policy
            binding = CoordinationBinding.from_environment()
            if binding is None:
                raise PolicyError('coordination host binding required')
            policy = _policy(args.repo, binding, args.context, args.approved_revision)
        elif args.command in ('review', 'preflight-composite'):
            from wiki_core.coordination_context import CoordinationBinding
            binding = CoordinationBinding.from_environment()
            if binding is None:
                raise PolicyError('coordination host binding required')
            if args.command == 'preflight-composite' and binding.manifest != 'wiki.config.yaml':
                raise PolicyError('folder coordination host binding required')
            policy = load_policy(args.repo, args.approved_revision, binding.manifest, trusted_ref=binding.trusted_ref)
        else:
            policy=load_policy(args.repo,args.approved_revision,args.manifest)
        if args.command in ('requirements','preflight') and args.trusted_context:
            if not args.context: raise PolicyError('explicit executor context required for trusted selection')
            from wiki_core.coordination_context import CoordinationBinding
            binding=CoordinationBinding(tuple(dict.fromkeys([args.context, *args.trusted_context, *args.additional_reader])),policy._binding[1],args.manifest)
        if args.command=='impact':
            options={'before':args.before,'after':args.after,'destination_context':args.context,'max_fanout':args.limit,'offset':args.offset,'expected_selection':args.selection,'trace':json.loads(args.trace),'trusted_binding':binding}
            if not args.graph and args.consumer is None:
                try:
                    options['scope'] = Path.cwd().absolute().relative_to(Path(args.repo).resolve()).as_posix()
                except ValueError as exc:
                    raise PolicyError('current folder is outside the selected wiki') from exc
            out=(assess_impact(args.repo,policy,strict_json_loads(Path(args.graph).read_text(encoding='utf-8')),**options) if args.graph else assess_approved_impact(args.repo,policy,consumers=args.consumer,**options))
            route = (args.event_id, args.action_id, args.action_path, args.profile, args.expected_sha256)
            if any(route):
                if not all(route) or args.graph or args.consumer is not None:
                    raise RequirementError('complete authorized action route required')
                out['action'] = route_impact_to_action(args.repo, binding, destination_context=args.context,
                    before=args.before, after=args.after, scope=options['scope'], event_id=args.event_id,
                    action_id=args.action_id, action_path=args.action_path, profile=args.profile,
                    expected_sha256=args.expected_sha256, trace=options['trace'])
        elif args.command=='revalidate':
            out=revalidate_approved_queries(args.repo,policy,consumer=args.consumer,context_id=args.context)
        elif args.command=='requirements':
            packet=strict_json_loads(Path(args.packet).read_text(encoding='utf-8'))
            if args.context and (not isinstance(packet,dict) or packet.get('context_id')!=args.context):
                raise PolicyError('packet context differs from explicit executor')
            out=requirements_from_result(args.repo,policy,packet=packet,result=strict_json_loads(Path(args.result).read_text(encoding='utf-8')),output_path=args.output,proposal_head=args.proposal_head,temporal=args.temporal,max_age_days=args.max_age_days,trusted_additional_readers=tuple(args.additional_reader),trusted_binding=binding)
        elif args.command=='review':
            candidate = strict_json_loads(Path(args.candidate).read_text(encoding='utf-8'))
            from wiki_core.coordination_context import _policy
            policy = _policy(args.repo, binding, candidate.get('destination_context'), args.approved_revision)
            out=report_review(args.repo,policy,candidate,disposition=args.disposition,reason=args.reason,evidence_revision=args.evidence_revision,trusted_binding=binding)
        elif args.command=='preflight-composite':
            out=preflight_composite(args.repo,policy,base=args.base,head=args.head,branch=args.branch,
                participants=_composite_participants(args.participants),trusted_binding=binding)
        else:
            out=preflight(args.repo,policy,context_id=args.context,base=args.base,head=args.head,branch=args.branch,packet=strict_json_loads(Path(args.packet).read_text(encoding='utf-8')),result=strict_json_loads(Path(args.result).read_text(encoding='utf-8')),trusted_additional_readers=tuple(args.additional_reader),trusted_binding=binding,allow_owned_range=args.owned_range)
        print(json.dumps(out,ensure_ascii=False,sort_keys=True,indent=2))
    except (PolicyError,ImpactError,IntegrationError,RequirementError,ValueError,KeyError,OSError,RecursionError) as exc:
        report_context_error(exc); return 1
    return 0
if __name__=='__main__': raise SystemExit(main())
