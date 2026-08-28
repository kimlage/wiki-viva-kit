"""Fail-closed Git process authority for release and migration code.

Release evidence must not inherit executable Git configuration from the
operator environment.  This module deliberately exposes only an argv/env
builder plus a conservative local-config audit so callers can keep their own
error types while sharing one process boundary.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Mapping, Sequence

from wiki_core.process_safety import ProcessSafetyError, run_bounded_process


class GitSafetyError(ValueError):
    """The exact Git executable or repository policy is unsafe."""


_CONFIG_OVERRIDES = (
    "core.hooksPath=/dev/null",
    "core.fsmonitor=false",
    "core.untrackedCache=false",
    "core.useReplaceRefs=false",
    "commit.gpgSign=false",
    "tag.gpgSign=false",
)

_DANGEROUS_LOCAL_KEYS = (
    re.compile(
        r"^core\.(?:alternaterefscommand|attributesfile|fsmonitor|gitproxy|"
        r"hookspath|sshcommand|worktree)$"
    ),
    re.compile(r"^filter\..+$"),
    re.compile(r"^alias\..+$"),
    re.compile(r"^credential\.(?:helper|.+\.helper)$"),
    re.compile(r"^diff\.external$"),
    re.compile(r"^diff\..+\.command$"),
    re.compile(r"^difftool\..+\.cmd$"),
    re.compile(r"^interactive\.difffilter$"),
    re.compile(r"^include\.path$"),
    re.compile(r"^includeif\..+\.path$"),
    re.compile(r"^merge\..+\.driver$"),
    re.compile(r"^mergetool\..+\.cmd$"),
    re.compile(r"^gpg\.program$"),
    re.compile(r"^sequence\.editor$"),
    re.compile(r"^remote\..+\.(?:receivepack|uploadpack)$"),
    re.compile(r"^submodule\..+\.update$"),
    re.compile(r"^protocol(?:\..+)?\.allow$"),
    re.compile(r"^url\..+\.(?:insteadof|pushinsteadof)$"),
)


def resolved_git_executable() -> str:
    """Return one absolute Git executable selected before env sanitization."""

    for executable in (Path("/usr/bin/git"), Path("/bin/git")):
        try:
            resolved = executable.resolve(strict=True)
        except OSError:
            continue
        if resolved.is_file():
            return str(resolved)
    raise GitSafetyError("a system Git authority is unavailable")


def sanitized_git_environment(
    *, executable: str | None = None, extra: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Build a fresh, non-interactive Git environment.

    Ambient ``GIT_*``, SSH, pager/editor, language-runtime and config-injection
    variables are intentionally absent.  Explicit extras are limited to safe
    commit identity fields used by the migration boundary writer.
    """

    git = Path(executable or resolved_git_executable())
    environment = {
        "GIT_AUTHOR_EMAIL": "wiki-viva-runner@localhost",
        "GIT_AUTHOR_NAME": "Wiki Viva Runner",
        "GIT_COMMITTER_EMAIL": "wiki-viva-runner@localhost",
        "GIT_COMMITTER_NAME": "Wiki Viva Runner",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_PROTOCOL_FROM_USER": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": os.pathsep.join((str(git.parent), "/usr/bin", "/bin")),
    }
    if extra:
        allowed = {
            "GIT_AUTHOR_DATE",
            "GIT_AUTHOR_EMAIL",
            "GIT_AUTHOR_NAME",
            "GIT_COMMITTER_DATE",
            "GIT_COMMITTER_EMAIL",
            "GIT_COMMITTER_NAME",
        }
        unexpected = sorted(set(extra) - allowed)
        if unexpected:
            raise GitSafetyError("unsafe explicit Git environment key")
        environment.update({key: str(value) for key, value in extra.items()})
    return environment


def sanitized_git_argv(
    arguments: Sequence[str],
    *,
    executable: str | None = None,
    allow_file_protocol: bool = False,
) -> list[str]:
    """Prefix a Git command with non-executable policy overrides."""

    git = executable or resolved_git_executable()
    args = [str(value) for value in arguments]
    if not args or any(not value or "\x00" in value for value in args):
        raise GitSafetyError("Git arguments are empty or invalid")
    command = [git, "--no-pager"]
    for override in _CONFIG_OVERRIDES:
        command.extend(("-c", override))
    if allow_file_protocol and args[0] not in {"clone", "fetch"}:
        raise GitSafetyError("file protocol authority is invalid for this Git command")
    if allow_file_protocol or (args[0] == "clone" and "--no-local" in args):
        command.extend(("-c", "protocol.file.allow=always"))
    if args[0] == "diff":
        args = ["diff", "--no-ext-diff", "--no-textconv", *args[1:]]
    command.extend(args)
    return command


def dangerous_local_config_keys(root: Path) -> list[str]:
    """Return repo-local keys capable of starting an external process."""

    executable = resolved_git_executable()
    try:
        result = run_bounded_process(
            sanitized_git_argv(
                [
                    "config",
                    "--local",
                    "--no-includes",
                    "--name-only",
                    "--null",
                    "--list",
                ],
                executable=executable,
            ),
            cwd=root,
            env=sanitized_git_environment(executable=executable),
            timeout=30,
            output_limit=4 * 1024 * 1024,
        )
    except (OSError, ProcessSafetyError) as exc:
        raise GitSafetyError("repository Git config could not be audited") from exc
    if result.returncode != 0:
        raise GitSafetyError("repository Git config could not be audited")
    try:
        keys = [
            item.decode("utf-8", "strict").lower()
            for item in result.output.split(b"\0")
            if item
        ]
    except UnicodeDecodeError as exc:
        raise GitSafetyError("repository Git config is not canonical UTF-8") from exc
    return sorted(
        key
        for key in keys
        if any(pattern.fullmatch(key) for pattern in _DANGEROUS_LOCAL_KEYS)
    )


def require_safe_local_config(root: Path) -> None:
    """Reject repository-local process hooks before release-bearing Git I/O."""

    if dangerous_local_config_keys(root):
        raise GitSafetyError("repository Git config contains executable policy")
