"""Codex capability probe — the honest gate for the agentic-missions feature.

The cockpit only offers to *launch* a Codex job when Codex is genuinely usable
on the operator's machine: the binary runs AND an auth session exists. This
module answers "can we run Codex right now?" deterministically, with zero
tokens and no side effects, so the UI can advertise the capability truthfully
(or disable it with a plain-language reason) instead of faking a run.

Auth follows the plan's model: ChatGPT OAuth via `codex login`, token cached in
`~/.codex/auth.json` (auth_mode "chatgpt", with `tokens`) — never in the repo.
An API-key session is reported honestly too, but the cockpit's launch path is
OAuth-first and never asks for or stores a key.

The probe is intentionally forgiving about *installed but broken*: a Codex npm
wrapper whose vendored native binary is missing is `installed` yet not
`runnable`, so `usable` is False and the reason explains why. That is a real,
observed state — honest degradation must cover it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from wiki_core.config import WikiConfig

CODEX_CAPABILITY_SCHEMA_VERSION = "wiki_web_codex.v1"

_VERSION_TIMEOUT_SECONDS = 10


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line[:200]
    return ""


def _codex_home(codex_home: str | os.PathLike[str] | None) -> Path:
    if codex_home:
        return Path(codex_home)
    env = os.environ.get("CODEX_HOME")
    if env:
        return Path(env)
    return Path.home() / ".codex"


def _probe_auth(codex_home: str | os.PathLike[str] | None) -> tuple[bool, str | None]:
    """A Codex auth session exists if ~/.codex/auth.json carries OAuth tokens or
    an API key. We do NOT crack JWT expiry — Codex refreshes its own tokens, and
    a genuinely stale session degrades honestly at run time (the job fails with a
    reason). This answers "is there a session to use", not "will it never fail"."""
    path = _codex_home(codex_home) / "auth.json"
    if not path.is_file():
        return False, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, None
    if not isinstance(data, dict):
        return False, None
    auth_mode = data.get("auth_mode")
    auth_mode = str(auth_mode) if auth_mode else None
    if data.get("tokens"):
        return True, auth_mode or "chatgpt"
    if data.get("OPENAI_API_KEY"):
        return True, auth_mode or "apikey"
    return bool(auth_mode), auth_mode


def probe_codex(
    *,
    binary: str = "codex",
    codex_home: str | os.PathLike[str] | None = None,
    enabled: bool = True,
) -> dict[str, Any]:
    """Return the Codex capability record the cockpit gates on.

    Fields:
      enabled   — operator/config opt-out (False ⇒ never offer Codex).
      installed — the `binary` resolves on PATH.
      runnable  — `codex --version` exits 0 (rules out broken installs).
      authed    — an auth session exists in CODEX_HOME/auth.json.
      auth_mode — "chatgpt" (OAuth) | "apikey" | None.
      version   — the reported version string when runnable.
      usable    — enabled AND runnable AND authed (the one flag the UI trusts).
      reason    — plain-language explanation whenever usable is False.
    """
    record: dict[str, Any] = {
        "schema_version": CODEX_CAPABILITY_SCHEMA_VERSION,
        "enabled": bool(enabled),
        "installed": False,
        "runnable": False,
        "authed": False,
        "auth_mode": None,
        "version": None,
        "usable": False,
        "reason": "",
    }

    authed, auth_mode = _probe_auth(codex_home)
    record["authed"] = authed
    record["auth_mode"] = auth_mode

    if not enabled:
        record["reason"] = "Codex is turned off for this wiki (codex.enabled: false)."
        return record

    installed = shutil.which(binary) is not None
    record["installed"] = installed
    if not installed:
        record["reason"] = "Codex is not installed. Install the Codex CLI to enable this."
        return record

    try:
        completed = subprocess.run(  # noqa: S603 - fixed binary, no shell, --version only
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=_VERSION_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        record["installed"] = False
        record["reason"] = "Codex is not installed. Install the Codex CLI to enable this."
        return record
    except (subprocess.TimeoutExpired, OSError) as exc:
        record["reason"] = f"Codex did not respond: {_first_line(str(exc)) or 'timed out'}."
        return record

    if completed.returncode == 0 and completed.stdout.strip():
        record["runnable"] = True
        record["version"] = completed.stdout.strip().splitlines()[0][:120]
    else:
        detail = _first_line(completed.stderr) or _first_line(completed.stdout) or "codex --version failed"
        record["reason"] = f"Codex is installed but not runnable: {detail}"
        return record

    if not authed:
        record["reason"] = "Codex is installed but not signed in. Run `codex login` (Sign in with ChatGPT)."
        return record

    record["usable"] = True
    return record


def probe_codex_for(config: WikiConfig) -> dict[str, Any]:
    """Config-aware probe used by the operator server."""
    codex_cfg = getattr(config, "codex", {}) or {}
    binary = str(codex_cfg.get("binary") or os.environ.get("WIKI_CODEX_BINARY") or "codex")
    enabled = bool(config.codex_enabled) if hasattr(config, "codex_enabled") else True
    return probe_codex(binary=binary, enabled=enabled)
