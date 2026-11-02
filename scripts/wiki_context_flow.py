#!/usr/bin/env python3
"""Finite, read-only context impact and proposal preflight."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from wiki_core.context_policy import load_policy, PolicyError
from wiki_core.context_impact import assess_impact, report_review, ImpactError
from wiki_core.context_integration import preflight, IntegrationError
from wiki_core.context_requirements import assess_approved_impact, requirements_from_result, RequirementError

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo',default='.')
    p.add_argument('--approved-revision',required=True)
    p.add_argument('--manifest',default='context.yaml')
    sub=p.add_subparsers(dest='command',required=True)
    impact=sub.add_parser('impact'); source=impact.add_mutually_exclusive_group(required=True); source.add_argument('--graph'); source.add_argument('--consumer',action='append'); impact.add_argument('--before',required=True); impact.add_argument('--after',required=True); impact.add_argument('--context',required=True); impact.add_argument('--limit',type=int,default=100); impact.add_argument('--offset',type=int,default=0); impact.add_argument('--selection'); impact.add_argument('--trace',default='[]')
    requirements=sub.add_parser('requirements'); requirements.add_argument('--packet',required=True); requirements.add_argument('--result',required=True); requirements.add_argument('--output',required=True); requirements.add_argument('--proposal-head',required=True); requirements.add_argument('--temporal',required=True,choices=['current','historical']); requirements.add_argument('--max-age-days',type=int,required=True)
    review=sub.add_parser('review'); review.add_argument('--candidate',required=True); review.add_argument('--disposition',required=True,choices=['updated','still_valid','superseded','blocked']); review.add_argument('--reason',required=True); review.add_argument('--evidence-revision',required=True)
    check=sub.add_parser('preflight'); check.add_argument('--context',required=True); check.add_argument('--base',required=True); check.add_argument('--head',required=True); check.add_argument('--branch',required=True); check.add_argument('--packet',required=True); check.add_argument('--result',required=True)
    args=p.parse_args()
    try:
        policy=load_policy(args.repo,args.approved_revision,args.manifest)
        if args.command=='impact':
            options={'before':args.before,'after':args.after,'destination_context':args.context,'max_fanout':args.limit,'offset':args.offset,'expected_selection':args.selection,'trace':json.loads(args.trace)}
            out=(assess_impact(args.repo,policy,json.loads(Path(args.graph).read_text(encoding='utf-8')),**options) if args.graph else assess_approved_impact(args.repo,policy,consumers=args.consumer,**options))
        elif args.command=='requirements':
            out=requirements_from_result(args.repo,policy,packet=json.loads(Path(args.packet).read_text(encoding='utf-8')),result=json.loads(Path(args.result).read_text(encoding='utf-8')),output_path=args.output,proposal_head=args.proposal_head,temporal=args.temporal,max_age_days=args.max_age_days)
        elif args.command=='review':
            out=report_review(args.repo,policy,json.loads(Path(args.candidate).read_text(encoding='utf-8')),disposition=args.disposition,reason=args.reason,evidence_revision=args.evidence_revision)
        else:
            out=preflight(args.repo,policy,context_id=args.context,base=args.base,head=args.head,branch=args.branch,packet=json.loads(Path(args.packet).read_text(encoding='utf-8')),result=json.loads(Path(args.result).read_text(encoding='utf-8')))
        print(json.dumps(out,ensure_ascii=False,sort_keys=True,indent=2))
    except (PolicyError,ImpactError,IntegrationError,RequirementError,ValueError,KeyError,OSError) as exc:
        print(str(exc),file=sys.stderr); return 1
    return 0
if __name__=='__main__': raise SystemExit(main())
