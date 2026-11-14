#!/usr/bin/env python3
"""Optional fast pre-push checks; opt in with ``--install`` per repository."""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

from _common import ROOT
from wiki_session_hook import _run_group, _terminate
from wiki_core.detectors.secrets import scan_secrets


class Blocked(Exception):
    pass


def run(root: Path, args: list[str], deadline: float, *, data: bytes | None = None) -> bytes:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise Blocked('time budget exceeded')
    try:
        # Git object contents may contain credentials: retain them in memory
        # only. The outer supervisor bounds and terminates the process group.
        p = subprocess.run(args, cwd=root, input=data, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, timeout=remaining)
    except (OSError, subprocess.TimeoutExpired):
        raise Blocked('command unavailable or timed out') from None
    if p.returncode:
        raise Blocked('check failed')
    return p.stdout


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
        if fields[1] in {b'blob', b'commit', b'tag', b'tree'}:
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
        if kind == b'tree':
            # Git tree records contain raw object IDs after each NUL-terminated
            # mode/name. Scan names separately without displaying them.
            object_bytes = len(expected) // 2
            while content:
                entry, separator, remaining = content.partition(b'\0')
                mode, space, name = entry.partition(b' ')
                if not separator or not mode or not space or not name or len(remaining) < object_bytes:
                    raise Blocked('object read incomplete')
                if scan_secrets(name.decode('utf-8', errors='replace')):
                    raise Blocked('secret detected in pushed history')
                content = remaining[object_bytes:]
        elif scan_secrets(content.decode('utf-8', errors='replace')):
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


def bind_python_command(command: list[str], *, executable: str, windows: bool) -> list[str]:
    """Use the hook's selected interpreter for conventional Python aliases."""
    alias = command[0].lower() if windows else command[0]
    aliases = {'python', 'python3'} | ({'python.exe', 'python3.exe'} if windows else set())
    if alias not in aliases:
        return command
    if not executable:
        raise Blocked('selected Python interpreter unavailable')
    return [executable, *command[1:]]


def verify_worktree(root: Path, expected: str, deadline: float) -> None:
    """Compare raw worktree bytes, including submodules, with the pushed tree."""
    head = git(root, deadline, 'rev-parse', '--verify', 'HEAD^{commit}').decode().strip()
    if head != expected:
        raise Blocked('consumer checks require the pushed HEAD to be checked out')
    entries = git(root, deadline, 'ls-files', '-v', '-z').split(b'\x00')
    if any(entry and (entry[:1].islower() or entry[:1] == b'S') for entry in entries):
        raise Blocked('index flags can hide changes from consumer checks')
    git(root, deadline, 'diff', '--cached', '--quiet', '--no-ext-diff', '--no-textconv',
        '--ignore-submodules=none', 'HEAD', '--')
    object_format = git(root, deadline, 'rev-parse', '--show-object-format').decode().strip()
    if object_format not in {'sha1', 'sha256'}:
        raise Blocked('unsupported object format')
    checked_dirs: set[Path] = set()
    for entry in git(root, deadline, 'ls-files', '--stage', '-z').split(b'\x00'):
        if not entry:
            continue
        metadata, separator, relative = entry.partition(b'\t')
        fields = metadata.split()
        if not separator or len(fields) != 3 or fields[2] != b'0':
            raise Blocked('index unavailable or unmerged')
        mode, expected_oid, _ = fields
        relpath = Path(os.fsdecode(relative))
        if relpath.is_absolute() or '..' in relpath.parts:
            raise Blocked('tracked path outside repository')
        path = root / relpath
        parent = root
        for part in relpath.parts[:-1]:
            parent = parent / part
            if parent not in checked_dirs:
                if parent.is_symlink():
                    raise Blocked('tracked path crosses a symlink')
                checked_dirs.add(parent)
        if mode == b'160000':
            if path.is_symlink():
                raise Blocked('submodule path is a symlink')
            top = os.fsdecode(git(path, deadline, 'rev-parse', '--show-toplevel').strip())
            if Path(top).resolve() != path.resolve():
                raise Blocked('submodule state unavailable or differs from HEAD')
            verify_worktree(path, expected_oid.decode('ascii'), deadline)
            continue
        info = path.lstat()
        if mode == b'120000' and stat.S_ISLNK(info.st_mode):
            data = os.fsencode(os.readlink(path))
            digest = hashlib.new(object_format, b'blob ' + str(len(data)).encode() + b'\0' + data)
        elif mode in {b'100644', b'100755'} and stat.S_ISREG(info.st_mode):
            if os.name != 'nt' and bool(info.st_mode & 0o111) != (mode == b'100755'):
                raise Blocked('tracked file mode differs from commit')
            digest = hashlib.new(object_format, b'blob ' + str(info.st_size).encode() + b'\0')
            with path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1_048_576), b''):
                    digest.update(chunk)
                    if time.monotonic() >= deadline:
                        raise Blocked('time budget exceeded')
        else:
            raise Blocked('tracked file type differs from commit')
        if digest.hexdigest().encode() != expected_oid:
            raise Blocked('tracked file content differs from commit')


