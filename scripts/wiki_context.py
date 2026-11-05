#!/usr/bin/env python3
"""Resolve a context or build a bounded packet; approval is external to this CLI."""
import argparse
import json
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wiki_core.context_selection import strict_json_loads
from wiki_core.context_policy import load_policy, PolicyError
from wiki_core.context_packet import build_packet
from wiki_core.git_env import local_git_environment, local_git_executable


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo', help='wiki Git root; defaults to the current Git root')
    p.add_argument('--approved-revision', required=True, help='externally approved policy revision (not verified by this tool)')
    p.add_argument('--manifest', choices=['wiki.config.yaml'], default='wiki.config.yaml')
    sub = p.add_subparsers(dest='command', required=True)
    resolve = sub.add_parser('resolve'); resolve.add_argument('context')
    pack = sub.add_parser('pack'); pack.add_argument('context'); pack.add_argument('--content-revision', required=True); pack.add_argument('--request', required=True)
    pack.add_argument('--folder', help='physical entry folder relative to the wiki root')
    pack.add_argument('--index', help='context index relative to the wiki root')
    args = p.parse_args()
    try:
        if args.repo is None:
            result = subprocess.run([local_git_executable(), '--no-lazy-fetch', '-C', str(Path.cwd()),
                                     'rev-parse', '--show-toplevel'], stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, env=local_git_environment())
            if result.returncode: raise PolicyError('current Git root unavailable')
            args.repo = result.stdout.decode('utf-8').strip()
            if not args.repo: raise PolicyError('current Git root unavailable')
        policy = load_policy(args.repo, args.approved_revision, args.manifest)
        if args.command == 'resolve':
            output = {'policy_revision': policy.policy_revision, 'context': args.context, 'effective': policy.effective[args.context], 'lineage': [c['id'] for c in policy.lineage(args.context)], 'authorized': False, 'enforcement_claim': 'none; selected context has not been qualified'}
        else:
            request = strict_json_loads(Path(args.request).read_text(encoding='utf-8'))
            folder = args.folder
            if folder is None:
                try: relative = Path.cwd().resolve().relative_to(Path(args.repo).resolve())
                except ValueError: relative = None
                folder = relative.as_posix() if relative is not None and relative.parts else args.context
            output = build_packet(args.repo, policy, args.context, args.content_revision, request['evidence'], request['max_bytes'], query_fingerprint=request.get('query_fingerprint'), omissions=request.get('omissions', []), task_id=request['task_id'], goal=request['goal'], output=request['output'], integrator=request['integrator'], queries=request.get('queries', []), entry_folder=folder, entry_index=args.index)
        if args.command == 'pack':
            sys.stdout.write(json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
        else:
            print(json.dumps(output, ensure_ascii=False, indent=2))
    except (PolicyError, KeyError, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr); return 1
    return 0

if __name__ == '__main__': raise SystemExit(main())
