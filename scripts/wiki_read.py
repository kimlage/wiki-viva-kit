#!/usr/bin/env python3
"""Read explicitly scoped Git content; this low-level CLI does not grant access."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from _common import ROOT
from wiki_core.repository_reader import RepositoryReader
from wiki_core.detectors import contains_secret_structure


def main() -> int:
    # argparse may echo invalid argument values. Refuse detected credentials
    # before parsing so even its usage/errors cannot disclose them.
    try:
        invalid_arguments = contains_secret_structure(' '.join(sys.argv[1:]))
    except (ValueError, TypeError, RecursionError):
        invalid_arguments = True
    if invalid_arguments:
        print('read unavailable: detected access secret', file=sys.stderr)
        return 1
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--revision', required=True, help='Git content revision; resolved once to a commit SHA.')
    parser.add_argument('--mode', required=True, choices=('read', 'catalog'), help='Read content or enumerate metadata.')
    parser.add_argument('--allow-path', action='append', required=True, help='Exact authorized repository path; repeat to enumerate.')
    parser.add_argument('--ref', help='Exact path or page_id resolved only within allowed paths.')
    selectors = parser.add_mutually_exclusive_group()
    selectors.add_argument('--section', help='Explicit stable heading section ID; missing IDs fail.')
    selectors.add_argument('--field', help='Exact frontmatter field.')
    selectors.add_argument('--whole-body', action='store_true', help='Explicitly request the entire document.')
    args = parser.parse_args()
    try:
        reader = RepositoryReader(args.root, args.revision)
        if args.mode == 'catalog':
            if args.ref or args.section or args.field or args.whole_body:
                parser.error('catalog does not accept content selectors')
            result = reader.query(allowed_paths=args.allow_path)
        else:
            if not args.ref or not (args.section or args.field or args.whole_body):
                parser.error('read requires --ref and an explicit selector or --whole-body')
            allowed = set(args.allow_path)
            if args.ref in allowed:
                path = args.ref
            else:
                matches = [row['path'] for row in reader.catalogue(allowed_paths=allowed) if row['page_id'] == args.ref]
                if len(matches) != 1:
                    parser.error('reference missing or ambiguous within authorized paths')
                path = matches[0]
            result = reader.read(path, section=args.section, field=args.field)
            # Return only the selected content; raw bytes are represented by UTF-8 text.
            result = {key: value for key, value in result.items()
                      if key not in {'content', 'frontmatter', 'body'}}
            result['byte_length'] = len(result['text'].encode())
        result.update(policy_mode='explicit_local_scope', policy_enforced=False)
        if contains_secret_structure(result):
            print('read unavailable: detected access secret', file=sys.stderr)
            return 1
        serialized = json.dumps(result, ensure_ascii=False, indent=2, default=str)
        # Preserve a selected field's original key for assignment-style
        # detectors; the output's generic 'value' key is insufficient.
        field_value = {result['field']: result['value']} if 'field' in result else {}
        if contains_secret_structure(serialized) or contains_secret_structure(field_value):
            print('read unavailable: detected access secret', file=sys.stderr)
            return 1
        print(serialized)
        return 0
    except Exception:
        # Reader/selector errors may include paths, IDs or authored text.
        print('read unavailable', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
