import json
from pathlib import Path

from wiki_core.web.agent_adapters import build_claude_argv, list_agent_connectors, probe_claude


def _shim(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755)
    return path


def test_claude_argv_is_non_interactive_and_keeps_git_with_runner(tmp_path: Path) -> None:
    argv = build_claude_argv("claude", tmp_path)
    assert argv[:2] == ["claude", "--print"]
    assert "stream-json" in argv
    assert "acceptEdits" in argv
    assert "Bash(git *)" in argv
    assert "Bash(gh *)" in argv
    assert "--dangerously-skip-permissions" not in argv


def test_claude_probe_reports_version_and_auth_without_credentials(tmp_path: Path) -> None:
    payload = json.dumps({"loggedIn": True, "authMethod": "claude.ai", "token": "must-not-leak"})
    binary = _shim(
        tmp_path / "claude",
        f'if [ "$1" = "--version" ]; then echo "2.1.197"; else echo \'{payload}\'; fi\n',
    )
    result = probe_claude(binary=str(binary))
    assert result["usable"] is True
    assert result["version"] == "2.1.197"
    assert result["auth_mode"] == "claude.ai"
    assert "token" not in result


def test_claude_probe_fails_closed_when_disabled(tmp_path: Path) -> None:
    result = probe_claude(binary=str(tmp_path / "missing"), enabled=False)
    assert result["usable"] is False
    assert result["enabled"] is False


def test_connector_probe_returns_names_without_raw_configuration(tmp_path: Path) -> None:
    binary = _shim(
        tmp_path / "claude",
        'echo "drive: https://connector.invalid/token-value - ✔ Connected"\n'
        'echo "broken: local-command - ✘ Failed"\n',
    )
    assert list_agent_connectors("claude", binary=str(binary)) == ["drive"]
