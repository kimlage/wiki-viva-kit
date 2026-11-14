#!/usr/bin/env python3
"""Optional fast pre-push checks; opt in with ``--install`` per repository."""
from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from _common import ROOT
from wiki_session_hook import _run_group
from wiki_core.detectors.secrets import scan_secrets


class Blocked(Exception):
    pass


def run(root: Path, args: list[str], deadline: float, *, data: bytes | None = None) -> bytes:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise Blocked('time budget exceeded')
    try:
        with tempfile.TemporaryFile() as output:
            p = subprocess.run(args, cwd=root, input=data, stdout=output,
                               stderr=subprocess.DEVNULL, timeout=remaining)
            output.seek(0)
            result = output.read()
    except (OSError, subprocess.TimeoutExpired):
        raise Blocked('command unavailable or timed out') from None
    if p.returncode:
        raise Blocked('check failed')
    return result


def git(root: Path, deadline: float, *args: str, data: bytes | None = None) -> bytes:
    return run(root, ['git', '--no-replace-objects', '--no-optional-locks', *args], deadline, data=data)


def oid(root: Path, deadline: float, value: str) -> str:
    if not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', value):
        raise Blocked('invalid push object')
    return git(root, deadline, 'rev-parse', '--verify', value + '^{commit}').decode('ascii').strip()


def scan_objects(root: Path, deadline: float, new: str, old: str | None) -> None:
    args = ['rev-list', '--objects', new]
    if old:
        args.append('^' + old)
    objects = git(root, deadline, *args).splitlines()
    names = sorted({line.split(b' ', 1)[0] for line in objects})
    if not names:
        return
    records = git(root, deadline, 'cat-file', '--batch-check=%(objectname) %(objecttype) %(objectsize)',
                  data=b'\n'.join(names) + b'\n').splitlines()
    objects_to_scan = []
    size = 0
    for record in records:
        fields = record.split()
        if len(fields) != 3:
            raise Blocked('object inventory incomplete')
        if fields[1] in {b'blob', b'commit', b'tag'}:
            size += int(fields[2])
            objects_to_scan.append((fields[0], fields[1]))
    if size > 50_000_000:
        raise Blocked('secret scan exceeds local limit')
    names = [name for name, _ in objects_to_scan]
    payload = git(root, deadline, 'cat-file', '--batch', data=b'\n'.join(names) + b'\n') if names else b''
    for expected, kind in objects_to_scan:
        header, separator, payload = payload.partition(b'\n')
        parts = header.split()
        if not separator or len(parts) != 3 or parts[0] != expected or parts[1] != kind:
            raise Blocked('object read incomplete')
        length = int(parts[2])
        content, payload = payload[:length], payload[length:]
        if len(content) != length or not payload.startswith(b'\n'):
            raise Blocked('object read incomplete')
        payload = payload[1:]
        if scan_secrets(content.decode('utf-8', errors='replace')):
            raise Blocked('secret detected in pushed history')
        if time.monotonic() >= deadline:
            raise Blocked('time budget exceeded')


def quick_commands(root: Path, commit: str, deadline: float) -> list[list[str]]:
    # Read policy from the pushed commit, never from a possibly modified file.
    if not git(root, deadline, 'ls-tree', '--name-only', commit, '--', 'wiki.config.yaml').strip():
        return []
    import yaml
    try:
        config = yaml.safe_load(git(root, deadline, 'show', commit + ':wiki.config.yaml'))
        section = (config or {}).get('pre_push', {})
        commands = section.get('quick_commands', [])
        if not isinstance(commands, list) or any(not isinstance(c, list) or not c or
                any(not isinstance(x, str) or not x or '\x00' in x for x in c) for c in commands):
            raise ValueError
        return commands
    except (OSError, ValueError, AttributeError, yaml.YAMLError):
        raise Blocked('invalid pre_push.quick_commands configuration') from None


