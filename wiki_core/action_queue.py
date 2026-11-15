"""Read the pending queue from canonical actions, without a shared generated file."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from wiki_core.action_state import CANONICAL_ACTION_STATES, NON_TERMINAL_ACTION_STATES
from wiki_core.action_transition import (
    ActionTransitionError, _lifecycle_contract_error, _parse_document,
    action_transition_diagnostics,
)
from wiki_core.config import load_config
from wiki_core.paths import WikiPaths


def _inventory(documents: dict[str, str]) -> tuple[dict[str, tuple[str, dict, str]], list[str]]:
    actions = {}
    errors = []
    for path, text in sorted(documents.items()):
        try:
            fm, _ = _parse_document(text)
        except ActionTransitionError:
            errors.append(f'{path}: invalid frontmatter')
            continue
        if fm.get('page_type') != 'action':
            continue
        page_id = fm.get('page_id')
        state = fm.get('action_state')
        if not isinstance(page_id, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,160}', page_id):
            errors.append(f'{path}: invalid page_id')
            continue
        if page_id in actions:
            errors.append(f'{path}: duplicate page_id')
            continue
        if state not in CANONICAL_ACTION_STATES:
            errors.append(f'{path}: invalid action_state')
        else:
            error = _lifecycle_contract_error(fm, state)
            if error:
                errors.append(f'{path}: {error}')
        actions[page_id] = (path, fm, text)
    return actions, errors


def read_queue(root: Path, *, base: str | None = None) -> tuple[list[dict], list[str]]:
    """Read all configured action collections; optionally audit against a Git base."""
    root = root.resolve()
    paths = WikiPaths(root, load_config(root))
    docs = {p.relative_to(root).as_posix(): p.read_text(encoding='utf-8') for p in paths.action_files()}
    current, errors = _inventory(docs)
    if base is not None:
        listing = subprocess.run(['git', 'ls-tree', '-r', '--name-only', '-z', base], cwd=root,
                                 capture_output=True, check=False)
        if listing.returncode:
            return [], errors + ['base action inventory unavailable']
        base_docs = {}
        for raw in listing.stdout.split(b'\0'):
            if not raw:
                continue
            rel = raw.decode('utf-8')
            if not rel.endswith('.md') or paths.collection_root(root / rel, 'actions_dirname') is None:
                continue
            blob = subprocess.run(['git', 'show', f'{base}:{rel}'], cwd=root, capture_output=True, check=False)
            if blob.returncode:
                return [], errors + ['base action blob unavailable']
            base_docs[rel] = blob.stdout.decode('utf-8')
        previous, base_errors = _inventory(base_docs)
        errors.extend(f'base: {error}' for error in base_errors)
        for page_id, (old_path, _fm, old_text) in previous.items():
            if page_id not in current:
                errors.append(f'{old_path}: action missing from current inventory')
                continue
            path, _fm, text = current[page_id]
            if text != old_text:
                errors.extend(f'{path}: {item.code}' for item in action_transition_diagnostics(old_text, text))
    rows = [{'page_id': key, 'path': path, 'title': str(fm.get('title') or key),
             'state': fm.get('action_state'), 'next_action': str(fm.get('next_action') or '')}
            for key, (path, fm, _text) in current.items() if fm.get('action_state') in NON_TERMINAL_ACTION_STATES]
    order = {'in_progress': 0, 'open': 1, 'blocked': 2, 'waiting_human': 3}
    rows.sort(key=lambda row: (order[row['state']], row['title'].casefold(), row['page_id']))
    return rows, errors
