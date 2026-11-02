#!/usr/bin/env python3
"""Read-only trusted-working-tree preview; does not establish approval or ACLs."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wiki_core.config import load_config
from wiki_core.page_types import load_page_type_registry
from wiki_core.template_sections import validate_section_page
from wiki_core.templates import resolve_template


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--page-type', required=True)
    parser.add_argument('--page', type=Path, help='Existing page; omitted validates the resolved contract only')
    parser.add_argument('--mode', choices=['structure', 'filled'], default='structure')
    args = parser.parse_args()
    try:
        root = args.root.resolve()
        registry = load_page_type_registry(root)
        if registry is None:
            raise ValueError('page type registry missing')
        resolved = resolve_template(root, load_config(root), registry, args.page_type)
        if resolved.section_contract is None:
            raise ValueError('page type has no opt-in section contract; legacy templates unchanged')
        errors = []
        if args.page:
            from wiki_core.template_sections import read_template_file
            errors = validate_section_page(read_template_file(root, args.page.as_posix()),
                                           resolved.section_contract, mode=args.mode)
        print(json.dumps({'template_id': resolved.template_id, 'template_version': resolved.template_version,
                          'mode': args.mode if args.page else 'contract', 'errors': errors}))
        return int(bool(errors))
    except (ValueError, OSError) as exc:
        print(json.dumps({'errors': [str(exc)]}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
