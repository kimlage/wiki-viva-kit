#!/usr/bin/env python3
"""Resolve a context or build a bounded packet; approval is external to this CLI."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wiki_core.context_policy import load_policy, PolicyError
from wiki_core.context_packet import build_packet


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo', default='.')
    p.add_argument('--approved-revision', required=True, help='externally approved policy revision (not verified by this tool)')
    p.add_argument('--manifest', default='context.yaml')
    sub = p.add_subparsers(dest='command', required=True)
    resolve = sub.add_parser('resolve'); resolve.add_argument('context')
    pack = sub.add_parser('pack'); pack.add_argument('context'); pack.add_argument('--content-revision', required=True); pack.add_argument('--request', required=True)
    args = p.parse_args()
    try:
        policy = load_policy(args.repo, args.approved_revision, args.manifest)
        if args.command == 'resolve':
            output = {'policy_revision': policy.policy_revision, 'context': args.context, 'effective': policy.effective[args.context], 'lineage': [c['id'] for c in policy.lineage(args.context)], 'enforcement_claim': 'none'}
        else:
            request = json.loads(Path(args.request).read_text(encoding='utf-8'))
            output = build_packet(args.repo, policy, args.context, args.content_revision, request['evidence'], request['max_bytes'], query_fingerprint=request.get('query_fingerprint'), omissions=request.get('omissions', []), task_id=request['task_id'], goal=request['goal'], output=request['output'], integrator=request['integrator'])
        if args.command == 'pack':
            sys.stdout.write(json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
        else:
            print(json.dumps(output, ensure_ascii=False, indent=2))
    except (PolicyError, KeyError, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr); return 1
    return 0

if __name__ == '__main__': raise SystemExit(main())