def remote_url_may_be_rewritten(root: Path, url: str, deadline: float) -> bool:
    """A second insteadOf rewrite could direct ls-remote to another server."""
    try:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return True
        result = subprocess.run(['git', 'config', '--null', '--get-regexp', r'^url\..*\.insteadof$'],
                                cwd=root, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=remaining)
        if result.returncode == 1 and not result.stdout:
            return False
        if result.returncode:
            return True
        for record in result.stdout.split(b'\0'):
            if not record:
                continue
            _key, separator, prefix = record.partition(b'\n')
            if not separator or os.fsencode(url).startswith(prefix):
                return True
        return False
    except (OSError, subprocess.TimeoutExpired):
        return True


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
    if (push_url and any(old is None for _, _, old in changes)
            and not remote_url_may_be_rewritten(root, push_url, deadline)):
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
            if len({new for _, new, _ in changes}) != 1:
                raise Blocked('consumer checks require the pushed HEAD to be checked out')
            verify_worktree(root, changes[0][1], deadline)
        for command in commands:
            run(root, bind_python_command(command, executable=sys.executable, windows=os.name == 'nt'), deadline)


def install(root: Path) -> None:
    deadline = time.monotonic() + 10
    common = Path(os.fsdecode(git(root, deadline, 'rev-parse', '--path-format=absolute', '--git-common-dir').strip()))
    configured = subprocess.run(['git', 'config', '--get', 'core.hooksPath'], cwd=root,
                                capture_output=True, text=True)
    hooks = common / 'hooks'
    existing = hooks.is_dir() and any(not path.name.endswith('.sample') for path in hooks.iterdir())
    if configured.returncode == 0 or existing:
        raise Blocked('existing hooks configuration requires manual integration')
    if not (root / 'scripts' / 'wiki_pre_push.py').is_file():
        raise Blocked('pre-push script must exist in the repository worktree')
    hookdir = common / 'wiki-viva-hooks'
    hookdir.mkdir(exist_ok=True)
    hook = hookdir / 'pre-push'
    if hook.exists():
        raise Blocked('pre-push hook already exists')
    hook.write_text('#!/bin/sh\nroot=$(git rev-parse --show-toplevel) || exit 1\n'
                    'if [ -x "$root/.venv/bin/python3" ]; then py="$root/.venv/bin/python3"\n'
                    'elif [ -x "$root/.venv/Scripts/python.exe" ]; then py="$root/.venv/Scripts/python.exe"\n'
                    'else py=$(command -v python3) || { echo "pre-push blocked: Python unavailable" >&2; exit 1; }; fi\n'
                    '"$py" -c "import yaml" >/dev/null 2>&1 || { echo "pre-push blocked: Python dependencies unavailable" >&2; exit 1; }\n'
                    'exec "$py" "$root/scripts/wiki_pre_push.py" --root "$root" "$@"\n', encoding='utf-8')
    hook.chmod(0o755)
    run(root, ['git', 'config', '--local', 'core.hooksPath', str(hookdir)], deadline)
    print('pre-push installed for this repository')


def main() -> int:
    # Replacement refs and grafts can hide history while Git pushes originals.
    os.environ['GIT_NO_REPLACE_OBJECTS'] = '1'
    os.environ['GIT_GRAFT_FILE'] = os.devnull
    for key in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_COMMON_DIR',
                'GIT_OBJECT_DIRECTORY', 'GIT_ALTERNATE_OBJECT_DIRECTORIES', 'GIT_PREFIX'):
        os.environ.pop(key, None)
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
    signal.signal(signal.SIGTERM, _terminate)
    signal.signal(signal.SIGINT, _terminate)
    raise SystemExit(main())
