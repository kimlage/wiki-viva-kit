from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from wiki_core.config import WikiConfig, load_config
from wiki_core.web.codex_probe import probe_codex, probe_codex_for


def _make_shim(path: Path, *, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _runnable_codex(tmp_path: Path) -> Path:
    return _make_shim(tmp_path / "codex", body='#!/bin/sh\necho "codex-cli 0.99.0"\n')


def _broken_codex(tmp_path: Path) -> Path:
    # Mirrors the observed real failure: npm wrapper present, native binary gone.
    return _make_shim(tmp_path / "codex", body='#!/bin/sh\necho "spawn codex ENOENT" >&2\nexit 1\n')


def _auth_home(tmp_path: Path, payload: dict | None) -> Path:
    home = tmp_path / "codex-home"
    home.mkdir()
    if payload is not None:
        (home / "auth.json").write_text(json.dumps(payload), encoding="utf-8")
    return home


def test_probe_absent(tmp_path: Path) -> None:
    home = _auth_home(tmp_path, {"auth_mode": "chatgpt", "tokens": {"access_token": "x"}})
    record = probe_codex(binary=str(tmp_path / "does-not-exist"), codex_home=home)
    assert record["installed"] is False
    assert record["usable"] is False
    assert "not installed" in record["reason"].lower()
    # Auth can be present even when the binary is missing — reported honestly.
    assert record["authed"] is True


def test_probe_installed_unauthed(tmp_path: Path) -> None:
    binary = _runnable_codex(tmp_path)
    home = _auth_home(tmp_path, None)  # no auth.json
    record = probe_codex(binary=str(binary), codex_home=home)
    assert record["installed"] is True
    assert record["runnable"] is True
    assert record["authed"] is False
    assert record["usable"] is False
    assert "login" in record["reason"].lower()


def test_probe_authed_usable(tmp_path: Path) -> None:
    binary = _runnable_codex(tmp_path)
    home = _auth_home(tmp_path, {"auth_mode": "chatgpt", "tokens": {"access_token": "x"}})
    record = probe_codex(binary=str(binary), codex_home=home)
    assert record["usable"] is True
    assert record["installed"] is True
    assert record["runnable"] is True
    assert record["authed"] is True
    assert record["auth_mode"] == "chatgpt"
    assert record["version"] == "codex-cli 0.99.0"
    assert record["reason"] == ""


def test_probe_installed_but_broken(tmp_path: Path) -> None:
    binary = _broken_codex(tmp_path)
    home = _auth_home(tmp_path, {"auth_mode": "chatgpt", "tokens": {"access_token": "x"}})
    record = probe_codex(binary=str(binary), codex_home=home)
    assert record["installed"] is True
    assert record["runnable"] is False
    assert record["usable"] is False
    assert "not runnable" in record["reason"].lower()


def test_probe_apikey_auth_mode(tmp_path: Path) -> None:
    binary = _runnable_codex(tmp_path)
    home = _auth_home(tmp_path, {"OPENAI_API_KEY": "sk-test"})
    record = probe_codex(binary=str(binary), codex_home=home)
    assert record["authed"] is True
    assert record["auth_mode"] == "apikey"
    assert record["usable"] is True


def test_probe_disabled_short_circuits(tmp_path: Path) -> None:
    binary = _runnable_codex(tmp_path)
    home = _auth_home(tmp_path, {"auth_mode": "chatgpt", "tokens": {"access_token": "x"}})
    record = probe_codex(binary=str(binary), codex_home=home, enabled=False)
    assert record["enabled"] is False
    assert record["usable"] is False
    assert "off" in record["reason"].lower()
    # Disabled means we never even claim runnable — pure opt-out.
    assert record["runnable"] is False


def test_probe_corrupt_auth_json_is_unauthed(tmp_path: Path) -> None:
    binary = _runnable_codex(tmp_path)
    home = tmp_path / "codex-home"
    home.mkdir()
    (home / "auth.json").write_text("{ not json", encoding="utf-8")
    record = probe_codex(binary=str(binary), codex_home=home)
    assert record["authed"] is False
    assert record["usable"] is False


def test_probe_for_config_respects_binary_and_enabled(tmp_path: Path) -> None:
    binary = _runnable_codex(tmp_path)
    home = _auth_home(tmp_path, {"auth_mode": "chatgpt", "tokens": {"access_token": "x"}})
    os.environ["CODEX_HOME"] = str(home)
    try:
        enabled_cfg = WikiConfig(codex={"enabled": True, "binary": str(binary)})
        record = probe_codex_for(enabled_cfg)
        assert record["usable"] is True

        disabled_cfg = WikiConfig(codex={"enabled": False, "binary": str(binary)})
        record = probe_codex_for(disabled_cfg)
        assert record["usable"] is False
        assert record["enabled"] is False
    finally:
        os.environ.pop("CODEX_HOME", None)


def test_config_loads_codex_block(tmp_path: Path) -> None:
    (tmp_path / "wiki.config.yaml").write_text(
        "repo_id: t\ncodex:\n  enabled: false\n", encoding="utf-8"
    )
    config = load_config(tmp_path)
    assert config.codex_enabled is False
    # Default binary survives a partial override.
    assert config.codex.get("binary") == "codex"


@pytest.mark.parametrize("enabled", [True, False])
def test_config_default_codex_enabled(enabled: bool, tmp_path: Path) -> None:
    (tmp_path / "wiki.config.yaml").write_text(
        f"repo_id: t\ncodex:\n  enabled: {str(enabled).lower()}\n", encoding="utf-8"
    )
    assert load_config(tmp_path).codex_enabled is enabled
