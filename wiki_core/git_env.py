"""Closed local Git process environment for revision-bound authority checks.

Authority callers must also pass the Git global ``--no-lazy-fetch`` option.
An older Git without that option fails before executing the requested command.
The tested local implementation is Git 2.50.1; this is not a cross-version
compatibility claim. This boundary is not a filesystem sandbox.
"""
from __future__ import annotations

import ntpath
import sys
import subprocess
from pathlib import Path

from wiki_core.git_safety import GitSafetyError, resolved_git_executable, sanitized_git_environment
from wiki_core.process_safety import ProcessSafetyError, run_bounded_process


_WINDOWS_GIT_PATHS = (
    r'C:\Program Files\Git\cmd\git.exe',
    r'C:\Program Files (x86)\Git\cmd\git.exe',
)
GIT_TREE_OUTPUT_LIMIT = 16_000_000
GIT_TREE_TIMEOUT_SECONDS = 30


def _existing_windows_git(candidate: str) -> str | None:
    try:
        resolved = Path(candidate).resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    # A junction or symlink to an unrelated user-controlled path is not a
    # trusted installation even if its advertised path is under Program Files.
    if str(resolved).casefold() != candidate.casefold() or not resolved.is_file():
        return None
    return str(resolved)


def local_git_executable() -> str:
    if sys.platform == 'win32':
        for candidate in _WINDOWS_GIT_PATHS:
            if found := _existing_windows_git(candidate):
                return found
        raise GitSafetyError('a trusted Git for Windows installation is unavailable')
    return resolved_git_executable()


def local_git_environment() -> dict[str, str]:
    executable = local_git_executable()
    env = sanitized_git_environment(executable=executable)
    if sys.platform == 'win32':
        # Do not inherit user-controlled executable or configuration paths.
        env['SystemRoot'] = r'C:\Windows'
        env['PATH'] = ';'.join((ntpath.dirname(executable), r'C:\Windows\System32', r'C:\Windows'))
    # Prevent a partial clone from spawning a promisor fetch on object access.
    env['GIT_NO_LAZY_FETCH'] = '1'
    env['GIT_ALLOW_PROTOCOL'] = ''
    return env


def local_git_tree(root: Path, *args: str) -> bytes:
    """Read a complete recursive tree or fail; never return truncated bytes.

    POSIX limits output before allocation. Windows retains the previous
    subprocess behavior with a timeout and a post-read limit until a bounded
    native Windows process implementation is available.
    """
    argv = [local_git_executable(), '--no-lazy-fetch', '-C', str(root), *args]
    env = local_git_environment()
    if sys.platform == 'win32':
        try:
            result = subprocess.run(argv, capture_output=True, env=env, timeout=GIT_TREE_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as exc:
            raise GitSafetyError('git tree enumeration timed out') from exc
        if result.returncode or len(result.stdout) > GIT_TREE_OUTPUT_LIMIT:
            raise GitSafetyError('git tree enumeration unavailable or exceeded limit')
        return result.stdout
    try:
        result = run_bounded_process(argv, cwd=root, env=env, timeout=GIT_TREE_TIMEOUT_SECONDS,
                                     output_limit=GIT_TREE_OUTPUT_LIMIT, stderr=subprocess.DEVNULL)
    except ProcessSafetyError as exc:
        raise GitSafetyError('git tree enumeration unavailable or exceeded limit') from exc
    if result.returncode:
        raise GitSafetyError('git tree enumeration unavailable')
    return result.output
