#!/usr/bin/env python3
"""Update the marked quadrant lists of one anchor, or check their freshness."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from urllib.parse import quote

from _common import ROOT
from wiki_core.config import load_config
from wiki_core.template_blocks import anchor_record, is_anchor_type, load_block_world


def render_map(root: Path, anchor_ref: str) -> tuple[Path, str]:
    world = load_block_world(root, load_config(root))
    anchor = world.by_id.get(anchor_ref) or world.by_path.get(anchor_ref)
    if not anchor or not is_anchor_type(world, anchor['page_type']):
        raise ValueError('anchor not found or not a block anchor')
    path = root / anchor['path']
    if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != root and root in p.parents):
        raise ValueError('anchor path contains a symlink')
    derived = anchor_record(world, anchor).get('derived') or {}
    if 'quadrant_projections' not in derived:
        raise ValueError('anchor has no active quadrants block')
    projections = derived['quadrant_projections']
    text = path.read_text(encoding='utf-8')
    for quadrant in ('q1', 'q2', 'q3', 'q4'):
        start = f'<!-- integral-map:{quadrant}:start -->'
        end = f'<!-- integral-map:{quadrant}:end -->'
        if text.count(start) != 1 or text.count(end) != 1 or text.index(start) > text.index(end):
            raise ValueError(f'{quadrant}: missing, duplicate or reversed markers')
        ids = sorted({page_id for page_id, entries in projections.items()
                      if page_id != anchor['id'] and any(entry.get('quadrant') == quadrant for entry in entries)})
        lines = []
        for page_id in ids:
            page = world.by_id.get(page_id)
            if not page:
                raise ValueError(f'projection references unknown page: {page_id}')
            target = quote(os.path.relpath(root / page['path'], path.parent), safe='/.-_~')
            label = page['title'].replace('\\', '\\\\').replace('[', '\\[').replace(']', '\\]').replace('\n', ' ')
            lines.append(f'- [{label}]({target})')
        if not lines:
            lines.append('_Empty: `quadrant_absence` mission._')
        before, tail = text.split(start, 1)
        _, after = tail.split(end, 1)
        text = before + start + '\n' + '\n'.join(lines) + '\n' + end + after
    return path, text


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--anchor', required=True, help='Anchor page ID or repository-relative path')
    parser.add_argument('--check', action='store_true', help='Report stale content without writing')
    args = parser.parse_args(argv)
    try:
        path, expected = render_map(ROOT, args.anchor)
        current = path.read_text(encoding='utf-8')
        if current != expected:
            if args.check:
                print(f'stale integral map: {path.relative_to(ROOT)}', file=sys.stderr)
                return 1
            path.write_text(expected, encoding='utf-8')
        print(f'integral map: {path.relative_to(ROOT)}')
        return 0
    except (OSError, ValueError) as exc:
        print(f'integral map: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
