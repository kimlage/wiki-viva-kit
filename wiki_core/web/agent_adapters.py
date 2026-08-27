"""CLI adapters for the operator's governed agent job runner.

Adapters only describe capability and argv.  Git ownership, stale-brief checks,
redacted logs, branch isolation and human review remain centralized in the
existing JobRunner; adding Claude therefore does not duplicate the core job or
connector logic.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

AGENT_ADAPTER_SCHEMA_VERSION = "wiki_agent_adapter.v1"
AGENT_IDS = {"codex", "claude"}


def list_agent_connectors(agent: str, *, binary: str) -> list[str]:
    """Return connector names only; never expose raw CLI configuration."""
    resolved = shutil.which(binary) if not Path(binary).is_absolute() else binary
    if agent not in AGENT_IDS or not resolved or not Path(resolved).is_file():
        return []
    try:
        argv = [binary, "mcp", "list", "--json"] if agent == "codex" else [binary, "mcp", "list"]
        result = subprocess.run(argv, capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    if agent == "codex":
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, list):
            return []
        return sorted({str(item.get("name") or "") for item in payload if isinstance(item, dict) and item.get("enabled") is True and item.get("name")})
    connected: set[str] = set()
    for line in result.stdout.splitlines():
        match = re.match(r"^([A-Za-z0-9_.-]+):.*(?:Connected|✔)", line.strip())
        if match:
            connected.add(match.group(1))
    return sorted(connected)


def build_claude_argv(binary: str, root: Path) -> list[str]:
    """Non-interactive Claude Code invocation with edits allowed but no
    autonomous network tools or Git/PR ownership."""
    return [
        binary,
        "--print",
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-mode",
        "acceptEdits",
        "--allowedTools",
        "Read,Edit,Write,Glob,Grep,Bash",
        "--disallowedTools",
        "Bash(git *)",
        "Bash(gh *)",
        "--add-dir",
        str(root),
    ]


def probe_claude(*, binary: str = "claude", enabled: bool = True) -> dict[str, Any]:
    record: dict[str, Any] = {
        "schema_version": AGENT_ADAPTER_SCHEMA_VERSION,
        "agent": "claude",
        "enabled": bool(enabled),
        "installed": False,
        "runnable": False,
        "authed": False,
        "auth_mode": None,
        "version": None,
        "usable": False,
        "reason": "",
    }
    if not enabled:
        record["reason"] = "Claude is turned off for this wiki (claude.enabled: false)."
        return record
    resolved = shutil.which(binary) if not Path(binary).is_absolute() else binary
    if not resolved or not Path(resolved).is_file():
        record["reason"] = "Claude Code is not installed."
        return record
    record["installed"] = True
    try:
        version = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=8, check=False)
    except (OSError, subprocess.TimeoutExpired):
        record["reason"] = "Claude Code is installed but does not run."
        return record
    if version.returncode != 0:
        record["reason"] = (version.stderr or version.stdout or "Claude Code failed").splitlines()[0][:240]
        return record
    record["runnable"] = True
    record["version"] = (version.stdout or version.stderr).splitlines()[0][:120]
    try:
        status = subprocess.run(
            [binary, "auth", "status", "--json"], capture_output=True, text=True, timeout=8, check=False
        )
        auth = json.loads(status.stdout) if status.returncode == 0 else {}
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        auth = {}
    record["authed"] = bool(auth.get("loggedIn"))
    record["auth_mode"] = str(auth.get("authMethod") or "") or None
    if not record["authed"]:
        record["reason"] = "Claude Code is not signed in. Run `claude auth login`."
        return record
    record["usable"] = True
    return record


def probe_claude_for(config: Any) -> dict[str, Any]:
    block = getattr(config, "claude", {}) or {}
    return probe_claude(binary=str(block.get("binary") or "claude"), enabled=bool(getattr(config, "claude_enabled", True)))
