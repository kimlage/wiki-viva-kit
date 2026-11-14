#!/usr/bin/env python3
"""Optional Codex/Claude lifecycle hook for integration handoffs.

This is a host adapter, not a scheduler or authority source. It consumes a
single provider event from stdin and emits one provider-compatible JSON object.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import signal
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

CHECKER = Path(__file__).with_name('wiki_integration_check.py')
MAX_INPUT = 1_000_000
FIELDS = ('proposal', 'head', 'base', 'review', 'gates', 'pending', 'responsible-thread')


def check(root: Path, timeout: float) -> dict:
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


def _worktree_dirty(root: Path) -> bool | None:
    try:
        p = subprocess.run(['git', '--no-optional-locks', 'status', '--porcelain', '--untracked-files=normal'],
                           cwd=root, capture_output=True, text=True, timeout=5)
        return bool(p.stdout) if p.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _branch_without_upstream(root: Path) -> bool | None:
    """Observe local tracking configuration, not whether a remote/PR exists."""
    try:
        branch = subprocess.run(['git', 'symbolic-ref', '--quiet', '--short', 'HEAD'], cwd=root,
                                capture_output=True, text=True, timeout=5)
        if branch.returncode or not branch.stdout.strip():
            return None
        ref = 'refs/heads/' + branch.stdout.strip()
        tracking = subprocess.run(['git', 'for-each-ref', '--format=%(refname) %(upstream)', ref],
                                  cwd=root, capture_output=True, text=True, timeout=5)
        line = tracking.stdout.rstrip('\n')
        if tracking.returncode or not line.startswith(ref + ' '):
            return None
        return not bool(line[len(ref) + 1:].strip())
    except (OSError, subprocess.TimeoutExpired):
        return None


def handoff_problems(message: Any) -> list[str]:
    if not isinstance(message, str) or len(message) > MAX_INPUT:
        return list(FIELDS)
    fields: dict[str, str] = {}
    for line in message.splitlines():
        match = re.match(r'^\s*(proposal|head|base|review|gates|pending|responsible-thread)\s*:\s*(\S.*)$', line, re.I)
        if match:
            fields[match.group(1).lower()] = match.group(2).strip()
    problems = {name for name in FIELDS if not fields.get(name)}
    for name in ('head', 'base'):
        value = fields.get(name, '')
        if value and (not re.fullmatch(r'(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})', value) or set(value) == {'0'}):
            problems.add(name)
    placeholders = {'unknown', 'none', 'n/a', 'na', 'tbd', 'pending', 'missing', 'unavailable', '-'}
    for name in ('proposal', 'review', 'gates', 'responsible-thread'):
        if fields.get(name, '').lower() in placeholders:
            problems.add(name)
    if fields.get('pending', '').lower() in {'unknown', 'tbd', 'missing', 'unavailable', '-'}:
        problems.add('pending')
    proposal = fields.get('proposal', '')
    url = re.search(r'(?i)https?://[^/\s]+/[^/\s]+/[^/\s]+/\S+', proposal)
    numbered = re.search(r'(?i)\b(?:pr|proposal)\s*#?\s*\d+\b', proposal)
    repository = re.search(r'(?i)\brepo=[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\b', proposal)
    target = re.search(r'(?i)\btarget=[A-Za-z0-9_./-]+', proposal)
    if proposal and (not target or not (url or (numbered and repository))):
        problems.add('proposal')
    review = fields.get('review', '')
    if review and (not re.search(r'(?i)(?:https?://|t3-thread://|review:)[^\s]+', review)
                   or not fields.get('head') or fields['head'].lower() not in review.lower()):
        problems.add('review')
    gates_value = fields.get('gates', '')
    gates = [gate.strip() for gate in gates_value.split(',')] if gates_value else []
    if gates and any(not re.fullmatch(r'[A-Za-z0-9_./-]+=(?:passed|failed|pending|waiting)', gate, re.I) for gate in gates):
        problems.add('gates')
    if fields.get('pending', '').lower() == 'none' and any(gate.rsplit('=', 1)[-1].lower() != 'passed' for gate in gates):
        problems.add('pending')
    thread = fields.get('responsible-thread', '')
    if thread and not re.search(r'(?i)(?:thread:|t3-thread://|mcp:launch:)[^\s]+', thread):
        problems.add('responsible-thread')
    return [name for name in FIELDS if name in problems]


def complete_handoff(message: Any) -> bool:
    return not handoff_problems(message)


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
           executor_types: set[str], timeout: float) -> dict:
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
        if event.get('agent_type') not in executor_types:
            return {}
        problems = handoff_problems(message)
        if not problems:
            return {}
        return {'systemMessage': 'Executor handoff missing or invalid fields: ' + ', '.join(problems) + '.'}
    if name == 'Stop':
        # Only local facts: tracking configuration does not establish PR state.
        dirty = _worktree_dirty(root)
        without_upstream = _branch_without_upstream(root)
        findings = []
        if dirty is True:
            findings.append('uncommitted_changes')
        if without_upstream is True:
            findings.append('local_branch_without_upstream')
        remote_note = 'PR state unknown offline; see SessionStart or wiki_integration_check.py.'
        if not findings:
            if dirty is None or without_upstream is None:
                return {'systemMessage': 'Local Git observation incomplete. ' + remote_note}
            return {'systemMessage': remote_note}
        reason = 'Local Git findings: ' + ', '.join(findings) + '. ' + remote_note
        if mode == 'enforce' and not stopped() and not continued:
            return {'decision': 'block', 'reason': reason + ' Resolve the specific finding or report its blocker.'}
        return {'systemMessage': reason}

    return {}


def _windows_job():
    """Use a Windows job whose closure terminates the worker and descendants."""
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [('PerProcessUserTimeLimit', ctypes.c_longlong),
                    ('PerJobUserTimeLimit', ctypes.c_longlong), ('LimitFlags', wintypes.DWORD),
                    ('MinimumWorkingSetSize', ctypes.c_size_t), ('MaximumWorkingSetSize', ctypes.c_size_t),
                    ('ActiveProcessLimit', wintypes.DWORD), ('Affinity', ctypes.c_size_t),
                    ('PriorityClass', wintypes.DWORD), ('SchedulingClass', wintypes.DWORD)]

    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in ('ReadOperationCount', 'WriteOperationCount',
                    'OtherOperationCount', 'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [('BasicLimitInformation', BasicLimits), ('IoInfo', IoCounters),
                    ('ProcessMemoryLimit', ctypes.c_size_t), ('JobMemoryLimit', ctypes.c_size_t),
                    ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise OSError('job creation failed')
    limits = ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE
    if not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        kernel.CloseHandle(job)
        raise OSError('job configuration failed')
    return kernel, job


def _run_group(argv: list[str], payload: str, timeout: float) -> str | None:
    """Bound and reap a worker tree, including children holding its pipes."""
    if timeout <= 0:
        return None
    deadline = time.monotonic() + timeout
    job = kernel = proc = None
    threads: list[threading.Thread] = []
    output: list[str] = []
    overflow = [False]
    success = False

    def write_input() -> None:
        try:
            proc.stdin.write(payload)
        except (OSError, ValueError, UnicodeError):
            pass
        finally:
            try:
                proc.stdin.close()
            except (OSError, ValueError):
                pass

    def drain(stream, keep: bool) -> None:
        size = 0
        try:
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    break
                if keep:
                    size += len(chunk)
                    if size <= MAX_INPUT:
                        output.append(chunk)
                    else:
                        overflow[0] = True
        except (OSError, ValueError, UnicodeError):
            overflow[0] = True

    try:
        if os.name == 'nt':
            kernel, job = _windows_job()
        # Defer catchable termination until the newly created worker is stored;
        # otherwise a signal inside Popen could leave an untracked child.
        pending: list[int] = []
        previous = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
        def defer(signum: int, _frame: Any) -> None:
            pending.append(signum)
        for sig in previous:
            signal.signal(sig, defer)
        try:
            proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True, encoding='utf-8',
                                    start_new_session=(os.name != 'nt'),
                                    creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0))
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            if pending:
                _terminate(pending[0], None)
        if job is not None and not kernel.AssignProcessToJobObject(job, int(proc._handle)):
            proc.kill()
            proc.wait()
            return None
        # The worker reads stdin before starting any subprocess. On Windows the
        # job assignment above therefore precedes all worker descendants. Pipe
        # I/O uses daemon threads so a full stdin pipe cannot bypass the timer.
        for target, args in ((write_input, ()), (drain, (proc.stdout, True)), (drain, (proc.stderr, False))):
            thread = threading.Thread(target=target, args=args, daemon=True)
            thread.start()
            threads.append(thread)
        proc.wait(timeout=max(0, deadline - time.monotonic()))
        success = proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        pass
    finally:
        if job is not None:
            kernel.CloseHandle(job)
        elif proc is not None and os.name != 'nt':
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
        if proc is not None:
            if proc.poll() is None:
                try:
                    proc.kill()
                except OSError:
                    pass
            try:
                proc.wait(timeout=0.2)
            except (OSError, subprocess.TimeoutExpired):
                pass
        for thread in threads:
            thread.join(timeout=0.1)
    return ''.join(output) if success and not overflow[0] and not any(t.is_alive() for t in threads) else None


def _read_input(timeout: float) -> str | None:
    """Bound waiting for the provider to finish writing its event."""
    result: queue.Queue = queue.Queue(maxsize=1)
    def read() -> None:
        try:
            chunks: list[bytes] = []
            size = 0
            while size <= MAX_INPUT:
                chunk = os.read(sys.stdin.fileno(), min(65536, MAX_INPUT + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            result.put(b''.join(chunks).decode('utf-8'))
        except (OSError, UnicodeError, ValueError):
            result.put(None)
    threading.Thread(target=read, daemon=True).start()
    try:
        return result.get(timeout=max(0, timeout))
    except queue.Empty:
        return None


def main() -> int:
    started = time.monotonic()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, help='Repository root; defaults to event cwd')
    parser.add_argument('--mode', choices=('observe', 'enforce'), default='observe')
    parser.add_argument('--stop-state-file', type=Path, help='Fresh trusted runtime JSON with matching session_id and state')
    parser.add_argument('--executor-type', action='append', default=[], help='Exact executor agent_type; repeatable')
    parser.add_argument('--timeout', type=float, default=5, help='Total event budget in seconds (default: 5)')
    parser.add_argument('--_worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 0 < args.timeout <= 60:
        parser.error('--timeout must be greater than 0 and at most 60 seconds')
    if not args._worker:
        raw = _read_input(args.timeout - (time.monotonic() - started))
        remaining = args.timeout - (time.monotonic() - started)
        output = (_run_group([sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], '--_worker'], raw, remaining)
                  if raw is not None and len(raw) <= MAX_INPUT else None)
        print(output.strip() if output else json.dumps({'systemMessage': 'Hook timed out or unavailable; no continuation requested.'}))
        return 0
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1).decode('utf-8')
        event = json.loads(raw) if len(raw) <= MAX_INPUT else None
        if not isinstance(event, dict):
            raise ValueError
        root = _repository_root((args.root or Path(event.get('cwd') or '.')).resolve())
        if root is None:
            output = {'systemMessage': 'Repository root unavailable; no continuation was requested.'}
        else:
            output = handle(event, root, args.mode, lambda: _stop_state(args.stop_state_file, event.get('session_id')),
                            set(args.executor_type or ['executor']), args.timeout)
    except (ValueError, OSError, TypeError, UnicodeError):
        output = {'systemMessage': 'Hook input unavailable; no continuation was requested.'}
    print(json.dumps(output, ensure_ascii=False))
    return 0


def _terminate(signum: int, _frame: Any) -> None:
    # Python otherwise exits on SIGTERM without unwinding the worker cleanup.
    raise SystemExit(128 + signum)


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, _terminate)
    signal.signal(signal.SIGINT, _terminate)
    raise SystemExit(main())
