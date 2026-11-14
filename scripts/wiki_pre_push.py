#!/usr/bin/env python3
"""Optional fast pre-push checks; opt in with ``--install`` per repository."""
from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

from _common import ROOT
from wiki_core.detectors import scan_text


class Blocked(Exception):
    pass


def run(root: Path, args: list[str], deadline: float, *, data: bytes | None = None) -> bytes:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise Blocked('time budget exceeded')
    try:
        p = subprocess.run(args, cwd=root, input=data, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, timeout=remaining)
    except (OSError, subprocess.TimeoutExpired):
        raise Blocked('command unavailable or timed out') from None
    if p.returncode:
        raise Blocked('check failed')
    return p.stdout


def git(root: Path, deadline: float, *args: str, data: bytes | None = None) -> bytes:
    return run(root, ['git', '--no-optional-locks', *args], deadline, data=data)


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
    blobs = []
    size = 0
    for record in records:
        fields = record.split()
        if len(fields) != 3:
            raise Blocked('object inventory incomplete')
        if fields[1] == b'blob':
            size += int(fields[2])
            blobs.append(fields[0])
    if size > 50_000_000:
        raise Blocked('secret scan exceeds local limit')
    payload = git(root, deadline, 'cat-file', '--batch', data=b'\n'.join(blobs) + b'\n') if blobs else b''
    for expected in blobs:
        header, separator, payload = payload.partition(b'\n')
        parts = header.split()
        if not separator or len(parts) != 3 or parts[0] != expected or parts[1] != b'blob':
            raise Blocked('object read incomplete')
        length = int(parts[2])
        content, payload = payload[:length], payload[length:]
        if len(content) != length or not payload.startswith(b'\n'):
            raise Blocked('object read incomplete')
        payload = payload[1:]
        if any(f.category == 'secret' for f in scan_text(content.decode('utf-8', errors='replace'))):
            raise Blocked('secret detected in pushed history')
        if time.monotonic() >= deadline:
            raise Blocked('time budget exceeded')


def quick_commands(root: Path) -> list[list[str]]:
    path = root / 'wiki.config.yaml'
    if not path.exists():
        return []
    import yaml
    try:
        config = yaml.safe_load(path.read_text(encoding='utf-8'))
        section = (config or {}).get('pre_push', {})
        commands = section.get('quick_commands', [])
        if not isinstance(commands, list) or any(not isinstance(c, list) or not c or
                any(not isinstance(x, str) or not x or '\x00' in x for x in c) for c in commands):
            raise ValueError
        return commands
    except (OSError, ValueError, AttributeError, yaml.YAMLError):
        raise Blocked('invalid pre_push.quick_commands configuration') from None


def check(root: Path, updates: str, deadline: float, remote_name: str | None = None) -> None:
    changes: list[tuple[str, str | None]] = []
    for line in updates.splitlines():
        fields = line.split()
        if len(fields) != 4:
            raise Blocked('invalid Git pre-push input')
        _, local, _, remote = fields
        if set(local) == {'0'}:
            continue
        new = oid(root, deadline, local)
        old = None if set(remote) == {'0'} else oid(root, deadline, remote)
        changes.append((new, old))
    for new, old in changes:
        if old is None:
            # This is an offline estimate of already-shared history at this remote.
            try:
                if not remote_name or not re.fullmatch(r'[A-Za-z0-9._-]+', remote_name):
                    raise Blocked('remote tracking unknown')
                candidate = git(root, deadline, 'rev-parse', '--verify',
                                f'refs/remotes/{remote_name}/main^{{commit}}').decode().strip()
                git(root, deadline, 'merge-base', '--is-ancestor', candidate, new)
                old = candidate
            except Blocked:
                old = None
        if old:
            git(root, deadline, 'diff', '--check', '--no-ext-diff', old, new, '--')
        else:
            # Empty tree versus tip checks the entire initial tree.
            empty = git(root, deadline, 'hash-object', '-t', 'tree', '--stdin', data=b'').decode().strip()
            git(root, deadline, 'diff', '--check', '--no-ext-diff', empty, new, '--')
        scan_objects(root, deadline, new, old)
    if changes:
        commands = quick_commands(root)
        if commands:
            head = git(root, deadline, 'rev-parse', '--verify', 'HEAD^{commit}').decode().strip()
            if any(new != head for new, _ in changes):
                raise Blocked('consumer checks require the pushed HEAD to be checked out')
            git(root, deadline, 'diff', '--quiet', 'HEAD', '--')
        for command in commands:
            run(root, command, deadline)


def install(root: Path) -> None:
    deadline = time.monotonic() + 10
    common = Path(os.fsdecode(git(root, deadline, 'rev-parse', '--path-format=absolute', '--git-common-dir').strip()))
    configured = subprocess.run(['git', 'config', '--get', 'core.hooksPath'], cwd=root,
                                capture_output=True, text=True)
    if configured.returncode == 0 or (common / 'hooks' / 'pre-push').exists():
        raise Blocked('existing hooks configuration requires manual integration')
    hookdir = common / 'wiki-viva-hooks'
    hookdir.mkdir(exist_ok=True)
    hook = hookdir / 'pre-push'
    if hook.exists():
        raise Blocked('pre-push hook already exists')
    hook.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' '
                    + shlex.quote(str(Path(__file__).resolve())) + ' --root '
                    + shlex.quote(str(root)) + ' "$@"\n', encoding='utf-8')
    hook.chmod(0o755)
    run(root, ['git', 'config', '--local', 'core.hooksPath', str(hookdir)], deadline)
    print('pre-push installed for this repository')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--install', action='store_true')
    parser.add_argument('--timeout', type=float, default=10)
    parser.add_argument('remote', nargs='?')
    parser.add_argument('url', nargs='?')
    args = parser.parse_args()
    if not 0 < args.timeout <= 60:
        parser.error('--timeout must be greater than zero and at most 60')
    try:
        if args.install:
            install(args.root.resolve())
        else:
            check(args.root.resolve(), sys.stdin.read(), time.monotonic() + args.timeout, args.remote)
    except Blocked as error:
        print(f'pre-push blocked: {error}', file=sys.stderr)
        return 1
    except (OSError, ValueError):
        print('pre-push blocked: a quick check failed or could not complete', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
