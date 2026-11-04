#!/usr/bin/env python3
"""Inspect tracked context instructions and indexes; never grants permissions."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wiki_core.safe_cli import SafeArgumentParser, report_failure
from wiki_core.folder_context import FolderContextError, inspect_folder


def main():
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument('--repo', default='.', help='Git repository root')
    parser.add_argument('--revision', required=True, help='content revision; trust must be checked separately')
    parser.add_argument('--max-instruction-bytes', type=int, default=32768)
    parser.add_argument('--index', help='explicit context index path')
    parser.add_argument('folder', help='repository-relative starting directory, or .')
    args = parser.parse_args()
    try:
        result = inspect_folder(args.repo, args.revision, args.folder, max_instruction_bytes=args.max_instruction_bytes, index_path=args.index)
    except FolderContextError as exc:
        report_failure(exc)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
