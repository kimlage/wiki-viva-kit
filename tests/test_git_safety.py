from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from wiki_core.git_safety import (
    GitSafetyError,
    dangerous_local_config_keys,
    require_safe_local_config,
    resolved_git_executable,
    sanitized_git_argv,
    sanitized_git_environment,
)


def _system_git_or_skip() -> str:
    try:
        return resolved_git_executable()
    except GitSafetyError:
        pytest.skip("system Git authority is genuinely unavailable")


def _git(root: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [_system_git_or_skip(), *arguments],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    (root / "tracked.txt").write_text("stable\n", encoding="utf-8")
    _git(root, "add", "tracked.txt")
    _git(
        root,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "fixture",
    )
    return root


def test_sanitized_environment_drops_ambient_process_injection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    poisoned = {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.fsmonitor",
        "GIT_CONFIG_VALUE_0": "/tmp/never-run",
        "GIT_DIR": "/tmp/wrong",
        "GIT_EXTERNAL_DIFF": "/tmp/never-run",
        "GIT_SSH_COMMAND": "/tmp/never-run",
        "PAGER": "/tmp/never-run",
        "EDITOR": "/tmp/never-run",
        "PYTHONPATH": "/tmp/never-run",
        "NODE_OPTIONS": "--require=/tmp/never-run",
    }
    for key, value in poisoned.items():
        monkeypatch.setenv(key, value)
    environment = sanitized_git_environment()
    assert not (set(poisoned) & set(environment))
    assert environment["GIT_CONFIG_GLOBAL"] == os.devnull
    assert environment["GIT_CONFIG_NOSYSTEM"] == "1"
    assert environment["GIT_NO_REPLACE_OBJECTS"] == "1"
    assert environment["GIT_PROTOCOL_FROM_USER"] == "0"


def test_ambient_path_cannot_replace_system_git_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sentinel = tmp_path / "fake-git-ran"
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_git = fake_bin / "git"
    fake_git.write_text(
        f"#!/bin/sh\n: > '{sentinel}'\nexit 99\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin))

    executable = _system_git_or_skip()
    assert Path(executable).is_absolute()
    assert Path(executable) != fake_git
    result = subprocess.run(
        sanitized_git_argv(["--version"], executable=executable),
        env=sanitized_git_environment(executable=executable),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0
    assert not sentinel.exists()


def test_status_ignores_ambient_and_local_fsmonitor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo(tmp_path)
    sentinel = tmp_path / "sentinel"
    hook = tmp_path / "fsmonitor.sh"
    hook.write_text(f"#!/bin/sh\ntouch '{sentinel}'\nexit 0\n", encoding="utf-8")
    hook.chmod(0o755)
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.fsmonitor")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(hook))
    executable = resolved_git_executable()
    result = subprocess.run(
        sanitized_git_argv(
            ["status", "--porcelain=v1", "--untracked-files=all"],
            executable=executable,
        ),
        cwd=root,
        env=sanitized_git_environment(executable=executable),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0
    assert not sentinel.exists()


def test_commit_disables_repository_hooks(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    sentinel = tmp_path / "hook-ran"
    hook = root / ".git" / "hooks" / "pre-commit"
    hook.write_text(f"#!/bin/sh\ntouch '{sentinel}'\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    (root / "tracked.txt").write_text("changed\n", encoding="utf-8")
    executable = resolved_git_executable()
    result = subprocess.run(
        sanitized_git_argv(["commit", "-qam", "safe boundary"], executable=executable),
        cwd=root,
        env=sanitized_git_environment(executable=executable),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0
    assert not sentinel.exists()


@pytest.mark.parametrize(
    "key,value",
    [
        ("filter.evil.clean", "/tmp/never-run"),
        ("diff.evil.command", "/tmp/never-run"),
        ("merge.evil.driver", "/tmp/never-run"),
        ("core.attributesFile", "/tmp/attributes"),
        ("submodule.evil.update", "!/tmp/never-run"),
        ("core.alternateRefsCommand", "/tmp/never-run"),
        ("core.worktree", "/tmp/wrong-worktree"),
        ("protocol.ext.allow", "always"),
        ("protocol.allow", "always"),
        ("url.ext::/usr/bin/false.insteadOf", "/tmp/stage"),
        ("url.ext::/usr/bin/false.pushInsteadOf", "/tmp/stage"),
    ],
)
def test_local_executable_config_fails_closed(
    tmp_path: Path, key: str, value: str
) -> None:
    root = _repo(tmp_path)
    _git(root, "config", "--local", key, value)
    assert dangerous_local_config_keys(root)
    with pytest.raises(GitSafetyError, match="executable policy"):
        require_safe_local_config(root)


def test_diff_disables_external_and_textconv() -> None:
    argv = sanitized_git_argv(["diff", "--quiet", "HEAD"])
    assert "--no-ext-diff" in argv
    assert "--no-textconv" in argv


def test_local_include_is_rejected_without_executing_it(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    sentinel = tmp_path / "included-hook-ran"
    hook = tmp_path / "included-fsmonitor.sh"
    hook.write_text(f"#!/bin/sh\ntouch '{sentinel}'\nexit 0\n", encoding="utf-8")
    hook.chmod(0o755)
    included = tmp_path / "included.config"
    included.write_text(f"[core]\n\tfsmonitor = {hook}\n", encoding="utf-8")
    _git(root, "config", "--local", "include.path", str(included))
    with pytest.raises(GitSafetyError, match="executable policy"):
        require_safe_local_config(root)
    assert not sentinel.exists()


@pytest.mark.parametrize(
    "key",
    [
        "alias.release-proof",
        "credential.helper",
        "credential.https://example.invalid.helper",
    ],
)
def test_local_command_alias_and_credential_helpers_fail_closed_without_execution(
    tmp_path: Path, key: str
) -> None:
    root = _repo(tmp_path)
    sentinel = tmp_path / "local-config-command-ran"
    executable = tmp_path / "local-config-command.sh"
    executable.write_text(
        f"#!/bin/sh\ntouch '{sentinel}'\nexit 0\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    _git(root, "config", "--local", key, f"!{executable}")

    assert key.lower() in dangerous_local_config_keys(root)
    with pytest.raises(GitSafetyError, match="executable policy"):
        require_safe_local_config(root)
    assert not sentinel.exists()


def test_reviewed_local_clone_protocol_remains_available(tmp_path: Path) -> None:
    source = _repo(tmp_path)
    destination = tmp_path / "clone"
    executable = resolved_git_executable()
    result = subprocess.run(
        sanitized_git_argv(
            ["clone", "--quiet", "--no-local", str(source), str(destination)],
            executable=executable,
        ),
        env=sanitized_git_environment(executable=executable),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")


def test_reviewed_local_fetch_requires_explicit_file_protocol_authority(
    tmp_path: Path,
) -> None:
    source = _repo(tmp_path)
    stage = tmp_path / "stage"
    executable = resolved_git_executable()
    _git(source, "clone", "-q", "--no-local", str(source), str(stage))
    _git(
        stage,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "prepared boundary",
    )
    prepared = _git(stage, "rev-parse", "HEAD").stdout.decode("ascii").strip()
    arguments = ["fetch", "--quiet", "--no-tags", str(stage), prepared]
    environment = sanitized_git_environment(executable=executable)

    denied = subprocess.run(
        sanitized_git_argv(arguments, executable=executable),
        cwd=source,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )
    assert denied.returncode != 0

    accepted = subprocess.run(
        sanitized_git_argv(
            arguments,
            executable=executable,
            allow_file_protocol=True,
        ),
        cwd=source,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )
    assert accepted.returncode == 0, accepted.stderr.decode("utf-8", "replace")
    assert _git(source, "cat-file", "-e", f"{prepared}^{{commit}}").returncode == 0


def test_file_protocol_authority_is_rejected_for_unrelated_git_commands() -> None:
    with pytest.raises(GitSafetyError, match="file protocol authority"):
        sanitized_git_argv(["status", "--porcelain"], allow_file_protocol=True)
