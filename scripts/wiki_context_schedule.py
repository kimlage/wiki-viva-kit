#!/usr/bin/env python3
"""Read-only schedule advice. Does not install, enqueue or execute anything."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wiki_core.context_policy import PolicyError, load_policy
from wiki_core.context_schedule import MAX_BYTES, evaluate_wake


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', default='.')
    parser.add_argument('--approved-revision', required=True)
    parser.add_argument('--manifest', default='context.yaml')
    parser.add_argument('--request', required=True)
    args = parser.parse_args()
    try:
        with Path(args.request).open('rb') as stream: data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES: raise PolicyError('request exceeds budget')
        def pairs(values):
            result = {}
            for key, value in values:
                if key in result: raise PolicyError('duplicate JSON key')
                result[key] = value
            return result
        request = json.loads(data, object_pairs_hook=pairs)
        policy = load_policy(args.repo, args.approved_revision, args.manifest)
        if not isinstance(request, dict) or set(request) - {'schedule', 'wake', 'observation'}:
            raise PolicyError('invalid request')
        output = evaluate_wake(policy, request['schedule'], request['wake'], request.get('observation'))
        print(json.dumps(output, sort_keys=True))
    except (PolicyError, OSError, KeyError, ValueError, TypeError, RecursionError):
        print('schedule request rejected', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__': raise SystemExit(main())