def check(root: Path, updates: str, deadline: float, push_url: str | None) -> None:
    changes: list[tuple[str, str, str | None]] = []
    for line in updates.splitlines():
        fields = line.split()
        if len(fields) != 4:
            raise Blocked('invalid Git pre-push input')
        _, local, _, remote = fields
        if set(local) == {'0'}:
            continue
        new = oid(root, deadline, local)
        old = None if set(remote) == {'0'} else oid(root, deadline, remote)
        changes.append((local, new, old))
    # A remote-tracking ref may be stale. For a newly created ref, only an
    # observed live server main can bound the historical inventory.
    remote_main = None
    if push_url and any(old is None for _, _, old in changes):
        try:
            lines = git(root, deadline, 'ls-remote', '--heads', '--', push_url, 'refs/heads/main').splitlines()
            if len(lines) == 1:
                candidate, ref = lines[0].decode('ascii').split('\t', 1)
                if ref == 'refs/heads/main':
                    remote_main = oid(root, deadline, candidate)
        except (Blocked, ValueError, UnicodeError):
            remote_main = None
    for raw_new, new, old in changes:
        if old is None and remote_main:
            try:
                git(root, deadline, 'merge-base', '--is-ancestor', remote_main, new)
                old = remote_main
            except Blocked:
                pass
        if old:
            git(root, deadline, 'diff', '--check', '--no-ext-diff', old, new, '--')
        else:
            # Empty tree versus tip checks the entire initial tree.
            empty = git(root, deadline, 'hash-object', '-t', 'tree', '--stdin', data=b'').decode().strip()
            git(root, deadline, 'diff', '--check', '--no-ext-diff', empty, new, '--')
        scan_objects(root, deadline, raw_new, old)
    if changes:
        commands = [command for _, new, _ in changes for command in quick_commands(root, new, deadline)]
        if commands:
            head = git(root, deadline, 'rev-parse', '--verify', 'HEAD^{commit}').decode().strip()
            if any(new != head for _, new, _ in changes):
                raise Blocked('consumer checks require the pushed HEAD to be checked out')
            entries = git(root, deadline, 'ls-files', '-v', '-z').split(b'\x00')
            if any(entry and (entry[:1].islower() or entry[:1] == b'S') for entry in entries):
                raise Blocked('index flags can hide changes from consumer checks')
            git(root, deadline, 'diff', '--quiet', 'HEAD', '--')
        for command in commands:
            run(root, command, deadline)


def install(root: Path) -> None:
    deadline = time.monotonic() + 10
    common = Path(os.fsdecode(git(root, deadline, 'rev-parse', '--path-format=absolute', '--git-common-dir').strip()))
    configured = subprocess.run(['git', 'config', '--get', 'core.hooksPath'], cwd=root,
                                capture_output=True, text=True)
    hooks = common / 'hooks'
    existing = hooks.is_dir() and any(not path.name.endswith('.sample') for path in hooks.iterdir())
    if configured.returncode == 0 or existing:
        raise Blocked('existing hooks configuration requires manual integration')
    hookdir = common / 'wiki-viva-hooks'
    hookdir.mkdir(exist_ok=True)
    hook = hookdir / 'pre-push'
    if hook.exists():
        raise Blocked('pre-push hook already exists')
    hook.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' '
                    + shlex.quote(str(Path(__file__).resolve())) + ' --root . "$@"\n', encoding='utf-8')
    hook.chmod(0o755)
    run(root, ['git', 'config', '--local', 'core.hooksPath', str(hookdir)], deadline)
    print('pre-push installed for this repository')


def main() -> int:
    # Replacement refs and grafts can hide history while Git pushes originals.
    os.environ['GIT_NO_REPLACE_OBJECTS'] = '1'
    os.environ['GIT_GRAFT_FILE'] = os.devnull
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--install', action='store_true')
    parser.add_argument('--timeout', type=float, default=10)
    parser.add_argument('--_worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('remote', nargs='?')
    parser.add_argument('url', nargs='?')
    args = parser.parse_args()
    if not 0 < args.timeout <= 60:
        parser.error('--timeout must be greater than zero and at most 60')
    if not args.install and not args._worker:
        try:
            raw = sys.stdin.buffer.read(1_000_001)
            if len(raw) > 1_000_000:
                raise ValueError
            payload = raw.decode('utf-8')
        except (OSError, UnicodeError, ValueError):
            print('pre-push blocked: invalid Git pre-push input', file=sys.stderr)
            return 1
        result = _run_group([sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], '--_worker'],
                            payload, args.timeout)
        if result is None:
            print('pre-push blocked: time budget exceeded or worker unavailable', file=sys.stderr)
            return 1
        if result.startswith('FAIL:'):
            print('pre-push blocked: ' + result.removeprefix('FAIL:').strip(), file=sys.stderr)
            return 1
        if result.strip() != 'OK':
            print('pre-push blocked: invalid worker result', file=sys.stderr)
            return 1
        return 0
    try:
        if args.install:
            install(args.root.resolve())
        else:
            check(args.root.resolve(), sys.stdin.read(), time.monotonic() + args.timeout, args.url)
    except Blocked as error:
        print(f'FAIL:{error}' if args._worker else f'pre-push blocked: {error}',
              file=sys.stdout if args._worker else sys.stderr)
        return 0 if args._worker else 1
    except (OSError, ValueError):
        message = 'a quick check failed or could not complete'
        print(f'FAIL:{message}' if args._worker else f'pre-push blocked: {message}',
              file=sys.stdout if args._worker else sys.stderr)
        return 0 if args._worker else 1
    if args._worker:
        print('OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
