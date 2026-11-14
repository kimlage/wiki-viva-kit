#!/usr/bin/env python3
"""Optional Codex/Claude lifecycle hook for integration handoffs.

This is a host adapter, not a scheduler or authority source. It consumes a
single provider event from stdin and emits one provider-compatible JSON object.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

CHECKER = Path(__file__).with_name('wiki_integration_check.py')
MAX_INPUT = 1_000_000
FIELDS = ('proposal', 'head', 'base', 'review', 'gates', 'pending', 'responsible-thread')


def check(root: Path, timeout: int) -> dict:
    if not CHECKER.is_file():
        return {'ok': False, 'status': 'waiting:integration_checker_unavailable'}
    try:
        p = subprocess.run([sys.executable, str(CHECKER), '--root', str(root), '--json'],
                           capture_output=True, text=True, timeout=timeout)
        result = json.loads(p.stdout)
        if p.returncode or not isinstance(result, dict):
            raise ValueError
        return result
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {'ok': False, 'status': 'waiting:integration_observation_unavailable'}


def _repository_root(path: Path) -> Path | None:
    try:
        p = subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=path,
                           capture_output=True, text=True, timeout=5)
        return Path(p.stdout.strip()).resolve() if p.returncode == 0 and p.stdout.strip() else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _current_branch(root: Path) -> str | None:
    try:
        p = subprocess.run(['git', 'symbolic-ref', '--quiet', '--short', 'HEAD'], cwd=root,
                           capture_output=True, text=True, timeout=5)
        return p.stdout.strip() if p.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _worktree_dirty(root: Path) -> bool | None:
    try:
        p = subprocess.run(['git', '--no-optional-locks', 'status', '--porcelain', '--untracked-files=normal'],
                           cwd=root, capture_output=True, text=True, timeout=5)
        return bool(p.stdout) if p.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def mechanical_findings(observation: dict, root: Path, branch: str | None) -> list[str]:
    if not observation.get('ok'):
        return []
    findings = set()
    for item in observation.get('hygiene', []):
        status = item.get('status')
        current_branch = branch is not None and item.get('branch') == branch
        current_tree = item.get('path') == str(root.resolve())
        if current_branch and status == 'fix:local_branch_without_pr':
            findings.add('current_branch_without_proposal')
        if current_tree and status == 'fix:dirty_worktree':
            findings.add('uncommitted_changes')
        if status in {'fix:merged_branch_remaining', 'fix:merged_worktree_remaining'}:
            findings.add('merged_branch_or_worktree_remaining')
    return sorted(findings)


def complete_handoff(message: Any) -> bool:
    if not isinstance(message, str) or len(message) > MAX_INPUT:
        return False
    fields: dict[str, str] = {}
    for line in message.splitlines():
        match = re.match(r'^\s*(proposal|head|base|review|gates|pending|responsible-thread)\s*:\s*(\S.*)$', line, re.I)
        if match:
            fields[match.group(1).lower()] = match.group(2).strip()
    if any(not fields.get(name) for name in FIELDS):
        return False
    if not all(re.fullmatch(r'(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})', fields[name]) and set(fields[name]) != {'0'} for name in ('head', 'base')):
        return False
    placeholders = {'unknown', 'none', 'n/a', 'na', 'tbd', 'pending', 'missing', 'unavailable', '-'}
    if any(fields[name].lower() in placeholders for name in ('proposal', 'review', 'gates', 'responsible-thread')):
        return False
    if fields['pending'].lower() in {'unknown', 'tbd', 'missing', 'unavailable', '-'}:
        return False
    proposal = fields['proposal']
    url = re.search(r'(?i)https?://[^/\s]+/[^/\s]+/[^/\s]+/\S+', proposal)
    numbered = re.search(r'(?i)\b(?:pr|proposal)\s*#?\s*\d+\b', proposal)
    repository = re.search(r'(?i)\brepo=[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\b', proposal)
    target = re.search(r'(?i)\btarget=[A-Za-z0-9_./-]+', proposal)
    if not target or not (url or (numbered and repository)):
        return False
    if (not re.search(r'(?i)(?:https?://|t3-thread://|review:)[^\s]+', fields['review'])
            or fields['head'].lower() not in fields['review'].lower()):
        return False
    gates = [gate.strip() for gate in fields['gates'].split(',')]
    if not gates or any(not re.fullmatch(r'[A-Za-z0-9_./-]+=(?:passed|failed|pending|waiting)', gate, re.I) for gate in gates):
        return False
    if fields['pending'].lower() == 'none' and any(gate.rsplit('=', 1)[-1].lower() != 'passed' for gate in gates):
        return False
    if not re.search(r'(?i)(?:thread:|t3-thread://|mcp:launch:)[^\s]+', fields['responsible-thread']):
        return False
    return True


def _stop_state(path: Path | None, session_id: Any) -> str:
    """Only fresh, session-bound state from the trusted runtime permits blocking."""
    if path is None or not isinstance(session_id, str) or not session_id:
        return 'unknown'
    try:
        if path.is_symlink() or not path.is_file():
            return 'unknown'
        stat = path.stat()
        age = time.time() - stat.st_mtime
        if stat.st_size > 4096 or age < 0 or age > 45:
            return 'unknown'
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or data.get('session_id') != session_id:
            return 'unknown'
        state = data.get('state')
        return state if state in {'running', 'stop'} else 'unknown'
    except (OSError, UnicodeError, ValueError):
        return 'unknown'


def handle(event: dict, root: Path, mode: str, stop_state: str,
           executor_types: set[str], timeout: int) -> dict:
    name = event.get('hook_event_name')
    message = event.get('last_assistant_message')
    def stopped() -> bool:
        current = stop_state() if callable(stop_state) else stop_state
        return (current != 'running' or event.get('stop_requested') is True
                or (isinstance(message, str) and bool(re.search(r'\bSTOP\b', message, re.I))))
    continued = event.get('stop_hook_active') is not False
    if name == 'SessionStart':
        observation = check(root, timeout)
        if observation.get('ok'):
            counts: dict[str, int] = {}
            for item in observation.get('proposals', []) + observation.get('hygiene', []):
                key = str(item.get('status', 'unknown')).split(':', 1)[0]
                counts[key] = counts.get(key, 0) + 1
            summary = 'Integration observations: ' + (', '.join(f'{k}={v}' for k, v in sorted(counts.items())) or 'none')
        else:
            summary = 'Integration observation unavailable; run wiki_integration_check.py when available.'
        return {'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext': summary}}
    if name == 'SubagentStop':
        if event.get('agent_type') not in executor_types or complete_handoff(message):
            return {}
        warning = 'Executor handoff incomplete: include proposal, head, base, review, gates, pending and responsible-thread.'
        if not stopped() and not continued:
            return {'decision': 'block', 'reason': warning}
        return {'systemMessage': warning + ' Automatic continuation is held or already attempted.'}
    if name == 'Stop':
        observation = check(root, timeout)
        findings = mechanical_findings(observation, root, _current_branch(root))
        if _worktree_dirty(root) is True and 'uncommitted_changes' not in findings:
            findings.append('uncommitted_changes')
        if not findings:
            return {} if observation.get('ok') else {'systemMessage': 'Integration observation unavailable; no mechanical finding was verified.'}
        reason = 'Mechanical integration findings: ' + ', '.join(findings) + '.'
        if mode == 'enforce' and not stopped() and not continued:
            return {'decision': 'block', 'reason': reason + ' Resolve the specific finding or report its blocker.'}
        return {'systemMessage': reason}
    return {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, help='Repository root; defaults to event cwd')
    parser.add_argument('--mode', choices=('observe', 'enforce'), default='observe')
    parser.add_argument('--stop-state-file', type=Path, help='Fresh trusted runtime JSON with matching session_id and state')
    parser.add_argument('--executor-type', action='append', default=[], help='Exact executor agent_type; repeatable')
    parser.add_argument('--timeout', type=int, default=30)
    args = parser.parse_args()
    if args.timeout < 1 or args.timeout > 60:
        parser.error('--timeout must be 1..60 seconds')
    raw = sys.stdin.read(MAX_INPUT + 1)
    try:
        event = json.loads(raw) if len(raw) <= MAX_INPUT else None
        if not isinstance(event, dict):
            raise ValueError
        root = _repository_root((args.root or Path(event.get('cwd') or '.')).resolve())
        if root is None:
            output = {'systemMessage': 'Repository root unavailable; no continuation was requested.'}
        else:
            output = handle(event, root, args.mode, lambda: _stop_state(args.stop_state_file, event.get('session_id')),
                            set(args.executor_type or ['executor']), args.timeout)
    except (ValueError, OSError, TypeError):
        output = {'systemMessage': 'Hook input unavailable; no continuation was requested.'}
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
